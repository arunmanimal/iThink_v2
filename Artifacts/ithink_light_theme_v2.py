"""
iThink UI theme -- light mode
-----------------------------
Palette, global CSS, logo helpers and small reusable components.
Change a colour here and the whole app follows.

Save as: app/theme.py
"""
import base64
from functools import lru_cache
from html import escape
from pathlib import Path

import streamlit as st

# ------------------------------------------------------------------ assets
ASSETS_DIR = Path(__file__).parent / "assets"
LOGO_FULL = ASSETS_DIR / "ithink_logo_light_full.png"              # stacked  -> login page
LOGO_HORIZONTAL = ASSETS_DIR / "ithink_logo_light_horizontal.png"  # lockup   -> sidebar header
LOGO_ICON = ASSETS_DIR / "ithink_logo_light_icon.png"              # icon     -> favicon / collapsed sidebar

# ------------------------------------------------------------------ palette (as specified)
CHARCOAL = "#1E293B"   # text, headings
EMERALD = "#10B981"    # primary accent: CTAs, growth, positive sentiment
VIOLET = "#7C3AED"     # secondary accent: filters, secondary buttons, AI badges
COOL_GRAY = "#E2E8F0"  # borders, dividers, inactive tints
WHITE = "#FFFFFF"      # canvas

# ------------------------------------------------------------------ proposed extensions (need sign-off)
SURFACE = "#F8FAFC"        # sidebar + placeholder fill (a hair off-white so panels separate from the canvas)
MUTED = "#64748B"          # secondary text (4.8:1 on white)
EMERALD_DARK = "#047857"   # emerald used AS TEXT -- #10B981 on white is only 2.5:1
VIOLET_DARK = "#6D28D9"    # violet text on violet tints
NEGATIVE = "#E11D48"
NEUTRAL = "#94A3B8"
SENTIMENT_COLORS = {"Positive": EMERALD, "Neutral": NEUTRAL, "Negative": NEGATIVE}
# Brand series for charts: own brand first. Green and red are kept free for sentiment.
BRAND_SERIES = [VIOLET, "#0EA5E9", "#F59E0B", "#EC4899"]

# ------------------------------------------------------------------ global CSS
_CSS_TEMPLATE = """
<style>
/* ---- canvas ---- */
.stApp { background: __WHITE__; }
header[data-testid="stHeader"] { background: transparent; }
.block-container { padding-top: 2.2rem; padding-bottom: 3rem; max-width: 1480px; }
hr { border-color: __GRAY__ !important; }
.stMarkdown a { color: __VIOLET__; }

/* ---- sidebar ---- */
section[data-testid="stSidebar"] {
  background: __SURFACE__;
  border-right: 1px solid __GRAY__;
}
section[data-testid="stSidebar"] h3 {
  font-size: 0.78rem; letter-spacing: 0.12em; text-transform: uppercase;
  color: __MUTED__; margin-top: 0.4rem;
}

/* ---- typography ---- */
.page-title { font-size: 1.75rem; font-weight: 700; color: __INK__; margin: 0; line-height: 1.2; }
.page-sub   { color: __MUTED__; font-size: 0.9rem; margin: 2px 0 12px 0; }
.section-label {
  font-size: 0.74rem; font-weight: 700; letter-spacing: 0.14em; text-transform: uppercase;
  color: __INK__; margin: 26px 0 10px 0;
  border-left: 3px solid __EMERALD__; padding-left: 10px;
}
.note { color: __MUTED__; font-size: 0.78rem; margin-top: 4px; }

/* ---- KPI tiles ---- */
.kpi-tile {
  background: __WHITE__;
  border: 1px solid __GRAY__;
  border-radius: 14px;
  padding: 16px 18px;
  min-height: 116px;
  margin-bottom: 14px;
  box-shadow: 0 1px 2px rgba(30,41,59,0.06), 0 4px 12px rgba(30,41,59,0.04);
  transition: border-color .2s ease, box-shadow .2s ease, transform .2s ease;
}
.kpi-tile:hover {
  border-color: __EMERALD__;
  box-shadow: 0 0 0 1px rgba(16,185,129,0.25), 0 8px 22px rgba(16,185,129,0.12);
  transform: translateY(-1px);
}
.kpi-tile.accent { border-left: 4px solid __EMERALD__; }
.kpi-head    { display: flex; justify-content: space-between; align-items: center; min-height: 22px; }
.kpi-label   { font-size: 0.72rem; letter-spacing: 0.1em; text-transform: uppercase; color: __MUTED__; font-weight: 600; }
.kpi-value   { font-size: 2rem; font-weight: 700; color: __INK__; line-height: 1.15; margin-top: 6px; }
.kpi-caption { font-size: 0.74rem; color: __MUTED__; margin-top: 6px; }
.ai-badge {
  background: rgba(124,58,237,0.10); color: __VIOLET_DARK__;
  border: 1px solid rgba(124,58,237,0.30);
  border-radius: 999px; padding: 1px 9px; font-size: 0.66rem; font-weight: 700; letter-spacing: 0.08em;
}

/* ---- active filter chips ---- */
.chip-row { display: flex; flex-wrap: wrap; gap: 8px; margin: 0 0 4px 0; }
.chip {
  background: rgba(124,58,237,0.08); border: 1px solid rgba(124,58,237,0.25);
  color: __INK__; border-radius: 999px; padding: 3px 12px; font-size: 0.78rem;
}
.chip b { color: __VIOLET_DARK__; font-weight: 600; }

/* ---- placeholder chart cards (replaced by real charts in Phase 5) ---- */
.ph-card {
  background: __SURFACE__;
  border: 2px dashed __GRAY__;
  border-radius: 14px; padding: 16px 18px;
  display: flex; flex-direction: column; justify-content: center;
  margin-bottom: 14px;
}
.ph-title { color: __INK__; font-weight: 600; font-size: 0.95rem; }
.ph-hint  { color: __MUTED__; font-size: 0.8rem; margin-top: 4px; }

/* ---- buttons: charcoal text on emerald (white-on-emerald is only 2.5:1) ---- */
button[kind="primary"], button[kind="primaryFormSubmit"],
button[data-testid="stBaseButton-primary"], button[data-testid="stBaseButton-primaryFormSubmit"] {
  background: __EMERALD__; color: __INK__; border: none; font-weight: 700;
}
button[kind="primary"] p, button[kind="primaryFormSubmit"] p,
button[data-testid="stBaseButton-primary"] p, button[data-testid="stBaseButton-primaryFormSubmit"] p {
  color: __INK__ !important;
}
button[kind="primary"]:hover, button[kind="primaryFormSubmit"]:hover,
button[data-testid="stBaseButton-primary"]:hover, button[data-testid="stBaseButton-primaryFormSubmit"]:hover {
  background: #34D399; box-shadow: 0 4px 14px rgba(16,185,129,0.35);
}
/* secondary buttons: violet outline */
button[kind="secondary"], button[data-testid="stBaseButton-secondary"] {
  background: __WHITE__; border: 1px solid __VIOLET__; color: __VIOLET__;
}
button[kind="secondary"] p, button[data-testid="stBaseButton-secondary"] p { color: __VIOLET__ !important; }
button[kind="secondary"]:hover, button[data-testid="stBaseButton-secondary"]:hover {
  background: rgba(124,58,237,0.08); border-color: __VIOLET__;
}

/* ---- multiselect tags (filters): violet tint ---- */
[data-baseweb="tag"], [data-testid="stMultiSelect"] [data-baseweb="tag"] {
  background-color: rgba(124,58,237,0.10) !important;
  border: 1px solid rgba(124,58,237,0.30) !important;
}
[data-baseweb="tag"] span, [data-baseweb="tag"] div,
[data-testid="stMultiSelect"] [data-baseweb="tag"] span { color: __VIOLET_DARK__ !important; }
[data-baseweb="tag"] svg { fill: __VIOLET_DARK__ !important; color: __VIOLET_DARK__ !important; }

/* ---- login ---- */
.login-wrap { text-align: center; margin: 6vh 0 6px 0; }
.login-tag { color: __MUTED__; font-size: 0.95rem; margin: 6px 0 22px 0; text-align: center; }
div[data-testid="stForm"] {
  background: __WHITE__;
  border: 1px solid __GRAY__;
  border-radius: 16px;
  padding: 1.4rem 1.4rem 0.8rem 1.4rem;
  box-shadow: 0 10px 34px rgba(30,41,59,0.08);
}
div[data-testid="stForm"] button { width: 100%; }
</style>
"""


def _css() -> str:
    css = _CSS_TEMPLATE
    tokens = {
        "__INK__": CHARCOAL,
        "__EMERALD__": EMERALD,
        "__VIOLET__": VIOLET,
        "__GRAY__": COOL_GRAY,
        "__WHITE__": WHITE,
        "__SURFACE__": SURFACE,
        "__MUTED__": MUTED,
        "__VIOLET_DARK__": VIOLET_DARK,
    }
    # longest tokens first so __VIOLET_DARK__ is never half-replaced by __VIOLET__
    for token in sorted(tokens, key=len, reverse=True):
        css = css.replace(token, tokens[token])
    return css


def inject_css() -> None:
    st.markdown(_css(), unsafe_allow_html=True)


# ------------------------------------------------------------------ logo helpers
@lru_cache(maxsize=8)
def _b64(path_str: str) -> str:
    return base64.b64encode(Path(path_str).read_bytes()).decode()


def _img_tag(path: Path, width: int) -> str:
    if not path.exists():
        return ""
    return f'<img src="data:image/png;base64,{_b64(str(path))}" width="{width}" alt="iThink">'


def login_header(tagline: str = "Social intelligence for two-wheeler brands") -> None:
    img = _img_tag(LOGO_FULL, 230)
    fallback = '<div class="page-title">iThink</div>'
    st.markdown(
        f'<div class="login-wrap">{img or fallback}</div>'
        f'<div class="login-tag">{escape(tagline)}</div>',
        unsafe_allow_html=True,
    )


# ------------------------------------------------------------------ components
def page_header(title: str, subtitle: str = "") -> None:
    sub = f'<div class="page-sub">{escape(subtitle)}</div>' if subtitle else ""
    st.markdown(f'<div class="page-title">{escape(title)}</div>{sub}', unsafe_allow_html=True)


def section_label(text: str) -> None:
    st.markdown(f'<div class="section-label">{escape(text)}</div>', unsafe_allow_html=True)


def note(text: str) -> None:
    st.markdown(f'<div class="note">{escape(text)}</div>', unsafe_allow_html=True)


def kpi_tile(label: str, value, caption: str = "", accent: bool = False, ai: bool = False) -> None:
    """accent -> emerald left bar (headline metric). ai -> violet 'AI' badge (number depends on AI tagging)."""
    tile_cls = "kpi-tile accent" if accent else "kpi-tile"
    badge = '<span class="ai-badge">AI</span>' if ai else ""
    st.markdown(
        f'<div class="{tile_cls}"><div class="kpi-head"><span class="kpi-label">{escape(label)}</span>{badge}</div>'
        f'<div class="kpi-value">{escape(str(value))}</div>'
        f'<div class="kpi-caption">{escape(caption)}</div></div>',
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
