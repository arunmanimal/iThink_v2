"""
iThink UI theme
---------------
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
LOGO_FULL = ASSETS_DIR / "ithink_logo_dark_full.png"              # stacked  -> login page
LOGO_HORIZONTAL = ASSETS_DIR / "ithink_logo_dark_horizontal.png"  # lockup   -> sidebar header
LOGO_ICON = ASSETS_DIR / "ithink_logo_dark_icon.png"              # icon     -> favicon / collapsed sidebar

# ------------------------------------------------------------------ palette (as specified)
DEEP_OCEAN = "#0B253A"    # canvas / app background
OCEAN_SLATE = "#163E59"   # cards, sidebar, elevated containers
NEON_CYAN = "#00F0FF"     # primary CTA, active states, critical metrics
SKY_BLUE = "#3A86FF"      # secondary accent
ICE_WHITE = "#F0F4F8"     # text

# ------------------------------------------------------------------ proposed extensions (need sign-off)
MUTED = "#9FB3C8"         # secondary text
POSITIVE = "#2EE59D"
NEUTRAL = "#8FA9BF"
NEGATIVE = "#FF5C7A"
AMBER = "#FFB703"
VIOLET = "#B388FF"
BRAND_SERIES = [NEON_CYAN, SKY_BLUE, AMBER, VIOLET]   # own brand first, then competitors
SENTIMENT_COLORS = {"Positive": POSITIVE, "Neutral": NEUTRAL, "Negative": NEGATIVE}

# ------------------------------------------------------------------ global CSS
_CSS_TEMPLATE = """
<style>
/* ---- canvas ---- */
.stApp {
  background:
    radial-gradient(900px 420px at 92% -8%, rgba(0,240,255,0.10), transparent 62%),
    radial-gradient(700px 380px at -5% 105%, rgba(58,134,255,0.10), transparent 60%),
    __DEEP__;
}
header[data-testid="stHeader"] { background: transparent; }
.block-container { padding-top: 2.2rem; padding-bottom: 3rem; max-width: 1480px; }

/* ---- sidebar ---- */
section[data-testid="stSidebar"] {
  background: __SLATE__;
  border-right: 1px solid rgba(0,240,255,0.14);
}
section[data-testid="stSidebar"] h3 {
  font-size: 0.78rem; letter-spacing: 0.12em; text-transform: uppercase;
  color: __MUTED__; margin-top: 0.4rem;
}

/* ---- typography ---- */
.page-title { font-size: 1.75rem; font-weight: 700; color: __ICE__; margin: 0; line-height: 1.2; }
.page-sub   { color: __MUTED__; font-size: 0.9rem; margin: 2px 0 12px 0; }
.section-label {
  font-size: 0.74rem; font-weight: 600; letter-spacing: 0.14em; text-transform: uppercase;
  color: __CYAN__; margin: 24px 0 10px 0;
}
.note { color: __MUTED__; font-size: 0.78rem; margin-top: 4px; }

/* ---- KPI tiles ---- */
.kpi-tile {
  background: __SLATE__;
  border: 1px solid rgba(0,240,255,0.14);
  border-radius: 14px;
  padding: 16px 18px;
  min-height: 116px;
  margin-bottom: 14px;
  box-shadow: 0 6px 18px rgba(0,0,0,0.25);
  transition: border-color .2s ease, box-shadow .2s ease, transform .2s ease;
}
.kpi-tile:hover {
  border-color: rgba(0,240,255,0.55);
  box-shadow: 0 0 0 1px rgba(0,240,255,0.22), 0 8px 24px rgba(0,240,255,0.10);
  transform: translateY(-1px);
}
.kpi-label   { font-size: 0.72rem; letter-spacing: 0.1em; text-transform: uppercase; color: __MUTED__; font-weight: 600; }
.kpi-value   { font-size: 2rem; font-weight: 700; color: __ICE__; line-height: 1.15; margin-top: 6px; }
.kpi-value.accent { color: __CYAN__; text-shadow: 0 0 18px rgba(0,240,255,0.35); }
.kpi-caption { font-size: 0.74rem; color: __MUTED__; margin-top: 6px; }

/* ---- active filter chips ---- */
.chip-row { display: flex; flex-wrap: wrap; gap: 8px; margin: 0 0 4px 0; }
.chip {
  background: rgba(0,240,255,0.08); border: 1px solid rgba(0,240,255,0.28);
  color: __ICE__; border-radius: 999px; padding: 3px 12px; font-size: 0.78rem;
}
.chip b { color: __CYAN__; font-weight: 600; }

/* ---- placeholder chart cards (replaced by real charts in Phase 5) ---- */
.ph-card {
  background: rgba(22,62,89,0.55);
  border: 1px dashed rgba(0,240,255,0.30);
  border-radius: 14px; padding: 16px 18px;
  display: flex; flex-direction: column; justify-content: center;
  margin-bottom: 14px;
}
.ph-title { color: __ICE__; font-weight: 600; font-size: 0.95rem; }
.ph-hint  { color: __MUTED__; font-size: 0.8rem; margin-top: 4px; }

/* ---- buttons: dark text on neon cyan (white-on-cyan is unreadable) ---- */
button[kind="primary"], button[kind="primaryFormSubmit"],
button[data-testid="stBaseButton-primary"], button[data-testid="stBaseButton-primaryFormSubmit"] {
  background: __CYAN__; color: __DEEP__; border: none; font-weight: 700;
}
button[kind="primary"] p, button[kind="primaryFormSubmit"] p,
button[data-testid="stBaseButton-primary"] p, button[data-testid="stBaseButton-primaryFormSubmit"] p {
  color: __DEEP__ !important;
}
button[kind="primary"]:hover, button[kind="primaryFormSubmit"]:hover,
button[data-testid="stBaseButton-primary"]:hover, button[data-testid="stBaseButton-primaryFormSubmit"]:hover {
  background: #5CF5FF; box-shadow: 0 0 18px rgba(0,240,255,0.45);
}
button[kind="secondary"], button[data-testid="stBaseButton-secondary"] {
  background: transparent; border: 1px solid rgba(0,240,255,0.35); color: __ICE__;
}
button[kind="secondary"]:hover, button[data-testid="stBaseButton-secondary"]:hover {
  border-color: __CYAN__; color: __CYAN__;
}

/* ---- multiselect tags: readable on dark ---- */
span[data-baseweb="tag"] {
  background-color: rgba(0,240,255,0.16) !important;
  border: 1px solid rgba(0,240,255,0.40);
}
span[data-baseweb="tag"] span { color: __ICE__ !important; }

/* ---- login ---- */
.login-wrap { text-align: center; margin: 6vh 0 6px 0; }
.login-wrap img { filter: drop-shadow(0 0 28px rgba(0,240,255,0.25)); }
.login-tag { color: __MUTED__; font-size: 0.95rem; margin: 6px 0 22px 0; text-align: center; }
div[data-testid="stForm"] {
  background: __SLATE__;
  border: 1px solid rgba(0,240,255,0.18);
  border-radius: 16px;
  padding: 1.4rem 1.4rem 0.8rem 1.4rem;
  box-shadow: 0 10px 40px rgba(0,0,0,0.35);
}
div[data-testid="stForm"] button { width: 100%; }
</style>
"""


def _css() -> str:
    css = _CSS_TEMPLATE
    tokens = {
        "__DEEP__": DEEP_OCEAN,
        "__SLATE__": OCEAN_SLATE,
        "__CYAN__": NEON_CYAN,
        "__SKY__": SKY_BLUE,
        "__ICE__": ICE_WHITE,
        "__MUTED__": MUTED,
    }
    for token, value in tokens.items():
        css = css.replace(token, value)
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


def kpi_tile(label: str, value, caption: str = "", accent: bool = False) -> None:
    value_cls = "kpi-value accent" if accent else "kpi-value"
    st.markdown(
        f'<div class="kpi-tile"><div class="kpi-label">{escape(label)}</div>'
        f'<div class="{value_cls}">{escape(str(value))}</div>'
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
