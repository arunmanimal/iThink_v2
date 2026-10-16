"""
iThink Dashboard -- themed shell (light mode)
--------------------------------
Login, sidebar (logo + navigation + global filters), five pages, KPI tile grid.
Overview is wired to live data through the overview_data() database function;
the other pages are still layout placeholders.

Auth uses the Supabase anon key plus the signed-in user's JWT, so Row-Level
Security really applies (backend scripts use service_role and bypass it).

Save as: app/dashboard.py   (needs app/theme.py and app/assets/*.png next to it)
"""
import json
from contextlib import contextmanager
from datetime import date, datetime, timedelta

import streamlit as st
from PIL import Image
from supabase import create_client

import ai_ui
import charts
import data_page
import team_page
import theme


@contextmanager
def guarded(name):
    """One chart that fails must not blank the whole page: show what failed, keep drawing the rest."""
    try:
        yield
    except Exception as e:   # st.rerun() and friends are BaseException, so they still pass through
        st.error(f"The '{name}' chart could not be drawn ({type(e).__name__}: {e}). The rest of the page is unaffected.")


def _page_icon():
    try:
        return Image.open(theme.LOGO_ICON)
    except Exception:
        return "\U0001F4CA"


st.set_page_config(
    page_title="iThink",
    page_icon=_page_icon(),
    layout="wide",
    initial_sidebar_state="expanded",
)
theme.inject_css()

SUPABASE_URL = st.secrets["SUPABASE_URL"]
SUPABASE_ANON_KEY = st.secrets["SUPABASE_ANON_KEY"]

DASH = "\u2014"
APP_BUILD = "v19"   # shown in the sidebar so it is always clear which file is running

# Pilot basis -- flip these when AI tagging covers the dataset (the badges and captions follow).
SENTIMENT_SOURCE = "sprinklr"   # "sprinklr" now; "ai" once AI-tagged sentiment is complete
BRAND_SOURCE = "source file"    # pilot: brand = the export file a conversation came from; later "ai"

ATTRIBUTE_SOURCE = "sprinklr"   # pilot: Sprinklr's own category fields; later "ai" (our 168-attribute taxonomy)
# Preferred Sprinklr fields for a default, in order. The first with enough coverage wins; the user can change it.
FIELD_PRIORITY = ["Product", "Service & Spare Parts", "Sales Subcategories", "Product Subcategories", "ICE Attributes",
                  "Workshop Subcategories", "Symptoms", "Category", "Subcategory", "NPD & QAD", "CX Journey"]
MIN_FIELD_COVERAGE = 0.02       # a default field must cover at least 2% of conversations

# Fallback if the live list of networks cannot be loaded
DEFAULT_NETWORKS = ["INSTAGRAM", "YOUTUBE", "FACEBOOK", "TWITTER"]
SENTIMENTS = ["Positive", "Neutral", "Negative"]
PRODUCT_TYPES = ["ICE", "EV"]

# What each role may do. Everyone signed in can upload and edit brands today (a decision from the pilot);
# remove a role from a tuple to take that right away from it.
PERMISSIONS = {
    "upload": ("admin", "analyst", "viewer"),
    "edit_brands": ("admin", "analyst", "viewer"),
    "manage_team": ("admin",),
}


def can(action: str) -> bool:
    role = (st.session_state.get("membership") or {}).get("role")
    return role in PERMISSIONS.get(action, ())


FILTER_KEYS = ("f_date", "f_product", "f_brand", "f_category", "f_network", "f_sentiment")
SESSION_KEYS = (
    "user", "access_token", "sb_client", "membership",
    "date_bounds", "filter_opts", "own_override", "f_own_brand", "dp_saved", "dp_edit", "dp_found", "dp_last", "global_filters", "synthetic_count", "stream_page", "stream_sig",
    # one person's AI chat, counters and team screens must never be seen by the next person on this browser
    "chat_history", "chat_calls", "chat_pending", "chat_q", "ai_calls", "ai_seen", "_page_cards", "_page_cards_saved",
    "tm_secrets", "tm_flash", "tm_editor",
) + FILTER_KEYS


# ====================================================================== auth
def get_client():
    if "sb_client" not in st.session_state:
        st.session_state.sb_client = create_client(SUPABASE_URL, SUPABASE_ANON_KEY)
    return st.session_state.sb_client


@st.cache_resource(show_spinner=False)
def get_admin_client():
    """Server-side client for uploads (bypasses row-level security). Used only by the Data & Brand Selection page,
    always fixed to the signed-in user's own tenant. None when the key is not in the app secrets."""
    key = st.secrets.get("SUPABASE_SERVICE_ROLE_KEY")
    return create_client(SUPABASE_URL, key) if key else None


def login_view():
    theme.login_header()
    _, mid, _ = st.columns([1, 1.1, 1])
    with mid:
        with st.form("login_form"):
            email = st.text_input("Email")
            password = st.text_input("Password", type="password")
            submitted = st.form_submit_button("Log in", type="primary")

        if submitted:
            ok = False
            try:
                result = get_client().auth.sign_in_with_password({"email": email, "password": password})
                st.session_state.user = result.user
                st.session_state.access_token = result.session.access_token
                ok = True
            except Exception:
                st.error("Login failed. Check your e-mail and password.")
            if ok:
                st.rerun()
        st.caption("Access is by invitation. Ask your workspace admin to add you or to reset your password.")


def change_password_form(sb, admin, membership, forced: bool):
    """Lets a signed-in person choose their own password. When forced, nothing else is shown until they do."""
    with st.form("pw_form" + ("_forced" if forced else "")):
        new = st.text_input("New password", type="password", help="At least 10 characters.")
        again = st.text_input("Repeat new password", type="password")
        go = st.form_submit_button("Save password", type="primary")
    if not go:
        return
    if len(new) < 10:
        st.error("Use at least 10 characters.")
    elif new != again:
        st.error("The two passwords do not match.")
    else:
        try:
            sb.auth.update_user({"password": new})
            if admin is not None:
                (admin.table("tenant_users").update({"must_change_password": False})
                 .eq("tenant_id", membership["tenant_id"]).eq("user_id", st.session_state.user.id).execute())
            st.session_state["membership"] = {**membership, "must_change_password": False}
            st.session_state["pw_done"] = True
            st.rerun()
        except Exception as e:
            st.error(f"Could not change the password. {e}")


def load_membership(sb, user_id):
    if "membership" in st.session_state:
        return st.session_state["membership"]
    try:
        resp = (
            sb.table("tenant_users")
            .select("tenant_id, role, must_change_password, tenants(name)")
            .eq("user_id", user_id)
            .execute()
        )
    except Exception:       # the Team SQL has not been run yet: fall back to the older shape
        resp = (
            sb.table("tenant_users")
            .select("tenant_id, role, tenants(name)")
            .eq("user_id", user_id)
            .execute()
        )
    membership = resp.data[0] if resp.data else None
    st.session_state["membership"] = membership
    return membership


# ====================================================================== filters
def _to_date(value: str) -> date:
    return datetime.fromisoformat(value.replace("Z", "+00:00")).date()


def load_date_bounds(sb):
    if "date_bounds" in st.session_state:
        return st.session_state["date_bounds"]
    def edge(desc: bool) -> date:
        # A fresh query per call: the client's query builders are mutable, so reusing one
        # builder for both lookups made the "latest" query also sort ascending.
        rows = (
            sb.table("conversations").select("conversation_date")
            .not_.is_("conversation_date", "null")
            .order("conversation_date", desc=desc).limit(1).execute().data
        )
        return _to_date(rows[0]["conversation_date"])

    try:
        bounds = (edge(False), edge(True))
    except Exception:
        today = date.today()
        bounds = (today - timedelta(days=90), today)
    st.session_state["date_bounds"] = bounds
    return bounds


def load_filter_options(sb):
    cached = st.session_state.get("filter_opts")
    if cached and "networks" in cached:
        return cached
    opts = {"brands": [], "own_brand": None, "categories": [], "networks": list(DEFAULT_NETWORKS)}
    try:
        rows = sb.table("brands").select("id, brand_name, is_own_brand").execute().data or []
        rows.sort(key=lambda r: r["brand_name"].lower())
        opts["brands"] = [r["brand_name"] for r in rows]
        opts["brand_ids"] = {r["brand_name"]: r["id"] for r in rows}
        default_own = next((r["brand_name"] for r in rows if r.get("is_own_brand")), None)
        opts["default_own"] = default_own
        chosen = None
        try:   # this user's own choice (needs the flexible-brands SQL); falls back to the tenant default
            membership = st.session_state.get("membership") or {}
            pref = (
                sb.table("user_preferences").select("own_brand_id")
                .eq("tenant_id", membership.get("tenant_id")).eq("user_id", st.session_state.user.id)
                .execute().data or []
            )
            if pref and pref[0].get("own_brand_id"):
                chosen = next((r["brand_name"] for r in rows if r["id"] == pref[0]["own_brand_id"]), None)
        except Exception:
            pass
        override = st.session_state.get("own_override")
        opts["own_brand"] = override if override in opts["brands"] else (chosen or default_own)
        # own brand first, so it leads every brand list
        opts["brands"].sort(key=lambda b: (b != opts["own_brand"], b.lower()))
    except Exception as e:
        st.sidebar.warning(f"Could not load brands: {e}")
    try:
        rows = (
            sb.table("business_taxonomy").select("l1_name")
            .is_("tenant_id", "null").order("l1_name").execute().data or []
        )
        opts["categories"] = [r["l1_name"] for r in rows]
    except Exception as e:
        st.sidebar.warning(f"Could not load categories: {e}")
    try:
        listed = sb.rpc("list_sources").execute().data
        if isinstance(listed, list) and listed:
            opts["networks"] = [s for s in listed if s]
    except Exception:
        pass   # keep the default list
    st.session_state["filter_opts"] = opts
    return opts


def load_synthetic_count(sb) -> int:
    """How many conversations carry a simulated date (0 once real dates are loaded)."""
    if "synthetic_count" in st.session_state:
        return st.session_state["synthetic_count"]
    try:
        n = sb.table("conversations").select("id", count="exact").eq("date_is_synthetic", True).limit(1).execute().count
        n = int(n or 0)
    except Exception:
        n = 0   # column not created yet, or query failed -> no banner
    st.session_state["synthetic_count"] = n
    return n


def refresh_data():
    """Drop cached query results and lookups so the next render re-reads the database."""
    st.cache_data.clear()
    for key in ("synthetic_count", "date_bounds", "filter_opts", "dp_saved"):
        st.session_state.pop(key, None)


def reset_filters():
    for key in FILTER_KEYS:
        st.session_state.pop(key, None)


def change_own_brand():
    """Remember this user's own brand. Only this user's view changes; the choice is stored per user."""
    sb = get_client()
    opts = st.session_state.get("filter_opts") or {}
    name = st.session_state.get("f_own_brand")
    st.session_state["own_override"] = name       # applies at once, even if saving fails
    brand_id = (opts.get("brand_ids") or {}).get(name)
    membership = st.session_state.get("membership") or {}
    if brand_id:
        try:
            sb.table("user_preferences").upsert(
                {"tenant_id": membership.get("tenant_id"), "user_id": st.session_state.user.id,
                 "own_brand_id": brand_id},
                on_conflict="tenant_id,user_id",
            ).execute()
        except Exception as e:
            st.session_state["own_brand_error"] = str(e)
    st.session_state.pop("filter_opts", None)     # rebuilt next run with the new own brand
    st.session_state.pop("bench_competitor", None)


def render_sidebar_filters(sb):
    opts = load_filter_options(sb)
    lo, hi = load_date_bounds(sb)

    with st.sidebar:
        if opts["brands"]:
            st.markdown("### Your brand")
            current = opts.get("own_brand")
            st.selectbox("Own brand", opts["brands"], key="f_own_brand",
                         index=opts["brands"].index(current) if current in opts["brands"] else None,
                         placeholder="Choose your brand", on_change=change_own_brand,
                         help="Pick which brand counts as yours. The others become competitors. "
                              "This changes only your own view.")
            if st.session_state.pop("own_brand_error", None):
                st.caption("Applies for this session only - it could not be saved. Has the flexible-brands SQL been run?")
        st.markdown("### Filters")
        st.date_input("Date range", value=(lo, hi), min_value=lo, max_value=hi, key="f_date")
        # Empty selection means "All" -- tags only appear when a filter is narrowed.
        st.multiselect("Product type", PRODUCT_TYPES, key="f_product", placeholder="All types",
                       disabled=True, help="Switches on once AI tagging covers the dataset.")
        st.multiselect("Brand", opts["brands"], key="f_brand", placeholder="All brands")
        st.multiselect("Business category", opts["categories"], key="f_category", placeholder="All categories",
                       disabled=True, help="Switches on once AI tagging covers the dataset.")
        st.multiselect("Social network", opts["networks"], key="f_network", placeholder="All networks")
        st.multiselect("Sentiment", SENTIMENTS, key="f_sentiment", placeholder="All sentiments")
        st.button("Reset filters", on_click=reset_filters, key="reset_filters_btn")
        st.button("Refresh data", on_click=refresh_data, key="refresh_data_btn",
                  help="Reload from the database (results are otherwise cached for 2 minutes).")

    date_value = st.session_state.get("f_date", (lo, hi))
    if isinstance(date_value, (list, tuple)):
        if len(date_value) == 2:
            start, end = date_value
        elif len(date_value) == 1:
            start = end = date_value[0]
        else:
            start, end = lo, hi
    else:
        start = end = date_value

    def pick(key, universe):
        """Empty selection = All. Everything downstream always receives an explicit list."""
        chosen = st.session_state.get(key) or []
        return list(chosen) if chosen else list(universe)

    st.session_state["global_filters"] = {
        "date_range": (start, end),
        "products": pick("f_product", PRODUCT_TYPES),
        "brands": pick("f_brand", opts["brands"]),
        "categories": pick("f_category", opts["categories"]),
        "networks": pick("f_network", opts["networks"]),
        "sentiments": pick("f_sentiment", SENTIMENTS),
    }


def effective_filters(page: str, chart_id: str = None) -> dict:
    """Every chart calls this. Resolution order: chart override -> page override -> global.
    Only the global tier has UI today; page/chart overrides plug in here later
    without touching any chart code."""
    merged = dict(st.session_state.get("global_filters", {}))
    merged.update(st.session_state.get("page_filters", {}).get(page, {}))
    if chart_id:
        merged.update(st.session_state.get("chart_filters", {}).get((page, chart_id), {}))
    return merged


def filter_summary(f: dict):
    opts = st.session_state.get("filter_opts", {})
    start, end = f["date_range"]
    chips = [("Date", f"{start:%d %b} - {end:%d %b %Y}")]

    def add(label, selected, universe, noun, always=False):
        if not universe or len(selected) == len(universe):
            if always:
                chips.append((label, f"All {noun}"))
        elif selected and len(selected) <= 2:
            chips.append((label, ", ".join(selected)))
        else:
            chips.append((label, f"{len(selected)} of {len(universe)}"))

    add("Brands", f["brands"], opts.get("brands", []), "brands", always=True)
    add("Networks", f["networks"], opts.get("networks", DEFAULT_NETWORKS), "networks", always=True)
    add("Sentiment", f["sentiments"], SENTIMENTS, "sentiments")
    add("Categories", f["categories"], opts.get("categories", []), "categories")
    add("Product", f["products"], PRODUCT_TYPES, "types")
    return chips


def overview_params(f: dict, opts: dict) -> dict:
    """Filters -> database function arguments. A filter that covers every option is sent as null (= no filter)."""
    start, end = f["date_range"]

    def narrowed(selected, universe, lower=False):
        if not selected or set(selected) >= set(universe):
            return None
        return [s.lower() for s in selected] if lower else list(selected)

    return {
        "p_start": start.isoformat(),
        "p_end": end.isoformat(),
        "p_networks": narrowed(f["networks"], opts.get("networks", DEFAULT_NETWORKS)),
        "p_brands": narrowed(f["brands"], opts.get("brands", [])),
        "p_sentiments": narrowed(f["sentiments"], SENTIMENTS, lower=True),
    }


@st.cache_data(ttl=120, show_spinner=False)
def _overview_cached(_sb, tenant_id: str, params_json: str):
    # tenant_id is part of the cache key on purpose: two tenants must never share a cached result.
    return _sb.rpc("overview_data", json.loads(params_json)).execute().data


def load_overview(sb, membership, params):
    try:
        data = _overview_cached(sb, (membership or {}).get("tenant_id", ""), json.dumps(params, sort_keys=True))
        return data, None
    except Exception as e:
        return None, str(e)


@st.cache_data(ttl=120, show_spinner=False)
def _wordcloud_cached(_sb, tenant_id: str, params_json: str):
    return _sb.rpc("wordcloud_data", json.loads(params_json)).execute().data


def load_wordcloud(sb, membership, params):
    try:
        payload = json.dumps({**params, "p_limit": 60}, sort_keys=True)
        return _wordcloud_cached(sb, (membership or {}).get("tenant_id", ""), payload), None
    except Exception as e:
        return None, str(e)


@st.cache_data(ttl=120, show_spinner=False)
def _virality_cached(_sb, tenant_id: str, params_json: str):
    return _sb.rpc("virality_data", json.loads(params_json)).execute().data


@st.cache_data(ttl=120, show_spinner=False)
def _switching_cached(_sb, tenant_id: str, params_json: str):
    return _sb.rpc("switching_data", json.loads(params_json)).execute().data


def fmt_int(n):
    return f"{int(n):,}" if n is not None else None


GENDER_LABELS = {"F": "Female", "FEMALE": "Female", "M": "Male", "MALE": "Male",
                 "OTHER": "Unknown", "UNKNOWN": "Unknown"}


def gender_rows(rows):
    """Sprinklr reports gender as M / MALE / F / FEMALE / OTHER. Merge the variants into one bar each."""
    merged = {}
    for row in rows or []:
        label = GENDER_LABELS.get(str(row["gender"]).upper(), str(row["gender"]).title())
        merged[label] = merged.get(label, 0) + (row.get("mentions") or 0)
    return [{"gender": k, "mentions": v} for k, v in sorted(merged.items(), key=lambda kv: -kv[1])]


def people_rows(rows):
    """Different accounts can share a display name. Tell them apart by follower count, not a bare '(2)'."""
    names = [r["name"] for r in rows or []]
    out = []
    for row in rows or []:
        label = row["name"]
        if names.count(label) > 1 and row.get("followers") is not None:
            label = f"{label} ({fmt_compact(row['followers'])} fol.)"
        out.append({**row, "name": label})
    return out


def fmt_when(iso_text):
    try:
        return datetime.fromisoformat(str(iso_text).replace("Z", "+00:00")).strftime("%d %b %Y, %H:%M")
    except ValueError:
        return str(iso_text or "")


def coverage_note(have, total, noun):
    """Every demographic chart says how much of the data it is based on."""
    if not total:
        return ""
    pct = 100 * have / total
    note = f"Based on {have:,} of {total:,} conversations ({pct:.1f}%) with {noun} data"
    return note + (". Low coverage - indicative only." if pct < 10 else ".")


def brand_data_gaps(trend_rows, min_gap_days=14):
    """Brands whose conversations stop well before the others. That is usually a shorter export,
    not a real silence, so the dashboard says so instead of letting the line read as a drop.
    Returns ([(brand, last_date), ...], latest_date_across_brands)."""
    last = {}
    for row in trend_rows or []:
        brand = row.get("brand")
        if brand in (None, "Unassigned"):
            continue
        day = date.fromisoformat(str(row["bucket"])[:10])
        if brand not in last or day > last[brand]:
            last[brand] = day
    if len(last) < 2:
        return [], None
    latest = max(last.values())
    gaps = sorted((b, d_) for b, d_ in last.items() if (latest - d_).days > min_gap_days)
    return gaps, latest


def fmt_compact(n):
    if n is None:
        return None
    n = float(n)
    for suffix, size in (("B", 1e9), ("M", 1e6), ("K", 1e3)):
        if abs(n) >= size:
            return f"{n / size:.1f}".rstrip("0").rstrip(".") + suffix
    return f"{int(n):,}"


# ====================================================================== pages
def page_overview():
    sb = get_client()
    membership = st.session_state.get("membership") or {}
    opts = st.session_state.get("filter_opts", {})
    f = effective_filters("overview")
    own = opts.get("own_brand") or "Own brand"

    theme.page_header("Overview", "Brand conversation snapshot across all tracked networks")
    theme.filter_chips(filter_summary(f))

    data, error = load_overview(sb, membership, overview_params(f, opts))
    if error:
        st.error(f"Could not load the overview data. Have the Phase 4 SQL queries been run? Details: {error}")
    new_sections = ("hashtags", "advocates", "detractors", "reach_drivers", "gender", "states", "cities", "coverage")
    if data and any(section not in data for section in new_sections):
        st.warning("Some charts need the latest database function. Run the newest overview_data SQL in "
                   "Supabase, then click Refresh data in the sidebar.")
    k = (data or {}).get("kpis") or {}

    mentions = k.get("mentions")
    pos, neg = k.get("positive") or 0, k.get("negative") or 0
    score = 10 * (pos - neg) / (pos + neg) if (pos + neg) else None
    # share of voice is worked out here from the per-brand counts, so it follows whichever brand the user picked as own
    sov_rows = (data or {}).get("sov") or []
    branded = sum(r.get("mentions") or 0 for r in sov_rows)
    own_mentions = sum(r.get("mentions") or 0 for r in sov_rows if r.get("brand") == opts.get("own_brand"))
    share = 100 * own_mentions / branded if branded and opts.get("own_brand") else None
    top = (data or {}).get("top_attribute")
    tagged = (data or {}).get("tagged_conversations") or 0
    ai_sentiment, ai_brand = SENTIMENT_SOURCE == "ai", BRAND_SOURCE == "ai"
    sentiment_label = "AI-tagged" if ai_sentiment else "Sprinklr"

    theme.section_label("Performance snapshot")
    r1 = st.columns(4, gap="medium")
    with r1[0]:
        theme.kpi_tile("Mentions Count", fmt_int(mentions), "Matching the filters")
    with r1[1]:
        theme.kpi_tile("Sentiment Score", f"{score:+.1f}" if score is not None else None,
                       f"{sentiment_label} | (Pos - Neg) / (Pos + Neg) x 10", accent=True, ai=ai_sentiment)
    with r1[2]:
        theme.kpi_tile("Distinct Users", fmt_int(k.get("distinct_users")), "Unique authors")
    with r1[3]:
        theme.kpi_tile("Negative Mentions", fmt_int(neg) if data else None,
                       f"{100 * neg / mentions:.0f}% of mentions" if mentions else f"{sentiment_label} sentiment",
                       ai=ai_sentiment)

    r2 = st.columns(4, gap="medium")
    with r2[0]:
        theme.kpi_tile("Reach", fmt_compact(k.get("reach")), "Followers of distinct authors (proxy)")
    with r2[1]:
        theme.kpi_tile("Engagements", fmt_compact(k.get("engagements")), "Likes + shares (no comments)")
    with r2[2]:
        theme.kpi_tile("Share of Voice", f"{share:.1f}%" if share is not None else None,
                       f"{own} share, by {BRAND_SOURCE}", ai=ai_brand)
    with r2[3]:
        theme.kpi_tile("Top Attribute", top["attribute"] if top else None,
                       f"{top['mentions']:,} of {tagged:,} AI-tagged conversations" if top else "Needs AI-tagged conversations",
                       ai=True)
    theme.note(f"Pilot basis: sentiment from {sentiment_label}, brand assigned by {BRAND_SOURCE}. "
               "Top Attribute uses the AI-tagged sample only.")

    gaps, latest = brand_data_gaps((data or {}).get("trend"))
    if gaps:
        names = ", ".join(f"{b} (ends {d_:%d %b})" for b, d_ in gaps)
        theme.data_notice(
            "Data gap",
            f"{names}. Other brands run to {latest:%d %b %Y}. Likely a shorter export, not a real drop in conversation.",
        )

    colours = theme.brand_colors(opts.get("brands", []), own=opts.get("own_brand"))
    colours["Unassigned"] = theme.NEUTRAL
    has_data = bool(data) and bool(mentions)

    def empty_state(section=None, message=None):
        """Says WHY a card is empty: no data at all, an outdated database function, or genuinely nothing to show."""
        if not data:
            st.info("No data to show.")
        elif section and section not in data:
            st.warning("Needs the latest database function.")
        elif not mentions:
            st.info("No conversations match these filters.")
        else:
            st.info(message or "No data for these filters.")

    theme.section_label("Volume & sentiment")
    a, b = st.columns([2, 1], gap="medium")
    with a:
        with st.container(border=True):
            with guarded("Mentions over time"):
                if has_data:
                    fig, grain = charts.trend_chart(data.get("trend", []), colours)
                    theme.chart_title("Mentions over time", f"{grain} mentions by brand")
                    ai_ui.chart(fig, config={"displayModeBar": False}, key="ov_trend")
                else:
                    theme.chart_title("Mentions over time")
                    empty_state()
    with b:
        with st.container(border=True):
            with guarded("Sentiment share"):
                theme.chart_title("Sentiment share", f"{sentiment_label} sentiment")
                if has_data:
                    ai_ui.chart(charts.sentiment_pie(data.get("sentiment", [])),
                                    config={"displayModeBar": False}, key="ov_sentiment")
                else:
                    empty_state()

    cfg = {"displayModeBar": False}

    theme.section_label("Brands & channels")
    c, d_, e = st.columns(3, gap="medium")
    with c:
        with st.container(border=True):
            with guarded("Share of voice"):
                theme.chart_title("Share of voice", f"Mentions by brand (by {BRAND_SOURCE})")
                if has_data:
                    ai_ui.chart(charts.share_of_voice_pie(data.get("sov", []), colours), config=cfg, key="ov_sov")
                else:
                    empty_state()
    with d_:
        with st.container(border=True):
            with guarded("Mentions by source"):
                theme.chart_title("Mentions by source", "One bar per social network")
                if has_data:
                    ai_ui.chart(charts.source_bar(data.get("sources", [])), config=cfg, key="ov_sources")
                else:
                    empty_state()
    with e:
        with st.container(border=True):
            with guarded("Top 10 hashtags"):
                theme.chart_title("Top 10 hashtags", "Most-used hashtags (once per conversation)")
                rows = (data or {}).get("hashtags") or []
                if has_data and rows:
                    ai_ui.chart(charts.hbar(rows, "tag", "mentions", label_fn=lambda t: "#" + str(t)),
                                    config=cfg, key="ov_hashtags")
                else:
                    empty_state("hashtags", "No hashtags found in these conversations.")

    theme.section_label("Voices")
    theme.note("Advocates and detractors leave out anonymous profiles such as 'Instagram User'.")
    g, h, i = st.columns(3, gap="medium")
    with g:
        with st.container(border=True):
            with guarded("Top 10 advocates"):
                theme.chart_title("Top 10 advocates", f"Most positive mentions ({sentiment_label})")
                rows = people_rows((data or {}).get("advocates"))
                if has_data and rows:
                    ai_ui.chart(charts.hbar(rows, "name", "mentions", colour=theme.EMERALD), config=cfg, key="ov_advocates")
                else:
                    empty_state("advocates", "No named authors with positive mentions.")
    with h:
        with st.container(border=True):
            with guarded("Top 10 detractors"):
                theme.chart_title("Top 10 detractors", f"Most negative mentions ({sentiment_label})")
                rows = people_rows((data or {}).get("detractors"))
                if has_data and rows:
                    ai_ui.chart(charts.hbar(rows, "name", "mentions", colour=theme.NEGATIVE), config=cfg, key="ov_detractors")
                else:
                    empty_state("detractors", "No named authors with negative mentions.")
    with i:
        with st.container(border=True):
            with guarded("Top 5 reach drivers"):
                theme.chart_title("Top 5 reach drivers", "Ranked by follower count")
                rows = people_rows((data or {}).get("reach_drivers"))
                if has_data and rows:
                    ai_ui.chart(charts.hbar(rows, "name", "followers", value_format=".3s"), config=cfg, key="ov_reach")
                else:
                    empty_state("reach_drivers", "No authors with follower data.")

    theme.section_label("Audience & themes")
    cov = (data or {}).get("coverage") or {}
    total = mentions or 0
    j, k_ = st.columns([1, 2], gap="medium")
    with j:
        with st.container(border=True):
            with guarded("Gender"):
                theme.chart_title("Gender", "Authors' reported gender")
                rows = gender_rows((data or {}).get("gender"))
                if has_data and rows:
                    ai_ui.chart(charts.column_chart(rows, "gender", "mentions"), config=cfg, key="ov_gender")
                    theme.note(coverage_note(cov.get("gender", 0), total, "gender"))
                else:
                    empty_state("gender", "No gender data in these conversations.")
    with k_:
        with st.container(border=True):
            with guarded("Top locations"):
                theme.chart_title("Top locations", "Top 10 by mentions")
                default_level = 0 if (cov.get("state", 0) >= cov.get("city", 0)) else 1
                level = st.radio("Location level", ["State", "City"], index=default_level, horizontal=True,
                                 label_visibility="collapsed", key="ov_geo_level")
                geo_key, geo_noun = ("cities", "city") if level == "City" else ("states", "state")
                rows = (data or {}).get(geo_key) or []
                if has_data and rows:
                    ai_ui.chart(charts.hbar(rows, "name", "mentions", height=280), config=cfg, key="ov_geo")
                    theme.note(coverage_note(cov.get(geo_noun, 0), total, geo_noun))
                else:
                    empty_state(geo_key, f"No {geo_noun} data in these conversations.")
    if True:   # word cloud: full-width row below Gender and Top locations
        with st.container(border=True):
            with guarded("Word cloud"):
                theme.chart_title("Word cloud", "Most-used words; brand names, links and filler words are left out")
                cloud, cloud_error = load_wordcloud(sb, membership, overview_params(f, opts))
                if cloud_error:
                    st.error(f"Could not load the word cloud. Has the Word cloud SQL been run? Details: {cloud_error}")
                elif not has_data:
                    empty_state()
                elif theme.word_cloud((cloud or {}).get("words")):
                    theme.note(f"Based on {(cloud or {}).get('conversations', 0):,} conversations. Frequency-based pilot: "
                               "people, places and organisations come with the NLP step.")
                    ai_ui.data_insights("ov_cloud", [{"name": "Conversations using each word", "points": [
                        [w.get("word"), w.get("mentions")] for w in ((cloud or {}).get("words") or [])[:40]]}])
                else:
                    st.info("Not enough text for a word cloud with these filters.")


@st.cache_data(ttl=120, show_spinner=False)
def _attribute_cached(_sb, tenant_id: str, params_json: str):
    return _sb.rpc("attribute_data", json.loads(params_json)).execute().data


def load_attribute(sb, membership, params, field=None):
    """Returns (data, error). With no field chosen yet, prefers a meaningful, well-covered Sprinklr field."""
    tenant = (membership or {}).get("tenant_id", "")

    def call(chosen):
        payload = {**params, "p_field": chosen, "p_top": 10}
        return _attribute_cached(sb, tenant, json.dumps(payload, sort_keys=True))

    try:
        data = call(field)
        if field is None and data and data.get("fields"):
            total = data.get("total_conversations") or 0
            cover = {x["field"]: x["conversations"] for x in data["fields"]}
            for name in FIELD_PRIORITY:
                if cover.get(name, 0) >= MIN_FIELD_COVERAGE * max(total, 1):
                    if name != data.get("field"):
                        data = call(name)
                    break
        return data, None
    except Exception as e:
        return None, str(e)


def pick_category_field(widget_key, sb, membership, params):
    """Loads the attribute data for the chosen Sprinklr category field and draws the field picker.
    The choice is remembered across the Attribute and Benchmarking pages."""
    requested = st.session_state.get(widget_key) or st.session_state.get("attr_field_choice")
    data, error = load_attribute(sb, membership, params, requested)
    if error or not data:
        return data, error
    fields = data.get("fields") or []
    names = [x["field"] for x in fields]
    if not names:
        return data, None
    cover = {x["field"]: x["conversations"] for x in fields}
    chosen = data.get("field") if data.get("field") in names else names[0]
    if st.session_state.get(widget_key) not in names:
        st.session_state.pop(widget_key, None)
    picked = st.selectbox("Sprinklr category field", names, index=names.index(chosen), key=widget_key,
                          format_func=lambda n: f"{n} ({cover.get(n, 0):,} conversations)")
    st.session_state["attr_field_choice"] = picked
    return data, None


def attribute_notice(field):
    theme.data_notice(
        "Pilot basis",
        f"Attributes are Sprinklr's own '{field}' categories, not our AI taxonomy. "
        "AI-tagged attributes take over once tagging covers the dataset.",
    )


def render_virality(sb, membership, opts, f):
    """Pilot virality map for one topic: when it started, who spiked it, who sided how."""
    params = overview_params(f, opts)
    tenant = (membership or {}).get("tenant_id", "")
    cfg = {"displayModeBar": False}

    overview, _ = load_overview(sb, membership, params)
    cloud, _ = load_wordcloud(sb, membership, params)
    tags = ["#" + str(r["tag"]) for r in ((overview or {}).get("hashtags") or [])][:10]
    words = [r["word"] for r in ((cloud or {}).get("words") or [])][:10]
    suggestions = tags + [w for w in words if w not in tags]

    pick_col, type_col = st.columns(2, gap="medium")
    with pick_col:
        picked = st.selectbox("Topic", suggestions, key="viral_pick") if suggestions else None
    with type_col:
        typed = st.text_input("Or type your own topic", key="viral_typed",
                              placeholder="a hashtag, or a word")
    topic = ((typed or "").strip() or (picked or ""))[:60]
    if len(topic) < 2:
        st.info("Pick a topic from the list, or type one, to see how it spread.")
        return

    try:
        data = _virality_cached(sb, tenant, json.dumps({**params, "p_topic": topic}, sort_keys=True))
    except Exception as e:
        st.error(f"Could not load the virality map. Has the Virality SQL been run? Details: {e}")
        return
    total = (data or {}).get("total") or 0
    if not total:
        st.info(f"No conversations mention '{topic}' for these filters.")
        return

    simulated = (data or {}).get("simulated_share") or 0
    if simulated > 0:
        theme.data_notice("Simulated dates",
                          f"{simulated:.0%} of these conversations carry simulated dates, so the timeline and "
                          "'who started it' are indicative only.")

    first = (data.get("first") or [None])[0]
    fig, info = charts.topic_timeline(data.get("timeline") or [])
    t1, t2, t3 = st.columns(3, gap="medium")
    with t1:
        theme.kpi_tile("Conversations", fmt_int(total), f"Mentioning '{topic}'")
    with t2:
        theme.kpi_tile("First seen", fmt_when(first.get("date")).split(",")[0] if first else None,
                       f"{first.get('author') or 'Anonymous'} on {str(first.get('source') or '').title()}" if first else "")
    with t3:
        theme.kpi_tile("Peak day", info["peak"].strftime("%d %b %Y") if info["peak"] else None,
                       f"{info['peak_mentions']:,} conversations" if info["peak"] else "")

    with st.container(border=True):
        with guarded("Topic timeline"):
            theme.chart_title("How it spread", f"{info['grain']} conversations mentioning '{topic}'")
            ai_ui.chart(fig, config=cfg, key="vr_timeline")

    left, right = st.columns(2, gap="medium")
    with left:
        with st.container(border=True):
            with guarded("Who started it"):
                theme.chart_title("Who started it", "The first conversations on the topic, oldest first")
                for row in data.get("first") or []:
                    when = fmt_when(row.get("date")) + (" (simulated date)" if row.get("simulated") else "")
                    followers = row.get("followers")
                    theme.stream_item(
                        author=row.get("author") or "Anonymous profile",
                        followers_text=f"{fmt_compact(followers)} followers" if followers else "",
                        source=row.get("source"), date_text=when, sentiment=row.get("sentiment"),
                        text=row.get("text"), likes=0, shares=0, url=row.get("url"),
                    )
    with right:
        with st.container(border=True):
            with guarded("Who spiked it"):
                theme.chart_title("Who spiked it", "Authors with the most pull on this topic")
                rank = st.radio("Rank by", ["Engagement", "Reach"], horizontal=True,
                                label_visibility="collapsed", key="viral_rank")
                if rank == "Reach":
                    rows = people_rows(data.get("amplifiers"))
                    chart = charts.hbar(rows, "name", "followers", value_format=".3s", height=300) if rows else None
                else:
                    rows = people_rows(data.get("spikers"))
                    chart = charts.hbar(rows, "name", "engagement", height=300) if rows else None
                if chart is not None:
                    ai_ui.chart(chart, config=cfg, key="vr_spikers")
                    theme.note("Engagement = likes + shares on their conversations about the topic." if rank == "Engagement"
                               else "Reach = the author's follower count.")
                else:
                    st.info("No named authors with " + ("followers" if rank == "Reach" else "engagement") + " data here.")

    pro, con = st.columns(2, gap="medium")
    with pro:
        with st.container(border=True):
            with guarded("Supporters"):
                theme.chart_title("Supporters", "Most positive mentions of the topic (Sprinklr sentiment)")
                rows = people_rows(data.get("supporters"))
                if rows:
                    ai_ui.chart(charts.hbar(rows, "name", "mentions", colour=theme.EMERALD, height=300),
                                    config=cfg, key="vr_supporters")
                else:
                    st.info("No named authors with positive mentions.")
    with con:
        with st.container(border=True):
            with guarded("Opposers"):
                theme.chart_title("Opposers", "Most negative mentions of the topic (Sprinklr sentiment)")
                rows = people_rows(data.get("opposers"))
                if rows:
                    ai_ui.chart(charts.hbar(rows, "name", "mentions", colour=theme.NEGATIVE, height=300),
                                    config=cfg, key="vr_opposers")
                else:
                    st.info("No named authors with negative mentions.")
    theme.note("Supporter / opposer is a proxy: positive vs negative sentiment on conversations about the topic, "
               "not a verified stance. Anonymous profiles are left out of the author lists.")


def page_attribute():
    sb = get_client()
    membership = st.session_state.get("membership") or {}
    opts = st.session_state.get("filter_opts", {})
    f = effective_filters("attribute")
    brand_order = opts.get("brands", [])
    cfg = {"displayModeBar": False}

    theme.page_header("Attribute", "What people talk about, and how each brand scores on it")
    theme.filter_chips(filter_summary(f))

    data, error = pick_category_field("attr_field_widget_attribute", sb, membership, overview_params(f, opts))
    if error:
        st.error(f"Could not load the attribute data. Has the Attribute SQL been run? Details: {error}")
        return
    if not (data or {}).get("fields"):
        st.warning("No Sprinklr category values found yet. Run the Attribute SQL, run the ingestion script once "
                   "(it fills the categories), then click Refresh data.")
        return

    field = data["field"]
    total = data.get("total_conversations") or 0
    shares = data.get("shares") or []
    colours = charts.category_colours(shares)
    has = bool(shares) and total > 0
    attribute_notice(field)
    note = coverage_note(data.get("categorised_conversations") or 0, total, f"'{field}' category")

    theme.section_label("Attribute mix & trend")
    a, b = st.columns(2, gap="medium")
    with a:
        with st.container(border=True):
            with guarded("Share of mentions by attribute"):
                theme.chart_title("Share of mentions by attribute", f"Top {len(shares)} values of '{field}'")
                if has:
                    ai_ui.chart(charts.category_donut(shares, data.get("total_pairs")), config=cfg, key="at_share")
                    theme.note(note)
                else:
                    st.info("No categorised conversations for these filters.")
    with b:
        with st.container(border=True):
            with guarded("Mentions trend by attribute"):
                rows = data.get("trend") or []
                if has and rows:
                    fig, grain = charts.trend_chart(rows, colours)
                    theme.chart_title("Mentions trend by attribute", f"{grain} mentions of the six most-mentioned values")
                    ai_ui.chart(fig, config=cfg, key="at_trend")
                else:
                    theme.chart_title("Mentions trend by attribute")
                    st.info("No trend data for these filters.")

    theme.section_label("Virality map")
    render_virality(sb, membership, opts, f)

    theme.section_label("Benchmark")
    with st.container(border=True):
        with guarded("Brand x attribute matrix"):
            theme.chart_title("Brand x attribute matrix",
                              "Net sentiment score, -10 to +10. Blank where there are fewer than 10 opinionated mentions")
            matrix = data.get("matrix") or []
            if has and matrix:
                ai_ui.chart(charts.score_heatmap(matrix, brand_order, [s["value"] for s in shares]),
                                config=cfg, key="at_matrix")
            else:
                st.info("No brand x attribute data for these filters.")


@st.cache_data(ttl=120, show_spinner=False)
def _signals_cached(_sb, tenant_id: str, params_json: str):
    return _sb.rpc("signals_data", json.loads(params_json)).execute().data


def load_signals(sb, membership, params):
    try:
        return _signals_cached(sb, (membership or {}).get("tenant_id", ""), json.dumps(params, sort_keys=True)), None
    except Exception as e:
        return None, str(e)


def page_signals():
    sb = get_client()
    membership = st.session_state.get("membership") or {}
    opts = st.session_state.get("filter_opts", {})
    f = effective_filters("signals")
    brand_order = opts.get("brands", [])
    colours = theme.brand_colors(brand_order, own=opts.get("own_brand"))
    colours["Unassigned"] = theme.NEUTRAL
    cfg = {"displayModeBar": False}
    sentiment_label = "AI-tagged" if SENTIMENT_SOURCE == "ai" else "Sprinklr"

    theme.page_header("Signals & Sentiment", "How people feel, and where they are in the customer journey")
    theme.filter_chips(filter_summary(f))

    data, error = load_signals(sb, membership, overview_params(f, opts))
    if error:
        st.error(f"Could not load the signals data. Has the Signals SQL been run? Details: {error}")
    total = (data or {}).get("total_conversations") or 0
    ai_n = (data or {}).get("ai_tagged_conversations") or 0
    has_data = bool(data) and total > 0
    ai_note = coverage_note(ai_n, total, "AI-tag")

    def empty_state(section, message):
        if not data:
            st.info("No data to show.")
        elif section not in data:
            st.warning("Needs the latest database function.")
        elif not total:
            st.info("No conversations match these filters.")
        else:
            st.info(message)

    theme.section_label("Sentiment & emotion")
    a, b = st.columns(2, gap="medium")
    with a:
        with st.container(border=True):
            with guarded("Sentiment distribution per brand"):
                theme.chart_title("Sentiment distribution per brand", f"Share of each brand's mentions ({sentiment_label})")
                rows = (data or {}).get("sentiment_by_brand") or []
                if has_data and rows:
                    ai_ui.chart(charts.sentiment_by_brand_bar(rows, brand_order), config=cfg, key="sg_sentiment")
                else:
                    empty_state("sentiment_by_brand", "No sentiment data for these filters.")
    with b:
        with st.container(border=True):
            with guarded("Emotion breakdown per brand"):
                theme.chart_title("Emotion breakdown per brand", "From AI-tagged conversations")
                rows = (data or {}).get("emotion_by_brand") or []
                if has_data and rows:
                    ai_ui.chart(charts.grouped_columns(rows, "emotion", colours), config=cfg, key="sg_emotion")
                    theme.note(ai_note)
                else:
                    empty_state("emotion_by_brand", "No AI-tagged emotion data for these filters yet.")

    theme.section_label("Journey & trend")
    c, d_ = st.columns(2, gap="medium")
    with c:
        with st.container(border=True):
            with guarded("Customer journey"):
                theme.chart_title("Customer journey", "Where conversations sit, by stage (AI-tagged)")
                rows = (data or {}).get("journey") or []
                if has_data and rows:
                    order = charts.order_stages(sorted({r["stage"] for r in rows}))
                    ai_ui.chart(charts.grouped_columns(rows, "stage", colours, order=order), config=cfg, key="sg_journey")
                    theme.note(ai_note)
                else:
                    empty_state("journey", "No AI-tagged journey data for these filters yet.")
    with d_:
        with st.container(border=True):
            with guarded("Sentiment trend"):
                rows = (data or {}).get("sentiment_trend") or []
                if has_data and rows:
                    fig, grain = charts.sentiment_trend_chart(rows, colours)
                    theme.chart_title("Sentiment trend", f"{grain} net score by brand, -10 to +10 ({sentiment_label})")
                    ai_ui.chart(fig, config=cfg, key="sg_trend")
                    if grain == "Weekly":
                        theme.note("Weeks with fewer than 30 positive or negative mentions are left out.")
                else:
                    theme.chart_title("Sentiment trend")
                    empty_state("sentiment_trend", "No sentiment data for these filters.")


def render_switching(sb, membership, opts, f, own, competitor):
    """Pilot switching risk: conversations that name both brands, flagged for comparison / switching language."""
    base = overview_params(f, opts)
    payload = {"p_start": base["p_start"], "p_end": base["p_end"], "p_networks": base["p_networks"],
               "p_sentiments": base["p_sentiments"], "p_own": own, "p_competitor": competitor, "p_limit": 8}
    with st.container(border=True):
        with guarded("Switching risk"):
            theme.chart_title("Switching risk", f"Conversations that mention both {own} and {competitor}")
            try:
                data = _switching_cached(sb, (membership or {}).get("tenant_id", ""), json.dumps(payload, sort_keys=True))
            except Exception as e:
                st.error(f"Could not load switching risk. Has the Switching SQL been run? Details: {e}")
                return
            total = (data or {}).get("total") or 0
            if not total:
                st.info("No conversations mention both brands for these filters.")
                return
            compare, switching = data.get("compare") or 0, data.get("switching") or 0
            c1, c2, c3 = st.columns(3, gap="medium")
            with c1:
                theme.kpi_tile("Mention both brands", fmt_int(total), "Conversations naming both")
            with c2:
                theme.kpi_tile("Comparison language", fmt_int(compare), f"{100 * compare / total:.0f}% of these")
            with c3:
                theme.kpi_tile("Switching language", fmt_int(switching), f"{100 * switching / total:.0f}% of these", accent=True)
            ai_ui.data_insights("bm_switching", [{"name": f"Conversations naming {own} and {competitor}", "points": [
                ["Mention both brands", total], ["Comparison language", compare], ["Switching language", switching]]}])
            for row in data.get("examples") or []:
                tags = []
                if row.get("switch"):
                    tags.append(("Switching", "switch"))
                if row.get("compare"):
                    tags.append(("Comparison", "compare"))
                when = fmt_when(row.get("date")) + (" (simulated date)" if row.get("simulated") else "")
                followers = row.get("followers")
                theme.stream_item(
                    author=row.get("author") or "Anonymous profile",
                    followers_text=f"{fmt_compact(followers)} followers" if followers else "",
                    source=row.get("source"), date_text=when, sentiment=row.get("sentiment"),
                    text=row.get("text"), likes=row.get("likes"), shares=0, url=row.get("url"), tags=tags,
                )
            theme.note("Keyword-based pilot: a conversation counts when its text names both brands (or their aliases) "
                       "and uses words like switch, shift, sold my, trade in, upgrade or replace. AI intent tags "
                       "(Intent = Switching) take over once tagging covers the dataset.")


def page_benchmarking():
    sb = get_client()
    membership = st.session_state.get("membership") or {}
    f = effective_filters("benchmarking")
    opts = st.session_state.get("filter_opts", {})
    own = opts.get("own_brand")
    competitors = [b for b in opts.get("brands", []) if b != own]
    cfg = {"displayModeBar": False}

    theme.page_header("Benchmarking", "Head-to-head comparison against one competitor at a time")
    theme.filter_chips(filter_summary(f))
    if not own or not competitors:
        st.info("Benchmarking needs an own brand (pick one under Your brand in the sidebar) and at least one competitor.")
        return

    if st.session_state.get("bench_competitor") not in competitors:
        st.session_state.pop("bench_competitor", None)    # the own brand changed, so the old pick may be stale
    competitor = st.selectbox(f"Compare {own} against", competitors, key="bench_competitor")

    # a head-to-head always uses exactly these two brands, whatever the sidebar brand filter says
    params = {**overview_params(f, opts), "p_brands": [own, competitor]}
    data, error = pick_category_field("attr_field_widget_benchmarking", sb, membership, params)
    if error:
        st.error(f"Could not load the benchmarking data. Has the Attribute SQL been run? Details: {error}")
        return
    if not (data or {}).get("fields"):
        st.warning("No Sprinklr category values found yet. Run the Attribute SQL, run the ingestion script once "
                   "(it fills the categories), then click Refresh data.")
        return

    field = data["field"]
    attribute_notice(field)
    colours = theme.brand_colors(opts.get("brands", []), own=own)
    matrix = data.get("matrix") or []

    theme.section_label("Head to head")
    left, right = st.columns(2, gap="medium")
    with left:
        with st.container(border=True):
            with guarded("Radar"):
                theme.chart_title("Radar", f"Net sentiment on the most-discussed '{field}' values, both brands")
                fig, count = charts.radar_chart(matrix, own, competitor, colours)
                if count >= 3:
                    ai_ui.chart(fig, config=cfg, key="bm_radar")
                else:
                    st.info("Fewer than 3 attributes have enough opinionated mentions (10+) for both brands.")
    with right:
        with st.container(border=True):
            with guarded("Scorecard"):
                theme.chart_title("Scorecard", "Net sentiment score, -10 to +10")
                rows = charts.scorecard_rows(matrix, own, competitor)
                if rows:
                    theme.scorecard_table(rows)
                    theme.note("Gap = your score minus theirs. Trend compares your second half of the period with the first.")
                    ai_ui.data_insights("bm_scorecard", [
                        {"name": f"{own} score", "points": [[r.get("attribute"), r.get("yours")] for r in rows]},
                        {"name": f"{competitor} score", "points": [[r.get("attribute"), r.get("theirs")] for r in rows]},
                        {"name": "Gap (own minus competitor)", "points": [[r.get("attribute"), r.get("gap")] for r in rows]}])
                else:
                    st.info("No attributes with enough opinionated mentions for both brands.")

    theme.section_label("Switching risk")
    render_switching(sb, membership, opts, f, own, competitor)


STREAM_PAGE_SIZE = 25
STREAM_SORTS = {"Newest first": "newest", "Most engaged": "engaged", "Largest reach": "reach"}


@st.cache_data(ttl=60, show_spinner=False)
def _stream_cached(_sb, tenant_id: str, params_json: str):
    return _sb.rpc("conversation_stream", json.loads(params_json)).execute().data


def page_stream():
    sb = get_client()
    membership = st.session_state.get("membership") or {}
    tenant_id = membership.get("tenant_id", "")
    opts = st.session_state.get("filter_opts", {})
    f = effective_filters("stream")

    theme.page_header("Consumer Stream", "The conversations behind the numbers")
    theme.filter_chips(filter_summary(f))

    left, right = st.columns([2, 1], gap="medium")
    with left:
        brand = st.selectbox("Brand", ["All brands"] + list(opts.get("brands", [])), key="stream_brand")
    with right:
        sort_label = st.selectbox("Sort by", list(STREAM_SORTS), key="stream_sort")

    base = overview_params(f, opts)
    params = {
        "p_start": base["p_start"], "p_end": base["p_end"],
        "p_brand": None if brand == "All brands" else brand,
        "p_networks": base["p_networks"], "p_sentiments": base["p_sentiments"],
        "p_sort": STREAM_SORTS.get(sort_label, "newest"),
    }

    # a new filter, brand or sort starts again from page 1
    signature = json.dumps(params, sort_keys=True)
    if st.session_state.get("stream_sig") != signature:
        st.session_state["stream_sig"] = signature
        st.session_state["stream_page"] = 0

    def fetch(page_index):
        payload = {**params, "p_limit": STREAM_PAGE_SIZE, "p_offset": page_index * STREAM_PAGE_SIZE}
        return _stream_cached(sb, tenant_id, json.dumps(payload, sort_keys=True))

    page = st.session_state.get("stream_page", 0)
    try:
        data = fetch(page)
        pages = max(1, -(-(data.get("total") or 0) // STREAM_PAGE_SIZE))
        if page > pages - 1:                      # the list got shorter since this page was opened
            page = pages - 1
            st.session_state["stream_page"] = page
            data = fetch(page)
    except Exception as e:
        st.error(f"Could not load the conversation stream. Has the Consumer Stream SQL been run? Details: {e}")
        return

    total = data.get("total") or 0
    rows = data.get("rows") or []
    if not total:
        st.info("No conversations match these filters.")
        return

    def go(step):
        st.session_state["stream_page"] = max(0, st.session_state.get("stream_page", 0) + step)

    first = page * STREAM_PAGE_SIZE + 1
    last = first + len(rows) - 1
    nav_prev, nav_next, nav_info = st.columns([1, 1, 5], gap="small")
    with nav_prev:
        st.button("Previous", on_click=go, args=(-1,), disabled=page <= 0, key="stream_prev")
    with nav_next:
        st.button("Next", on_click=go, args=(1,), disabled=page >= pages - 1, key="stream_next")
    with nav_info:
        theme.note(f"Showing {first:,}-{last:,} of {total:,} conversations (page {page + 1} of {pages})")

    for row in rows:
        when = fmt_when(row.get("date"))
        if row.get("simulated"):
            when += " (simulated date)"
        followers = row.get("followers")
        theme.stream_item(
            author=row.get("author"),
            followers_text=f"{fmt_compact(followers)} followers" if followers else "",
            source=row.get("source"),
            date_text=when,
            sentiment=row.get("sentiment"),
            text=row.get("text"),
            likes=row.get("likes"),
            shares=row.get("shares"),
            url=row.get("url"),
            truncated=row.get("truncated"),
        )


# ====================================================================== data & brand selection
def page_data_brands():
    if not (can("upload") or can("edit_brands")):
        theme.page_header("Data & Brand Selection", "Your role cannot upload files or change brands")
        st.info("Ask a workspace admin if you need to add data or change the tracked brands.")
        return
    data_page.render(
        sb=get_client(),
        admin=get_admin_client(),
        membership=st.session_state.get("membership") or {},
        user=st.session_state.user,
        opts=st.session_state.get("filter_opts") or load_filter_options(get_client()),
        on_data_changed=refresh_data,
    )



# ====================================================================== Ask iThink: the data the chat may use
CHAT_BRAND_FIELDS = ("author", "source", "date", "sentiment", "text", "url")


EVIDENCE_FIELDS = ("author", "source", "date", "sentiment", "text", "url")


def make_evidence_fetcher():
    """Posts that back up an AI insight. Same tenant, dates and networks as the chat; only the brand and sentiment change."""
    sb = get_client()
    membership = st.session_state.get("membership") or {}
    tenant = membership.get("tenant_id", "")
    opts = st.session_state.get("filter_opts", {})
    base = overview_params(effective_filters("chat"), opts)
    known = set(opts.get("brands", []))

    def fetch(brand, sentiment, limit):
        if brand not in known or sentiment not in SENTIMENTS:
            return []
        payload = {"p_start": base["p_start"], "p_end": base["p_end"], "p_brand": brand,
                   "p_networks": base["p_networks"], "p_sentiments": [sentiment.lower()],
                   "p_sort": "engaged", "p_limit": int(limit), "p_offset": 0}
        data = _stream_cached(sb, tenant, json.dumps(payload, sort_keys=True))
        return [{k: r.get(k) for k in EVIDENCE_FIELDS} for r in (data or {}).get("rows") or []]

    return fetch


def build_chat_env():
    """The chat can only call these functions, with the signed-in user's own filters and permissions.
    It never writes SQL and never chooses a tenant."""
    sb = get_client()
    membership = st.session_state.get("membership") or {}
    tenant = membership.get("tenant_id", "")
    opts = st.session_state.get("filter_opts", {})
    f = effective_filters("chat")
    base = overview_params(f, opts)
    own = opts.get("own_brand")
    brands = list(opts.get("brands", []))

    def dumps(x):
        return json.dumps(x, sort_keys=True)

    def t_overview(_args):
        return _overview_cached(sb, tenant, dumps(base))

    def t_signals(_args):
        return _signals_cached(sb, tenant, dumps(base))

    def t_attribute(args):
        data, _err = load_attribute(sb, membership, base, args.get("field") or None)
        return data

    def t_switching(args):
        rival = args.get("competitor")
        if rival not in brands or rival == own or not own:
            return None
        payload = {"p_start": base["p_start"], "p_end": base["p_end"], "p_networks": base["p_networks"],
                   "p_sentiments": base["p_sentiments"], "p_own": own, "p_competitor": rival, "p_limit": 1}
        return _switching_cached(sb, tenant, dumps(payload))

    def t_posts(args):
        brand = args.get("brand")
        sentiment = args.get("sentiment")
        sort = args.get("sort") if args.get("sort") in ("newest", "engaged", "reach") else "engaged"
        payload = {"p_start": base["p_start"], "p_end": base["p_end"],
                   "p_brand": brand if brand in brands else None,
                   "p_networks": base["p_networks"],
                   "p_sentiments": [sentiment.lower()] if sentiment in SENTIMENTS else base["p_sentiments"],
                   "p_sort": sort, "p_limit": 5, "p_offset": 0}
        data = _stream_cached(sb, tenant, dumps(payload))
        return [{k: r.get(k) for k in CHAT_BRAND_FIELDS} for r in (data or {}).get("rows") or []]

    return {"context": ai_ui._context(),
            "tools": {"overview": t_overview, "signals": t_signals, "attribute": t_attribute,
                      "switching": t_switching, "posts": t_posts}}


def page_team():
    team_page.render(get_admin_client(), st.session_state.get("membership") or {}, st.session_state.user)


# ====================================================================== shell
def render_account_box(sb, membership):
    user = st.session_state.user
    with st.sidebar:
        st.divider()
        st.caption(f"Signed in as **{user.email}**")
        if membership:
            st.caption(f"Tenant: **{membership['tenants']['name']}**  |  Role: **{membership['role']}**")
        st.caption(f"Build {APP_BUILD}")
        if membership:
            with st.expander("Change password"):
                change_password_form(sb, get_admin_client(), membership, forced=False)
        if st.button("Log out", key="logout_btn"):
            try:
                sb.auth.sign_out()
            except Exception:
                pass
            for key in SESSION_KEYS:
                st.session_state.pop(key, None)
            st.rerun()


def main():
    if "user" not in st.session_state:
        login_view()
        return

    sb = get_client()
    sb.postgrest.auth(st.session_state.access_token)  # attach the user's JWT so RLS applies
    membership = load_membership(sb, st.session_state.user.id)

    horizontal, icon = theme.logo_path("horizontal"), theme.logo_path("icon")
    if horizontal.exists() and icon.exists():
        st.logo(str(horizontal), icon_image=str(icon), size="large")

    if membership is None:
        st.warning("Your account isn't linked to any tenant yet. Contact your admin.")
        render_account_box(sb, membership)
        return

    if membership.get("must_change_password"):
        theme.page_header("Choose your password", "Your admin gave you a temporary password. Set your own to continue.")
        _, mid, _ = st.columns([1, 1.1, 1])
        with mid:
            change_password_form(sb, get_admin_client(), membership, forced=True)
        return

    render_sidebar_filters(sb)
    render_account_box(sb, membership)

    simulated = load_synthetic_count(sb)
    if simulated:
        theme.data_notice(
            "Pilot data",
            f"{simulated:,} conversations carry simulated dates until corrected exports are loaded. "
            "Time-based views are indicative only.",
        )

    chat_slot = st.container()          # filled after the page has drawn, so the chat knows which charts are on screen
    st.session_state["_page_cards"] = []
    pages = [
        st.Page(page_data_brands, title="Data & Brand Selection", icon=":material/upload_file:", url_path="data"),
        st.Page(page_overview, title="Overview", icon=":material/dashboard:", default=True),
        st.Page(page_attribute, title="Attribute", icon=":material/sell:"),
        st.Page(page_signals, title="Signals & Sentiment", icon=":material/mood:"),
        st.Page(page_benchmarking, title="Benchmarking", icon=":material/compare_arrows:"),
        st.Page(page_stream, title="Consumer Stream", icon=":material/forum:"),
    ]
    if can("manage_team"):
        pages.append(st.Page(page_team, title="Team", icon=":material/group:", url_path="team"))
    navigation = st.navigation(pages)
    ai_ui.set_evidence(make_evidence_fetcher())
    navigation.run()
    if navigation.title not in ("Data & Brand Selection", "Team"):
        with chat_slot:
            ai_ui.chat_button(build_chat_env, navigation.title)


if __name__ == "__main__":
    main()
