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
from datetime import date, datetime, timedelta

import streamlit as st
from PIL import Image
from supabase import create_client

import charts
import theme


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

# Pilot basis -- flip these when AI tagging covers the dataset (the badges and captions follow).
SENTIMENT_SOURCE = "sprinklr"   # "sprinklr" now; "ai" once AI-tagged sentiment is complete
BRAND_SOURCE = "source file"    # pilot: brand = the export file a conversation came from; later "ai"

# Fallback if the live list of networks cannot be loaded
DEFAULT_NETWORKS = ["INSTAGRAM", "YOUTUBE", "FACEBOOK", "TWITTER"]
SENTIMENTS = ["Positive", "Neutral", "Negative"]
PRODUCT_TYPES = ["ICE", "EV"]

FILTER_KEYS = ("f_date", "f_product", "f_brand", "f_category", "f_network", "f_sentiment")
SESSION_KEYS = (
    "user", "access_token", "sb_client", "membership",
    "date_bounds", "filter_opts", "global_filters", "synthetic_count",
) + FILTER_KEYS


# ====================================================================== auth
def get_client():
    if "sb_client" not in st.session_state:
        st.session_state.sb_client = create_client(SUPABASE_URL, SUPABASE_ANON_KEY)
    return st.session_state.sb_client


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
            except Exception as e:
                st.error(f"Login failed: {e}")
            if ok:
                st.rerun()


def load_membership(sb, user_id):
    if "membership" in st.session_state:
        return st.session_state["membership"]
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
        rows = sb.table("brands").select("brand_name, is_own_brand").execute().data or []
        rows.sort(key=lambda r: (not r["is_own_brand"], r["brand_name"]))
        opts["brands"] = [r["brand_name"] for r in rows]
        own = [r["brand_name"] for r in rows if r["is_own_brand"]]
        opts["own_brand"] = own[0] if own else None
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


def reset_filters():
    for key in FILTER_KEYS:
        st.session_state.pop(key, None)


def render_sidebar_filters(sb):
    opts = load_filter_options(sb)
    lo, hi = load_date_bounds(sb)

    with st.sidebar:
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


def fmt_int(n):
    return f"{int(n):,}" if n is not None else None


GENDER_LABELS = {"F": "Female", "FEMALE": "Female", "M": "Male", "MALE": "Male", "OTHER": "Other"}


def coverage_note(have, total, noun):
    """Every demographic chart says how much of the data it is based on."""
    if not total:
        return ""
    pct = 100 * have / total
    note = f"Based on {have:,} of {total:,} conversations ({pct:.1f}%) with {noun} data"
    return note + (". Low coverage - indicative only." if pct < 10 else ".")


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
    k = (data or {}).get("kpis") or {}

    mentions = k.get("mentions")
    pos, neg = k.get("positive") or 0, k.get("negative") or 0
    score = 10 * (pos - neg) / (pos + neg) if (pos + neg) else None
    branded = k.get("branded_mentions") or 0
    share = 100 * (k.get("own_mentions") or 0) / branded if branded else None
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
        theme.kpi_tile("Engagements", fmt_compact(k.get("engagements")), "Likes + shares (comments not in the export)")
    with r2[2]:
        theme.kpi_tile("Share of Voice", f"{share:.1f}%" if share is not None else None,
                       f"{own} share of branded mentions (by {BRAND_SOURCE})", ai=ai_brand)
    with r2[3]:
        theme.kpi_tile("Top Attribute", top["attribute"] if top else None,
                       f"{top['mentions']:,} of {tagged:,} AI-tagged conversations" if top else "Needs AI-tagged conversations",
                       ai=True)
    theme.note(f"Pilot basis: sentiment from {sentiment_label}, brand assigned by {BRAND_SOURCE}. "
               "Top Attribute uses the AI-tagged sample only.")

    colours = theme.brand_colors(opts.get("brands", []), own=opts.get("own_brand"))
    colours["Unassigned"] = theme.NEUTRAL
    has_data = bool(data) and bool(mentions)

    def empty_state():
        st.info("No conversations match these filters." if data else "No data to show.")

    theme.section_label("Volume & sentiment")
    a, b = st.columns([2, 1], gap="medium")
    with a:
        with st.container(border=True):
            if has_data:
                fig, grain = charts.trend_chart(data.get("trend", []), colours)
                theme.chart_title("Mentions over time", f"{grain} mentions by brand")
                st.plotly_chart(fig, config={"displayModeBar": False}, key="ov_trend")
            else:
                theme.chart_title("Mentions over time")
                empty_state()
    with b:
        with st.container(border=True):
            theme.chart_title("Sentiment share", f"{sentiment_label} sentiment")
            if has_data:
                st.plotly_chart(charts.sentiment_pie(data.get("sentiment", [])),
                                config={"displayModeBar": False}, key="ov_sentiment")
            else:
                empty_state()

    cfg = {"displayModeBar": False}

    theme.section_label("Brands & channels")
    c, d_, e = st.columns(3, gap="medium")
    with c:
        with st.container(border=True):
            theme.chart_title("Share of voice", f"Mentions by brand (by {BRAND_SOURCE})")
            if has_data:
                st.plotly_chart(charts.share_of_voice_pie(data.get("sov", []), colours), config=cfg, key="ov_sov")
            else:
                empty_state()
    with d_:
        with st.container(border=True):
            theme.chart_title("Mentions by source", "One bar per social network")
            if has_data:
                st.plotly_chart(charts.source_bar(data.get("sources", [])), config=cfg, key="ov_sources")
            else:
                empty_state()
    with e:
        with st.container(border=True):
            theme.chart_title("Top 10 hashtags", "Most-used hashtags (once per conversation)")
            rows = (data or {}).get("hashtags") or []
            if has_data and rows:
                st.plotly_chart(charts.hbar(rows, "tag", "mentions", label_fn=lambda t: "#" + str(t)),
                                config=cfg, key="ov_hashtags")
            else:
                empty_state()

    theme.section_label("Voices")
    g, h, i = st.columns(3, gap="medium")
    with g:
        with st.container(border=True):
            theme.chart_title("Top 10 advocates", f"Most positive mentions ({sentiment_label}); anonymous profiles excluded")
            rows = (data or {}).get("advocates") or []
            if has_data and rows:
                st.plotly_chart(charts.hbar(rows, "name", "mentions", colour=theme.EMERALD), config=cfg, key="ov_advocates")
            else:
                empty_state()
    with h:
        with st.container(border=True):
            theme.chart_title("Top 10 detractors", f"Most negative mentions ({sentiment_label}); anonymous profiles excluded")
            rows = (data or {}).get("detractors") or []
            if has_data and rows:
                st.plotly_chart(charts.hbar(rows, "name", "mentions", colour=theme.NEGATIVE), config=cfg, key="ov_detractors")
            else:
                empty_state()
    with i:
        with st.container(border=True):
            theme.chart_title("Top 5 reach drivers", "Authors ranked by follower count")
            rows = (data or {}).get("reach_drivers") or []
            if has_data and rows:
                st.plotly_chart(charts.hbar(rows, "name", "followers"), config=cfg, key="ov_reach")
            else:
                empty_state()

    theme.section_label("Audience & themes")
    cov = (data or {}).get("coverage") or {}
    total = mentions or 0
    j, k_, w = st.columns([1, 2, 2], gap="medium")
    with j:
        with st.container(border=True):
            theme.chart_title("Gender", "Authors' reported gender")
            rows = (data or {}).get("gender") or []
            if has_data and rows:
                st.plotly_chart(
                    charts.column_chart(rows, "gender", "mentions",
                                        label_fn=lambda g_: GENDER_LABELS.get(str(g_).upper(), str(g_).title())),
                    config=cfg, key="ov_gender")
                theme.note(coverage_note(cov.get("gender", 0), total, "gender"))
            else:
                empty_state()
    with k_:
        with st.container(border=True):
            theme.chart_title("Top locations", "Top 10 by mentions")
            default_level = 0 if (cov.get("state", 0) >= cov.get("city", 0)) else 1
            level = st.radio("Location level", ["State", "City"], index=default_level, horizontal=True,
                             label_visibility="collapsed", key="ov_geo_level")
            geo_key, geo_noun = ("cities", "city") if level == "City" else ("states", "state")
            rows = (data or {}).get(geo_key) or []
            if has_data and rows:
                st.plotly_chart(charts.hbar(rows, "name", "mentions", height=280), config=cfg, key="ov_geo")
                theme.note(coverage_note(cov.get(geo_noun, 0), total, geo_noun))
            else:
                empty_state()
    with w:
        theme.placeholder_card("Word cloud", "Nouns, topics, people, places, organisations, brands - next up", 380)


def page_attribute():
    f = effective_filters("attribute")
    theme.page_header("Attribute", "What people talk about, and how each brand scores on it")
    theme.filter_chips(filter_summary(f))

    theme.section_label("Attribute mix & trend")
    a, b = st.columns(2, gap="medium")
    with a:
        theme.placeholder_card("Share of mentions by attribute", "Pie chart", 320)
    with b:
        theme.placeholder_card("Mentions trend by attribute", "Trend line - one line per attribute", 320)

    theme.section_label("Virality map")
    theme.placeholder_card(
        "Who started it - who spiked it - who supports / opposes",
        "Phase 2 feature: needs thread reconstruction, engagement data and stance detection", 220,
    )

    theme.section_label("Benchmark")
    theme.placeholder_card("Brand x attribute matrix", "Table of sentiment scores - rows are attributes, columns are brands", 320)


def page_signals():
    f = effective_filters("signals")
    theme.page_header("Signals & Sentiment", "How people feel, and where they are in the customer journey")
    theme.filter_chips(filter_summary(f))

    theme.section_label("Sentiment & emotion")
    a, b = st.columns(2, gap="medium")
    with a:
        theme.placeholder_card("Sentiment distribution per brand", "Stacked bar", 300)
    with b:
        theme.placeholder_card("Emotion breakdown per brand", "Grouped bar", 300)

    theme.section_label("Journey & trend")
    c, d = st.columns(2, gap="medium")
    with c:
        theme.placeholder_card(
            "Customer journey funnel",
            "Awareness > Consideration > Purchase > Ownership > Service > Loyalty > Advocacy, per brand", 300,
        )
    with d:
        theme.placeholder_card("Overall sentiment trend", "Line chart - all brands overlaid", 300)


def page_benchmarking():
    f = effective_filters("benchmarking")
    opts = st.session_state.get("filter_opts", {})
    own = opts.get("own_brand") or "Own brand"
    competitors = [b for b in opts.get("brands", []) if b != own]

    theme.page_header("Benchmarking", "Head-to-head comparison against one competitor at a time")
    theme.filter_chips(filter_summary(f))

    if competitors:
        default = next((i for i, b in enumerate(competitors) if "KTM" in b), 0)
        st.selectbox(f"Compare {own} against", competitors, index=default, key="bench_competitor")
    else:
        st.info("No competitor brands found for this tenant yet.")

    theme.section_label("Head to head")
    a, b = st.columns(2, gap="medium")
    with a:
        theme.placeholder_card("Radar chart", "Own brand vs selected competitor - top 8-10 attributes by sentiment score", 340)
    with b:
        theme.placeholder_card("Scorecard", "Attribute | Your score | Their score | Gap | Trend arrow", 340)

    theme.section_label("Switching risk")
    theme.placeholder_card("Switching risk", "Conversations tagged Intent = Switching that mention both brands", 220)


def page_stream():
    f = effective_filters("stream")
    opts = st.session_state.get("filter_opts", {})
    theme.page_header("Consumer Stream", "The conversations behind the numbers")
    theme.filter_chips(filter_summary(f))

    if opts.get("brands"):
        st.selectbox("Brand", opts["brands"], key="stream_brand")
    theme.section_label("Conversations")
    theme.placeholder_card("Conversation list", "Paginated feed for the selected brand, with tags and sentiment", 420)


# ====================================================================== shell
def render_account_box(sb, membership):
    user = st.session_state.user
    with st.sidebar:
        st.divider()
        st.caption(f"Signed in as **{user.email}**")
        if membership:
            st.caption(f"Tenant: **{membership['tenants']['name']}**  |  Role: **{membership['role']}**")
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

    if theme.LOGO_HORIZONTAL.exists() and theme.LOGO_ICON.exists():
        st.logo(str(theme.LOGO_HORIZONTAL), icon_image=str(theme.LOGO_ICON), size="large")

    if membership is None:
        st.warning("Your account isn't linked to any tenant yet. Contact your admin.")
        render_account_box(sb, membership)
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

    navigation = st.navigation([
        st.Page(page_overview, title="Overview", icon=":material/dashboard:", default=True),
        st.Page(page_attribute, title="Attribute", icon=":material/sell:"),
        st.Page(page_signals, title="Signals & Sentiment", icon=":material/mood:"),
        st.Page(page_benchmarking, title="Benchmarking", icon=":material/compare_arrows:"),
        st.Page(page_stream, title="Consumer Stream", icon=":material/forum:"),
    ])
    navigation.run()


if __name__ == "__main__":
    main()
