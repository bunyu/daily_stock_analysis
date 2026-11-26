# -*- coding: utf-8 -*-
"""One-image stock summary card: data extraction, HTML and pipeline publishing."""

from unittest.mock import MagicMock, patch

from src.analyzer import AnalysisResult
from src.stock_card import (
    build_stock_card_data,
    build_stock_card_html,
    card_caption,
    render_card_png,
)


def _result(**overrides):
    result = AnalysisResult(
        code="MC.PA",
        name="LVMH",
        sentiment_score=48,
        trend_prediction="Sideways",
        operation_advice="Hold",
        decision_type="hold",
        confidence_level="Medium",
        report_language="en",
        action="hold",
    )
    result.current_price = 404.0
    result.change_pct = -0.06
    result.short_term_outlook = "Hold above 399.55."
    result.medium_term_outlook = "Sideways; long term down below MA200."
    result.multi_horizon = {
        "as_of": "2026-11-13",
        "close": 404.0,
        "trends": {
            "short": {"trend": "up", "slow_ma": 20, "slow_ma_value": 395.96, "price_vs_slow_pct": 1.9},
            "long": {"trend": "down", "slow_ma": 200, "slow_ma_value": 459.44, "price_vs_slow_pct": -12.2},
        },
        "returns_pct": {"3m": -9.9, "12m": -32.4},
        "range_position_pct": 10.0,
        "supports": [{"price": 399.55, "distance_pct": -1.0, "touches": 1, "tags": ["ma50", "swing"]}],
        "resistances": [{"price": 431.15, "distance_pct": 6.9, "touches": 3, "tags": ["swing"]}],
    }
    result.dashboard = {
        "core_conclusion": {
            "one_sentence": "Wait for support <399.55> before entering.",
            "position_advice": {"no_position": "Wait.", "has_position": "Hold with a stop."},
        },
        "intelligence": {
            "positive_catalysts": ["Catalyst 1: Dividend yield 3.2%."],
            "risk_alerts": ["Risk 1: Below MA200.", "Risk 2: Tariffs.", "r3", "r4", "r5"],
        },
        "battle_plan": {
            "sniper_points": {
                "ideal_buy": "Ideal buy point: €399.55 (near MA50 support)",
                "secondary_buy": "396.70",
                "stop_loss": "Stop-loss: 394.50 (break below MA20)",
                "take_profit": "N/A",
            }
        },
        "phase_decision": {"confidence_reason": "Quote fallback.", "data_limitations": ["Chip data missing"]},
    }
    for key, value in overrides.items():
        setattr(result, key, value)
    return result


def test_card_data_extracts_verdict_levels_and_lists():
    data = build_stock_card_data(_result())
    assert data["verdict"] == "HOLD"
    assert data["exchange"] == "Euronext Paris" and data["currency"] == "EUR"
    plan = {item["label"]: item for item in data["plan"]}
    assert plan["Buy zone"]["price"] == "399.55"
    assert plan["Buy zone"]["note"] == "near MA50 support"
    assert plan["Stop loss"]["price"] == "394.50"
    assert plan["Target"]["price"] == "-"
    assert data["positives"] == ["Dividend yield 3.2%."]
    assert len(data["risks"]) == 4 and data["risks"][0] == "Below MA200."
    assert [h["label"] for h in data["horizons"]] == ["Short term", "Long term"]
    assert data["confidence"] == "Medium" and data["confidence_score"] == 2
    assert data["limitations"][0] == "No news evidence in this run"
    assert card_caption(data) == "LVMH (MC.PA) 404.00 EUR: HOLD"


def test_card_handles_missing_dashboard_and_history():
    data = build_stock_card_data(
        _result(dashboard=None, multi_horizon=None, action="buy", decision_type="buy", code="AAPL")
    )
    assert data["verdict"] == "BUY"
    assert data["horizons"] == [] and data["supports"] == []
    html = build_stock_card_html(data)
    assert "Not enough price history" in html
    assert "No positive catalyst reported" in html


def test_card_html_escapes_model_text():
    html = build_stock_card_html(build_stock_card_data(_result()))
    assert "&lt;399.55&gt;" in html and "<399.55>" not in html
    assert "Key levels" in html and "Analysis reliability" in html


def test_render_returns_none_without_any_browser():
    with patch("src.stock_card._render_with_playwright", return_value=None), patch(
        "src.stock_card._resolve_chrome", return_value=None
    ):
        assert render_card_png("<html></html>") is None


def test_pipeline_publishes_cards_to_disk_and_telegram(tmp_path):
    from src.core.pipeline import StockAnalysisPipeline
    from src.notification import NotificationChannel

    pipeline = StockAnalysisPipeline.__new__(StockAnalysisPipeline)
    pipeline.config = MagicMock(stock_cards_only=False)
    pipeline.notifier = MagicMock()
    pipeline.notifier.is_available.return_value = True
    pipeline.notifier.get_available_channels.return_value = [NotificationChannel.TELEGRAM]
    pipeline.notifier._send_telegram_photo.return_value = True

    with patch("src.stock_card.render_card_png", return_value=b"PNG"), patch(
        "src.core.pipeline.Path.resolve", return_value=tmp_path / "src" / "core" / "pipeline.py"
    ):
        pipeline._publish_stock_cards([_result()], send=True)

    saved = list(tmp_path.glob("reports/cards/*/MC.PA.png"))
    assert len(saved) == 1 and saved[0].read_bytes() == b"PNG"
    args, kwargs = pipeline.notifier._send_telegram_photo.call_args
    assert args == (b"PNG",)
    assert kwargs["caption"].endswith("HOLD") and kwargs["filename"] == "MC.PA.png"


def test_pipeline_cards_not_sent_when_notifications_disabled(tmp_path):
    from src.core.pipeline import StockAnalysisPipeline

    pipeline = StockAnalysisPipeline.__new__(StockAnalysisPipeline)
    pipeline.config = MagicMock(stock_cards_only=False)
    pipeline.notifier = MagicMock()
    with patch("src.stock_card.render_card_png", return_value=b"PNG"), patch(
        "src.core.pipeline.Path.resolve", return_value=tmp_path / "src" / "core" / "pipeline.py"
    ):
        pipeline._publish_stock_cards([_result()], send=False)
    pipeline.notifier._send_telegram_photo.assert_not_called()
    assert list(tmp_path.glob("reports/cards/*/MC.PA.png"))


def _card_pipeline(cards_only, photo_ok=True):
    from src.core.pipeline import StockAnalysisPipeline
    from src.notification import NotificationChannel

    pipeline = StockAnalysisPipeline.__new__(StockAnalysisPipeline)
    pipeline.config = MagicMock(stock_cards_only=cards_only)
    pipeline.notifier = MagicMock()
    pipeline.notifier.is_available.return_value = True
    pipeline.notifier.get_available_channels.return_value = [NotificationChannel.TELEGRAM]
    pipeline.notifier._send_telegram_photo.return_value = photo_ok
    return pipeline


def test_cards_only_suppresses_telegram_text_after_all_cards_sent(tmp_path):
    from src.notification import NotificationChannel

    pipeline = _card_pipeline(cards_only=True)
    with patch("src.stock_card.render_card_png", return_value=b"PNG"), patch(
        "src.core.pipeline.Path.resolve", return_value=tmp_path / "src" / "core" / "pipeline.py"
    ):
        pipeline._publish_stock_cards([_result(), _result(code="TTE.PA")], send=True)
    pipeline.notifier.suppress_report_channel.assert_called_once_with(NotificationChannel.TELEGRAM)


def test_cards_only_keeps_text_when_a_card_fails(tmp_path):
    for cards_only, photo_ok in ((True, False), (False, True)):
        pipeline = _card_pipeline(cards_only=cards_only, photo_ok=photo_ok)
        with patch("src.stock_card.render_card_png", return_value=b"PNG"), patch(
            "src.core.pipeline.Path.resolve", return_value=tmp_path / "src" / "core" / "pipeline.py"
        ):
            pipeline._publish_stock_cards([_result()], send=True)
        pipeline.notifier.suppress_report_channel.assert_not_called()


def test_suppressed_channel_is_removed_from_report_route_only():
    from src.notification import NotificationChannel, NotificationService

    service = NotificationService.__new__(NotificationService)
    service._config = MagicMock(notification_report_channels=[], notification_alert_channels=[])
    service._available_channels = [NotificationChannel.TELEGRAM, NotificationChannel.EMAIL]
    service._suppressed_report_channels = set()
    service.suppress_report_channel(NotificationChannel.TELEGRAM)
    assert service.get_channels_for_route("report") == [NotificationChannel.EMAIL]
    assert NotificationChannel.TELEGRAM in service.get_channels_for_route("alert")
