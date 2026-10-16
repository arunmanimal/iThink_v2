"""
iThink - Data & Brand Selection page
------------------------------------
Upload export files, choose which brands to track (type them, or let the platform find them), and keep an
audit trail of every file with a download link.

Three steps on one page:  1 Upload  ->  2 Brands  ->  3 Review and process.   Below them: Uploaded files.

Anyone signed in to a tenant can use it. Writes go through a service-role client that is fixed to the
signed-in user's own tenant (taken from their membership, never from a form field).

Save as: app/data_page.py   (needs brand_setup.py, ingest_core.py and theme.py in the same folder)
"""
from datetime import datetime

import pandas as pd
import streamlit as st

import brand_setup as bs
import ingest_core as core
import theme

ACCEPT = ["xlsx", "csv", "json", "ndjson"]


# ---------------------------------------------------------------- cached file reading
@st.cache_data(show_spinner=False, max_entries=4)
def _read(name: str, data: bytes) -> pd.DataFrame:
    return core.read_bytes(name, data)


@st.cache_data(show_spinner=False, max_entries=16)
def _inspect(name: str, data: bytes) -> dict:
    return core.inspect_frame(_read(name, data), name)


@st.cache_data(ttl=300, show_spinner=False)
def _signed_url(_admin, path: str):
    try:
        res = _admin.storage.from_("uploads").create_signed_url(path, 900)
        return res.get("signedURL") or res.get("signedUrl")
    except Exception:
        return None


# ---------------------------------------------------------------- saved brands
def _load_saved(ctx):
    """{'defs': [{'name','aliases'}], 'industry': str} for this tenant, cached for the session."""
    cached = st.session_state.get("dp_saved")
    if cached is not None:
        return cached
    defs = []
    try:
        if ctx["admin"] is not None:
            defs = bs.load_brand_definitions(ctx["admin"], ctx["tenant_id"])
        else:
            defs = [{"name": b, "aliases": []} for b in ctx["opts"].get("brands", [])]
    except Exception:
        defs = [{"name": b, "aliases": []} for b in ctx["opts"].get("brands", [])]
    industry = ""
    try:
        rows = ctx["sb"].table("tenants").select("industry").eq("id", ctx["tenant_id"]).execute().data or []
        industry = (rows[0].get("industry") or "") if rows else ""
    except Exception:
        pass
    saved = {"defs": defs, "industry": industry}
    st.session_state["dp_saved"] = saved
    return saved


def _extra_aliases(defn):
    auto = {a.lower() for a in bs.all_aliases(defn["name"], [])}
    return [a for a in defn.get("aliases", []) if a.lower() not in auto]


def _brand_line(defn):
    extra = _extra_aliases(defn)
    return f"{defn['name']} ({', '.join(extra)})" if extra else defn["name"]


def _seed_editor(saved, own_name):
    """Fill the text boxes from what is saved (called when Edit is pressed)."""
    own = next((d for d in saved["defs"] if d["name"] == own_name), None)
    others = [d for d in saved["defs"] if d is not own]
    st.session_state["bs_own"] = _brand_line(own) if own else ""
    st.session_state["bs_comp"] = "\n".join(_brand_line(d) for d in others)
    st.session_state["bs_ind1"] = saved["industry"]
    st.session_state["bs_ind2"] = saved["industry"]


def _begin_edit(saved, own_name):
    _seed_editor(saved, own_name)
    st.session_state["dp_edit"] = True
    st.session_state.pop("dp_found", None)


def _cancel_edit():
    st.session_state["dp_edit"] = False


def _flash(kind, message):
    st.session_state["dp_flash"] = (kind, message)


def _set_own_for_user(ctx, name):
    """Make `name` this user's own brand (the same stored setting as the sidebar switcher)."""
    st.session_state["own_override"] = name
    try:
        rows = ctx["admin"].table("brands").select("id").eq("tenant_id", ctx["tenant_id"]).eq("brand_name", name).execute().data
        if rows:
            ctx["sb"].table("user_preferences").upsert(
                {"tenant_id": ctx["tenant_id"], "user_id": ctx["user_id"], "own_brand_id": rows[0]["id"]},
                on_conflict="tenant_id,user_id",
            ).execute()
    except Exception:
        pass   # the choice still applies for this session
    st.session_state.pop("f_own_brand", None)      # let the sidebar selector pick up the new value
    st.session_state.pop("filter_opts", None)


def _persist(ctx, brands, own_name, industry):
    try:
        bs.save_brands(ctx["admin"], ctx["tenant_id"], brands, own_name=own_name, industry=industry)
        _set_own_for_user(ctx, own_name)
        st.session_state.pop("dp_saved", None)
        st.session_state["dp_edit"] = False
        st.session_state.pop("dp_found", None)
        _flash("success", f"Saved {len(brands)} brand(s). {own_name} is your brand.")
    except Exception as e:
        _flash("error", f"Could not save the brands: {e}")


def _save_typed(ctx):
    own = bs.parse_brand_text(st.session_state.get("bs_own", ""))
    comps = bs.parse_brand_text(st.session_state.get("bs_comp", ""))
    if not own:
        _flash("error", "Enter your own brand first.")
        return
    own_name = own[0]["name"]
    brands = own[:1] + [c for c in comps if c["name"].lower() != own_name.lower()]
    _persist(ctx, brands, own_name, (st.session_state.get("bs_ind1") or "").strip())


def _save_detected(ctx):
    edited = st.session_state.get("dp_found_edited")
    own_name = st.session_state.get("dp_found_own")
    if edited is None or not own_name:
        _flash("error", "Tick the brands to track, then choose which one is yours.")
        return
    brands = []
    for _, r in edited.iterrows():
        if r["Track"] and str(r["Brand"]).strip():
            aliases = [a.strip() for a in str(r["Other names"] or "").split(",") if a.strip()]
            brands.append({"name": str(r["Brand"]).strip(), "aliases": aliases})
    if own_name.lower() not in {b["name"].lower() for b in brands}:
        _flash("error", "Your brand must be one of the ticked brands.")
        return
    _persist(ctx, brands, own_name, (st.session_state.get("bs_ind2") or "").strip())


def _merge(ctx):
    src, dst = st.session_state.get("tidy_src"), st.session_state.get("tidy_dst")
    if not src or not dst:
        _flash("error", "Choose the brand to merge and the brand to merge it into.")
        return
    try:
        ok, message = bs.merge_brands(ctx["admin"], ctx["tenant_id"], src, dst)
    except Exception as e:
        ok, message = False, f"Merge failed: {e}"
    if st.session_state.get("own_override") == src:
        st.session_state["own_override"] = dst
    _after_tidy()
    _flash("success" if ok else "error", message)


def _remove(ctx):
    src = st.session_state.get("tidy_src")
    if not src:
        _flash("error", "Choose the brand to remove.")
        return
    try:
        ok, message = bs.remove_brand(ctx["admin"], ctx["tenant_id"], src)
    except Exception as e:
        ok, message = False, f"Remove failed: {e}"
    _after_tidy()
    _flash("success" if ok else "error", message)


def _after_tidy():
    for key in ("dp_saved", "filter_opts", "f_own_brand", "tidy_src", "tidy_dst"):
        st.session_state.pop(key, None)
    st.cache_data.clear()


# ---------------------------------------------------------------- page
def render(sb, admin, membership, user, opts, on_data_changed):
    """sb: the signed-in user's client. admin: service-role client or None. on_data_changed(): clears dashboard caches."""
    tenant_id = membership["tenant_id"]
    ctx = {"sb": sb, "admin": admin, "tenant_id": tenant_id, "user_id": user.id, "opts": opts}
    saved = _load_saved(ctx)
    own_default = opts.get("own_brand") or opts.get("default_own")

    theme.page_header("Data & Brand Selection", "Add data files and choose which brands to track")

    flash = st.session_state.pop("dp_flash", None)
    if flash:
        (st.success if flash[0] == "success" else st.error)(flash[1])
    if admin is None:
        st.warning("Uploading is switched off because the app has no SUPABASE_SERVICE_ROLE_KEY in its secrets. "
                   "Brands and the file list below are read-only until it is added.")

    # ---------------- 1. upload
    theme.section_label("1. Upload your files")
    nonce = st.session_state.get("upload_nonce", 0)
    files = st.file_uploader("Excel, CSV or JSON exports (Sprinklr, Brandwatch). Several files are fine.",
                             type=ACCEPT, accept_multiple_files=True, key=f"uploader_{nonce}",
                             disabled=admin is None)
    matchers = bs.build_matchers(saved["defs"])
    inspected = []
    for f in files or []:
        data = f.getvalue()
        if len(data) > core.MAX_FILE_BYTES:
            inspected.append({"file": f.name, "error": f"Larger than {core.MAX_FILE_BYTES // (1024 * 1024)} MB.", "rows": 0})
            continue
        try:
            info = dict(_inspect(f.name, data))
            info["file_brand"] = bs.brand_from_filename(f.name, matchers) if matchers else None
        except Exception as e:
            info = {"file": f.name, "error": f"Could not read this file ({e}).", "rows": 0}
        inspected.append(info)
    detect_label = "Work it out from each row"
    brand_names = [d["name"] for d in saved["defs"]]
    file_brands = {}
    for info in inspected:
        with st.container(border=True):
            if info.get("error"):
                st.markdown(f"**{info['file']}**  :red[{info['error']}]")
                continue
            parts = [f"**{info['file']}**", f":green[{info['profile'].title()} detected]", f"{info['rows']:,} rows"]
            if info.get("undated"):
                parts.append(f":orange[{info['undated']:,} rows without a date]")
            st.markdown("  \u00b7  ".join(parts))
            if brand_names:
                options = [detect_label] + brand_names
                guess = info.get("file_brand")
                choice = st.selectbox(
                    "Which brand is this file about?", options, key=f"fb_{nonce}_{info['file']}",
                    index=options.index(guess) if guess in options else 0,
                    help="Pick a brand if the whole file is about one. Otherwise each row is matched on the brand "
                         "names in its text.")
                file_brands[info["file"]] = None if choice == detect_label else choice
    readable = [f for f, info in zip(files or [], inspected) if not info.get("error")]

    # ---------------- 2. brands
    theme.section_label("2. Brands to track")
    editing = st.session_state.get("dp_edit", False) or not saved["defs"]
    if not saved["defs"] and "bs_own" not in st.session_state:
        for key in ("bs_own", "bs_comp", "bs_ind1", "bs_ind2"):
            st.session_state[key] = ""

    if saved["defs"] and not editing:
        with st.container(border=True):
            left, right = st.columns([5, 1])
            with left:
                st.markdown(f"**Industry:** {saved['industry'] or 'not set'}")
                theme.filter_chips(
                    [("Your brand", own_default or "not chosen")]
                    + [("Competitor", d["name"]) for d in saved["defs"] if d["name"] != own_default]
                )
                theme.note("Change which brand is yours at any time from Your brand in the sidebar.")
            with right:
                st.button("Edit", key="dp_edit_btn", on_click=_begin_edit, args=(saved, own_default),
                          disabled=admin is None)
    elif admin is not None:
        if not saved["defs"]:
            st.info("No brands are set up yet. Choose one of the two ways below.")
        else:
            st.caption("Brands already saved stay in place. Add new brands or extra names for existing ones.")
        tab_type, tab_find = st.tabs(["I will type them", "Find them in my files"])
        with tab_type:
            c1, c2 = st.columns(2, gap="medium")
            with c1:
                st.text_input("Own brand", key="bs_own", placeholder="TVS RTX 300 (rtx)",
                              help="Other names people use go in brackets.")
            with c2:
                st.text_area("Competitor brands", key="bs_comp", height=110,
                             placeholder="Hero Xpulse 200 (xpulse)\nKTM 390 Adventure (ktm)",
                             help="One per line, or separated by commas.")
            st.text_input("Industry", key="bs_ind1", placeholder="Two-wheelers")
            st.button("Save brands", type="primary", key="dp_save_typed", on_click=_save_typed, args=(ctx,))
        with tab_find:
            st.text_input("Industry", key="bs_ind2", placeholder="Two-wheelers")
            use_ai = False
            if "GEMINI_API_KEY" in st.secrets:
                use_ai = st.checkbox("Also ask AI to suggest brand names", key="dp_use_ai")
            if st.button("Find brands in my files", key="dp_find", disabled=not readable):
                with st.spinner("Reading your files"):
                    frames, text_col = [], None
                    for f in readable:
                        df = _read(f.name, f.getvalue())
                        frames.append(df)
                        text_col = text_col or core.text_column_of(df, f.name)
                    merged = pd.concat(frames, ignore_index=True)
                    ai_names = []
                    if use_ai:
                        ai_names = bs.ai_suggest_brands(st.session_state.get("bs_ind2", ""),
                                                        merged[text_col].dropna().astype(str).tolist(),
                                                        api_key=st.secrets["GEMINI_API_KEY"])
                    found = bs.detect_brands(merged, text_column=text_col, known_brands=saved["defs"], ai_names=ai_names)
                    st.session_state["dp_found"] = {"rows": int(len(merged)), "found": found}
            if not readable:
                st.caption("Add a file in step 1 first.")
            found = st.session_state.get("dp_found")
            if found:
                if not found["found"]:
                    st.warning("No brands could be identified. Use the other tab to type them.")
                else:
                    st.caption(f"Scanned {found['rows']:,} rows. Tick the brands that matter, edit names if needed, "
                               "then choose which one is yours.")
                    table = pd.DataFrame([{
                        "Track": d["confidence"] == "high",
                        "Brand": d["name"],
                        "Other names": ", ".join(d.get("aliases", [])),
                        "Mentions": d["mentions"],
                        "Found in": d["evidence"],
                    } for d in found["found"]])
                    edited = st.data_editor(
                        table, hide_index=True, key="dp_found_editor", use_container_width=True,
                        disabled=["Mentions", "Found in"],
                        column_config={"Track": st.column_config.CheckboxColumn("Track"),
                                       "Mentions": st.column_config.NumberColumn("Mentions", format="%d")},
                    )
                    st.session_state["dp_found_edited"] = edited
                    tracked = [str(b) for b, t in zip(edited["Brand"], edited["Track"]) if t and str(b).strip()]
                    st.selectbox("Which one is your brand?", tracked, key="dp_found_own",
                                 index=tracked.index(own_default) if own_default in tracked else None,
                                 placeholder="Choose your brand")
                    st.button("Save brands", type="primary", key="dp_save_found", on_click=_save_detected, args=(ctx,))
        if len(saved["defs"]) > 1:
            with st.expander("Tidy brands: merge a duplicate or remove an unused brand"):
                st.caption("Use this when the same brand was saved twice under different names. Merging moves all of "
                           "its conversations and names into the brand you keep, then removes the duplicate.")
                names = [d["name"] for d in saved["defs"]]
                t1, t2 = st.columns(2, gap="medium")
                with t1:
                    st.selectbox("Brand to merge or remove", names, key="tidy_src", index=None, placeholder="Choose a brand")
                with t2:
                    keep = [n for n in names if n != st.session_state.get("tidy_src")]
                    st.selectbox("Merge into (the brand to keep)", keep, key="tidy_dst", index=None, placeholder="Choose a brand")
                b1, b2, _ = st.columns([1, 1, 3])
                b1.button("Merge", key="dp_merge", type="primary", on_click=_merge, args=(ctx,))
                b2.button("Remove", key="dp_remove", on_click=_remove, args=(ctx,),
                          help="Only works for a brand with no conversations.")
        if saved["defs"]:
            st.button("Cancel", key="dp_cancel", on_click=_cancel_edit)

    # ---------------- 3. review and process
    theme.section_label("3. Review and process")
    last = st.session_state.get("dp_last")
    if last:
        for r in last:
            if r["status"] == "done":
                st.markdown(f":green[Done] **{r['file']}**: {r['inserted']:,} new rows, {r['duplicates']:,} already loaded, "
                            f"{r['unusable']:,} skipped, {r['undated']:,} without a date.")
            else:
                st.markdown(f":red[{'Warning' if r['status'] == 'warning' else 'Failed'}] **{r['file']}**: {r['error']}")
    if not readable:
        st.caption("Add one or more files in step 1 to continue.")
    elif not saved["defs"]:
        st.warning("Save your brands in step 2 first, so every row can be given a brand.")
    else:
        total_rows = sum(i["rows"] for i in inspected if not i.get("error"))
        theme.filter_chips([("Files", str(len(readable))), ("Rows", f"{total_rows:,}"),
                            ("Brands", str(len(saved["defs"]))), ("Your brand", own_default or "not chosen")])
        theme.note("New rows are added; rows that were loaded before are skipped. Keep this page open while files are processed.")
        if st.button("Process files", type="primary", key="dp_process", disabled=admin is None):
            bar = st.progress(0.0, text="Starting")

            def cb(i, n, fraction, message):
                bar.progress(min(1.0, (i + fraction) / max(n, 1)), text=f"File {i + 1} of {n}: {message}")

            results = core.process_uploads(admin, tenant_id, user.id, user.email,
                                           [(f.name, f.getvalue(), file_brands.get(f.name)) for f in readable], on_progress=cb)
            st.session_state["dp_last"] = results
            st.session_state["upload_nonce"] = nonce + 1
            st.session_state.pop("dp_saved", None)
            on_data_changed()
            st.rerun()

    # ---------------- uploaded files (audit trail)
    theme.section_label("Uploaded files")
    try:
        rows = (sb.table("uploaded_files").select("*").order("created_at", desc=True).limit(30).execute().data or [])
    except Exception:
        rows = None
    if rows is None:
        st.info("The file list needs the uploads SQL. Run ithink_sql_uploads.sql in Supabase, then click Refresh data.")
    elif not rows:
        st.caption("Nothing uploaded yet. Files you upload are kept here so you can download them again.")
    else:
        header = st.columns([3, 2.2, 1.6, 1.2, 1.2])
        for col, text in zip(header, ["File", "Uploaded", "Rows", "Status", ""]):
            col.caption(text)
        for r in rows:
            c = st.columns([3, 2.2, 1.6, 1.2, 1.2])
            c[0].markdown(f"**{r['file_name']}**")
            when = r.get("created_at", "")[:16].replace("T", " ")
            c[1].caption(f"{when} UTC  ·  {r.get('uploaded_by_email') or ''}")
            if r.get("rows_total") is not None:
                c[2].caption(f"{r['rows_total']:,} total, {r.get('rows_new') or 0:,} new")
            status = r.get("status", "")
            c[3].markdown({"done": ":green[Done]", "failed": ":red[Failed]"}.get(status, status.title()))
            url = _signed_url(admin, r["storage_path"]) if (admin is not None and r.get("storage_path")) else None
            if url:
                c[4].link_button("Download", url)
            if status == "failed" and r.get("error"):
                st.caption(f":red[{r['error']}]")
