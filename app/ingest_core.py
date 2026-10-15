"""
iThink ingestion core
---------------------
The loading logic as a library: no environment variables, no files on disk, no printing.
Used by the Data & Brand Selection page (uploaded files) and by scripts/ingest_excel.py (data/ folder).
Everything is scoped to the tenant_id given to Ingestor, so one tenant can never write into another.

Save as: app/ingest_core.py  (next to brand_setup.py)
"""
import io
import json
import datetime as dt
from datetime import datetime
from pathlib import Path

import numpy as np
import pandas as pd

import brand_setup as bs

BATCH_SIZE = 200
RPC_BATCH_SIZE = 500
SUPPORTED_EXTENSIONS = {".xlsx", ".csv", ".json", ".ndjson"}
MAX_FILE_BYTES = 50 * 1024 * 1024


# =========================================================================
# SOURCE PROFILES
# One block per tool. To add a new source: add a new profile here.
# Nothing else in this script needs to change.
#
# "signature_columns": columns that must ALL be present for this profile
#   to be auto-selected for a file (pick columns unique to that tool).
# "field_map": canonical field -> source column name, OR a list of
#   candidate column names (first one present & non-null wins), OR None
#   if that tool doesn't provide that field at all.
# "date_formats": list of strptime formats to try, in order.
# =========================================================================
SOURCE_PROFILES = {
    "sprinklr": {
        "signature_columns": ["UniversalMessageId", "SocialNetwork"],
        "field_map": {
            "message_id": "UniversalMessageId",
            "source": "SocialNetwork",
            "author_id": ["SenderUserId", "SenderScreenName"],
            "text": "Message",
            "date": "CreatedTime",
            "url": "Permalink",
            "sentiment": "Sentiment",
            "city": "City",
            "state": "State",
            "country": "Country",
            "model_variant": "Model/Variant",
            "followers": "Sender Followers Count",
            "likes": "Favorites",
            "shares": "Retweets",
            "author_name": ["SenderScreenName", "SenderListedName"],
            "gender": "SenderGender",
        },
        "date_formats": ["%b %d %H:%M:%S %Y"],
    },
    # TEMPLATE -- verify every column name against a real Brandwatch export
    # before trusting this one; not yet checked against real data.
    "brandwatch": {
        "signature_columns": ["Full Text", "Author"],
        "field_map": {
            "message_id": ["Resource Id", "Id"],
            "source": ["Channel Type", "Media Type"],
            "author_id": "Author",
            "text": "Full Text",
            "date": ["Added", "Date"],
            "url": "Url",
            "sentiment": "Sentiment",
            "city": None,
            "state": None,
            "country": "Country",
            "model_variant": None,
            "followers": None,
            "likes": None,
            "shares": None,
            "author_name": "Author",
            "gender": None,
        },
        "date_formats": ["%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M:%S"],
    },
}


def to_int_or_none(text):
    """'4', '4.0', '2003331.0' -> int; anything else -> None."""
    if text is None:
        return None
    try:
        return int(round(float(str(text).replace(",", "").strip())))
    except ValueError:
        return None


def detect_profile(df: pd.DataFrame, filename: str) -> str:
    matches = [
        name for name, profile in SOURCE_PROFILES.items()
        if all(col in df.columns for col in profile["signature_columns"])
    ]
    if len(matches) == 1:
        return matches[0]
    if len(matches) > 1:
        raise ValueError(
            f"{filename}: matches multiple source profiles {matches} -- "
            f"signature columns overlap, make them more distinctive"
        )
    raise ValueError(
        f"{filename}: doesn't match any known source profile "
        f"(checked: {list(SOURCE_PROFILES.keys())}). "
        f"Columns found: {list(df.columns)[:15]}... "
        f"Add a new profile to SOURCE_PROFILES for this tool."
    )


def get_mapped_value(row, field_map, canonical_field):
    """Handles: single column name, list of candidates (first non-null wins), or None."""
    mapping = field_map.get(canonical_field)
    if mapping is None:
        return None
    candidates = mapping if isinstance(mapping, list) else [mapping]
    for col in candidates:
        if col in row.index and pd.notna(row[col]):
            val = str(row[col]).strip()
            if val:
                return val
    return None


def parse_date_any(value, date_formats):
    """Returns an ISO string, or None when there is no usable date."""
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return None
    if isinstance(value, (pd.Timestamp, dt.datetime, dt.date)):
        return value.isoformat()
    raw = str(value).strip()
    # "#########" is what Excel shows when a column is too narrow. If that text was
    # saved into the file, the real date is gone -- never try to parse it.
    if not raw or set(raw) <= {"#"}:
        return None
    for fmt in date_formats:
        try:
            return datetime.strptime(raw, fmt).isoformat()
        except ValueError:
            continue
    try:
        return pd.to_datetime(raw).isoformat()
    except Exception:
        return None


def to_native(v):
    if isinstance(v, np.integer):
        return int(v)
    if isinstance(v, np.floating):
        return float(v)
    if isinstance(v, np.bool_):
        return bool(v)
    return v


def clean_row_for_json(row):
    """Makes a row safe to store as jsonb -- handles pandas NaN, pandas
    Timestamps, and plain Python datetime/date objects (Excel sometimes
    yields one or the other depending on how the column was formatted)."""
    out = {}
    for k, v in row.items():
        if pd.isna(v):
            out[k] = None
        elif isinstance(v, (pd.Timestamp, dt.datetime, dt.date)):
            out[k] = v.isoformat()
        else:
            out[k] = to_native(v)
    return out


def read_any(path: Path) -> pd.DataFrame:
    suffix = path.suffix.lower()
    if suffix == ".xlsx":
        return pd.read_excel(path)
    if suffix == ".csv":
        return pd.read_csv(path)
    if suffix == ".json":
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        if isinstance(data, dict):
            for key in ("data", "results", "items"):
                if key in data and isinstance(data[key], list):
                    data = data[key]
                    break
        return pd.json_normalize(data)
    if suffix == ".ndjson":
        records = []
        with open(path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line:
                    records.append(json.loads(line))
        return pd.json_normalize(records)
    raise ValueError(f"Unsupported file type: {suffix}")




def read_bytes(filename: str, data: bytes) -> pd.DataFrame:
    """Same formats as read_any, from uploaded bytes."""
    suffix = Path(filename).suffix.lower()
    if suffix == ".xlsx":
        return pd.read_excel(io.BytesIO(data))
    if suffix == ".csv":
        try:
            return pd.read_csv(io.BytesIO(data))
        except UnicodeDecodeError:
            return pd.read_csv(io.BytesIO(data), encoding="latin-1")
    if suffix in (".json", ".ndjson"):
        text = data.decode("utf-8", errors="replace")
        if suffix == ".ndjson":
            return pd.json_normalize([json.loads(line) for line in text.splitlines() if line.strip()])
        parsed = json.loads(text)
        if isinstance(parsed, dict):
            for key in ("data", "results", "items"):
                if key in parsed and isinstance(parsed[key], list):
                    parsed = parsed[key]
                    break
        return pd.json_normalize(parsed)
    raise ValueError(f"Unsupported file type: {suffix}")


def inspect_frame(df: pd.DataFrame, filename: str, matchers=None) -> dict:
    """What the upload page shows for each file before anything is saved."""
    info = {"file": filename, "rows": int(len(df)), "profile": None, "undated": None, "file_brand": None, "error": None}
    try:
        name = detect_profile(df, filename)
    except ValueError as e:
        info["error"] = str(e)
        return info
    profile = SOURCE_PROFILES[name]
    info["profile"] = name
    date_cols = profile["field_map"].get("date")
    date_cols = date_cols if isinstance(date_cols, list) else [date_cols]
    present = [c for c in date_cols if c and c in df.columns]
    undated = 0
    if present:
        for _, row in df[present].iterrows():
            value = next((row[c] for c in present if pd.notna(row[c])), None)
            if parse_date_any(value, profile["date_formats"]) is None:
                undated += 1
    else:
        undated = len(df)
    info["undated"] = undated
    if matchers:
        info["file_brand"] = bs.brand_from_filename(filename, matchers)
    return info


def text_column_of(df: pd.DataFrame, filename: str):
    profile = SOURCE_PROFILES[detect_profile(df, filename)]
    col = profile["field_map"].get("text")
    return col[0] if isinstance(col, list) else col


def chunked(items, size):
    for i in range(0, len(items), size):
        yield items[i:i + size]




class Ingestor:
    """Loads files for ONE tenant. sb must be a service-role client (it bypasses row-level security),
    which is why the tenant is fixed here and every query below filters on it."""

    def __init__(self, sb, tenant_id: str, log=None):
        self.sb = sb
        self.tenant_id = tenant_id
        self.log = log or (lambda msg: None)

    def _fetch_message_ids(self, only_needing_dates: bool):
        ids, page, page_size = set(), 0, 1000
        while True:
            q = (
                self.sb.table("conversations")
                .select("source_message_id")
                .eq("tenant_id", self.tenant_id)
                .not_.is_("source_message_id", "null")
            )
            if only_needing_dates:
                q = q.or_("conversation_date.is.null,date_is_synthetic.eq.true")
            rows = q.order("id").range(page * page_size, (page + 1) * page_size - 1).execute().data
            if not rows:
                break
            ids.update(r["source_message_id"] for r in rows)
            if len(rows) < page_size:
                break
            page += 1
        return ids


    def fetch_existing_message_ids(self):
        return self._fetch_message_ids(only_needing_dates=False)


    def fetch_ids_needing_dates(self):
        """Rows that currently have no date, or only a simulated one."""
        return self._fetch_message_ids(only_needing_dates=True)


    def fetch_brand_ids(self):
        rows = self.sb.table("brands").select("id, brand_name").eq("tenant_id", self.tenant_id).execute().data or []
        return {r["brand_name"]: r["id"] for r in rows}


    def get_or_create_data_source(self, filename: str, profile_name: str, file_brand_id=None):
        """Returns (data_source_id, brand_id). brand_id is set only when the file name names exactly one brand."""
        existing = (
            self.sb.table("data_sources")
            .select("id, brand_id")
            .eq("tenant_id", self.tenant_id)
            .eq("label", filename)
            .execute()
        )
        if existing.data:
            row = existing.data[0]
            brand_id = row.get("brand_id")
            if brand_id is None and file_brand_id:
                self.sb.table("data_sources").update({"brand_id": file_brand_id}).eq("id", row["id"]).execute()
                brand_id = file_brand_id
            return row["id"], brand_id
        inserted = self.sb.table("data_sources").insert({
            "tenant_id": self.tenant_id,
            "adapter_type": "excel_upload",
            "label": filename,
            "config": {"detected_profile": profile_name},
            "brand_id": file_brand_id,
        }).execute()
        return inserted.data[0]["id"], file_brand_id


    def build_conversation_record(self, row, profile, data_source_id, filename, brand_id=None):
        field_map = profile["field_map"]

        message_id = get_mapped_value(row, field_map, "message_id")
        if not message_id:
            return None  # can't dedupe safely without a stable id

        text = get_mapped_value(row, field_map, "text")
        if not text:
            return None  # no caption/comment text -- nothing to tag, skip rather than crash

        city = get_mapped_value(row, field_map, "city")
        state = get_mapped_value(row, field_map, "state")
        country = get_mapped_value(row, field_map, "country")
        geography = ", ".join(p for p in [city, state, country] if p) or None

        raw = clean_row_for_json(row)
        raw["_source_file"] = filename

        date_mapping = field_map.get("date")
        date_candidates = date_mapping if isinstance(date_mapping, list) else [date_mapping]
        date_col_value = None
        for col in date_candidates:
            if col and col in row.index and pd.notna(row[col]):
                date_col_value = row[col]
                break

        return {
            "tenant_id": self.tenant_id,
            "data_source_id": data_source_id,
            "source_message_id": message_id,
            "source": get_mapped_value(row, field_map, "source"),
            "author_id": get_mapped_value(row, field_map, "author_id"),
            "conversation_text": text,
            "conversation_date": parse_date_any(date_col_value, profile["date_formats"]),
            "url": get_mapped_value(row, field_map, "url"),
            "sentiment_raw": get_mapped_value(row, field_map, "sentiment"),
            "geography": geography,
            "language": None,  # left for LLM extraction (Phase 3)
            "model_extracted": get_mapped_value(row, field_map, "model_variant"),
            "variant_extracted": None,
            "brand_id": brand_id,
            "followers_count": to_int_or_none(get_mapped_value(row, field_map, "followers")),
            "likes_count": to_int_or_none(get_mapped_value(row, field_map, "likes")),
            "shares_count": to_int_or_none(get_mapped_value(row, field_map, "shares")),
            "author_name": get_mapped_value(row, field_map, "author_name"),
            "author_gender": get_mapped_value(row, field_map, "gender"),
            "city": city,
            "state": state,
            "raw_metadata": raw,
        }

    def process_frame(self, df, filename, existing_ids, needs_date_ids, brand_ids, matchers, on_progress=None, forced_brand=None):
        """Insert the new rows of one file. Returns a dict of counts."""
        def progress(fraction, message=""):
            if on_progress:
                on_progress(min(max(fraction, 0.0), 1.0), message)

        self.log(f"--- {filename} ---  {len(df)} rows")
        profile_name = detect_profile(df, filename)
        profile = SOURCE_PROFILES[profile_name]

        # a brand named in the file name wins; otherwise each row is matched on its own
        file_brand = forced_brand if forced_brand in brand_ids else bs.brand_from_filename(filename, matchers)
        data_source_id, _ = self.get_or_create_data_source(filename, profile_name, brand_ids.get(file_brand))
        brand_columns = [c for c in df.columns if str(c).strip().lower() in bs.BRAND_COLUMN_NAMES]
        text_column = profile["field_map"].get("text")
        text_column = text_column[0] if isinstance(text_column, list) else text_column
        by_brand = {}

        def brand_for(row):
            if file_brand:
                return file_brand
            for col in brand_columns:
                hit = bs.brand_from_value(row.get(col), matchers)
                if hit:
                    return hit
            if text_column and text_column in row.index:
                return bs.brand_from_text(str(row[text_column]) if pd.notna(row[text_column]) else "", matchers)
            return None

        new_records, backfill = [], []
        skipped_unusable = skipped_dup = undated = 0
        total = max(len(df), 1)
        for n, (_, row) in enumerate(df.iterrows()):
            if n % 500 == 0:
                progress(0.3 * n / total, "Reading rows")
            brand_name = brand_for(row) if matchers else None
            record = self.build_conversation_record(row, profile, data_source_id, filename, brand_ids.get(brand_name))
            if record is None:
                skipped_unusable += 1
                continue
            message_id = record["source_message_id"]
            has_date = record["conversation_date"] is not None
            if not has_date:
                undated += 1
            if message_id in existing_ids:
                skipped_dup += 1
                if has_date and message_id in needs_date_ids:
                    backfill.append({"id": message_id, "d": record["conversation_date"]})
                    needs_date_ids.discard(message_id)
                continue
            new_records.append(record)
            existing_ids.add(message_id)
            key = brand_name or "(no brand)"
            by_brand[key] = by_brand.get(key, 0) + 1

        inserted, failed = 0, 0
        for batch in chunked(new_records, BATCH_SIZE):
            try:
                self.sb.table("conversations").insert(batch).execute()
                inserted += len(batch)
            except Exception as e:
                failed += len(batch)
                self.log(f"batch failed ({len(batch)} rows): {e}")
            progress(0.3 + 0.65 * (inserted + failed) / max(len(new_records), 1), "Saving rows")

        backfilled = 0
        for batch in chunked(backfill, RPC_BATCH_SIZE):
            try:
                res = self.sb.rpc("apply_real_dates", {"p_tenant": self.tenant_id, "p_rows": batch}).execute()
                backfilled += res.data if isinstance(res.data, int) else len(batch)
            except Exception as e:
                self.log(f"date backfill failed ({len(batch)} rows): {e}")
        progress(1.0, "Done")
        return {"rows": int(len(df)), "inserted": inserted, "failed": failed, "duplicates": skipped_dup,
                "unusable": skipped_unusable, "undated": undated, "backfilled": backfilled,
                "by_brand": by_brand, "profile": profile_name}

    def refresh_categories(self) -> int:
        """Copy Sprinklr's category fields for new conversations (batches until nothing is left)."""
        processed = 0
        for _ in range(200):
            batch = self.sb.rpc("refresh_categories", {"p_tenant": self.tenant_id}).execute().data or 0
            processed += batch
            if batch == 0:
                break
        return processed


MIME_TYPES = {
    ".xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    ".csv": "text/csv",
    ".json": "application/json",
    ".ndjson": "application/x-ndjson",
}


def safe_file_name(name: str) -> str:
    keep = "".join(c if (c.isalnum() or c in "._- ") else "_" for c in Path(name).name)
    return keep.strip() or "upload"


def process_uploads(admin, tenant_id, user_id, user_email, files, on_progress=None):
    """Store the original files, then load them. files = [(file name, bytes)] or [(file name, bytes, brand name)]
    where the brand says which brand the whole file is about (None = work it out per row).
    One audit row per file in uploaded_files. Returns one result dict per file.
    admin is a service-role client; tenant_id must come from the signed-in user's membership, never from user input."""
    import uuid

    def progress(i, n, fraction, message):
        if on_progress:
            on_progress(i, n, fraction, message)

    ing = Ingestor(admin, tenant_id)
    definitions = bs.load_brand_definitions(admin, tenant_id)
    matchers = bs.build_matchers(definitions)
    brand_ids = ing.fetch_brand_ids()
    existing_ids = ing.fetch_existing_message_ids()
    needs_date_ids = ing.fetch_ids_needing_dates()

    results = []
    for i, item in enumerate(files):
        name, data = item[0], item[1]
        forced = item[2] if len(item) > 2 else None
        file_id = str(uuid.uuid4())
        path = f"{tenant_id}/{file_id}/{safe_file_name(name)}"
        row = {"id": file_id, "tenant_id": tenant_id, "uploaded_by": user_id, "uploaded_by_email": user_email,
               "file_name": name, "size_bytes": len(data), "status": "processing"}
        result = {"file": name, "status": "failed", "error": None}
        try:
            if len(data) > MAX_FILE_BYTES:
                raise ValueError(f"{name} is larger than {MAX_FILE_BYTES // (1024 * 1024)} MB.")
            progress(i, len(files), 0.0, f"Storing {name}")
            try:
                admin.storage.from_("uploads").upload(
                    path, data, {"content-type": MIME_TYPES.get(Path(name).suffix.lower(), "application/octet-stream")})
            except Exception as e:
                raise RuntimeError(f"The original file could not be stored ({e}). Has the uploads SQL been run?") from e
            row["storage_path"] = path
            admin.table("uploaded_files").insert(row).execute()
            df = read_bytes(name, data)
            res = ing.process_frame(df, name, existing_ids, needs_date_ids, brand_ids, matchers,
                                    on_progress=lambda f, m, i=i: progress(i, len(files), f, m),
                                    forced_brand=forced)
            admin.table("uploaded_files").update({
                "status": "done", "source_profile": res["profile"], "rows_total": res["rows"],
                "rows_new": res["inserted"], "rows_duplicate": res["duplicates"], "rows_undated": res["undated"],
                "brand_summary": res["by_brand"],
            }).eq("id", file_id).execute()
            result = {"file": name, "status": "done", **res}
        except Exception as e:
            result["error"] = str(e)
            try:
                admin.table("uploaded_files").update({"status": "failed", "error": str(e)[:500]}).eq("id", file_id).execute()
            except Exception:
                pass
        results.append(result)

    try:
        ing.refresh_categories()
    except Exception as e:
        results.append({"file": "(categories)", "status": "warning", "error": f"Category extraction skipped: {e}"})
    return results
