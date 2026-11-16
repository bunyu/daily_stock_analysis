# -*- coding: utf-8 -*-
"""Multi-horizon trend and support/resistance levels from daily bars.

Deterministic companion to ``StockTrendAnalyzer`` (which focuses on the
MA5/MA10/MA20 short-term structure). From roughly one to two years of daily
bars it derives:

- short / medium / long-term trend (MA10-MA20, MA20-MA50, MA50-MA200);
- 1M / 3M / 6M / 12M performance and the position inside the 52-week range;
- the nearest support and resistance levels, built from clustered swing
  highs/lows plus MA50 / MA200 and the 52-week extremes.

The result is a plain dict so it can be injected into the LLM prompt and
rendered in the report without any schema change.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

import pandas as pd

MIN_BARS = 60
TRADING_DAYS_1Y = 252
_PIVOT_WINDOW = 5
_CLUSTER_TOLERANCE = 0.015   # swing points within 1.5% form one level
_MERGE_TOLERANCE = 0.01      # final levels within 1% are merged
_MIN_DISTANCE = 0.003        # ignore levels closer than 0.3% to the price
_MAX_LEVELS = 3

TREND_UP = "up"
TREND_DOWN = "down"
TREND_SIDEWAYS = "sideways"
TREND_UNKNOWN = "n/a"

_HORIZONS = (
    # key, fast MA, slow MA, slope lookback (bars)
    ("short", 10, 20, 5),
    ("medium", 20, 50, 10),
    ("long", 50, 200, 20),
)

_TEXT = {
    "en": {
        "heading": "Multi-Horizon Trend & Key Levels",
        "horizon": "Horizon",
        "trend": "Trend",
        "basis": "Basis",
        "stance": "Technical stance",
        "short": "Short term (days to 2 weeks)",
        "medium": "Medium term (1-3 months)",
        "long": "Long term (6-12 months)",
        TREND_UP: "🟢 Uptrend",
        TREND_DOWN: "🔴 Downtrend",
        TREND_SIDEWAYS: "🟡 Sideways",
        TREND_UNKNOWN: "⚪ Not enough history",
        "stance_" + TREND_UP: "Hold / buy pullbacks toward support",
        "stance_" + TREND_DOWN: "Avoid new buys / reduce on rebounds toward resistance",
        "stance_" + TREND_SIDEWAYS: "Hold / wait for a breakout",
        "stance_" + TREND_UNKNOWN: "-",
        "performance": "Performance",
        "range": "52-week range",
        "range_position": "position in range",
        "supports": "Supports",
        "resistances": "Resistances",
        "none_support": "none below the price in the last year (price at lows)",
        "none_resistance": "none above the price in the last year (price at highs)",
        "above": "above",
        "below": "below",
        "rising": "rising",
        "falling": "falling",
        "flat": "flat",
        "price": "Price",
        "swing": "swing level",
        "touches": "touches",
        "high_52w": "52-week high",
        "low_52w": "52-week low",
        "ai_short": "AI view, short term",
        "ai_medium_long": "AI view, medium / long term",
        "as_of": "Computed from {bars} daily bars up to {as_of}. Technical reading only, not investment advice.",
    },
    "zh": {
        "heading": "多周期趋势与关键价位",
        "horizon": "周期",
        "trend": "趋势",
        "basis": "依据",
        "stance": "技术面立场",
        "short": "短期（数日至2周）",
        "medium": "中期（1-3个月）",
        "long": "长期（6-12个月）",
        TREND_UP: "🟢 上行",
        TREND_DOWN: "🔴 下行",
        TREND_SIDEWAYS: "🟡 震荡",
        TREND_UNKNOWN: "⚪ 历史数据不足",
        "stance_" + TREND_UP: "持有 / 回踩支撑可买入",
        "stance_" + TREND_DOWN: "不新开仓 / 反弹至压力位减仓",
        "stance_" + TREND_SIDEWAYS: "持有 / 等待突破",
        "stance_" + TREND_UNKNOWN: "-",
        "performance": "区间表现",
        "range": "52周区间",
        "range_position": "区间位置",
        "supports": "支撑位",
        "resistances": "压力位",
        "none_support": "近一年内现价下方无支撑（处于低位）",
        "none_resistance": "近一年内现价上方无压力（处于高位）",
        "above": "高于",
        "below": "低于",
        "rising": "上行",
        "falling": "下行",
        "flat": "走平",
        "price": "现价",
        "swing": "波段位",
        "touches": "次触及",
        "high_52w": "52周高点",
        "low_52w": "52周低点",
        "ai_short": "AI 观点（短期）",
        "ai_medium_long": "AI 观点（中长期）",
        "as_of": "基于截至 {as_of} 的 {bars} 根日线计算，仅为技术面参考，不构成投资建议。",
    },
}


def _text(language: Optional[str]) -> Dict[str, str]:
    return _TEXT["zh"] if str(language or "").lower().startswith("zh") else _TEXT["en"]


def _prepare(df: Optional[pd.DataFrame]) -> Optional[pd.DataFrame]:
    if df is None or len(df) == 0:
        return None
    required = {"date", "high", "low", "close"}
    if not required.issubset(df.columns):
        return None
    data = df[["date", "high", "low", "close"]].copy()
    data["date"] = pd.to_datetime(data["date"], errors="coerce")
    for column in ("high", "low", "close"):
        data[column] = pd.to_numeric(data[column], errors="coerce")
    data = data.dropna().drop_duplicates(subset="date", keep="last").sort_values("date")
    data = data[data["close"] > 0].reset_index(drop=True)
    return data if len(data) >= MIN_BARS else None


def _slope_state(series: pd.Series, lookback: int) -> Optional[str]:
    if len(series) <= lookback:
        return None
    now, before = series.iloc[-1], series.iloc[-1 - lookback]
    if pd.isna(now) or pd.isna(before) or before <= 0:
        return None
    change = (now - before) / before
    if change > 0.002:
        return "rising"
    if change < -0.002:
        return "falling"
    return "flat"


def _classify(close: float, fast: Optional[float], slow: Optional[float], slope: Optional[str]) -> str:
    if fast is None or slow is None or slope is None:
        return TREND_UNKNOWN
    if close > slow and fast > slow and slope != "falling":
        return TREND_UP
    if close < slow and fast < slow and slope != "rising":
        return TREND_DOWN
    return TREND_SIDEWAYS


def _swing_points(data: pd.DataFrame) -> List[float]:
    """Confirmed swing highs and lows of the last year (both can act as levels)."""
    window = data.tail(TRADING_DAYS_1Y).reset_index(drop=True)
    highs, lows = window["high"], window["low"]
    span = 2 * _PIVOT_WINDOW + 1
    is_high = highs == highs.rolling(span, center=True).max()
    is_low = lows == lows.rolling(span, center=True).min()
    return [float(v) for v in highs[is_high]] + [float(v) for v in lows[is_low]]


def _cluster(points: List[float]) -> List[Dict[str, Any]]:
    clusters: List[List[float]] = []
    for price in sorted(points):
        if clusters and abs(price - sum(clusters[-1]) / len(clusters[-1])) <= (
            _CLUSTER_TOLERANCE * price
        ):
            clusters[-1].append(price)
        else:
            clusters.append([price])
    return [
        {"price": sum(group) / len(group), "touches": len(group), "tags": ["swing"]}
        for group in clusters
    ]


def _merge_levels(levels: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    merged: List[Dict[str, Any]] = []
    for level in sorted(levels, key=lambda item: item["price"]):
        last = merged[-1] if merged else None
        if last and abs(level["price"] - last["price"]) <= _MERGE_TOLERANCE * level["price"]:
            # Keep the swing price when one side is a swing cluster; tags accumulate.
            if "swing" in level["tags"] and "swing" not in last["tags"]:
                last["price"] = level["price"]
            last["touches"] = last.get("touches", 0) + level.get("touches", 0)
            last["tags"] = last["tags"] + [t for t in level["tags"] if t not in last["tags"]]
        else:
            merged.append({**level, "tags": list(level["tags"])})
    return merged


def _round(value: Optional[float], digits: int = 2) -> Optional[float]:
    return None if value is None or pd.isna(value) else round(float(value), digits)


def compute_multi_horizon(df: Optional[pd.DataFrame]) -> Optional[Dict[str, Any]]:
    """Return the multi-horizon view, or ``None`` when history is too short."""
    data = _prepare(df)
    if data is None:
        return None

    close_series = data["close"]
    close = float(close_series.iloc[-1])
    bars = len(data)

    ma_series = {n: close_series.rolling(n).mean() for n in (10, 20, 50, 100, 200)}
    ma = {
        f"ma{n}": (_round(series.iloc[-1]) if bars >= n else None)
        for n, series in ma_series.items()
    }

    trends: Dict[str, Dict[str, Any]] = {}
    for key, fast_n, slow_n, lookback in _HORIZONS:
        fast = ma[f"ma{fast_n}"]
        slow = ma[f"ma{slow_n}"]
        slope = _slope_state(ma_series[slow_n].dropna(), lookback) if slow is not None else None
        trends[key] = {
            "trend": _classify(close, fast, slow, slope),
            "fast_ma": fast_n,
            "slow_ma": slow_n,
            "slow_ma_value": slow,
            "price_vs_slow_pct": _round((close - slow) / slow * 100) if slow else None,
            "slow_ma_slope": slope,
        }

    returns = {}
    for label, offset in (("1m", 21), ("3m", 63), ("6m", 126), ("12m", 252)):
        if bars > offset:
            base = float(close_series.iloc[-1 - offset])
            returns[label] = _round((close - base) / base * 100)
        else:
            returns[label] = None

    year = data.tail(TRADING_DAYS_1Y)
    high_52w = float(year["high"].max())
    low_52w = float(year["low"].min())
    span = high_52w - low_52w
    range_position = _round((close - low_52w) / span * 100, 1) if span > 0 else None

    candidates = _cluster(_swing_points(data))
    for tag in ("ma50", "ma200"):
        if ma[tag]:
            candidates.append({"price": ma[tag], "touches": 0, "tags": [tag]})
    candidates.append({"price": high_52w, "touches": 0, "tags": ["high_52w"]})
    candidates.append({"price": low_52w, "touches": 0, "tags": ["low_52w"]})
    levels = _merge_levels(candidates)

    def _export(level: Dict[str, Any]) -> Dict[str, Any]:
        return {
            "price": _round(level["price"]),
            "distance_pct": _round((level["price"] - close) / close * 100),
            "touches": level.get("touches", 0),
            "tags": level["tags"],
        }

    supports = [
        _export(level)
        for level in sorted(levels, key=lambda item: -item["price"])
        if level["price"] < close * (1 - _MIN_DISTANCE)
    ][:_MAX_LEVELS]
    resistances = [
        _export(level)
        for level in levels
        if level["price"] > close * (1 + _MIN_DISTANCE)
    ][:_MAX_LEVELS]

    return {
        "as_of": data["date"].iloc[-1].strftime("%Y-%m-%d"),
        "bars": bars,
        "close": _round(close),
        "ma": ma,
        "trends": trends,
        "returns_pct": returns,
        "high_52w": _round(high_52w),
        "low_52w": _round(low_52w),
        "range_position_pct": range_position,
        "supports": supports,
        "resistances": resistances,
    }


def _level_text(level: Dict[str, Any], text: Dict[str, str]) -> str:
    parts = []
    for tag in level.get("tags") or []:
        if tag == "swing":
            touches = level.get("touches") or 0
            parts.append(f"{text['swing']}, {touches} {text['touches']}" if touches > 1 else text["swing"])
        elif tag in ("ma50", "ma200"):
            parts.append(tag.upper())
        else:
            parts.append(text.get(tag, tag))
    basis = "; ".join(parts)
    return f"**{level['price']:.2f}** ({level['distance_pct']:+.1f}%, {basis})"


def _basis_text(info: Dict[str, Any], text: Dict[str, str]) -> str:
    if info.get("slow_ma_value") is None:
        return "-"
    delta = info.get("price_vs_slow_pct") or 0.0
    side = text["above"] if delta >= 0 else text["below"]
    slope = text.get(info.get("slow_ma_slope") or "flat", "")
    slow = f"MA{info['slow_ma']}"
    return (
        f"{text['price']} {abs(delta):.1f}% {side} {slow} ({info['slow_ma_value']:.2f}); "
        f"{slow} {slope}"
    )


def format_multi_horizon_markdown(
    multi_horizon: Optional[Dict[str, Any]],
    language: Optional[str] = "en",
    *,
    short_term_outlook: Optional[str] = None,
    medium_term_outlook: Optional[str] = None,
) -> List[str]:
    """Render the multi-horizon view as markdown lines (empty list when missing).

    The optional outlooks are the model's own per-horizon conclusions; they are
    appended under the computed table so the report shows both side by side.
    """
    if not isinstance(multi_horizon, dict) or not multi_horizon.get("trends"):
        return []
    text = _text(language)
    lines = [
        f"### 🧭 {text['heading']}",
        "",
        f"| {text['horizon']} | {text['trend']} | {text['basis']} | {text['stance']} |",
        "|------|------|------|------|",
    ]
    for key, _fast, _slow, _lookback in _HORIZONS:
        info = multi_horizon["trends"].get(key) or {}
        trend = info.get("trend", TREND_UNKNOWN)
        lines.append(
            f"| {text[key]} | {text.get(trend, trend)} | {_basis_text(info, text)} "
            f"| {text['stance_' + trend]} |"
        )
    lines.append("")

    returns = multi_horizon.get("returns_pct") or {}
    perf = " | ".join(
        f"{label.upper()} {value:+.1f}%"
        for label, value in returns.items()
        if value is not None
    )
    if perf:
        lines.append(f"**{text['performance']}**: {perf}")
        lines.append("")
    if multi_horizon.get("high_52w") and multi_horizon.get("low_52w"):
        position = multi_horizon.get("range_position_pct")
        position_text = f" ({text['range_position']}: {position:.0f}%)" if position is not None else ""
        lines.append(
            f"**{text['range']}**: {multi_horizon['low_52w']:.2f} - "
            f"{multi_horizon['high_52w']:.2f}{position_text}"
        )
        lines.append("")

    supports = multi_horizon.get("supports") or []
    resistances = multi_horizon.get("resistances") or []
    lines.append(
        f"**🛡️ {text['supports']}**: "
        + (" · ".join(_level_text(level, text) for level in supports) or text["none_support"])
    )
    lines.append("")
    lines.append(
        f"**🚧 {text['resistances']}**: "
        + (" · ".join(_level_text(level, text) for level in resistances) or text["none_resistance"])
    )
    lines.append("")
    for label, outlook in (
        (text["ai_short"], short_term_outlook),
        (text["ai_medium_long"], medium_term_outlook),
    ):
        if outlook and str(outlook).strip():
            lines.append(f"**🤖 {label}**: {str(outlook).strip()}")
            lines.append("")
    lines.append(
        "_" + text["as_of"].format(bars=multi_horizon.get("bars"), as_of=multi_horizon.get("as_of")) + "_"
    )
    lines.append("")
    return lines


def build_multi_horizon_prompt(
    multi_horizon: Optional[Dict[str, Any]], language: Optional[str] = "en"
) -> str:
    """Prompt block: the computed view plus how the model must use it."""
    lines = format_multi_horizon_markdown(multi_horizon, language)
    if not lines:
        return ""
    if str(language or "").lower().startswith("zh"):
        instructions = [
            "**使用要求（多周期）**：",
            "- 以上趋势与价位由程序基于日线确定性计算，引用价位时必须使用这些数值，不得自行编造价位。",
            "- 买入区间、止损位、目标位应与上述支撑/压力位一致：止损设在最近支撑下方，目标位参考最近压力位。",
            "- `short_term_outlook` 写短期（数日至2周）判断；`medium_term_outlook` 先写中期（1-3个月），"
            "再用一句话写长期（6-12个月）判断。每个周期都要明确给出 买入 / 持有 / 减仓 之一，并注明关键价位。",
            "- 三个周期结论相互矛盾时（例如短期下行、长期上行），必须明确说明，并分别给出空仓者与持仓者的建议。",
        ]
    else:
        instructions = [
            "**How to use this (multi-horizon)**:",
            "- The trends and levels above are computed deterministically from daily bars. "
            "When you quote a level, use these numbers; do not invent price levels.",
            "- Buy zone, stop-loss and target must be consistent with these supports/resistances: "
            "stop below the nearest support, target near the nearest resistance.",
            "- Write the short-term view (days to 2 weeks) in `short_term_outlook`. In `medium_term_outlook` "
            "write the medium-term view (1-3 months) and then one sentence on the long-term view (6-12 months). "
            "For each horizon state explicitly Buy, Hold or Reduce, with the key level that would change it.",
            "- When horizons disagree (for example short-term down, long-term up), say so explicitly and give "
            "separate advice for investors with and without a position.",
        ]
    return "\n" + "\n".join(lines + instructions) + "\n"
