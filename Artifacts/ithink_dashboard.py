"""
iThink Dashboard -- themed shell
--------------------------------
Login, sidebar (logo + navigation + global filters), five pages, KPI tile grid.
Charts are placeholders until the aggregation layer (Phase 4) exists.

Auth uses the Supabase anon key plus the signed-in user's JWT, so Row-Level
Security really applies (backend scripts use service_role and bypass it).

Save as: app/dashboard.py   (needs app/theme.py and app/assets/*.png next to it)
"""
from datetime import date, datetime, timedelta

import streamlit as st
from PIL import Image
from supabase import create_client

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

# Placeholder option lists -- swapped for live values once the aggregation layer exists
SOCIAL_NETWORKS = ["INSTAGRAM", "YOUTUBE", "FACEBOOK", "TWITTER"]
SENTIMENTS = ["Positive", "Neutral", "Negative"]
PRODUCT_TYPES = ["ICE", "EV"]

FILTER_KEYS = ("f_date", "f_product", "f_brand", "f_category", "f_network", "f_sentiment")
SESSION_KEYS = (
    "user", "access_token", "sb_client", "membership",
    "date_bounds", "filter_opts", "global_filters",
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
    try:
        base = sb.table("conversations").select("conversation_date").not_.is_("conversation_date", "null")
        lo = base.order("conversation_date").limit(1).execute().data
        hi = base.order("conversation_date", desc=True).limit(1).execute().data
        bounds = (_to_date(lo[0]["conversation_date"]), _to_date(hi[0]["conversation_date"]))
    except Exception:
        today = date.today()
        bounds = (today - timedelta(days=90), today)
    st.session_state["date_bounds"] = bounds
    return bounds


def load_filter_options(sb):
    if "filter_opts" in st.session_state:
        return st.session_state["filter_opts"]
    opts = {"brands": [], "own_brand": None, "categories": []}
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
    st.session_state["filter_opts"] = opts
    return opts


def reset_filters():
    for key in FILTER_KEYS:
        st.session_state.pop(key, None)


def render_sidebar_filters(sb):
    opts = load_filter_options(sb)
    lo, hi = load_date_bounds(sb)

    with st.sidebar:
        st.markdown("### Filters")
        st.date_input("Date range", value=(lo, hi), min_value=lo, max_value=hi, key="f_date")
        st.multiselect("Product type", PRODUCT_TYPES, default=PRODUCT_TYPES, key="f_product")
        st.multiselect("Brand", opts["brands"], default=opts["brands"], key="f_brand")
        st.multiselect("Business category", opts["categories"], default=opts["categories"], key="f_category")
        st.multiselect("Social network", SOCIAL_NETWORKS, default=SOCIAL_NETWORKS, key="f_network")
        st.multiselect("Sentiment", SENTIMENTS, default=SENTIMENTS, key="f_sentiment")
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

    st.session_state["global_filters"] = {
        "date_range": (start, end),
        "products": st.session_state.get("f_product", PRODUCT_TYPES),
        "brands": st.session_state.get("f_brand", opts["brands"]),
        "categories": st.session_state.get("f_category", opts["categories"]),
        "networks": st.session_state.get("f_network", SOCIAL_NETWORKS),
        "sentiments": st.session_state.get("f_sentiment", SENTIMENTS),
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
    add("Networks", f["networks"], SOCIAL_NETWORKS, "networks", always=True)
    add("Sentiment", f["sentiments"], SENTIMENTS, "sentiments")
    add("Categories", f["categories"], opts.get("categories", []), "categories")
    add("Product", f["products"], PRODUCT_TYPES, "types")
    return chips


def count_mentions(sb, f: dict):
    """Live count. Date + network filters only for now; brand/sentiment/category
    filters need the tag tables, which arrive with the Phase 4 aggregation layer."""
    try:
        start, end = f["date_range"]
        networks = f["networks"]
        if not networks:
            return 0
        q = (
            sb.table("conversations")
            .select("id", count="exact")
            .gte("conversation_date", f"{start.isoformat()}T00:00:00")
            .lt("conversation_date", f"{(end + timedelta(days=1)).isoformat()}T00:00:00")
        )
        if len(networks) < len(SOCIAL_NETWORKS):
            q = q.in_("source", networks)
        return q.limit(1).execute().count
    except Exception:
        return None


# ====================================================================== pages
def page_overview():
    sb = get_client()
    f = effective_filters("overview")
    own = st.session_state.get("filter_opts", {}).get("own_brand") or "Own brand"

    theme.page_header("Overview", "Brand conversation snapshot across all tracked networks")
    theme.filter_chips(filter_summary(f))

    theme.section_label("Performance snapshot")
    mentions = count_mentions(sb, f)
    mentions_text = f"{mentions:,}" if isinstance(mentions, int) else DASH

    r1 = st.columns(4, gap="medium")
    with r1[0]:
        theme.kpi_tile("Mentions Count", mentions_text, "Date & network filters applied")
    with r1[1]:
        theme.kpi_tile("Sentiment Score", DASH, "(Pos - Neg) / (Pos + Neg) x 10", accent=True)
    with r1[2]:
        theme.kpi_tile("Distinct Users", DASH, "Unique authors")
    with r1[3]:
        theme.kpi_tile("Negative Mentions", DASH, "AI-tagged negative sentiment")

    r2 = st.columns(4, gap="medium")
    with r2[0]:
        theme.kpi_tile("Reach", DASH, "Followers of distinct authors (proxy)")
    with r2[1]:
        theme.kpi_tile("Engagements", DASH, "Likes + comments + shares")
    with r2[2]:
        theme.kpi_tile("Share of Voice", DASH, f"{own} / all tracked brands")
    with r2[3]:
        theme.kpi_tile("Top Attribute", DASH, "Most-discussed attribute")
    theme.note("Tiles showing a dash go live when the aggregation layer (Phase 4) is built.")

    theme.section_label("Volume & sentiment")
    a, b = st.columns([2, 1], gap="medium")
    with a:
        theme.placeholder_card("Mentions over time", "Spline chart - date on X, mentions on Y", 300)
    with b:
        theme.placeholder_card("Sentiment share", "Pie chart - positive / neutral / negative", 300)

    theme.section_label("Brands & channels")
    c, d, e = st.columns(3, gap="medium")
    with c:
        theme.placeholder_card("Share of voice", "Pie chart - mentions by brand", 260)
    with d:
        theme.placeholder_card("Mentions by source", "Bar chart - one bar per social network", 260)
    with e:
        theme.placeholder_card("Top 10 hashtags", "Bar chart with a value label on every bar", 260)

    theme.section_label("Voices")
    g, h, i = st.columns(3, gap="medium")
    with g:
        theme.placeholder_card("Top 10 advocates", "Authors with the most positive mentions", 260)
    with h:
        theme.placeholder_card("Top 10 detractors", "Authors with the most negative mentions", 260)
    with i:
        theme.placeholder_card("Top 5 reach drivers", "Authors ranked by follower count", 260)

    theme.section_label("Audience & themes")
    j, k = st.columns([3, 2], gap="medium")
    with j:
        theme.placeholder_card("Demographics", "Column charts - gender, and top 10 cities / states", 300)
    with k:
        theme.placeholder_card("Word cloud", "Nouns, topics, people, places, organisations, brands", 300)


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
