"""
iThink brand setup
------------------
Everything needed to make the platform work for ANY brand, with no brand names hard-coded.
Shared by the ingestion script today and by the upload page later.

Two ways to tell the platform which brands matter:

  Option 1 - the user types them:
      own brand:    TVS RTX 300 (rtx, rtx300)
      competitors:  Hero Xpulse 200 (xpulse), Royal Enfield Himalayan 450, KTM 390 Adventure (ktm)
      (text in brackets = optional aliases; commas or new lines separate brands)

  Option 2 - the platform reads the uploaded file(s) and proposes the brands it finds, together
      with an industry entered by the user. The user ticks the ones that matter and picks the own brand.

Both end in the same place: rows in `brands` and `brand_aliases` for the tenant, and every
conversation tagged with a brand.

Save as: scripts/brand_setup.py
"""
import json
import os
import re
import urllib.request
from collections import Counter

import pandas as pd

# ---------------------------------------------------------------- Option 1: parse typed brands
def _split_top_level(text: str):
    """Split on commas / new lines that are not inside brackets."""
    parts, buf, depth = [], [], 0
    for ch in text or "":
        if ch in "([":
            depth += 1
        elif ch in ")]":
            depth = max(0, depth - 1)
        if ch in ",\n;" and depth == 0:
            parts.append("".join(buf))
            buf = []
        else:
            buf.append(ch)
    parts.append("".join(buf))
    return [p.strip() for p in parts if p.strip()]


def parse_brand_text(text: str):
    """'Hero Xpulse 200 (xpulse, hero xp), KTM 390 Adventure' ->
       [{'name': 'Hero Xpulse 200', 'aliases': ['xpulse', 'hero xp']}, {'name': 'KTM 390 Adventure', 'aliases': []}]"""
    out, seen = [], set()
    for part in _split_top_level(text):
        m = re.match(r"^(.*?)\s*[\(\[](.*)[\)\]]\s*$", part)
        name, alias_text = (m.group(1), m.group(2)) if m else (part, "")
        name = re.sub(r"\s+", " ", name).strip()
        if not name or name.lower() in seen:
            continue
        seen.add(name.lower())
        aliases = [a.strip() for a in re.split(r"[,|/]", alias_text) if a.strip()]
        out.append({"name": name, "aliases": aliases})
    return out


def all_aliases(name: str, aliases):
    """The name itself, the user's aliases, and the hashtag-style form without spaces."""
    terms = [name] + list(aliases or [])
    collapsed = re.sub(r"\s+", "", name)
    if collapsed.lower() != name.lower() and len(collapsed) >= 4:
        terms.append(collapsed)
    seen, out = set(), []
    for t in terms:
        t = t.strip()
        if len(t) >= 2 and t.lower() not in seen:
            seen.add(t.lower())
            out.append(t)
    return out


# ---------------------------------------------------------------- matching text to brands
def _term_regex(term: str):
    pieces = [re.escape(p) for p in re.split(r"[\s\-_]+", term.strip()) if p]
    return r"(?<![A-Za-z0-9])" + r"[\s\-_]*".join(pieces) + r"(?![A-Za-z0-9])"


def build_matchers(brands):
    """brands: [{'name', 'aliases'}]  ->  [(name, compiled regex over name + aliases)]"""
    matchers = []
    for b in brands:
        terms = all_aliases(b["name"], b.get("aliases"))
        if terms:
            pattern = "|".join(_term_regex(t) for t in sorted(terms, key=len, reverse=True))
            matchers.append((b["name"], re.compile(pattern, re.IGNORECASE)))
    return matchers


def brand_from_text(text, matchers):
    """The brand mentioned most often; ties go to the one mentioned first. None when none is mentioned."""
    if not text:
        return None
    best, best_key = None, None
    for name, rx in matchers:
        hits = list(rx.finditer(text))
        if hits:
            key = (-len(hits), hits[0].start())
            if best_key is None or key < best_key:
                best, best_key = name, key
    return best


def brand_from_filename(filename, matchers):
    """A brand whose name/alias appears in the file name - only when exactly one does."""
    stem = os.path.splitext(os.path.basename(filename or ""))[0].replace("_", " ").replace("-", " ")
    found = {name for name, rx in matchers if rx.search(stem)}
    return found.pop() if len(found) == 1 else None


def brand_from_value(value, matchers):
    """A brand column / topic cell: a brand if it matches exactly one brand."""
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return None
    found = {name for name, rx in matchers if rx.search(str(value))}
    return found.pop() if len(found) == 1 else None


# ---------------------------------------------------------------- Option 2: find brands in a file
BRAND_COLUMN_NAMES = {"brand", "brands", "brand name", "product", "product name", "model", "entity",
                      "topic", "keyword", "keywords", "listening topic", "campaign", "competitor"}
_STOP = set("""the this that and but for with just its it i we you they he she my our your what when why how who not
now yes no please thanks thank hi hello good great love best new one also all any are is was were can will do does
did if so or in on at to of as by from have has had be been more most very too got get here there then than these
those some such only even still much many other another every each both few less like look let make made see said
say says take think want ill im ive its lol omg wow ok okay yeah hey sir bro today yesterday tomorrow monday tuesday
wednesday thursday friday saturday sunday january february march april may june july august september october
november december rt via pic http https www com""".split())
_PHRASE = re.compile(r"\b[A-Z][A-Za-z0-9]+(?:[ \-][A-Z0-9][A-Za-z0-9]*){0,3}\b")
_HASHTAG = re.compile(r"#([A-Za-z][A-Za-z0-9_]{2,})")


def _clean_phrase(phrase: str):
    tokens = phrase.split()
    while tokens and tokens[0].lower() in _STOP:
        tokens.pop(0)
    while tokens and tokens[-1].lower() in _STOP:
        tokens.pop()
    return " ".join(tokens) if tokens else ""


def _split_cell(value):
    return [p.strip() for p in re.split(r"[;|,]", str(value)) if p.strip()]


def detect_brands(df: pd.DataFrame, text_column=None, known_brands=None, ai_names=None, max_brands=20):
    """Scan an uploaded table and propose brands. Returns [{'name','mentions','evidence','confidence'}],
    best first. Nothing is saved - the user confirms the list.
      * columns named brand / product / model / topic ...   -> high confidence
      * brands already known for the tenant, found in text    -> high
      * names suggested by AI (optional, already computed)    -> medium
      * capitalised names that repeat in the text             -> low (the user prunes these)"""
    n = len(df)
    found = {}   # lower-case key -> dict

    def add(name, mentions, evidence, confidence):
        key = name.lower()
        if key in found:
            if mentions > found[key]["mentions"]:
                found[key].update(mentions=mentions)
            return
        found[key] = {"name": name, "mentions": int(mentions), "evidence": evidence, "confidence": confidence}

    # 1. brand-like columns
    for col in df.columns:
        if str(col).strip().lower() in BRAND_COLUMN_NAMES:
            counts = Counter()
            for v in df[col].dropna():
                counts.update(_split_cell(v))
            for name, c in counts.most_common(30):
                if len(name) <= 60:
                    add(name, c, f"column '{col}'", "high")

    texts = []
    if text_column and text_column in df.columns:
        texts = [str(t) for t in df[text_column].dropna().tolist()]

    # 2. brands the tenant already has
    if known_brands and texts:
        matchers = build_matchers(known_brands)
        counts = Counter()
        for t in texts:
            for name, rx in matchers:
                if rx.search(t):
                    counts[name] += 1
        for name, c in counts.items():
            add(name, c, "already set up", "high")

    # 3. AI suggestions
    for name in ai_names or []:
        if texts:
            rx = re.compile(_term_regex(name), re.IGNORECASE)
            c = sum(1 for t in texts if rx.search(t))
        else:
            c = 0
        if c or not texts:
            add(name, c, "suggested by AI", "medium")

    # 4. repeated capitalised names and hashtags
    if texts:
        floor = max(5, int(0.003 * len(texts)))
        phrases, initial, tags = Counter(), Counter(), Counter()
        for t in texts:
            seen, at_start = set(), set()
            for m in _PHRASE.finditer(t):
                p = _clean_phrase(m.group(0))
                if len(p) >= 3 and p.lower() not in _STOP:
                    seen.add(p)
                    if not t[:m.start()].strip() or t[:m.start()].rstrip()[-1:] in ".!?":
                        at_start.add(p)
            phrases.update(seen)
            initial.update(at_start)
            tags.update({h.lower() for h in _HASHTAG.findall(t)})
        for p, c in phrases.most_common(60):
            # a plain word that nearly always opens a sentence ("Honestly", "Thanks") is not a name
            plain = " " not in p and not any(ch.isdigit() for ch in p) and not p.isupper()
            if c >= floor and not (plain and initial[p] / c > 0.6):
                add(p, c, "repeated name in text", "low")
        for h, c in tags.most_common(15):
            if c >= floor:
                add(h, c, "hashtag", "low")

    rank = {"high": 0, "medium": 1, "low": 2}
    def shape(d):   # names that look like products (several words, or digits) before single plain words
        n = d["name"]
        return 0 if (" " in n or any(ch.isdigit() for ch in n)) else 1

    ordered = sorted(found.values(), key=lambda d: (rank[d["confidence"]], shape(d), -d["mentions"]))
    return ordered[:max_brands]


def ai_suggest_brands(industry: str, texts, api_key=None, model="gemini-3.1-flash-lite", sample=150):
    """Optional: ask Gemini which brands/products these posts are about. One call. Returns [] on any failure."""
    api_key = api_key or os.environ.get("GEMINI_API_KEY")
    if not api_key or not texts:
        return []
    picked = [str(t)[:280] for t in texts[:: max(1, len(texts) // sample)]][:sample]
    prompt = (
        f"These are social media posts from the '{industry or 'consumer'}' industry. List the brands or specific "
        "products they discuss, most discussed first, at most 15. Use the full product name where one is given "
        "(for example 'KTM 390 Adventure', not just 'KTM'). Reply with a JSON array of strings only.\n\n"
        + "\n".join(f"- {t}" for t in picked)
    )
    body = json.dumps({
        "contents": [{"parts": [{"text": prompt}]}],
        "generationConfig": {"responseMimeType": "application/json", "temperature": 0},
    }).encode()
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key={api_key}"
    try:
        req = urllib.request.Request(url, data=body, headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=60) as resp:
            payload = json.load(resp)
        text = payload["candidates"][0]["content"]["parts"][0]["text"]
        names = json.loads(text)
        return [str(n).strip() for n in names if isinstance(n, str) and n.strip()][:15]
    except Exception:
        return []


# ---------------------------------------------------------------- the setup document (what the user confirms)
def make_setup_document(industry, detected):
    """Template the user edits: tick 'include' on real brands, name the own brand. The same shape
    drives the upload page later."""
    return {
        "industry": industry or "",
        "own_brand": None,
        "brands": [
            {"name": d["name"], "aliases": [], "mentions": d["mentions"], "found_in": d["evidence"],
             "confidence": d["confidence"], "include": d["confidence"] == "high"}
            for d in detected
        ],
    }


def read_setup_document(doc: dict):
    """-> (industry, own_name, [{'name','aliases'}]). Brands with include=false are dropped."""
    brands = [{"name": b["name"], "aliases": b.get("aliases") or []}
              for b in doc.get("brands", []) if b.get("include", True)]
    own = (doc.get("own_brand") or "").strip() or None
    if own and own.lower() not in {b["name"].lower() for b in brands}:
        brands.insert(0, {"name": own, "aliases": []})
    return (doc.get("industry") or "").strip(), own, brands


# ---------------------------------------------------------------- saving to the database
def save_brands(sb, tenant_id: str, brands, own_name=None, industry=None):
    """Create any missing brands and aliases for the tenant (case-insensitive on name). The own brand becomes
    the tenant default; each user can still switch their own view. Returns {brand name: brand id}."""
    existing = sb.table("brands").select("id, brand_name").eq("tenant_id", tenant_id).execute().data or []
    ids = {r["brand_name"].lower(): r["id"] for r in existing}
    canonical = {r["brand_name"].lower(): r["brand_name"] for r in existing}
    result = {}

    for b in brands:
        key = b["name"].lower()
        if key not in ids:
            row = sb.table("brands").insert({"tenant_id": tenant_id, "brand_name": b["name"],
                                             "is_own_brand": False}).execute().data[0]
            ids[key], canonical[key] = row["id"], b["name"]
        result[canonical[key]] = ids[key]
        have = sb.table("brand_aliases").select("alias").eq("brand_id", ids[key]).execute().data or []
        have_set = {r["alias"].lower() for r in have}
        fresh = [a for a in all_aliases(canonical[key], b.get("aliases")) if a.lower() not in have_set]
        if fresh:
            sb.table("brand_aliases").insert(
                [{"tenant_id": tenant_id, "brand_id": ids[key], "alias": a} for a in fresh]
            ).execute()

    if own_name:
        own_id = ids.get(own_name.lower())
        if own_id:
            sb.table("brands").update({"is_own_brand": False}).eq("tenant_id", tenant_id).execute()
            sb.table("brands").update({"is_own_brand": True}).eq("id", own_id).execute()
    if industry:
        try:
            sb.table("tenants").update({"industry": industry}).eq("id", tenant_id).execute()
        except Exception:
            pass   # migration not run yet
    return result


def load_brand_definitions(sb, tenant_id: str):
    """Existing brands + aliases for the tenant, in the same shape as parse_brand_text."""
    rows = sb.table("brands").select("id, brand_name").eq("tenant_id", tenant_id).execute().data or []
    aliases = sb.table("brand_aliases").select("brand_id, alias").execute().data or []
    by_brand = {}
    for a in aliases:
        by_brand.setdefault(a["brand_id"], []).append(a["alias"])
    return [{"name": r["brand_name"], "aliases": by_brand.get(r["id"], [])} for r in rows]
