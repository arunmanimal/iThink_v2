"""
iThink UI theme -- light and dark
---------------------------------
Palettes, global CSS, logo helpers and small reusable components.

The app follows Streamlit's own theme switch (Settings menu -> Theme), so Streamlit's native widgets and
this module's custom styling always agree. `active_mode()` reads the live choice. Nothing here mutates
module-level state per mode, so two people using different themes at once never affect each other.

Save as: app/theme.py
"""
import base64
import hashlib
from functools import lru_cache
from html import escape
from pathlib import Path

import streamlit as st

# ------------------------------------------------------------------ assets
ASSETS_DIR = Path(__file__).parent / "assets"
LOGO_FILES = {
    "light": {"full": ASSETS_DIR / "ithink_logo_light_full.png",
              "horizontal": ASSETS_DIR / "ithink_logo_light_horizontal.png",
              "icon": ASSETS_DIR / "ithink_logo_light_icon.png"},
    "dark": {"full": ASSETS_DIR / "ithink_logo_dark_full.png",
             "horizontal": ASSETS_DIR / "ithink_logo_dark_horizontal.png",
             "icon": ASSETS_DIR / "ithink_logo_dark_icon.png"},
}
LOGO_FULL = LOGO_FILES["light"]["full"]              # kept for older callers
LOGO_HORIZONTAL = LOGO_FILES["light"]["horizontal"]
LOGO_ICON = LOGO_FILES["light"]["icon"]

# ------------------------------------------------------------------ colours that do NOT change with the theme
EMERALD = "#10B981"    # primary accent: CTAs, growth, positive sentiment
VIOLET = "#7C3AED"     # secondary accent: filters, secondary buttons, AI badges
NEGATIVE = "#E11D48"
NEUTRAL = "#94A3B8"
SENTIMENT_COLORS = {"Positive": EMERALD, "Neutral": NEUTRAL, "Negative": NEGATIVE}
# Brand series for charts. Green and red are kept free for sentiment.
OWN_BRAND = "#0EA5E9"                                 # blue  -> your own brand
COMPETITOR_SERIES = [VIOLET, "#F59E0B", "#EC4899"]    # violet, amber, pink -> competitors, in list order
BRAND_SERIES = [OWN_BRAND] + COMPETITOR_SERIES

# ------------------------------------------------------------------ colours that DO change with the theme
PALETTES = {
    "light": {
        "canvas": "#FFFFFF", "card": "#FFFFFF", "sidebar": "#F8FAFC", "surface": "#F8FAFC",
        "ink": "#1E293B", "muted": "#64748B", "line": "#E2E8F0", "placeholder": "#CBD5E1", "bar": "#475569",
        "shadow1": "rgba(30,41,59,0.06)", "shadow2": "rgba(30,41,59,0.04)", "form_shadow": "rgba(30,41,59,0.08)",
        "on_emerald": "#1E293B",            # charcoal on emerald: white-on-emerald is only 2.5:1
        "em_text": "#047857", "vi_text": "#6D28D9", "vi_btn": "#7C3AED", "neg_text": "#BE123C", "amber_text": "#92400E",
        "heat_mid": "#F8FAFC", "slice_edge": "#FFFFFF",
        "cat_series": ["#4F46E5", "#EA580C", "#0284C7", "#C026D3", "#0D9488", "#65A30D", "#B45309", "#475569"],
    },
    "dark": {
        "canvas": "#0F172A", "card": "#1E293B", "sidebar": "#0B1220", "surface": "#162236",
        "ink": "#E2E8F0", "muted": "#94A3B8", "line": "#334155", "placeholder": "#475569", "bar": "#94A3B8",
        "shadow1": "rgba(0,0,0,0.35)", "shadow2": "rgba(0,0,0,0.25)", "form_shadow": "rgba(0,0,0,0.45)",
        "on_emerald": "#0B1220",
        "em_text": "#34D399", "vi_text": "#C4B5FD", "vi_btn": "#A78BFA", "neg_text": "#FB7185", "amber_text": "#FBBF24",
        "heat_mid": "#1E293B", "slice_edge": "#0F172A",
        "cat_series": ["#818CF8", "#FB923C", "#38BDF8", "#E879F9", "#2DD4BF", "#A3E635", "#FBBF24", "#94A3B8"],
    },
}

# Kept so older code that read these constants still works (light values).
CHARCOAL, COOL_GRAY, WHITE = PALETTES["light"]["ink"], PALETTES["light"]["line"], PALETTES["light"]["canvas"]
SURFACE, MUTED = PALETTES["light"]["surface"], PALETTES["light"]["muted"]
EMERALD_DARK, VIOLET_DARK = PALETTES["light"]["em_text"], PALETTES["light"]["vi_text"]
NEGATIVE_DARK, AMBER_DARK = PALETTES["light"]["neg_text"], PALETTES["light"]["amber_text"]
BAR_NEUTRAL, PLACEHOLDER = PALETTES["light"]["bar"], PALETTES["light"]["placeholder"]
CATEGORY_SERIES = PALETTES["light"]["cat_series"]


class _Palette:
    """Attribute access over one palette dict: pal().ink, pal().card, ..."""
    def __init__(self, values):
        self.__dict__.update(values)


_PALETTE_OBJECTS = {mode: _Palette(values) for mode, values in PALETTES.items()}


def active_mode() -> str:
    """'dark' or 'light': whatever the user chose in Streamlit's Settings menu (or their system setting)."""
    context = getattr(st, "context", None)
    info = getattr(context, "theme", None) if context is not None else None
    for key in ("base", "type"):
        try:
            value = getattr(info, key, None)
            if value is None:
                value = info[key]
        except Exception:
            value = None
        if value in ("light", "dark"):
            return value
    return "light"


def pal() -> _Palette:
    return _PALETTE_OBJECTS[active_mode()]


def logo_path(kind: str) -> Path:
    """'full' | 'horizontal' | 'icon' for the active mode; falls back to the light file if a dark one is missing."""
    path = LOGO_FILES[active_mode()][kind]
    return path if path.exists() else LOGO_FILES["light"][kind]


# ------------------------------------------------------------------ global CSS
_CSS_TEMPLATE = """
<style>
/* ---- canvas ---- */
.stApp { background: __CANVAS__; }
header[data-testid="stHeader"] { background: transparent; }
.block-container { padding-top: 2.2rem; padding-bottom: 3rem; max-width: 1480px; }
hr { border-color: __LINE__ !important; }
.stMarkdown a { color: __VI_BTN__; }

/* ---- sidebar ---- */
section[data-testid="stSidebar"] {
  background: __SIDEBAR__;
  border-right: 1px solid __LINE__;
}
section[data-testid="stSidebar"] h3 {
  font-size: 0.78rem; letter-spacing: 0.12em; text-transform: uppercase;
  color: __MUTED__; margin-top: 0.4rem;
}
/* active page in the sidebar nav: violet tint (best effort -- depends on Streamlit's nav markup) */
[data-testid="stSidebarNavLink"][aria-current="page"],
[data-testid="stSidebarNav"] a[aria-current="page"] { background: rgba(124,58,237,0.14) !important; }
[data-testid="stSidebarNavLink"][aria-current="page"] span,
[data-testid="stSidebarNav"] a[aria-current="page"] span { color: __VI_TEXT__ !important; font-weight: 600; }
[data-testid="stSidebarNavLink"]:hover, [data-testid="stSidebarNav"] a:hover { background: rgba(124,58,237,0.08); }

/* ---- typography ---- */
.page-title { font-size: 1.75rem; font-weight: 700; color: __INK__; margin: 0; line-height: 1.2; }
.accent-line { height: 4px; width: 56px; border-radius: 2px; margin: 8px 0 10px 0;
  background: linear-gradient(90deg, __EMERALD__, __VIOLET__); }
.page-sub   { color: __MUTED__; font-size: 0.9rem; margin: 0 0 12px 0; }
.section-label {
  font-size: 0.74rem; font-weight: 700; letter-spacing: 0.14em; text-transform: uppercase;
  color: __INK__; margin: 26px 0 10px 0;
  border-left: 3px solid __EMERALD__; padding-left: 10px;
}
.note { color: __MUTED__; font-size: 0.78rem; margin-top: 4px; }

/* ---- KPI tiles ---- */
.kpi-tile {
  background: __CARD__;
  border: 1px solid __LINE__;
  border-radius: 14px;
  padding: 16px 18px;
  box-sizing: border-box;
  height: 150px;
  overflow: hidden;
  margin-bottom: 14px;
  box-shadow: 0 1px 2px __SHADOW1__, 0 4px 12px __SHADOW2__;
  transition: border-color .2s ease, box-shadow .2s ease, transform .2s ease;
}
.kpi-tile:hover {
  border-color: __EMERALD__;
  box-shadow: 0 0 0 1px rgba(16,185,129,0.25), 0 8px 22px rgba(16,185,129,0.12);
  transform: translateY(-1px);
}
.kpi-tile.accent { position: relative; overflow: hidden; }
.kpi-tile.accent::before {
  content: ""; position: absolute; left: 0; top: 0; bottom: 0; width: 4px;
  background: linear-gradient(180deg, __EMERALD__, __VIOLET__);
}
.kpi-head    { display: flex; justify-content: space-between; align-items: center; min-height: 22px; }
.kpi-label   { font-size: 0.72rem; letter-spacing: 0.1em; text-transform: uppercase; color: __MUTED__; font-weight: 600; }
.kpi-value   { font-size: 2rem; font-weight: 700; color: __INK__; line-height: 1.15; margin-top: 6px; }
.kpi-value.empty { color: __PLACEHOLDER__; }
.kpi-value.small { font-size: 1.3rem; line-height: 1.25; margin-top: 8px; }
.kpi-caption { font-size: 0.74rem; color: __MUTED__; margin-top: 6px; }
.ai-badge {
  background: rgba(124,58,237,0.14); color: __VI_TEXT__;
  border: 1px solid rgba(124,58,237,0.35);
  border-radius: 999px; padding: 1px 9px; font-size: 0.66rem; font-weight: 700; letter-spacing: 0.08em;
}

/* ---- active filter chips ---- */
.chip-row { display: flex; flex-wrap: wrap; gap: 8px; margin: 0 0 4px 0; }
.chip {
  background: rgba(124,58,237,0.10); border: 1px solid rgba(124,58,237,0.30);
  color: __INK__; border-radius: 999px; padding: 3px 12px; font-size: 0.78rem;
}
.chip b { color: __VI_TEXT__; font-weight: 600; }

/* ---- consumer stream ---- */
.stream-item {
  background: __CARD__; border: 1px solid __LINE__; border-radius: 12px;
  padding: 12px 16px; margin: 0 0 10px 0; box-shadow: 0 1px 2px __SHADOW1__;
}
.stream-meta { display: flex; flex-wrap: wrap; gap: 4px 12px; align-items: center; font-size: 0.8rem; color: __MUTED__; margin-bottom: 6px; }
.stream-meta b { color: __INK__; font-size: 0.9rem; }
.stream-text { color: __INK__; font-size: 0.92rem; line-height: 1.5; word-break: break-word; }
.stream-foot { display: flex; gap: 14px; align-items: center; font-size: 0.78rem; color: __MUTED__; margin-top: 8px; }
.stream-foot a { color: __VI_BTN__; text-decoration: none; font-weight: 600; }
.pill { border-radius: 999px; padding: 1px 9px; font-size: 0.7rem; font-weight: 700; letter-spacing: 0.04em; border: 1px solid transparent; }
.pill-positive { background: rgba(16,185,129,0.14); color: __EM_TEXT__; border-color: rgba(16,185,129,0.40); }
.pill-neutral  { background: rgba(148,163,184,0.18); color: __MUTED__; border-color: rgba(148,163,184,0.40); }
.pill-negative { background: rgba(225,29,72,0.12); color: __NEG_TEXT__; border-color: rgba(225,29,72,0.40); }
.pill-switch   { background: rgba(245,158,11,0.16); color: __AMBER_TEXT__; border-color: rgba(245,158,11,0.45); }
.pill-compare  { background: rgba(124,58,237,0.12); color: __VI_TEXT__; border-color: rgba(124,58,237,0.35); }

/* ---- word cloud ---- */
.wc { display: flex; flex-wrap: wrap; gap: 4px 16px; align-items: baseline; justify-content: center;
      line-height: 1.2; padding: 10px 4px 4px 4px; }
.wc-word { transition: opacity .15s ease; cursor: default; }
.wc-word:hover { opacity: 0.7; }

/* ---- scorecard table ---- */
.scorecard { width: 100%; border-collapse: collapse; font-size: 0.9rem; }
.scorecard th { text-align: left; font-size: 0.7rem; letter-spacing: 0.1em; text-transform: uppercase; color: __MUTED__; font-weight: 600; padding: 8px 10px; border-bottom: 1px solid __LINE__; }
.scorecard td { padding: 9px 10px; border-bottom: 1px solid __LINE__; color: __INK__; }
.scorecard td.num, .scorecard th.num { text-align: right; font-variant-numeric: tabular-nums; }
.scorecard tr:last-child td { border-bottom: none; }
.scorecard td.gap-up   { color: __EM_TEXT__; font-weight: 700; }
.scorecard td.gap-down { color: __NEG_TEXT__; font-weight: 700; }
.trend-up { color: __EM_TEXT__; } .trend-down { color: __NEG_TEXT__; } .trend-flat { color: __MUTED__; }

/* ---- chart cards ---- */
.chart-title { font-weight: 600; font-size: 0.95rem; color: __INK__; margin: 2px 0 0 0; }
.chart-sub   { color: __MUTED__; font-size: 0.78rem; margin: 0 0 6px 0; }

/* ---- data-quality notice (pilot / simulated data) ---- */
.data-notice {
  display: flex; gap: 10px; align-items: center;
  background: rgba(245,158,11,0.12); border: 1px solid rgba(245,158,11,0.45);
  border-radius: 10px; padding: 8px 14px; margin: 0 0 12px 0; font-size: 0.82rem; color: __INK__;
}
.data-notice b { color: __AMBER_TEXT__; letter-spacing: 0.08em; text-transform: uppercase; font-size: 0.7rem; }

/* ---- AI insights ---- */
.ins-meta { display: flex; justify-content: space-between; gap: 8px; flex-wrap: wrap; color: __MUTED__; font-size: 0.74rem; margin: 6px 0 6px 0; }
.ai-pill { border: 1px solid __VIOLET__; background: rgba(124,58,237,0.10); color: __VI_TEXT__; border-radius: 999px;
           padding: 1px 9px; font-size: 0.68rem; font-weight: 700; letter-spacing: 0.06em; margin-right: 6px; }
.ins-row { border-radius: 10px; padding: 8px 12px; margin: 0 0 8px 0; display: grid; grid-template-columns: 56px minmax(0, 1fr); gap: 10px; }
.ins-tag { font-weight: 800; font-size: 0.7rem; letter-spacing: 0.1em; text-transform: uppercase; padding-top: 2px; }
.ins-row ul { margin: 0; padding-left: 16px; color: __INK__; font-size: 0.86rem; }
.ins-row li { margin: 2px 0; }
.ins-row.good { background: rgba(16,185,129,0.12); } .ins-row.good .ins-tag { color: __EM_TEXT__; }
.ins-row.bad  { background: rgba(245,158,11,0.15); } .ins-row.bad  .ins-tag { color: __AMBER_TEXT__; }
.ins-row.ugly { background: rgba(225,29,72,0.10); }  .ins-row.ugly .ins-tag { color: __NEG_TEXT__; }
/* ---- AI insights, action-led (Fix / Protect / Grow) ---- */
.ins-card { border-radius: 10px; padding: 10px 12px; margin: 0 0 10px 0; border-left: 4px solid transparent; }
.ins-card.fix { background: rgba(225,29,72,0.10); border-left-color: #E11D48; }
.ins-card.protect { background: rgba(16,185,129,0.12); border-left-color: #10B981; }
.ins-card.grow { background: rgba(124,58,237,0.12); border-left-color: #7C3AED; }
.ins-kind { font-weight: 800; font-size: 0.68rem; letter-spacing: 0.1em; text-transform: uppercase; margin-right: 8px; }
.ins-card.fix .ins-kind { color: __NEG_TEXT__; } .ins-card.protect .ins-kind { color: __EM_TEXT__; } .ins-card.grow .ins-kind { color: __VI_TEXT__; }
.ins-head { color: __INK__; font-weight: 600; font-size: 0.88rem; }
.ins-quote { color: __INK__; font-size: 0.82rem; font-style: italic; margin: 6px 0 0 0; padding-left: 10px; border-left: 2px solid __MUTED__; }
.ins-src { color: __MUTED__; font-size: 0.72rem; font-style: normal; margin-left: 6px; }
.ins-src a { color: inherit; }
.ins-action { color: __INK__; font-size: 0.84rem; margin: 6px 0 0 0; }

/* ---- placeholder cards ---- */
.ph-card {
  background: __SURFACE__;
  border: 2px dashed __LINE__;
  border-radius: 14px; padding: 16px 18px;
  display: flex; flex-direction: column; justify-content: center;
  margin-bottom: 14px;
}
.ph-title { color: __INK__; font-weight: 600; font-size: 0.95rem; }
.ph-hint  { color: __MUTED__; font-size: 0.8rem; margin-top: 4px; }

/* ---- buttons: dark text on emerald (white-on-emerald is only 2.5:1) ---- */
button[kind="primary"], button[kind="primaryFormSubmit"],
button[data-testid="stBaseButton-primary"], button[data-testid="stBaseButton-primaryFormSubmit"] {
  background: __EMERALD__; color: __ON_EMERALD__; border: none; font-weight: 700;
}
button[kind="primary"] p, button[kind="primaryFormSubmit"] p,
button[data-testid="stBaseButton-primary"] p, button[data-testid="stBaseButton-primaryFormSubmit"] p {
  color: __ON_EMERALD__ !important;
}
button[kind="primary"]:hover, button[kind="primaryFormSubmit"]:hover,
button[data-testid="stBaseButton-primary"]:hover, button[data-testid="stBaseButton-primaryFormSubmit"]:hover {
  background: #34D399; box-shadow: 0 4px 14px rgba(16,185,129,0.35);
}
/* secondary buttons: violet outline */
button[kind="secondary"], button[data-testid="stBaseButton-secondary"] {
  background: __CARD__; border: 1px solid __VI_BTN__; color: __VI_BTN__;
}
button[kind="secondary"] p, button[data-testid="stBaseButton-secondary"] p { color: __VI_BTN__ !important; }
button[kind="secondary"]:hover, button[data-testid="stBaseButton-secondary"]:hover {
  background: rgba(124,58,237,0.12); border-color: __VI_BTN__;
}

/* ---- multiselect tags (filters): violet tint ---- */
[data-baseweb="tag"], [data-testid="stMultiSelect"] [data-baseweb="tag"] {
  background-color: rgba(124,58,237,0.14) !important;
  border: 1px solid rgba(124,58,237,0.35) !important;
}
[data-baseweb="tag"] span, [data-baseweb="tag"] div,
[data-testid="stMultiSelect"] [data-baseweb="tag"] span { color: __VI_TEXT__ !important; }
[data-baseweb="tag"] svg { fill: __VI_TEXT__ !important; color: __VI_TEXT__ !important; }

/* ---- login ---- */
.login-wrap { text-align: center; margin: 6vh 0 6px 0; }
.login-tag { color: __MUTED__; font-size: 0.95rem; margin: 6px 0 22px 0; text-align: center; }
div[data-testid="stForm"] {
  background: __CARD__;
  border: 1px solid __LINE__;
  border-radius: 16px;
  padding: 1.4rem 1.4rem 0.8rem 1.4rem;
  box-shadow: 0 10px 34px __FORM_SHADOW__;
}
div[data-testid="stForm"] button { width: 100%; }
</style>
"""

_TOKEN_KEYS = {
    "__CANVAS__": "canvas", "__CARD__": "card", "__SIDEBAR__": "sidebar", "__SURFACE__": "surface",
    "__INK__": "ink", "__MUTED__": "muted", "__LINE__": "line", "__PLACEHOLDER__": "placeholder",
    "__SHADOW1__": "shadow1", "__SHADOW2__": "shadow2", "__FORM_SHADOW__": "form_shadow",
    "__ON_EMERALD__": "on_emerald", "__EM_TEXT__": "em_text", "__VI_TEXT__": "vi_text", "__VI_BTN__": "vi_btn",
    "__NEG_TEXT__": "neg_text", "__AMBER_TEXT__": "amber_text",
}


def _css_for(mode: str) -> str:
    palette = PALETTES[mode]
    tokens = {token: palette[key] for token, key in _TOKEN_KEYS.items()}
    tokens.update({"__EMERALD__": EMERALD, "__VIOLET__": VIOLET})
    css = _CSS_TEMPLATE
    for token in sorted(tokens, key=len, reverse=True):      # longest first, so no token is half-replaced
        css = css.replace(token, tokens[token])
    return css


def _css() -> str:
    return _css_for(active_mode())


def inject_css() -> None:
    st.markdown(_css(), unsafe_allow_html=True)


# ------------------------------------------------------------------ logo helpers
@lru_cache(maxsize=16)
def _b64(path_str: str) -> str:
    return base64.b64encode(Path(path_str).read_bytes()).decode()


def _img_tag(path: Path, width: int) -> str:
    if not path.exists():
        return ""
    return f'<img src="data:image/png;base64,{_b64(str(path))}" width="{width}" alt="iThink">'


def login_header(tagline: str = "Social intelligence and competitor benchmarking") -> None:
    img = _img_tag(logo_path("full"), 230)
    fallback = '<div class="page-title">iThink</div>'
    st.markdown(
        f'<div class="login-wrap">{img or fallback}</div>'
        f'<div class="login-tag">{escape(tagline)}</div>',
        unsafe_allow_html=True,
    )


# ------------------------------------------------------------------ components
def page_header(title: str, subtitle: str = "") -> None:
    sub = f'<div class="page-sub">{escape(subtitle)}</div>' if subtitle else ""
    st.markdown(
        f'<div class="page-title">{escape(title)}</div><div class="accent-line"></div>{sub}',
        unsafe_allow_html=True,
    )


def section_label(text: str) -> None:
    st.markdown(f'<div class="section-label">{escape(text)}</div>', unsafe_allow_html=True)


def note(text: str) -> None:
    st.markdown(f'<div class="note">{escape(text)}</div>', unsafe_allow_html=True)


def kpi_tile(label: str, value, caption: str = "", accent: bool = False, ai: bool = False) -> None:
    """accent -> emerald-to-violet bar on the left (headline metric).
    ai -> violet 'AI' badge (number depends on AI tagging).
    An empty value (None, '' or an em dash) is shown as a faint dash so live numbers stand out."""
    is_empty = value is None or str(value).strip() in ("", "\u2014")
    shown = "\u2014" if is_empty else str(value)
    tile_cls = "kpi-tile accent" if accent else "kpi-tile"
    value_cls = "kpi-value empty" if is_empty else ("kpi-value small" if len(shown) > 12 else "kpi-value")
    badge = '<span class="ai-badge">AI</span>' if ai else ""
    st.markdown(
        f'<div class="{tile_cls}"><div class="kpi-head"><span class="kpi-label">{escape(label)}</span>{badge}</div>'
        f'<div class="{value_cls}">{escape(shown)}</div>'
        f'<div class="kpi-caption">{escape(caption)}</div></div>',
        unsafe_allow_html=True,
    )


def chart_title(title: str, subtitle: str = "") -> None:
    st.session_state["_card"] = {"title": title, "subtitle": subtitle}     # read by the Insights button under the chart
    sub = f'<div class="chart-sub">{escape(subtitle)}</div>' if subtitle else ""
    st.markdown(f'<div class="chart-title">{escape(title)}</div>{sub}', unsafe_allow_html=True)


def _h(value) -> str:
    """HTML-escape untrusted text. Also neutralises '$' so Streamlit does not read it as maths."""
    return escape("" if value is None else str(value)).replace("$", "&#36;")


def stream_item(author, followers_text, source, date_text, sentiment, text, likes, shares, url,
                truncated=False, tags=None) -> None:
    """One conversation in the feed. Everything from the data is escaped; links must be http(s).
    tags: optional [(label, kind)] pills, kind 'switch' | 'compare'."""
    body = _h(text).replace("\r", "").replace("\n", "<br>") + ("..." if truncated else "")
    sentiment = (sentiment or "unclassified").lower()
    pill_kind = sentiment if sentiment in ("positive", "neutral", "negative") else "neutral"
    pills = f'<span class="pill pill-{pill_kind}">{_h(sentiment.title())}</span>'
    for label, kind in tags or []:
        kind = kind if kind in ("switch", "compare") else "compare"
        pills += f'<span class="pill pill-{kind}">{_h(label)}</span>'
    meta = [f"<b>{_h(author or 'Unknown author')}</b>"]
    if followers_text:
        meta.append(_h(followers_text))
    meta += [_h(str(source or "").title()), _h(date_text)]
    meta_html = "".join(f"<span>{m}</span>" if not m.startswith("<b>") else m for m in meta if m)
    foot = [f"<span>Likes {int(likes or 0):,}</span>", f"<span>Shares {int(shares or 0):,}</span>"]
    if url and str(url).lower().startswith(("http://", "https://")):
        foot.append(f'<a href="{escape(str(url), quote=True)}" target="_blank" rel="noopener noreferrer">Open original</a>')
    st.markdown(
        f'<div class="stream-item"><div class="stream-meta">{meta_html}{pills}</div>'
        f'<div class="stream-text">{body}</div><div class="stream-foot">{"".join(foot)}</div></div>',
        unsafe_allow_html=True,
    )


def word_cloud(words, limit: int = 60) -> bool:
    """A tag cloud: bigger word = more conversations. words: [{'word': str, 'mentions': int}].
    Returns False when there is nothing to draw."""
    items = [w for w in (words or []) if w.get("word")][:limit]
    if not items:
        return False
    counts = [float(w.get("mentions") or 0) for w in items]
    top, low = max(counts), min(counts)
    palette = pal().cat_series

    def size(n):
        return 1.35 if top == low else 0.85 + 1.6 * ((n - low) / (top - low)) ** 0.5

    rank = {w["word"]: i for i, w in enumerate(sorted(items, key=lambda w: -float(w.get("mentions") or 0)))}
    # a stable, hash-based order looks like a cloud; sorting by size would look like a staircase
    ordered = sorted(items, key=lambda w: hashlib.md5(str(w["word"]).encode("utf-8")).hexdigest())
    spans = ""
    for w in ordered:
        r, n = rank[w["word"]], float(w.get("mentions") or 0)
        colour = palette[r % len(palette)] if r < 24 else pal().muted
        weight = 700 if r < 8 else 500
        tip = escape(f"{w['word']}: {int(n):,} conversations", quote=True)
        spans += (f'<span class="wc-word" title="{tip}" '
                  f'style="font-size:{size(n):.2f}rem;color:{colour};font-weight:{weight}">{_h(w["word"])}</span>')
    st.markdown(f'<div class="wc">{spans}</div>', unsafe_allow_html=True)
    return True


def scorecard_table(rows) -> None:
    """rows: dicts with attribute, yours, theirs, gap (floats or None) and trend ('up' | 'down' | 'flat' | None)."""
    def num(value, signed=True):
        return "-" if value is None else (f"{value:+.1f}" if signed else f"{value:.1f}")
    arrows = {"up": '<span class="trend-up">&#9650;</span>', "down": '<span class="trend-down">&#9660;</span>',
              "flat": '<span class="trend-flat">&#9654;</span>'}
    body = ""
    for row in rows:
        gap = row.get("gap")
        gap_cls = "" if gap is None or abs(gap) < 0.05 else ("gap-up" if gap > 0 else "gap-down")
        body += (f'<tr><td>{_h(row.get("attribute"))}</td><td class="num">{num(row.get("yours"))}</td>'
                 f'<td class="num">{num(row.get("theirs"))}</td><td class="num {gap_cls}">{num(gap)}</td>'
                 f'<td class="num">{arrows.get(row.get("trend"), "-")}</td></tr>')
    head = ('<tr><th>Attribute</th><th class="num">Your score</th><th class="num">Their score</th>'
            '<th class="num">Gap</th><th class="num">Trend</th></tr>')
    st.markdown(f'<table class="scorecard"><thead>{head}</thead><tbody>{body}</tbody></table>', unsafe_allow_html=True)


def data_notice(label: str, text: str) -> None:
    """Amber strip for data-quality caveats, e.g. simulated dates in pilot data."""
    st.markdown(
        f'<div class="data-notice"><b>{escape(label)}</b><span>{escape(text)}</span></div>',
        unsafe_allow_html=True,
    )


def placeholder_card(title: str, hint: str, height: int = 220) -> None:
    st.markdown(
        f'<div class="ph-card" style="min-height:{int(height)}px">'
        f'<div class="ph-title">{escape(title)}</div>'
        f'<div class="ph-hint">{escape(hint)}</div></div>',
        unsafe_allow_html=True,
    )


def filter_chips(items) -> None:
    """items: list of (label, value) tuples."""
    chips = "".join(
        f'<span class="chip">{escape(label)} <b>{escape(value)}</b></span>' for label, value in items
    )
    st.markdown(f'<div class="chip-row">{chips}</div>', unsafe_allow_html=True)


def brand_colors(brands, own=None) -> dict:
    """Stable brand -> colour map. Your own brand is always blue; competitors take violet, amber, pink
    in list order. Build it from the tenant's FULL brand list (not the filtered one) so a brand keeps
    its colour when the user changes filters."""
    colours, i = {}, 0
    for b in brands:
        if b == own:
            colours[b] = OWN_BRAND
        else:
            colours[b] = COMPETITOR_SERIES[i % len(COMPETITOR_SERIES)]
            i += 1
    return colours


def insight_cards(items: list, meta: str = "") -> None:
    """Action-led insights. items: [{kind: fix|protect|grow, headline, quote, source, url, action}] (plain text, escaped here)."""
    labels = {"fix": "Fix", "protect": "Protect", "grow": "Grow"}
    head = f'<div class="ins-meta"><span><span class="ai-pill">AI</span>{escape(meta)}</span></div>'
    cards = ""
    for it in items:
        kind = it.get("kind") if it.get("kind") in labels else "grow"
        quote = ""
        if it.get("quote"):
            link = ""
            url = str(it.get("url") or "")
            if url.startswith(("http://", "https://")):
                link = f' &middot; <a href="{escape(url, quote=True)}" target="_blank" rel="noopener noreferrer">open post</a>'
            src = f'<span class="ins-src">{escape(it.get("source") or "")}{link}</span>'
            quote = f'<div class="ins-quote">&ldquo;{escape(it["quote"])}&rdquo;{src}</div>'
        cards += (f'<div class="ins-card {kind}"><div><span class="ins-kind">{labels[kind]}</span>'
                  f'<span class="ins-head">{escape(it.get("headline") or "")}</span></div>{quote}'
                  f'<div class="ins-action"><b>Action:</b> {escape(it.get("action") or "")}</div></div>')
    st.markdown(head + cards, unsafe_allow_html=True)


def insight_block(groups: dict, meta: str = "") -> None:
    """Good / Bad / Ugly rows. groups: {'good': [...], 'bad': [...], 'ugly': [...]} (plain text, escaped here)."""
    head = f'<div class="ins-meta"><span><span class="ai-pill">AI</span>{escape(meta)}</span></div>'
    rows = ""
    for key, label in (("good", "Good"), ("bad", "Bad"), ("ugly", "Ugly")):
        bullets = groups.get(key) or []
        if bullets:
            items = "".join(f"<li>{_h(b)}</li>" for b in bullets)
            rows += f'<div class="ins-row {key}"><span class="ins-tag">{label}</span><ul>{items}</ul></div>'
    st.markdown(head + rows, unsafe_allow_html=True)
