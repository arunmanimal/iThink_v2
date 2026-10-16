"""
iThink chart builders (Plotly)
------------------------------
Pure functions: rows from the database functions in, a Plotly figure out.
Colours come from theme.py.

Save as: app/charts.py
"""
import numpy as np
import pandas as pd
import plotly.graph_objects as go

import theme

FONT = "Source Sans Pro, Helvetica, Arial, sans-serif"
SENTIMENT_ORDER = ["positive", "neutral", "negative", "unclassified"]


def _sentiment_colours():
    return {
        "positive": theme.EMERALD,
        "neutral": theme.NEUTRAL,
        "negative": theme.NEGATIVE,
        "unclassified": theme.pal().placeholder,
    }


STAGE_ORDER = ["awareness", "consideration", "purchase", "ownership", "service", "loyalty", "advocacy"]
WEEKLY_AFTER_DAYS = 45        # ranges longer than this are shown as weekly totals (daily is too noisy)
MIN_SAMPLE_WEEKLY = 30        # a sentiment score on fewer opinionated mentions than this is noise
MIN_SAMPLE_DAILY = 10
MIN_CELL_SAMPLE = 10          # a brand x attribute score needs at least this many opinionated mentions
MIN_HALF_SAMPLE = 5           # ...and this many in each half of the period for a trend arrow
TREND_THRESHOLD = 0.5         # score change between halves that counts as up / down


def _style(fig, height=300, legend=True, margin=None):
    P = theme.pal()
    fig.update_layout(
        height=height,
        margin=margin or dict(l=4, r=4, t=8, b=4),
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(0,0,0,0)",
        font=dict(family=FONT, color=P.ink, size=13),
        showlegend=legend,
        legend=dict(orientation="h", yanchor="top", y=-0.12, xanchor="left", x=0),
        hoverlabel=dict(bgcolor=P.card, font_color=P.ink, bordercolor=P.line),
    )
    return fig


def _short(text, limit=30):
    text = str(text)
    return text if len(text) <= limit else text[: limit - 3] + "..."


def _unique(labels):
    """Plotly merges bars that share a label, so repeated labels get a suffix."""
    seen, out = {}, []
    for label in labels:
        seen[label] = seen.get(label, 0) + 1
        out.append(label if seen[label] == 1 else f"{label} ({seen[label]})")
    return out


def order_stages(names):
    """Journey stages in funnel order; unknown names go after, alphabetically."""
    def key(name):
        lowered = str(name).lower()
        for position, stage in enumerate(STAGE_ORDER):
            if stage in lowered:
                return (position, str(name))
        return (len(STAGE_ORDER), str(name))
    return sorted(names, key=key)


# ---------------------------------------------------------------- time series
def _brand_frames(df, value_cols):
    """Per-brand frames on a shared date axis, with honest gaps.

    * Days outside a brand's own first..last date are NaN: no data is not the same as zero.
    * Ranges longer than WEEKLY_AFTER_DAYS become weekly sums. Weeks that the global range
      or the brand's data only partly covers are dropped, so edges do not ramp falsely.
    Returns ({brand: frame}, is_weekly).
    """
    days = pd.date_range(df["bucket"].min(), df["bucket"].max(), freq="D")
    weekly = len(days) > WEEKLY_AFTER_DAYS
    full_weeks = None
    if weekly:
        span = pd.Series(1, index=days).resample("W").sum()
        full_weeks = span[span == 7].index

    frames = {}
    for brand, group in df.groupby("brand"):
        part = group.set_index("bucket")[value_cols].astype(float)
        first, last = part.index.min(), part.index.max()
        # Plain numpy from here on. Assigning into a pandas frame that shares memory with another one
        # (copy-on-write) fails on some pandas versions, so no pandas in-place assignment is used.
        values = part.reindex(days, fill_value=0.0).to_numpy(dtype=float, copy=True)
        outside = np.asarray((days < first) | (days > last)).ravel()
        values[outside, :] = np.nan
        if weekly:
            daily = pd.DataFrame(values, index=days, columns=value_cols)
            missing = pd.Series(np.isnan(values).any(axis=1).astype(int), index=days).resample("W").sum()
            summed = daily.resample("W").sum(min_count=1)
            weekly_values = summed.to_numpy(dtype=float, copy=True)
            weekly_values[missing.reindex(summed.index).to_numpy() > 0, :] = np.nan
            frame = pd.DataFrame(weekly_values, index=summed.index, columns=value_cols)
            frame = frame.loc[frame.index.isin(full_weeks)]
        else:
            frame = pd.DataFrame(values, index=days, columns=value_cols)
        frames[brand] = frame
    return frames, weekly


def trend_chart(rows, colours):
    """Mentions over time, one spline per brand. Returns (figure, 'Daily' | 'Weekly')."""
    fig = go.Figure()
    df = pd.DataFrame(rows)
    if df.empty:
        return _style(fig), "Daily"
    df["bucket"] = pd.to_datetime(df["bucket"])
    frames, weekly = _brand_frames(df, ["mentions"])

    for brand, frame in frames.items():
        colour = colours.get(brand, theme.NEUTRAL)
        fig.add_trace(go.Scatter(
            x=frame.index,
            y=frame["mentions"].values,
            name=brand,
            mode="lines",
            connectgaps=False,
            line=dict(color=colour, width=3.5 if colour == theme.OWN_BRAND else 2.2, shape="spline", smoothing=0.7),
            hovertemplate=("Week ending " if weekly else "") + "%{x|%d %b %Y}: %{y:,.0f}<extra>" + brand + "</extra>",
        ))
    fig.update_xaxes(showgrid=False, tickformat="%d %b", linecolor=theme.pal().line)
    fig.update_yaxes(gridcolor=theme.pal().line, zeroline=False, rangemode="tozero", tickformat=",")
    return _style(fig, 320), ("Weekly" if weekly else "Daily")


def sentiment_trend_chart(rows, colours):
    """Net sentiment score ((pos - neg) / (pos + neg) x 10) over time, one line per brand."""
    fig = go.Figure()
    df = pd.DataFrame(rows)
    if df.empty:
        return _style(fig), "Daily"
    df["bucket"] = pd.to_datetime(df["bucket"])
    frames, weekly = _brand_frames(df, ["positive", "negative"])
    minimum = MIN_SAMPLE_WEEKLY if weekly else MIN_SAMPLE_DAILY

    for brand, frame in frames.items():
        opinion = frame["positive"] + frame["negative"]
        score = (10 * (frame["positive"] - frame["negative"]) / opinion).where(opinion >= minimum)
        colour = colours.get(brand, theme.NEUTRAL)
        fig.add_trace(go.Scatter(
            x=frame.index,
            y=score.values,
            name=brand,
            mode="lines",
            connectgaps=False,
            line=dict(color=colour, width=3.5 if colour == theme.OWN_BRAND else 2.2, shape="spline", smoothing=0.7),
            hovertemplate=("Week ending " if weekly else "") + "%{x|%d %b %Y}: %{y:+.1f}<extra>" + brand + "</extra>",
        ))
    fig.update_xaxes(showgrid=False, tickformat="%d %b", linecolor=theme.pal().line)
    fig.update_yaxes(gridcolor=theme.pal().line, zeroline=True, zerolinecolor=theme.pal().muted, range=[-10, 10], tickformat="+.0f")
    return _style(fig, 320), ("Weekly" if weekly else "Daily")


# ---------------------------------------------------------------- donuts
def _donut(labels, values, colours, height=300):
    fig = go.Figure()
    fig.add_trace(go.Pie(
        labels=labels,
        values=values,
        hole=0.58,
        sort=False,
        marker=dict(colors=colours, line=dict(color=theme.pal().slice_edge, width=2)),
        texttemplate="%{percent:.1%}",
        insidetextorientation="horizontal",
        hovertemplate="%{label}: %{value:,} (%{percent})<extra></extra>",
    ))
    return _style(fig, height)


def sentiment_pie(rows):
    df = pd.DataFrame(rows)
    if df.empty:
        return _style(go.Figure())
    df["order"] = df["sentiment"].map({k: i for i, k in enumerate(SENTIMENT_ORDER)}).fillna(99)
    df = df.sort_values("order")
    return _donut(
        [s.capitalize() for s in df["sentiment"]],
        list(df["mentions"]),
        [_sentiment_colours().get(s, theme.NEUTRAL) for s in df["sentiment"]],
    )


def share_of_voice_pie(rows, colours):
    df = pd.DataFrame(rows)
    if df.empty:
        return _style(go.Figure())
    return _donut(
        list(df["brand"]),
        list(df["mentions"]),
        [colours.get(b, theme.NEUTRAL) for b in df["brand"]],
    )


# ---------------------------------------------------------------- bars
def hbar(rows, label_key, value_key, colour=None, label_fn=None, height=300, value_format=",.0f"):
    """Horizontal bars with a value label on each bar, largest on top.
    value_format is a d3 format: ',.0f' for counts, '.3s' for compact numbers like 31.0M."""
    fig = go.Figure()
    df = pd.DataFrame(rows)
    if df.empty:
        return _style(fig, height, legend=False)
    df = df.sort_values(value_key, kind="stable")
    labels = [_short(label_fn(v) if label_fn else v) for v in df[label_key]]
    fig.add_trace(go.Bar(
        x=df[value_key],
        y=_unique(labels),
        orientation="h",
        marker_color=colour or theme.pal().bar,
        text=df[value_key],
        texttemplate="%{x:" + value_format + "}",
        textposition="outside",
        cliponaxis=False,
        hovertemplate="%{y}: %{x:,.0f}<extra></extra>",
    ))
    fig.update_xaxes(visible=False)
    fig.update_yaxes(showgrid=False, linecolor=theme.pal().line)
    return _style(fig, height, legend=False, margin=dict(l=4, r=56, t=8, b=4))


def source_bar(rows):
    return hbar(rows, "source", "mentions", label_fn=lambda s: str(s).title())


def column_chart(rows, label_key, value_key, colour=None, label_fn=None, height=280):
    """Vertical columns with a value label on each column, in the order given."""
    fig = go.Figure()
    df = pd.DataFrame(rows)
    if df.empty:
        return _style(fig, height, legend=False)
    labels = [_short(label_fn(v) if label_fn else v, 18) for v in df[label_key]]
    fig.add_trace(go.Bar(
        x=_unique(labels),
        y=df[value_key],
        marker_color=colour or theme.pal().bar,
        text=df[value_key],
        texttemplate="%{y:,.0f}",
        textposition="outside",
        cliponaxis=False,
        hovertemplate="%{x}: %{y:,.0f}<extra></extra>",
    ))
    fig.update_yaxes(visible=False)
    fig.update_xaxes(showgrid=False, linecolor=theme.pal().line, tickangle=0)
    return _style(fig, height, legend=False, margin=dict(l=4, r=4, t=24, b=4))


def sentiment_by_brand_bar(rows, brand_order):
    """100% stacked bars: how each brand's mentions split into positive / neutral / negative."""
    fig = go.Figure()
    df = pd.DataFrame(rows)
    if df.empty:
        return _style(fig, 300)
    pivot = df.pivot_table(index="brand", columns="sentiment", values="mentions", aggfunc="sum", fill_value=0)
    totals = pivot.sum(axis=1)
    brands = [b for b in brand_order if b in pivot.index] + [b for b in pivot.index if b not in brand_order]
    brands = list(reversed(brands))        # horizontal bars draw bottom-up; this puts the first brand on top

    for sentiment in SENTIMENT_ORDER:
        if sentiment not in pivot.columns or pivot[sentiment].sum() == 0:
            continue
        counts = pivot[sentiment].reindex(brands)
        share = (100 * counts / totals.reindex(brands))
        fig.add_trace(go.Bar(
            name=sentiment.capitalize(),
            y=brands,
            x=share.values,
            orientation="h",
            marker_color=_sentiment_colours()[sentiment],
            text=[f"{v:.0f}%" if v >= 6 else "" for v in share.values],
            textposition="inside",
            insidetextanchor="middle",
            customdata=counts.values,
            hovertemplate="%{y} - " + sentiment.capitalize() + ": %{customdata:,.0f} (%{x:.1f}%)<extra></extra>",
        ))
    fig.update_layout(barmode="stack")
    fig.update_xaxes(range=[0, 100], ticksuffix="%", showgrid=False, linecolor=theme.pal().line)
    fig.update_yaxes(showgrid=False)
    return _style(fig, 300)


def grouped_columns(rows, category_key, colours, order=None, height=300):
    """Grouped columns: one group per category, one bar per brand."""
    fig = go.Figure()
    df = pd.DataFrame(rows)
    if df.empty:
        return _style(fig, height)
    if order is None:
        order = list(df.groupby(category_key)["mentions"].sum().sort_values(ascending=False).index)
    for brand, group in df.groupby("brand"):
        values = group.groupby(category_key)["mentions"].sum().reindex(order, fill_value=0)
        fig.add_trace(go.Bar(
            name=brand,
            x=list(order),
            y=values.values,
            marker_color=colours.get(brand, theme.NEUTRAL),
            hovertemplate="%{x} - " + brand + ": %{y:,.0f}<extra></extra>",
        ))
    fig.update_layout(barmode="group")
    fig.update_xaxes(showgrid=False, linecolor=theme.pal().line, tickangle=0)
    fig.update_yaxes(gridcolor=theme.pal().line, zeroline=False, tickformat=",")
    return _style(fig, height)


# ---------------------------------------------------------------- attributes / benchmarking
def _net_score(positive, negative, minimum):
    opinion = positive + negative
    return (10 * (positive - negative) / opinion).where(opinion >= minimum)


def attribute_scores(rows):
    """Per (attribute, brand): totals, net sentiment score, and scores for each half of the period."""
    df = pd.DataFrame(rows)
    if df.empty:
        return pd.DataFrame(columns=["value", "brand", "positive", "negative", "mentions", "score", "score_h1", "score_h2"])
    for col in ("positive", "negative", "mentions"):
        df[col] = df[col].astype(float)
    total = df.groupby(["value", "brand"])[["positive", "negative", "mentions"]].sum()
    total["score"] = _net_score(total["positive"], total["negative"], MIN_CELL_SAMPLE)
    halves = df.groupby(["value", "brand", "half"])[["positive", "negative"]].sum()
    halves["score"] = _net_score(halves["positive"], halves["negative"], MIN_HALF_SAMPLE)
    for half in (1, 2):
        part = halves.xs(half, level="half")["score"] if half in halves.index.get_level_values("half") else pd.Series(dtype=float)
        total[f"score_h{half}"] = part
    return total.reset_index()


def category_donut(shares, total_pairs):
    """Share of mentions by category value: the top values plus an 'Other' slice for the rest."""
    df = pd.DataFrame(shares)
    if df.empty:
        return _style(go.Figure())
    labels = [_short(v, 34) for v in df["value"]]
    values = [float(v) for v in df["mentions"]]
    series = theme.pal().cat_series
    colours = [series[i % len(series)] for i in range(len(labels))]
    other = float(total_pairs or 0) - sum(values)
    if other > 0:
        labels.append("Other")
        values.append(other)
        colours.append(theme.pal().placeholder)
    fig = _donut(labels, values, colours, height=340)
    fig.update_layout(legend=dict(orientation="v", yanchor="middle", y=0.5, xanchor="left", x=1.02))
    return fig


def category_colours(shares):
    series = theme.pal().cat_series
    return {row["value"]: series[i % len(series)] for i, row in enumerate(shares or [])}


def score_heatmap(rows, brand_order, value_order):
    """Brand x attribute matrix of net sentiment scores. Thin cells are left blank, not plotted as wild scores."""
    fig = go.Figure()
    scores = attribute_scores(rows)
    if scores.empty:
        return _style(fig, 300, legend=False)
    brands = [b for b in brand_order if b in set(scores["brand"])] + [b for b in sorted(set(scores["brand"])) if b not in brand_order]
    grid = scores.pivot(index="value", columns="brand", values="score").reindex(index=list(value_order), columns=brands)
    fig.add_trace(go.Heatmap(
        z=grid.values,
        x=list(grid.columns),
        y=[_short(v, 34) for v in grid.index],
        zmin=-10, zmax=10,
        colorscale=[[0, theme.NEGATIVE], [0.5, theme.pal().heat_mid], [1, theme.EMERALD]],
        texttemplate="%{z:+.1f}",
        xgap=3, ygap=3,
        hoverongaps=False,
        hovertemplate="%{y} / %{x}: %{z:+.1f}<extra></extra>",
        colorbar=dict(title="Net score", tickvals=[-10, 0, 10], len=0.8),
    ))
    fig.update_yaxes(autorange="reversed", showgrid=False)
    fig.update_xaxes(showgrid=False, side="top")
    return _style(fig, max(300, 40 * len(grid.index) + 110), legend=False, margin=dict(l=4, r=4, t=36, b=4))


def _compare(rows, brands, top):
    """Net-sentiment grid for the chosen brands (own brand first). Keeps attributes where the own brand and at
    least one other brand have enough opinions; a brand without enough opinions on an attribute stays blank."""
    scores = attribute_scores(rows)
    if scores.empty or not brands:
        return scores.iloc[0:0], scores.iloc[0:0]
    own = brands[0]
    pair = scores[scores["brand"].isin(brands)]
    grid = pair.pivot(index="value", columns="brand", values="score")
    if own not in grid.columns:
        return grid.iloc[0:0], pair
    others = [b for b in brands[1:] if b in grid.columns]
    if not others:
        return grid.iloc[0:0], pair
    grid = grid.dropna(subset=[own])
    grid = grid[grid[others].notna().any(axis=1)]
    volume = pair.groupby("value")["mentions"].sum().reindex(grid.index).sort_values(ascending=False)
    grid = grid.loc[list(volume.index[:top])]
    return grid, pair


def radar_chart(rows, brands, colours, top=10):
    """Own brand (first in brands) against one or more competitors across the most-discussed attributes.
    Returns (figure, number_of_attributes)."""
    fig = go.Figure()
    grid, _ = _compare(rows, brands, top)
    if len(grid) == 0:
        return _style(fig, 380), 0
    own = brands[0]
    names = [_short(v, 22) for v in grid.index]
    for brand in brands:
        if brand not in grid.columns:
            continue
        values = [None if pd.isna(v) else float(v) for v in grid[brand]]
        fig.add_trace(go.Scatterpolar(
            r=values + values[:1],
            theta=names + names[:1],
            name=brand,
            fill="toself",
            opacity=0.5,
            connectgaps=False,
            line=dict(color=colours.get(brand, theme.NEUTRAL), width=3 if brand == own else 2),
            hovertemplate="%{theta}: %{r:+.1f}<extra>" + brand + "</extra>",
        ))
    fig.update_layout(polar=dict(
        radialaxis=dict(range=[-10, 10], tickvals=[-10, -5, 0, 5, 10], gridcolor=theme.pal().line, linecolor=theme.pal().line),
        angularaxis=dict(gridcolor=theme.pal().line),
        bgcolor="rgba(0,0,0,0)",
    ))
    return _style(fig, 380, margin=dict(l=40, r=40, t=20, b=20)), len(grid)


def scorecard_rows(rows, brands, top=10):
    """Rows for the scorecard: every chosen brand's score, the own brand's gap to the average of the others, and the
    own brand's trend (second half vs first half). Returns [{attribute, scores: {brand: float | None}, gap, trend}]."""
    grid, pair = _compare(rows, brands, top)
    out = []
    if len(grid) == 0:
        return out
    own = brands[0]
    others = [b for b in brands[1:] if b in grid.columns]
    for value in grid.index:
        scores = {b: (None if pd.isna(grid.loc[value, b]) else float(grid.loc[value, b])) for b in brands if b in grid.columns}
        rivals = [scores[b] for b in others if scores.get(b) is not None]
        gap = scores[own] - sum(rivals) / len(rivals) if rivals else None
        mine = pair[(pair["value"] == value) & (pair["brand"] == own)].iloc[0]
        trend = None
        if pd.notna(mine["score_h1"]) and pd.notna(mine["score_h2"]):
            change = mine["score_h2"] - mine["score_h1"]
            trend = "up" if change >= TREND_THRESHOLD else ("down" if change <= -TREND_THRESHOLD else "flat")
        out.append({"attribute": value, "scores": scores, "gap": gap, "trend": trend})
    return out


# ---------------------------------------------------------------- virality
def topic_timeline(rows, weekly_after_days=WEEKLY_AFTER_DAYS):
    """Mentions of one topic over time, with the first day and the peak marked.
    Returns (figure, {'first': date | None, 'peak': date | None, 'peak_mentions': int, 'grain': 'Daily' | 'Weekly'})."""
    fig = go.Figure()
    df = pd.DataFrame(rows)
    info = {"first": None, "peak": None, "peak_mentions": 0, "grain": "Daily"}
    if df.empty:
        return _style(fig, 260, legend=False), info
    df["bucket"] = pd.to_datetime(df["bucket"])
    series = df.groupby("bucket")["mentions"].sum().astype(float)
    days = pd.date_range(series.index.min(), series.index.max(), freq="D")
    series = series.reindex(days, fill_value=0.0)
    info["first"] = series[series > 0].index.min().date()
    peak_day = series.idxmax()
    info["peak"], info["peak_mentions"] = peak_day.date(), int(series.max())
    if len(days) > weekly_after_days:
        series = series.resample("W").sum()
        info["grain"] = "Weekly"
    fig.add_trace(go.Bar(
        x=series.index, y=series.values, name="Mentions", marker_color=theme.VIOLET,
        hovertemplate=("Week ending " if info["grain"] == "Weekly" else "") + "%{x|%d %b %Y}: %{y:,.0f}<extra></extra>",
    ))
    fig.add_trace(go.Scatter(
        x=[pd.Timestamp(info["first"])], y=[float(series.max()) * 0.06], mode="markers+text", name="First seen",
        text=["First seen"], textposition="top center", marker=dict(size=11, color=theme.EMERALD),
        hovertemplate="First seen %{x|%d %b %Y}<extra></extra>",
    ))
    fig.update_xaxes(showgrid=False, tickformat="%d %b", linecolor=theme.pal().line)
    fig.update_yaxes(gridcolor=theme.pal().line, zeroline=False, tickformat=",")
    return _style(fig, 260, legend=False), info
