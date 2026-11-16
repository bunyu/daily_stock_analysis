# -*- coding: utf-8 -*-
"""Euronext Paris (``.PA``) market detection, routing and calendar contracts."""

from datetime import date, datetime
from unittest.mock import MagicMock
from zoneinfo import ZoneInfo

import pytest

from data_provider.base import _market_tag, normalize_stock_code
from data_provider.yfinance_fetcher import YfinanceFetcher
from src.core import trading_calendar
from src.core.market_profile import get_profile
from src.core.market_strategy import get_market_strategy_blueprint
from src.core.trading_calendar import (
    MarketPhase,
    build_market_phase_context,
    compute_effective_region,
    get_market_for_stock,
)
from src.market_context import detect_market, get_market_guidelines, get_market_role
from src.services.market_symbol_utils import get_suffix_market
from src.services.stock_list_parser import parse_stock_list
from src.utils.market_review_region import normalize_market_review_region_lenient


@pytest.mark.parametrize("code", ["MC.PA", "mc.pa", "TTE.PA", "AI.PA", "STLAP.PA", "4GLD.PA"])
def test_paris_codes_detected_as_fr_everywhere(code):
    assert get_suffix_market(code) == "fr"
    assert detect_market(code) == "fr"
    assert get_market_for_stock(code) == "fr"
    assert _market_tag(normalize_stock_code(code)) == "fr"


@pytest.mark.parametrize(
    "code, expected",
    [("BRK.B", "us"), ("AAPL", "us"), ("7203.T", "jp"), ("2330.TW", "tw"), ("600519", "cn")],
)
def test_other_markets_unchanged(code, expected):
    assert detect_market(code) == expected
    assert get_market_for_stock(code) == expected


@pytest.mark.parametrize("code", ["123.PA", "TOOLONG.PA", ".PA"])
def test_invalid_paris_bases_rejected(code):
    assert get_suffix_market(code) is None


def test_stock_list_keeps_paris_suffix():
    targets = parse_stock_list("MC.PA,tte.pa")
    assert [(t.canonical_id, t.exchange) for t in targets] == [("MC.PA", "PA"), ("TTE.PA", "PA")]


def test_prompt_uses_euronext_context():
    assert get_market_role("MC.PA", "en") == "Euronext Paris stock"
    guidelines = get_market_guidelines("MC.PA", "en")
    assert "EUR" in guidelines and "ECB" in guidelines


def test_yfinance_passes_paris_symbol_through():
    fetcher = YfinanceFetcher.__new__(YfinanceFetcher)
    assert fetcher._convert_stock_code("MC.PA") == "MC.PA"


def test_daily_fetchers_filtered_to_yfinance_for_fr():
    from data_provider.base import DataFetcherManager

    fetchers = []
    for name in ("AkshareFetcher", "TushareFetcher", "YfinanceFetcher"):
        fetcher = MagicMock()
        fetcher.name = name
        fetchers.append(fetcher)
    manager = DataFetcherManager.__new__(DataFetcherManager)
    filtered = manager._filter_daily_fetchers_for_market(fetchers, "fr")
    assert [f.name for f in filtered] == ["YfinanceFetcher"]


def test_yfinance_fr_main_indices_symbols():
    fetcher = YfinanceFetcher.__new__(YfinanceFetcher)
    seen = []

    def _fake(yf, yf_code, name, code):
        seen.append(yf_code)
        return {"code": code, "name": name}

    fetcher._fetch_yf_ticker_data = _fake
    result = fetcher._get_fr_main_indices(None)
    assert seen == ["^FCHI", "^SBF120", "^STOXX50E"]
    assert len(result) == 3


def test_market_review_region_accepts_fr():
    assert normalize_market_review_region_lenient("fr") == "fr"
    assert normalize_market_review_region_lenient("cn,fr") == "cn,fr"
    assert "fr" in normalize_market_review_region_lenient("both").split(",")
    assert compute_effective_region("fr", {"fr"}) == "fr"
    assert compute_effective_region("fr", {"us"}) == ""
    assert get_profile("fr").mood_index_code == "FCHI"
    assert get_market_strategy_blueprint("fr").region == "fr"


@pytest.mark.skipif(not trading_calendar._XCALS_AVAILABLE, reason="exchange-calendars not installed")
def test_xpar_calendar_and_premarket_phase():
    assert trading_calendar.is_market_open("fr", date(2026, 12, 25)) is False
    assert trading_calendar.is_market_open("fr", date(2026, 11, 13)) is True
    ctx = build_market_phase_context(
        market="fr",
        current_time=datetime(2026, 11, 13, 8, 30, tzinfo=ZoneInfo("Europe/Paris")),
    )
    assert ctx.phase == MarketPhase.PREMARKET
    assert ctx.effective_daily_bar_date == date(2026, 11, 12)


def test_amsterdam_suffix_rides_on_euronext_market():
    assert get_suffix_market("ASML.AS") == "fr"
    assert detect_market("ASML.AS") == "fr"
    assert get_market_for_stock("ASML.AS") == "fr"
    assert detect_market("BRK.A") == "us"


def test_curated_euronext_names_and_search_queries():
    from src.data.euronext_stocks import (
        EURONEXT_STOCK_PROFILES,
        build_euronext_news_query,
        build_euronext_search_dimensions,
        get_euronext_stock_name,
    )

    assert all(get_suffix_market(code) == "fr" for code in EURONEXT_STOCK_PROFILES)
    assert get_euronext_stock_name("mc.pa") == "LVMH"
    assert get_euronext_stock_name("AAPL") is None
    assert build_euronext_news_query("AAPL", "Apple") is None
    assert build_euronext_search_dimensions("600519", "贵州茅台") is None

    dims = build_euronext_search_dimensions("TTE.PA", "TotalEnergies")
    assert [d["name"] for d in dims] == [
        "latest_news", "market_analysis", "risk_check", "earnings", "industry",
    ]
    assert "objectif de cours" in dims[1]["query"]
    assert "Brent" in dims[4]["query"]
    # English templates for Amsterdam-listed ASML, ETF templates for the MSCI World tracker
    assert "price target" in build_euronext_search_dimensions("ASML.AS", "ASML")[1]["query"]
    assert "ETF" in build_euronext_news_query("DCAM.PA", "")
    # Unlisted Euronext symbols still get French queries built from the fetched name
    assert build_euronext_news_query("AI.PA", "Air Liquide") == "Air Liquide action bourse actualités"


def test_search_service_uses_euronext_queries_instead_of_chinese_templates():
    from src.search_service import SearchResponse, SearchService

    service = SearchService.__new__(SearchService)
    provider = MagicMock()
    provider.is_available = True
    provider.name = "Fake"
    queries = []

    def _search(query, max_results=5, days=7, **kwargs):
        queries.append(query)
        return SearchResponse(query=query, results=[], provider="Fake", success=True)

    provider.search.side_effect = _search
    service._providers = [provider]
    service.news_max_age_days = 3
    service.news_strategy_profile = "short"
    service.news_window_days = 3
    service.news_profile_days = 3

    service.search_comprehensive_intel("BNP.PA", "BNP Paribas", max_searches=5)

    assert len(queries) == 5
    assert all("BNP Paribas" in q for q in queries)
    assert not any(SearchService._contains_chinese_text(q) for q in queries)
    assert SearchService._brave_search_locale("BNP.PA", prefer_chinese=False) == {
        "search_lang": "fr", "country": "FR",
    }
