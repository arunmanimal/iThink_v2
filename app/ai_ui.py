"""
iThink AI - Streamlit glue
--------------------------
chart(fig, ...) draws a Plotly chart exactly like st.plotly_chart and adds an Insights button under it.
Pressing it opens two or three action-led insights (Fix / Protect / Grow). Each one explains what is happening, quotes
a real post that shows why, and names a next step. The AI reads the numbers behind the chart plus a handful of real
posts chosen for that card, and every number and quote is checked before it is shown.

Results are cached per chart, filters and data, so opening a card again costs nothing.

Save as: app/ai_ui.py   (needs ai_core.py and theme.py in the same folder)
"""
import hashlib
import json
import re
import time

import streamlit as st

import ai_core as ai
import theme

SESSION_LIMIT = 60            # insight requests per browser session, so one visitor cannot use the daily allowance


def _api_key():
    try:
        return st.secrets.get("GEMINI_API_KEY")
    except Exception:
        return None


def _filters_text(f: dict, opts: dict) -> str:
    if not f:
        return "none"
    start, end = f.get("date_range", (None, None))
    parts = [f"dates {start:%d %b %Y} to {end:%d %b %Y}" if start and end else ""]
    for label, key, universe in (("brands", "brands", opts.get("brands", [])),
                                 ("networks", "networks", opts.get("networks", [])),
                                 ("sentiments", "sentiments", [])):
        chosen = f.get(key) or []
        if chosen and universe and len(chosen) < len(universe):
            parts.append(f"{label}: {', '.join(chosen)}")
        elif chosen and not universe and key == "sentiments" and len(chosen) < 3:
            parts.append(f"{label}: {', '.join(chosen)}")
    return "; ".join(p for p in parts if p) or "none"


def _context() -> dict:
    opts = st.session_state.get("filter_opts") or {}
    own = opts.get("own_brand")
    notes = ["Sentiment is Sprinklr's own sentiment tag, not an AI judgement.",
             "Attribute values, where shown, are Sprinklr's own category fields."]
    if (st.session_state.get("synthetic_count") or 0) > 0:
        notes.append("Some conversations carry simulated dates, so never describe a change over time as a real trend.")
    return {
        "own_brand": own,
        "competitors": [b for b in opts.get("brands", []) if b != own],
        "filters": _filters_text(st.session_state.get("global_filters"), opts),
        "notes": notes,
    }


_EVIDENCE = {"fn": None}


def set_evidence(fn):
    """The dashboard supplies fn(brand, sentiment, limit) -> list of posts, already restricted to the signed-in user's
    tenant and filters. Without it, insights fall back to the chart numbers only."""
    _EVIDENCE["fn"] = fn


_STOP = set("""with from this that have your their about over under into than then them they what when where which while share
mentions mention total sentiment brand brands count counts number numbers other unknown overall percent time week month
day most more less each over per top""".split())
POSTS_PER_CARD = 12
POST_TEXT_CHARS = 280


def _card_terms(payload: dict, context: dict) -> set:
    skip = {w.lower() for name in [context.get("own_brand")] + list(context.get("competitors") or []) if name
            for w in re.findall(r"[A-Za-z0-9]+", name)}
    terms = set()
    for s in payload.get("series", []):
        for label, _ in s.get("points", [])[:60]:
            for w in re.findall(r"[A-Za-z]{4,}", str(label).lower()):
                if w not in _STOP and w not in skip:
                    terms.add(w)
    return terms


def gather_evidence(card: dict, payload: dict, context: dict) -> list:
    """A few real posts that bear on this card: the own brand's most engaged negative and positive posts, plus a
    competitor's negative posts when the card names it. Posts that use the card's own words rank first."""
    fn = _EVIDENCE.get("fn")
    if not fn:
        return []
    own, rivals = context.get("own_brand"), context.get("competitors") or []
    label_text = " ".join(f"{s.get('name', '')} " + " ".join(str(l) for l, _ in s.get("points", [])[:60])
                          for s in payload.get("series", [])).lower()
    mentioned = [b for b in rivals if b.lower() in label_text][:2]
    pool = []
    try:
        for sentiment, limit in (("Negative", 20), ("Positive", 12)):
            pool += [(own, r) for r in (fn(own, sentiment, limit) or [])]
        for b in mentioned:
            pool += [(b, r) for r in (fn(b, "Negative", 8) or [])]
    except Exception:
        return []
    terms = _card_terms(payload, context)
    seen, scored = set(), []
    for idx, (brand, r) in enumerate(pool):
        text = re.sub(r"\s+", " ", str(r.get("text") or "")).strip()
        if len(text) < 30 or text.lower() in seen:
            continue
        seen.add(text.lower())
        scored.append((-sum(1 for t in terms if t in text.lower()), idx, brand, r, text))
    scored.sort(key=lambda x: (x[0], x[1]))
    return [{"id": f"P{n}", "brand": brand, "sentiment": r.get("sentiment"), "source": r.get("source"),
             "date": str(r.get("date") or "")[:10], "url": r.get("url"), "text": text[:POST_TEXT_CHARS]}
            for n, (_, _, brand, r, text) in enumerate(scored[:POSTS_PER_CARD], 1)]


@st.cache_data(ttl=6 * 3600, show_spinner=False, max_entries=300)
def _cached_insights(card_json: str, payload_json: str, context_json: str, posts_json: str, nonce: int) -> dict:
    """nonce is only here so Regenerate can skip the cache. Errors are raised, so they are never cached."""
    result = ai.generate_insights(json.loads(card_json), json.loads(payload_json), json.loads(context_json), _api_key(),
                                  posts=json.loads(posts_json))
    result["at"] = time.strftime("%d %b, %H:%M")
    return result


def _toggle(open_key: str):
    st.session_state[open_key] = not st.session_state.get(open_key, False)


def _regenerate(nonce_key: str):
    st.session_state[nonce_key] = st.session_state.get(nonce_key, 0) + 1


def insights_for(fig, key: str, card: dict = None, payload: dict = None):
    """The button and, when open, the insight block. Call right after drawing a chart."""
    card = card or st.session_state.get("_card") or {"title": "Chart", "subtitle": ""}
    open_key, nonce_key = f"ins_open_{key}", f"ins_nonce_{key}"
    is_open = st.session_state.get(open_key, False)
    st.button("Hide insights" if is_open else "Insights", key=f"ins_btn_{key}", on_click=_toggle,
              args=(open_key,), use_container_width=True)
    if not is_open:
        return
    if not _api_key():
        st.info("Insights are switched off. Add GEMINI_API_KEY to the app's secrets to turn them on.")
        return
    if st.session_state.get("ai_calls", 0) >= SESSION_LIMIT:
        st.info("You have reached the insight limit for this session. Reload the page to continue.")
        return
    try:
        payload = payload or ai.figure_payload(fig)
    except Exception:
        st.info("Insights are not available for this chart.")
        return
    context = _context()
    posts = gather_evidence(card, payload, context)
    args = (json.dumps(card, sort_keys=True), json.dumps(payload, sort_keys=True),
            json.dumps(context, sort_keys=True), json.dumps(posts, sort_keys=True), st.session_state.get(nonce_key, 0))
    seen = st.session_state.setdefault("ai_seen", set())
    fingerprint = hashlib.md5("".join(map(str, args)).encode()).hexdigest()
    try:
        with st.spinner("Reading the numbers"):
            result = _cached_insights(*args)
    except ai.AIError as e:
        st.info(str(e))
        st.button("Try again", key=f"ins_retry_{key}", on_click=_regenerate, args=(nonce_key,), use_container_width=True)
        return
    except Exception:
        st.info("Insights could not be generated right now. Try again in a moment.")
        st.button("Try again", key=f"ins_retry_{key}", on_click=_regenerate, args=(nonce_key,), use_container_width=True)
        return
    if fingerprint not in seen:          # count a request once per distinct result shown
        seen.add(fingerprint)
        st.session_state["ai_calls"] = st.session_state.get("ai_calls", 0) + 1
    meta = f"What to do about this card, {result.get('at', '')}"
    theme.insight_cards(result.get("items") or [], meta)
    note = "Numbers are checked against the chart data. Quotes are real posts."
    if not posts:
        note = "Numbers are checked against the chart data. No posts were available for quotes."
    if result.get("dropped"):
        note += f" {result['dropped']} suggestion(s) were removed because they could not be checked."
    st.caption(note)
    st.button("Regenerate", key=f"ins_regen_{key}", on_click=_regenerate, args=(nonce_key,), use_container_width=True)


def _register(fig):
    """Remember the numbers behind every chart drawn on this page, so Ask iThink can answer at page level."""
    try:
        card = st.session_state.get("_card") or {}
        payload = ai.figure_payload(fig)
        if payload.get("series"):
            st.session_state.setdefault("_page_cards", []).append(
                {"title": card.get("title") or "Chart", "subtitle": card.get("subtitle") or "", "payload": payload})
    except Exception:
        pass


def data_insights(key: str, series: list, card: dict = None):
    """Insights for a card that is not a Plotly chart (word cloud, scorecard, KPI group).
    series = [{"name": "...", "points": [[label, number], ...]}, ...]: the numbers the card shows."""
    card = card or st.session_state.get("_card") or {"title": "Card", "subtitle": ""}
    series = [{"name": s.get("name", ""), "type": "table",
               "points": [[ai._clean_label(l), ai._num(v)] for l, v in s.get("points", []) if ai._num(v) is not None]}
              for s in series]
    series = [s for s in series if s["points"]]
    if not series:
        return
    payload = {"series": series}
    st.session_state.setdefault("_page_cards", []).append(
        {"title": card.get("title") or "Card", "subtitle": card.get("subtitle") or "", "payload": payload})
    insights_for(None, key, card, payload)


def chart(fig, *args, **kwargs):
    """Drop-in for st.plotly_chart that adds the Insights button below the chart."""
    st.plotly_chart(fig, *args, **kwargs)
    _register(fig)
    key = kwargs.get("key")
    if not key:
        card = st.session_state.get("_card") or {}
        key = "c_" + hashlib.md5(json.dumps(card, sort_keys=True).encode()).hexdigest()[:10]
    insights_for(fig, key)


# ====================================================================== Ask iThink (chat)
import ai_chat

CHAT_LIMIT = 30            # questions per browser session
EXAMPLES = {
    "page": ["Which brand leads on this page?", "What stands out here?", "Where is our brand weakest?"],
    "dashboard": ["How does our brand compare with the competitors?", "What are people complaining about?",
                  "Where is our share of voice lowest?"],
}


def _md_safe(text: str) -> str:
    """Post and AI text shown as markdown: stop markdown, links and $ maths from being interpreted."""
    out = str(text or "")
    for ch in ("\\", "`", "*", "_", "[", "]", "<", ">", "$", "#"):
        out = out.replace(ch, "\\" + ch)
    return out


def _ask_now(text: str):
    st.session_state["chat_pending"] = (text or "").strip()


def _submit():
    _ask_now(st.session_state.get("chat_q", ""))
    st.session_state["chat_q"] = ""


def _clear():
    st.session_state["chat_history"] = []


def _run_pending(env: dict, scope: str):
    question = st.session_state.pop("chat_pending", "")
    if not question:
        return
    history = st.session_state.setdefault("chat_history", [])
    entry = {"q": question, "scope": scope, "filters": env["context"].get("filters"), "at": time.strftime("%H:%M")}
    if st.session_state.get("chat_calls", 0) >= CHAT_LIMIT:
        entry["error"] = "You have reached the question limit for this session. Reload the page to continue."
    elif not _api_key():
        entry["error"] = "Ask iThink is switched off. Add GEMINI_API_KEY to the app's secrets to turn it on."
    else:
        try:
            with st.spinner("Reading the numbers"):
                result = ai_chat.ask(question, scope, env["context"], _api_key(), env["tools"],
                                     page_cards=st.session_state.get("_page_cards_saved") or [],
                                     history=[h for h in history if not h.get("error")])
            st.session_state["chat_calls"] = st.session_state.get("chat_calls", 0) + 1
            entry.update(result)
        except ai.AIError as e:
            entry["error"] = str(e)
        except Exception:
            entry["error"] = "Something went wrong while answering. Try again in a moment."
    history.append(entry)
    del history[:-12]


def _render_entry(h: dict):
    with st.chat_message("user"):
        st.write(h["q"])
    with st.chat_message("assistant"):
        if h.get("error"):
            st.info(h["error"])
            return
        for line in h["answer"]:
            st.markdown("- " + _md_safe(line))
        for q in h.get("quotes") or []:
            who = " | ".join(x for x in (q.get("author"), q.get("source"), str(q.get("date") or "")[:10]) if x)
            st.markdown(f"> \"{_md_safe(q['text'])}\"  \n> <small>{_md_safe(who)}</small>", unsafe_allow_html=True)
            if q.get("url"):
                st.link_button("Open post", q["url"])
        scope = "this page" if h["scope"] == "page" else "whole dashboard"
        note = f"AI answer from {scope}. Used: {', '.join(h.get('used') or [])}. Filters: {h.get('filters') or 'none'}. Every number is checked against the data."
        if h.get("dropped"):
            note += f" {h['dropped']} statement(s) removed because they could not be checked."
        st.caption(note)


@st.dialog("Ask iThink", width="large")
def _chat_dialog(env: dict):
    st.caption("Ask in plain words. Answers use the dashboard's numbers and your current filters, never anything else.")
    scope_label = st.radio("Look at", [f"This page ({env['page_title']})", "Whole dashboard"], horizontal=True,
                           key="chat_scope", label_visibility="collapsed")
    scope = "page" if scope_label.startswith("This page") else "dashboard"
    _run_pending(env, scope)
    history = st.session_state.get("chat_history") or []
    if not history:
        st.write("Try one of these:")
        for i, ex in enumerate(EXAMPLES[scope]):
            st.button(ex, key=f"chat_ex_{scope}_{i}", on_click=_ask_now, args=(ex,), use_container_width=True)
    for h in history:
        _render_entry(h)
    with st.form("chat_form", clear_on_submit=False):
        st.text_input("Your question", key="chat_q", placeholder="For example: why is Himalayan ahead of us?",
                      label_visibility="collapsed", max_chars=300)
        left, right = st.columns([3, 1])
        left.form_submit_button("Ask", on_click=_submit, use_container_width=True, type="primary")
        right.form_submit_button("Clear chat", on_click=_clear, use_container_width=True)


@st.cache_data(show_spinner=False)
def _icon_data_uri(path: str) -> str:
    """The iThink icon, shrunk so the page is not carrying a 100 KB image on every rerun."""
    import base64
    import io
    from PIL import Image
    img = Image.open(path).convert("RGBA")
    img.thumbnail((112, 112))
    buf = io.BytesIO()
    img.save(buf, "PNG", optimize=True)
    return "data:image/png;base64," + base64.b64encode(buf.getvalue()).decode()


def _fab_css() -> str:
    dark = theme.active_mode() == "dark"
    bg, edge, ink = ("#1B2438", "#8B6CF0", "#E8ECF4") if dark else ("#FFFFFF", "#6D4AE0", "#1B2438")
    try:
        icon = f"url({_icon_data_uri(str(theme.logo_path('icon')))})"
    except Exception:
        icon = "none"
    return f"""<style>
.st-key-chat_open {{ position: fixed; bottom: 24px; right: 28px; z-index: 1000; width: auto !important; }}
.st-key-chat_open button {{
  width: 60px; height: 60px; min-height: 60px; padding: 0; border-radius: 30px; overflow: hidden;
  background: {bg} {icon} no-repeat 50% 50% / 34px 34px; border: 1.5px solid {edge};
  box-shadow: 0 6px 20px rgba(0,0,0,.35); font-size: 0; color: transparent;
  transition: width .18s ease, box-shadow .18s ease, background-position .18s ease; white-space: nowrap;
}}
.st-key-chat_open button p {{ font-size: 0; }}
.st-key-chat_open button:hover {{
  width: 168px; background-position: 13px 50%; padding-left: 52px; box-shadow: 0 8px 26px rgba(0,0,0,.45);
  border-color: {edge};
}}
.st-key-chat_open button:hover::after {{
  content: "Ask iThink"; font-size: 15px; font-weight: 600; color: {ink}; font-family: inherit;
}}
.st-key-chat_open button:focus {{ box-shadow: 0 0 0 3px {edge}55; }}
</style>"""


def chat_button(env_builder, page_title: str):
    """Floating iThink icon at the lower right; on hover it widens to read "Ask iThink".
    env_builder() returns {'context': ..., 'tools': {...}} using the current filters.
    Call after the page has drawn, so this page's chart numbers are known."""
    st.session_state["_page_cards_saved"] = list(st.session_state.get("_page_cards") or [])
    st.markdown(_fab_css(), unsafe_allow_html=True)
    if st.button("Ask iThink", key="chat_open"):
        env = env_builder()
        env["page_title"] = page_title
        _chat_dialog(env)
