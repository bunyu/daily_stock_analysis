# -*- coding: utf-8 -*-
"""One-image summary card per analysed stock.

Turns one ``AnalysisResult`` into a fixed-size infographic (PNG) that holds the
essentials on a single screen: the Buy / Hold / Sell verdict with the price
plan, positives and risks, the multi-horizon trend with its forecast,
support / resistance levels, and how reliable the analysis is.

Pipeline:
    ``build_stock_card_data(result)`` -> plain dict (pure, testable)
    ``build_stock_card_html(data)``   -> self-contained HTML (no network)
    ``render_card_png(html)``         -> PNG bytes through headless Chrome

Rendering is best effort: it uses Python Playwright when installed (bundled
Chromium, ``CHROME_PATH`` or the system Chrome), then the Chrome CLI. Without a
browser it returns ``None`` and the text report is unaffected.
"""

from __future__ import annotations

import html
import logging
import os
import re
import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import Any, Dict, List, Optional

from src.report_language import localize_confidence_level, normalize_report_language
from src.schemas.decision_action import display_action_fields_for_result

logger = logging.getLogger(__name__)

CARD_WIDTH = 1080
CARD_HEIGHT = 1470
_MAX_ITEMS = 4

# Browser binaries tried in order; CHROME_PATH (if set) wins.
_CHROME_CANDIDATES = (
    "google-chrome",
    "google-chrome-stable",
    "chromium",
    "chromium-browser",
    "chrome",
)

# action taxonomy -> (verdict bucket, colour)
_VERDICTS = {
    "buy": ("BUY", "#16a34a"),
    "add": ("BUY", "#16a34a"),
    "hold": ("HOLD", "#ca8a04"),
    "watch": ("WATCH", "#64748b"),
    "avoid": ("AVOID", "#ea580c"),
    "reduce": ("REDUCE", "#ea580c"),
    "sell": ("SELL", "#dc2626"),
    "alert": ("SELL", "#dc2626"),
}

_TREND_STYLE = {
    "up": ("Uptrend", "#4ade80", "▲"),
    "down": ("Downtrend", "#f87171", "▼"),
    "sideways": ("Sideways", "#facc15", "▶"),
    "n/a": ("Not enough data", "#64748b", "•"),
}

_CONFIDENCE_SCORE = {"high": 3, "medium": 2, "low": 1}

_EXCHANGES = {"PA": "Euronext Paris", "AS": "Euronext Amsterdam"}

_LEADING_LABEL_RE = re.compile(
    r"^\s*(?:risk|catalyst|positive|negative|point|factor)\s*\d*\s*[:：.)-]\s*",
    re.IGNORECASE,
)
_PRICE_RE = re.compile(r"(?<![\w.])(\d{1,6}(?:[.,]\d{1,4})?)")
_PREFIX_RE = re.compile(
    r"^\s*(?:ideal (?:buy|entry)(?: point)?|secondary (?:buy|entry)(?: point)?|"
    r"stop[- ]?loss|target(?: price)?|take[- ]?profit)\s*[:：]?\s*",
    re.IGNORECASE,
)


def _dict(value: Any) -> Dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _clean_item(text: Any, limit: int = 150) -> str:
    value = re.sub(r"\s+", " ", str(text or "")).strip()
    value = _LEADING_LABEL_RE.sub("", value)
    if len(value) > limit:
        value = value[: limit - 1].rstrip() + "…"
    return value


def _items(values: Any) -> List[str]:
    if isinstance(values, str):
        values = [values]
    if not isinstance(values, list):
        return []
    cleaned = [_clean_item(v) for v in values]
    return [v for v in cleaned if v][:_MAX_ITEMS]


def _split_level(raw: Any) -> Dict[str, str]:
    """Split a sniper value like 'Ideal buy point: €39.54 (near support)' into price and note."""
    text = re.sub(r"\s+", " ", str(raw or "")).strip()
    if not text or text.upper() in {"N/A", "NONE", "-"}:
        return {"price": "-", "note": ""}
    text = _PREFIX_RE.sub("", text)
    match = _PRICE_RE.search(text)
    if not match:
        return {"price": "-", "note": _clean_item(text, 70)}
    price = match.group(1).replace(",", ".")
    note = text[match.end():].strip(" ()-–:;,€$")
    note = re.sub(r"^[(\[]|[)\]]$", "", note).strip()
    return {"price": price, "note": _clean_item(note, 70)}


def _to_float(value: Any) -> Optional[float]:
    try:
        if value is None:
            return None
        return float(str(value).replace("%", "").replace(",", "").strip())
    except (TypeError, ValueError):
        return None


def _exchange_label(code: str) -> str:
    suffix = code.rsplit(".", 1)[-1].upper() if "." in code else ""
    return _EXCHANGES.get(suffix, "")


def _confidence_key(value: Any) -> str:
    english = str(localize_confidence_level(value, "en") or "").strip().lower()
    for key in _CONFIDENCE_SCORE:
        if key in english:
            return key
    return "medium"


def build_stock_card_data(result: Any) -> Dict[str, Any]:
    """Collect everything the card shows from an ``AnalysisResult``."""
    code = str(getattr(result, "code", "") or "")
    dashboard = _dict(getattr(result, "dashboard", None))
    core = _dict(dashboard.get("core_conclusion"))
    position = _dict(core.get("position_advice"))
    intel = _dict(dashboard.get("intelligence"))
    battle = _dict(dashboard.get("battle_plan"))
    sniper = _dict(battle.get("sniper_points"))
    phase = _dict(dashboard.get("phase_decision"))
    mh = _dict(getattr(result, "multi_horizon", None))
    snapshot = _dict(getattr(result, "market_snapshot", None))

    fields = display_action_fields_for_result(result, report_language="en")
    action = str(fields.get("action") or getattr(result, "decision_type", "") or "hold").lower()
    verdict, colour = _VERDICTS.get(action, _VERDICTS["hold"])

    price = _to_float(getattr(result, "current_price", None))
    if price is None:
        price = _to_float(snapshot.get("close")) or _to_float(mh.get("close"))
    change = _to_float(getattr(result, "change_pct", None))
    if change is None:
        change = _to_float(snapshot.get("pct_chg"))

    horizons = []
    trends = _dict(mh.get("trends"))
    for key, label in (("short", "Short term"), ("medium", "Medium term"), ("long", "Long term")):
        info = _dict(trends.get(key))
        if not info:
            continue
        trend_label, trend_colour, arrow = _TREND_STYLE.get(info.get("trend"), _TREND_STYLE["n/a"])
        slow = info.get("slow_ma_value")
        delta = info.get("price_vs_slow_pct")
        basis = (
            f"{'above' if (delta or 0) >= 0 else 'below'} MA{info.get('slow_ma')} {slow:.2f}"
            if slow is not None and delta is not None
            else ""
        )
        horizons.append({
            "label": label,
            "span": {"short": "days-2 weeks", "medium": "1-3 months", "long": "6-12 months"}[key],
            "trend": trend_label,
            "colour": trend_colour,
            "arrow": arrow,
            "basis": basis,
        })

    confidence_key = _confidence_key(getattr(result, "confidence_level", None))
    limitations = _items(phase.get("data_limitations"))
    if getattr(result, "news_evidence_present", False) is False:
        limitations = (["No news evidence in this run"] + limitations)[:_MAX_ITEMS]

    returns = _dict(mh.get("returns_pct"))
    return {
        "code": code,
        "name": str(getattr(result, "name", "") or code),
        "exchange": _exchange_label(code),
        "as_of": mh.get("as_of") or snapshot.get("date") or "",
        "currency": "EUR" if _exchange_label(code) else "",
        "price": price,
        "change_pct": change,
        "verdict": verdict,
        "verdict_colour": colour,
        "action_label": str(fields.get("action_label") or verdict.title()),
        "score": getattr(result, "sentiment_score", None),
        "one_sentence": _clean_item(core.get("one_sentence") or getattr(result, "analysis_summary", ""), 220),
        "no_position": _clean_item(position.get("no_position"), 160),
        "has_position": _clean_item(position.get("has_position"), 160),
        "plan": [
            {"label": "Buy zone", "colour": "#4ade80", **_split_level(sniper.get("ideal_buy"))},
            {"label": "2nd entry", "colour": "#38bdf8", **_split_level(sniper.get("secondary_buy"))},
            {"label": "Stop loss", "colour": "#f87171", **_split_level(sniper.get("stop_loss"))},
            {"label": "Target", "colour": "#c084fc", **_split_level(sniper.get("take_profit"))},
        ],
        "positives": _items(intel.get("positive_catalysts")),
        "risks": _items(intel.get("risk_alerts")),
        "horizons": horizons,
        "short_outlook": _clean_item(getattr(result, "short_term_outlook", ""), 230),
        "medium_outlook": _clean_item(getattr(result, "medium_term_outlook", ""), 260),
        "supports": [lv for lv in (mh.get("supports") or []) if isinstance(lv, dict)][:3],
        "resistances": [lv for lv in (mh.get("resistances") or []) if isinstance(lv, dict)][:3],
        "return_12m": returns.get("12m"),
        "return_3m": returns.get("3m"),
        "range_position": mh.get("range_position_pct"),
        "confidence": confidence_key.title(),
        "confidence_score": _CONFIDENCE_SCORE[confidence_key],
        "confidence_reason": _clean_item(phase.get("confidence_reason"), 200),
        "limitations": limitations,
        "model": str(getattr(result, "model_used", "") or ""),
        "language": normalize_report_language(getattr(result, "report_language", "en")),
    }


def _e(value: Any) -> str:
    return html.escape(str(value if value is not None else ""), quote=True)


def _fmt_pct(value: Any) -> str:
    number = _to_float(value)
    return "-" if number is None else f"{number:+.1f}%"


def _fmt_price(value: Any) -> str:
    number = _to_float(value)
    return "-" if number is None else f"{number:,.2f}"


def _level_rows(levels: List[Dict[str, Any]], colour: str) -> str:
    if not levels:
        return '<div class="lv-empty">None within the last year</div>'
    rows = []
    for level in levels:
        tags = ", ".join(
            {"swing": "swing", "ma50": "MA50", "ma200": "MA200",
             "high_52w": "52w high", "low_52w": "52w low"}.get(t, str(t))
            for t in level.get("tags") or []
        )
        touches = level.get("touches") or 0
        if touches > 1:
            tags += f" ×{touches}"
        rows.append(
            f'<div class="lv"><span class="lv-p" style="color:{colour}">{_fmt_price(level.get("price"))}</span>'
            f'<span class="lv-d">{_fmt_pct(level.get("distance_pct"))}</span>'
            f'<span class="lv-t">{_e(tags)}</span></div>'
        )
    return "".join(rows)


def _list(items: List[str], empty: str) -> str:
    if not items:
        return f'<li class="muted">{_e(empty)}</li>'
    return "".join(f"<li><b>{i}</b><span>{_e(text)}</span></li>" for i, text in enumerate(items, 1))


def build_stock_card_html(data: Dict[str, Any]) -> str:
    """Self-contained HTML for a ``CARD_WIDTH`` x ``CARD_HEIGHT`` card."""
    price = data.get("price")
    change = _to_float(data.get("change_pct"))
    change_colour = "#4ade80" if (change or 0) >= 0 else "#f87171"
    price_text = f"{price:,.2f}" if isinstance(price, (int, float)) else "-"
    currency = data.get("currency") or ""

    plan = "".join(
        f'<div class="pl"><div class="pl-l" style="color:{p["colour"]}">{_e(p["label"])}</div>'
        f'<div class="pl-p">{_e(p["price"])}</div><div class="pl-n">{_e(p["note"])}</div></div>'
        for p in data.get("plan") or []
    )
    horizons = "".join(
        f'<div class="hz"><div class="hz-l">{_e(h["label"])}<small>{_e(h["span"])}</small></div>'
        f'<div class="hz-t" style="color:{h["colour"]}">{h["arrow"]} {_e(h["trend"])}</div>'
        f'<div class="hz-b">{_e(h["basis"])}</div></div>'
        for h in data.get("horizons") or []
    ) or '<div class="muted">Not enough price history for the multi-horizon view.</div>'

    bars = "".join(
        f'<i class="{"on" if n <= data.get("confidence_score", 0) else ""}"></i>' for n in (1, 2, 3)
    )
    limitations = " · ".join(_e(x) for x in data.get("limitations") or []) or "None reported"
    score = data.get("score")
    score_text = f"{int(score)}" if isinstance(score, (int, float)) else "-"

    return f"""<!doctype html>
<html><head><meta charset="utf-8"><style>
*{{box-sizing:border-box;margin:0;padding:0}}
html,body{{width:{CARD_WIDTH}px;height:{CARD_HEIGHT}px;overflow:hidden;background:#070d1a}}
body{{font-family:Inter,"Segoe UI",Roboto,"Noto Sans","DejaVu Sans",Arial,sans-serif;color:#e2e8f0;font-size:17px;line-height:1.35}}
.card{{width:{CARD_WIDTH}px;height:{CARD_HEIGHT}px;display:flex;flex-direction:column;gap:14px;padding:0 0 18px}}
.hd{{background:linear-gradient(135deg,#0f2447,#0a1628);border-bottom:1px solid #1e3a5f;color:#fff;padding:30px 40px 26px}}
.hd-top{{display:flex;justify-content:space-between;align-items:flex-start}}
.tick{{font-size:16px;letter-spacing:.08em;color:#93c5fd;font-weight:700;text-transform:uppercase}}
.nm{{font-size:46px;font-weight:800;line-height:1.1;margin-top:6px;max-width:700px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}}
.px{{text-align:right}}
.px-v{{font-size:44px;font-weight:800}}
.px-v small{{font-size:20px;color:#cbd5e1;font-weight:600;margin-left:6px}}
.px-c{{font-size:22px;font-weight:700;color:{change_colour}}}
.px-d{{font-size:14px;color:#94a3b8;margin-top:2px}}
.vd{{margin-top:20px;display:flex;align-items:center;gap:18px;background:rgba(255,255,255,.08);border-radius:14px;padding:14px 18px}}
.vd-b{{background:{data.get("verdict_colour")};color:#fff;font-weight:900;font-size:30px;letter-spacing:.06em;border-radius:10px;padding:8px 22px;white-space:nowrap}}
.vd-t{{font-size:18px;color:#e2e8f0;display:-webkit-box;-webkit-line-clamp:3;-webkit-box-orient:vertical;overflow:hidden}}
.vd-s{{margin-left:auto;text-align:center;min-width:92px}}
.vd-s b{{display:block;font-size:34px;font-weight:800}}
.vd-s span{{font-size:12px;color:#94a3b8;text-transform:uppercase;letter-spacing:.06em}}
.sec{{margin:0 28px;background:#0f172a;border:1px solid #1e293b;border-radius:16px;padding:16px 20px}}
.st{{font-size:14px;font-weight:800;letter-spacing:.08em;text-transform:uppercase;color:#94a3b8;margin-bottom:10px}}
.grid4{{display:grid;grid-template-columns:repeat(4,1fr);gap:12px}}
.pl{{background:#111c33;border:1px solid #1e293b;border-radius:12px;padding:10px 12px}}
.pl-l{{font-size:14px;font-weight:800;text-transform:uppercase;letter-spacing:.04em}}
.pl-p{{font-size:30px;font-weight:800;color:#f8fafc;margin:2px 0}}
.pl-n{{font-size:13px;color:#94a3b8;display:-webkit-box;-webkit-line-clamp:2;-webkit-box-orient:vertical;overflow:hidden;min-height:34px}}
.pos{{display:grid;grid-template-columns:1fr 1fr;gap:12px;margin-top:12px}}
.pos div{{background:#111c33;color:#cbd5e1;border-radius:10px;padding:10px 12px;font-size:15px;display:-webkit-box;-webkit-line-clamp:3;-webkit-box-orient:vertical;overflow:hidden}}
.pos b{{display:block;font-size:12px;text-transform:uppercase;letter-spacing:.06em;color:#7dd3fc}}
.two{{display:grid;grid-template-columns:1fr 1fr;gap:14px;margin:0 28px}}
.two .sec{{margin:0}}
ul{{list-style:none;display:flex;flex-direction:column;gap:8px}}
li{{display:flex;gap:10px;font-size:15.5px;color:#e2e8f0}}
li b{{flex:0 0 26px;height:26px;border-radius:50%;color:#fff;font-size:14px;display:flex;align-items:center;justify-content:center}}
li span{{display:-webkit-box;-webkit-line-clamp:3;-webkit-box-orient:vertical;overflow:hidden}}
.good .st{{color:#4ade80}} .good li b{{background:#16a34a}}
.bad .st{{color:#f87171}} .bad li b{{background:#dc2626}}
.hzs{{display:grid;grid-template-columns:repeat(3,1fr);gap:12px}}
.hz{{background:#111c33;border:1px solid #1e293b;border-radius:12px;padding:10px 12px}}
.hz-l{{font-weight:800;font-size:16px}} .hz-l small{{display:block;font-weight:500;color:#94a3b8;font-size:13px}}
.hz-t{{font-size:21px;font-weight:800;margin:4px 0}}
.hz-b{{font-size:13px;color:#94a3b8}}
.fc{{margin-top:10px;font-size:15px;color:#cbd5e1;display:flex;flex-direction:column;gap:6px}}
.fc p{{display:-webkit-box;-webkit-line-clamp:2;-webkit-box-orient:vertical;overflow:hidden}}
.fc b{{color:#f8fafc}}
.lvl{{display:grid;grid-template-columns:1fr 1fr;gap:16px}}
.lv{{display:flex;align-items:baseline;gap:10px;padding:5px 0;border-bottom:1px dashed #1e293b}}
.lv-p{{font-size:22px;font-weight:800;min-width:96px}}
.lv-d{{font-size:15px;font-weight:700;color:#cbd5e1;min-width:64px}}
.lv-t{{font-size:13px;color:#94a3b8}}
.lv-empty,.muted{{color:#64748b;font-size:15px}}
.kp{{display:flex;gap:20px;margin-top:10px;font-size:14px;color:#94a3b8}}
.kp b{{color:#f8fafc}}
.cf{{display:flex;gap:18px;align-items:center}}
.cf-m{{display:flex;gap:4px}} .cf-m i{{width:26px;height:12px;border-radius:3px;background:#1e293b;display:block}}
.cf-m i.on{{background:{data.get("verdict_colour")}}}
.cf-l{{font-size:22px;font-weight:800;color:#f8fafc;white-space:nowrap}}
.cf-r{{font-size:14px;color:#cbd5e1;display:-webkit-box;-webkit-line-clamp:2;-webkit-box-orient:vertical;overflow:hidden}}
.cf-x{{font-size:13px;color:#64748b;margin-top:6px;display:-webkit-box;-webkit-line-clamp:2;-webkit-box-orient:vertical;overflow:hidden}}
.ft{{margin:auto 28px 0;display:flex;justify-content:space-between;font-size:12.5px;color:#475569}}
</style></head><body><div class="card">
<div class="hd">
  <div class="hd-top">
    <div><div class="tick">{_e(data.get("code"))}{" · " + _e(data.get("exchange")) if data.get("exchange") else ""}</div>
    <div class="nm">{_e(data.get("name"))}</div></div>
    <div class="px"><div class="px-v">{price_text}<small>{_e(currency)}</small></div>
    <div class="px-c">{_fmt_pct(change)}</div><div class="px-d">Data as of {_e(data.get("as_of") or "-")}</div></div>
  </div>
  <div class="vd"><div class="vd-b">{_e(data.get("verdict"))}</div>
    <div class="vd-t">{_e(data.get("one_sentence"))}</div>
    <div class="vd-s"><b>{score_text}</b><span>Score /100</span></div></div>
</div>
<div class="sec"><div class="st">Price plan</div><div class="grid4">{plan}</div>
  <div class="pos"><div><b>No position</b>{_e(data.get("no_position") or "-")}</div>
  <div><b>Already holding</b>{_e(data.get("has_position") or "-")}</div></div></div>
<div class="two">
  <div class="sec good"><div class="st">▲ Positives</div><ul>{_list(data.get("positives") or [], "No positive catalyst reported")}</ul></div>
  <div class="sec bad"><div class="st">▼ Risks</div><ul>{_list(data.get("risks") or [], "No specific risk reported")}</ul></div>
</div>
<div class="sec"><div class="st">Trend & forecast</div><div class="hzs">{horizons}</div>
  <div class="fc"><p><b>Short term:</b> {_e(data.get("short_outlook") or "-")}</p>
  <p><b>Medium / long term:</b> {_e(data.get("medium_outlook") or "-")}</p></div></div>
<div class="sec"><div class="st">Key levels</div><div class="lvl">
  <div><div class="st" style="color:#4ade80;margin-bottom:4px">Supports</div>{_level_rows(data.get("supports") or [], "#4ade80")}</div>
  <div><div class="st" style="color:#f87171;margin-bottom:4px">Resistances</div>{_level_rows(data.get("resistances") or [], "#f87171")}</div></div>
  <div class="kp"><span>3M <b>{_fmt_pct(data.get("return_3m"))}</b></span><span>12M <b>{_fmt_pct(data.get("return_12m"))}</b></span>
  <span>52-week range position <b>{"-" if data.get("range_position") is None else f'{data.get("range_position"):.0f}%'}</b></span></div></div>
<div class="sec"><div class="st">Analysis reliability</div>
  <div class="cf"><div class="cf-m">{bars}</div><div class="cf-l">{_e(data.get("confidence"))}</div>
  <div class="cf-r">{_e(data.get("confidence_reason") or "")}</div></div>
  <div class="cf-x">Limitations: {limitations}</div></div>
<div class="ft"><span>{_e(data.get("model") and "Model: " + data["model"])}</span>
<span>AI-generated from delayed public data. Not investment advice.</span></div>
</div></body></html>"""


def _resolve_chrome() -> Optional[str]:
    explicit = (os.getenv("CHROME_PATH") or "").strip()
    if explicit and Path(explicit).is_file():
        return explicit
    for name in _CHROME_CANDIDATES:
        found = shutil.which(name)
        if found:
            return found
    return None


def _render_with_playwright(card_html: str, scale: float, timeout: int) -> Optional[bytes]:
    """Preferred renderer: Python Playwright driving Chromium/Chrome."""
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        return None

    explicit = (os.getenv("CHROME_PATH") or "").strip()
    launch_options: List[Dict[str, Any]] = []
    if explicit:
        launch_options.append({"executable_path": explicit})
    launch_options.append({})                    # browser downloaded by `playwright install`
    launch_options.append({"channel": "chrome"})  # system Google Chrome (GitHub runners)

    with sync_playwright() as playwright:
        for options in launch_options:
            try:
                browser = playwright.chromium.launch(timeout=timeout * 1000, **options)
            except Exception as exc:
                logger.debug("Stock card: Playwright launch %s failed: %s", options or "default", exc)
                continue
            try:
                page = browser.new_page(
                    viewport={"width": CARD_WIDTH, "height": CARD_HEIGHT},
                    device_scale_factor=scale,
                )
                page.set_content(card_html, wait_until="load", timeout=timeout * 1000)
                return page.screenshot(full_page=False, timeout=timeout * 1000)
            finally:
                browser.close()
    return None


def _render_with_chrome_cli(card_html: str, scale: float, timeout: int) -> Optional[bytes]:
    """Fallback renderer: `chrome --headless --screenshot`."""
    chrome = _resolve_chrome()
    if chrome is None:
        return None
    temp_dir = tempfile.mkdtemp(prefix="stock_card_")
    html_path = Path(temp_dir) / "card.html"
    png_path = Path(temp_dir) / "card.png"
    try:
        html_path.write_text(card_html, encoding="utf-8")
        command = [
            chrome,
            "--headless=new",
            "--disable-gpu",
            "--no-sandbox",
            "--hide-scrollbars",
            "--no-first-run",
            "--disable-background-networking",
            "--disable-component-update",
            f"--user-data-dir={Path(temp_dir) / 'profile'}",
            f"--force-device-scale-factor={scale}",
            f"--window-size={CARD_WIDTH},{CARD_HEIGHT}",
            f"--screenshot={png_path}",
            html_path.resolve().as_uri(),
        ]
        completed = subprocess.run(command, capture_output=True, timeout=timeout, check=False)
        if png_path.exists() and png_path.stat().st_size > 0:
            return png_path.read_bytes()
        logger.warning(
            "Stock card: Chrome CLI failed (exit %s): %s",
            completed.returncode,
            completed.stderr.decode("utf-8", errors="replace")[-300:],
        )
        return None
    finally:
        shutil.rmtree(temp_dir, ignore_errors=True)


def render_card_png(card_html: str, *, scale: float = 2.0, timeout: int = 60) -> Optional[bytes]:
    """Screenshot the card; ``None`` when no browser is available or rendering fails."""
    for renderer in (_render_with_playwright, _render_with_chrome_cli):
        try:
            png = renderer(card_html, scale, timeout)
        except Exception as exc:
            logger.warning("Stock card: %s error: %s", renderer.__name__, exc)
            png = None
        if png:
            return png
    logger.warning(
        "Stock card: no renderer available (pip install playwright, or set CHROME_PATH); cards skipped"
    )
    return None


def card_caption(data: Dict[str, Any]) -> str:
    """Short plain-text caption for the image message."""
    price = data.get("price")
    price_text = f" {price:,.2f} {data.get('currency') or ''}".rstrip() if isinstance(price, (int, float)) else ""
    return f"{data.get('name')} ({data.get('code')}){price_text}: {data.get('verdict')}"


def build_stock_card_png(result: Any) -> Optional[bytes]:
    """Convenience: result -> PNG bytes (``None`` on any failure)."""
    try:
        return render_card_png(build_stock_card_html(build_stock_card_data(result)))
    except Exception as exc:
        logger.warning("Stock card build failed for %s: %s", getattr(result, "code", "?"), exc)
        return None
