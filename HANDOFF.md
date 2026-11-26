# Handoff

State of the Euronext fork as of 2026-11-16. Read this before continuing the work; [`README.md`](README.md) explains usage and [`AGENTS.md`](AGENTS.md) the contribution rules.

## Goal

Analyse a personal Euronext watchlist every trading day at 08:30 Europe/Paris, before the 09:00 open, and push an English report with short, medium and long-term trends, support and resistance levels, and a clear Buy / Hold / Reduce view.

Owner preferences: work directly on `main` (personal fork, no pull requests), reports in English, the owner writes in French or English.

## What has been done

| Commit | Content |
| --- | --- |
| `7352f75` | Market `fr` for `.PA` symbols: detection, yfinance-only routing, `XPAR` calendar, European prompt context, `MARKET_REVIEW_REGION=fr` (CAC 40, SBF 120, Euro Stoxx 50). Daily schedule at 08:30 Paris with two UTC crons and a `schedule-gate` job. |
| `df782ff` | Daily workflow renamed "Daily Stock Analysis", steps and logs in English, reports printed on the run Summary page. |
| `7dc2aaf` | English number formats in reports (K/M/B, ISO currency, EUR default for `fr`). |
| this change | Reliable schedule (external trigger plus deduplicated backup cron), `.AS` suffix, curated French/English news queries for 17 stocks, multi-horizon trend and support/resistance block, English README / AGENTS, this handoff. |

### Design notes

- **Market detection**: `src/services/market_symbol_utils.py` holds one `SuffixMarketSpec("fr", ("PA", "AS"), ...)`. Everything else (`detect_market`, `get_market_for_stock`, data routing, calendar) derives from it. Amsterdam shares the Paris calendar on purpose: same hours, holidays and currency.
- **Names and search**: `src/data/euronext_stocks.py` is the single source for the short display name and the keywords. `DataFetcherManager.get_stock_name` reads it before asking Yahoo, and `SearchService` uses `build_euronext_search_dimensions` / `build_euronext_news_query` instead of the Chinese A-share templates. Symbols without a profile get generic French templates. "Orange" and "Euronext" are treated as ambiguous names in relevance scoring.
- **Multi-horizon**: `src/multi_horizon.py` is pure computation on a daily DataFrame. `StockAnalysisPipeline._compute_multi_horizon` fetches about 400 bars for non-A-share markets (best effort, failure only drops the block), stores the result on `TrendAnalysisResult.multi_horizon`, passes it to the prompt (`build_multi_horizon_prompt`) and to the report through the runtime-only field `AnalysisResult.multi_horizon` (`format_multi_horizon_markdown` in `generate_dashboard_report`). No schema, database or API change.
- **Horizon wording**: the LLM JSON schema was left untouched. The prompt asks the model to put the short-term view in `short_term_outlook` and the medium plus long-term view in `medium_term_outlook`; the report shows both under the computed table.
- **Schedule**: `.github/workflows/00-daily-analysis.yml`. External `workflow_dispatch` at 08:30 is the primary trigger. GitHub crons `47 6` (summer) and `47 7` (winter) UTC are a backup; `schedule-gate` lets through only the cron matching today's Paris offset, and skips it when a dispatched run of the same Paris day succeeded or is still running. If the API check fails, the backup runs.

### Summary cards (2026-11-26)

`src/stock_card.py` turns each `AnalysisResult` into a fixed 1080x1470 dark-theme HTML card and screenshots it (Python Playwright with its Chromium, `CHROME_PATH`, or the runner's Google Chrome; fallback `chrome --headless --screenshot`). `StockAnalysisPipeline._publish_stock_cards` saves the PNGs to `reports/cards/<date>/<code>.png` (uploaded with the run artifact) and sends them with `sendPhoto` when Telegram is configured. Controlled by `STOCK_CARD_IMAGES` (default false in code, `true` in the workflow, which installs `playwright` in a separate step). A rendering failure only skips the cards. Labels are English; the owner reviewed and approved a sample, then asked for the dark theme. Cards are published before the text report; with `STOCK_CARDS_ONLY` (workflow default `true`, asked for by the owner on 2026-11-26) the notifier drops Telegram from the `report` route for the rest of the run once every card was delivered, so Telegram gets images only; any failed card keeps the text report as fallback.

## Owner actions still open

1. **Set `STOCK_LIST`** (repository variable) to:
   `DCAM.PA,ASML.AS,BNP.PA,AIR.PA,EDEN.PA,ENGI.PA,ENX.PA,MC.PA,ORA.PA,OVH.PA,SAF.PA,SAN.PA,SU.PA,SOI.PA,STMPA.PA,HO.PA,TTE.PA`
2. **Create the external 08:30 trigger** on cron-job.org (steps in the README). Until then the report arrives when GitHub's backup cron fires, which was 9 hours late on 2026-11-16.
3. **Telegram**: the last run returned HTTP 404 from Telegram, which means `TELEGRAM_BOT_TOKEN` is wrong. Re-enter the token from BotFather, check it with `https://api.telegram.org/bot<token>/getMe`, and keep `TELEGRAM_CHAT_ID` set. Not confirmed fixed.
4. **News search key**: none is configured, so reports have no news. Add `TAVILY_API_KEYS` or `BRAVE_API_KEYS`. The watchlist needs about 1,900 searches a month.
5. **Timeout**: set the variable `ANALYSIS_TIMEOUT_MINUTES=45`; 17 stocks may not fit in the default 30 minutes.

## Not verified

- Verified on a real run (Actions run 43923578874, 2026-11-16): the 400-bar Yahoo history fetch works (419 bars) and the "Multi-Horizon Trend & Key Levels" block renders with the model's per-horizon view for `.PA` stocks. Yahoo Finance is blocked from the development sandbox, so such checks need a workflow run.
- `DCAM.PA` and `STMPA.PA` are assumed to be the right Yahoo symbols for the Amundi PEA MSCI World ETF and STMicroelectronics Paris. If a symbol returns no data, look it up on finance.yahoo.com and fix `STOCK_LIST` and `src/data/euronext_stocks.py`.
- The deduplication in `schedule-gate` has not run in production yet.
- French search queries have not been run against a real provider.

## Known limits and ideas

- The long history fetch adds one Yahoo request per stock and run.
- Support and resistance levels come from daily closes, highs and lows only; no volume profile.
- The multi-horizon block is rendered in the dashboard report only, not in the legacy daily report or the web history view (the field is not persisted).
- The web UI autocomplete, portfolio and market-light features have no `fr` support.
- Possible next steps: a persisted `long_term_outlook` field, a weekly summary, per-stock alerts when price crosses a computed level, upstream sync (the fork diverges in workflow text and docs, expect conflicts there).

## Testing

```bash
python -m pytest -q tests/test_euronext_paris_market.py tests/test_multi_horizon.py
python -m pytest -m "not network" -q --timeout=120 tests   # about 11 minutes
flake8 . --count --select=E9,F63,F7,F82
python scripts/check_ai_assets.py
```

Ten tests fail in a sandbox without the optional China data packages and are unrelated to the fork: `test_akshare_realtime_logging` (hot stocks), `test_etf_rotation` (real manager), three in `test_fundamental_adapter_contracts`, `test_runtime_scheduler_service` (worker exit), four in `test_screening_api` (hotspot).

## Rollback

Each feature is one commit on `main`; `git revert <sha>` restores the previous behaviour. The multi-horizon block and the Euronext search queries have no configuration or stored data to clean up.
