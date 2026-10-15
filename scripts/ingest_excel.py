"""
Command-line ingestion: loads every file in data/ for one tenant.
The loading logic itself lives in app/ingest_core.py (shared with the Data & Brand Selection page).

  python scripts/ingest_excel.py                       use the brands already set up
  python scripts/ingest_excel.py --own "TVS RTX 300 (rtx)" --competitors "Hero Xpulse 200 (xpulse), KTM 390 Adventure (ktm)" --industry "Two-wheelers"
  python scripts/ingest_excel.py --detect --industry "Two-wheelers"      list the brands found, write brand_setup.json
  python scripts/ingest_excel.py --setup brand_setup.json                load using the confirmed list

Needs SUPABASE_URL, SUPABASE_SERVICE_ROLE_KEY and TENANT_ID in .env.
Save as: scripts/ingest_excel.py
"""
import argparse
import json
import os
import sys
from pathlib import Path

import pandas as pd
from dotenv import load_dotenv
from supabase import create_client

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "app"))   # ingest_core.py and brand_setup.py live in app/
import brand_setup as bs
import ingest_core as core

load_dotenv()
TENANT_ID = os.environ["TENANT_ID"]
sb = create_client(os.environ["SUPABASE_URL"], os.environ["SUPABASE_SERVICE_ROLE_KEY"])
DATA_DIR = Path("data")


def list_files():
    return sorted(p for p in DATA_DIR.iterdir()
                  if p.is_file() and p.suffix.lower() in core.SUPPORTED_EXTENSIONS and not p.name.startswith("~$"))


def run_detect(files, industry, use_ai, out_path):
    known = bs.load_brand_definitions(sb, TENANT_ID)
    frames, text_col = [], None
    for path in files:
        try:
            df = core.read_any(path)
            col = core.text_column_of(df, path.name)
        except Exception as e:
            print(f"  skipped {path.name}: {e}")
            continue
        text_col = text_col or col
        frames.append(df)
    if not frames:
        print("Nothing to scan.")
        return
    df = pd.concat(frames, ignore_index=True)
    ai_names = []
    if use_ai:
        print("Asking Gemini for brand names (one call) ...")
        ai_names = bs.ai_suggest_brands(industry, df[text_col].dropna().astype(str).tolist())
        print(f"  Gemini suggested {len(ai_names)} name(s)." if ai_names else "  No AI suggestions (key missing or call failed).")
    found = bs.detect_brands(df, text_column=text_col, known_brands=known, ai_names=ai_names)
    doc = bs.make_setup_document(industry, found)
    Path(out_path).write_text(json.dumps(doc, indent=2), encoding="utf-8")
    print(f"\nBrands identified in {len(df):,} rows ({industry or 'industry not given'}):")
    for b in doc["brands"]:
        print(f"  [{'x' if b['include'] else ' '}] {b['name']:<34} {b['mentions']:>7,}  {b['confidence']:<6}  {b['found_in']}")
    print(f"\nWrote {out_path}. Set \"include\": true on the real brands, fill in \"own_brand\", "
          f"then run:  python scripts/ingest_excel.py --setup {out_path}")


def main():
    ap = argparse.ArgumentParser(description="Ingest export files and set up the brands to track.")
    ap.add_argument("--own", help='Own brand, e.g. "TVS RTX 300 (rtx, rtx300)"')
    ap.add_argument("--competitors", help="Competitor brands, comma separated; aliases in brackets")
    ap.add_argument("--industry", help='Industry, e.g. "Two-wheelers"')
    ap.add_argument("--detect", action="store_true", help="Scan the files, list the brands found, write the setup file, stop")
    ap.add_argument("--use-ai", action="store_true", help="With --detect: also ask Gemini for brand names")
    ap.add_argument("--setup", help="Ingest using a confirmed setup file (from --detect)")
    ap.add_argument("--setup-file", default="brand_setup.json", help="Where --detect writes (default brand_setup.json)")
    args = ap.parse_args()

    if not DATA_DIR.exists():
        print(f"No '{DATA_DIR}' folder found -- create it and add your export files.")
        return
    files = list_files()
    if not files:
        print(f"No supported files found in {DATA_DIR}/")
        return
    if args.detect:
        run_detect(files, args.industry or "", args.use_ai, args.setup_file)
        return

    industry, own_name, wanted = args.industry or "", None, []
    if args.setup:
        industry2, own_name, wanted = bs.read_setup_document(json.loads(Path(args.setup).read_text(encoding="utf-8")))
        industry = industry or industry2
    if args.own:
        own = bs.parse_brand_text(args.own)
        if own:
            own_name = own[0]["name"]
            wanted = own[:1] + wanted
    if args.competitors:
        wanted += bs.parse_brand_text(args.competitors)
    if wanted or industry:
        bs.save_brands(sb, TENANT_ID, wanted, own_name=own_name, industry=industry)

    ing = core.Ingestor(sb, TENANT_ID, log=print)
    definitions = bs.load_brand_definitions(sb, TENANT_ID)
    matchers = bs.build_matchers(definitions)
    brand_ids = ing.fetch_brand_ids()
    print(f"{len(definitions)} brand(s) active: {', '.join(d['name'] for d in definitions) or 'none'}")
    if not matchers:
        print("NOTE: no brands are set up, so rows will have no brand. Use --own/--competitors or --detect.")

    print("Fetching already-ingested message IDs for this tenant ...")
    existing_ids = ing.fetch_existing_message_ids()
    needs_date_ids = ing.fetch_ids_needing_dates()
    print(f"{len(existing_ids)} already ingested; {len(needs_date_ids)} of them have no real date yet")

    totals = {"inserted": 0, "duplicates": 0, "unusable": 0, "undated": 0, "backfilled": 0}
    for path in files:
        try:
            df = core.read_any(path)
            res = ing.process_frame(df, path.name, existing_ids, needs_date_ids, brand_ids, matchers)
        except Exception as e:
            print(f"  SKIPPED {path.name} -- {e}")
            continue
        print(f"  {res['inserted']} new, {res['duplicates']} already existed, {res['unusable']} skipped; "
              f"brands: " + ", ".join(f"{k} {v}" for k, v in sorted(res['by_brand'].items(), key=lambda kv: -kv[1])))
        for k in totals:
            totals[k] += res[k]
    try:
        print(f"\nSprinklr categories extracted for {ing.refresh_categories()} conversation(s).")
    except Exception as e:
        print(f"\n  NOTE: category extraction skipped ({e}). Run the Attribute SQL in Supabase first.")
    print(f"\nDone. Inserted {totals['inserted']}, duplicates skipped {totals['duplicates']}, "
          f"unusable rows skipped {totals['unusable']}, undated rows {totals['undated']}, dates filled in {totals['backfilled']}.")


if __name__ == "__main__":
    main()
