# -*- coding: utf-8 -*-
"""Multi-horizon trend and support/resistance computation contracts."""

import numpy as np
import pandas as pd

from src.multi_horizon import (
    TREND_DOWN,
    TREND_UNKNOWN,
    TREND_UP,
    build_multi_horizon_prompt,
    compute_multi_horizon,
    format_multi_horizon_markdown,
)


def _frame(closes):
    closes = np.asarray(closes, dtype=float)
    return pd.DataFrame(
        {
            "date": pd.bdate_range("2025-01-01", periods=len(closes)),
            "open": closes,
            "high": closes * 1.01,
            "low": closes * 0.99,
            "close": closes,
        }
    )


def test_steady_uptrend_is_up_on_every_horizon():
    result = compute_multi_horizon(_frame(np.linspace(50, 150, 400)))
    assert {h: result["trends"][h]["trend"] for h in ("short", "medium", "long")} == {
        "short": TREND_UP, "medium": TREND_UP, "long": TREND_UP,
    }
    assert result["returns_pct"]["12m"] > 0
    assert result["range_position_pct"] > 90
    assert result["ma"]["ma200"] < result["ma"]["ma50"] < result["close"]


def test_long_uptrend_with_recent_drop_shows_diverging_horizons():
    closes = np.concatenate([np.linspace(50, 150, 380), np.linspace(149, 138, 15)])
    result = compute_multi_horizon(_frame(closes))
    assert result["trends"]["short"]["trend"] == TREND_DOWN
    assert result["trends"]["long"]["trend"] == TREND_UP


def test_levels_are_on_the_right_side_of_price_and_sorted_by_distance():
    x = np.arange(400)
    closes = 100 + 10 * np.sin(x / 15.0) + 0.02 * x
    result = compute_multi_horizon(_frame(closes))
    close = result["close"]
    supports = [level["price"] for level in result["supports"]]
    resistances = [level["price"] for level in result["resistances"]]
    assert supports and resistances
    assert all(price < close for price in supports)
    assert all(price > close for price in resistances)
    assert supports == sorted(supports, reverse=True)
    assert resistances == sorted(resistances)
    assert len(supports) <= 3 and len(resistances) <= 3
    assert any("swing" in level["tags"] for level in result["supports"] + result["resistances"])


def test_short_history_degrades_gracefully():
    assert compute_multi_horizon(_frame(np.linspace(10, 12, 40))) is None
    assert compute_multi_horizon(None) is None
    assert compute_multi_horizon(pd.DataFrame({"close": [1.0]})) is None
    result = compute_multi_horizon(_frame(np.linspace(10, 12, 120)))
    assert result["trends"]["long"]["trend"] == TREND_UNKNOWN
    assert result["returns_pct"]["12m"] is None
    assert format_multi_horizon_markdown(result, "en")


def test_rendering_and_prompt_language():
    result = compute_multi_horizon(_frame(np.linspace(50, 150, 400)))
    english = "\n".join(
        format_multi_horizon_markdown(result, "en", short_term_outlook="Hold above 140.")
    )
    assert "Multi-Horizon Trend & Key Levels" in english
    assert "Long term (6-12 months)" in english
    assert "Hold above 140." in english
    assert "多周期趋势与关键价位" in "\n".join(format_multi_horizon_markdown(result, "zh"))
    prompt = build_multi_horizon_prompt(result, "en")
    assert "do not invent price levels" in prompt
    assert "medium_term_outlook" in prompt
    assert build_multi_horizon_prompt(None, "en") == ""
    assert format_multi_horizon_markdown({}, "en") == []
