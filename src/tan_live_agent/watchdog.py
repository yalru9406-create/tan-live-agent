"""Realtime market & position watchdog.

Runs every minute via systemd timer. STRICTLY READ-ONLY.

Detects:
  - BTC 1m / 5m price spikes (|change| over threshold)
  - Open position trail-stop / TP proximity (live positions shadow read)

On spike or critical proximity, asks the advisor for a position-review decision
and fires a Discord alert. NEVER places orders.

All thresholds are env-tunable so the operator can dial sensitivity without
code edits.
"""
from __future__ import annotations

import os
import time
from dataclasses import dataclass, field
from typing import Any

import httpx

from . import context as ctx_mod, journal
from .config import Settings
from .models import get_backend, ModelError, AdvisorDecision
from .discord_report import send_alert


SPIKE_1M_PCT = float(os.getenv("TAN_WATCHDOG_SPIKE_1M", "0.4"))
SPIKE_5M_PCT = float(os.getenv("TAN_WATCHDOG_SPIKE_5M", "1.0"))
TRAIL_PROXIMITY_PCT = float(os.getenv("TAN_WATCHDOG_TRAIL_PROX", "0.4"))
TP_PROXIMITY_PCT = float(os.getenv("TAN_WATCHDOG_TP_PROX", "0.4"))


POSITION_REVIEW_PROMPT = """\
You are the TAN LIVE AGENT realtime watchdog (position review).

A market spike or critical position proximity was just detected. Review the
CURRENT open position and advise: HOLD / TIGHTEN-PROTECTION / EXIT.

You are an advisor. You do not place orders. The operator wants PROFIT
MAXIMIZATION, so do NOT advise exit unless the position is genuinely threatened.

Decision framework:
- BTC spike WITH the position direction (LONG + BTC up): HOLD, maybe raise TP.
- BTC spike AGAINST the position (LONG + BTC dump): assess distance to trail stop.
  - trail_stop > 0.7% away: HOLD with confidence.
  - trail_stop within 0.3%: TIGHTEN-PROTECTION (raise trail) or EXIT if spike extreme.
- Extreme Fear/Greed contrarian positions may be winning -> HOLD.
- If 3+ correlated positions are all threatened simultaneously, that is systemic; prefer EXIT on the weakest.

Output STRICT JSON only (no prose, no fences):
{
  "action": "hold" | "tighten-protection" | "exit",
  "confidence": <float 0..1>,
  "rationale": "<=240 chars; cite spike + proximity facts>",
  "params": null | {"new_trail_buffer_atr": <float>}
}
"""


@dataclass
class WatchdogFinding:
    kind: str               # "btc_spike_1m" | "btc_spike_5m" | "trail_proximity" | "tp_proximity"
    symbol: str | None
    severity: str           # "info" | "warn" | "critical"
    detail: str
    extra: dict = field(default_factory=dict)


def _btc_recent_changes() -> tuple[float, float, float]:
    """Return (last_price, abs_1m_pct, abs_5m_pct) for BTCUSDT."""
    r = httpx.get(
        "https://fapi.binance.com/fapi/v1/klines?symbol=BTCUSDT&interval=1m&limit=6",
        timeout=10,
    )
    r.raise_for_status()
    rows = r.json()
    last = float(rows[-1][4])  # close
    prev1 = float(rows[-2][4])
    prev5 = float(rows[-6][4])
    ch_1m = abs(last - prev1) / prev1 * 100.0 if prev1 else 0.0
    ch_5m = abs(last - prev5) / prev5 * 100.0 if prev5 else 0.0
    return last, round(ch_1m, 3), round(ch_5m, 3)


def _symbol_price(symbol: str) -> float | None:
    try:
        r = httpx.get(f"https://fapi.binance.com/fapi/v1/ticker/price?symbol={symbol}", timeout=8)
        r.raise_for_status()
        return float(r.json()["price"])
    except Exception:
        return None


def _pct(a: float, b: float) -> float:
    return abs(a - b) / a * 100.0 if a else 0.0


def scan(btc_last: float, ch_1m: float, ch_5m: float, positions: list[dict]) -> list[WatchdogFinding]:
    findings: list[WatchdogFinding] = []
    if ch_1m >= SPIKE_1M_PCT:
        findings.append(WatchdogFinding("btc_spike_1m", "BTCUSDT", "warn",
            f"BTC 1m move {ch_1m:.2f}% (>= {SPIKE_1M_PCT}%)",
            extra={"btc": btc_last, "change_1m_pct": ch_1m}))
    if ch_5m >= SPIKE_5M_PCT:
        findings.append(WatchdogFinding("btc_spike_5m", "BTCUSDT", "critical",
            f"BTC 5m move {ch_5m:.2f}% (>= {SPIKE_5M_PCT}%)",
            extra={"btc": btc_last, "change_5m_pct": ch_5m}))
    for pos in positions:
        sym = pos.get("symbol")
        if not sym:
            continue
        price = _symbol_price(sym)
        if price is None:
            continue
        trail = pos.get("trail_stop")
        tp = pos.get("take_profit_price")
        side = pos.get("side", 0)
        entry = pos.get("last_add") or pos.get("entry_price")
        if trail is not None:
            d_trail = _pct(price, float(trail))
            if d_trail <= TRAIL_PROXIMITY_PCT:
                findings.append(WatchdogFinding("trail_proximity", sym, "critical",
                    f"{sym} price {price} within {d_trail:.2f}% of trail_stop {trail}",
                    extra={"price": price, "trail": trail, "distance_pct": round(d_trail, 3)}))
        if tp is not None:
            d_tp = _pct(price, float(tp))
            if d_tp <= TP_PROXIMITY_PCT:
                findings.append(WatchdogFinding("tp_proximity", sym, "info",
                    f"{sym} price {price} within {d_tp:.2f}% of TP {tp}",
                    extra={"price": price, "tp": tp, "distance_pct": round(d_tp, 3)}))
    return findings


def _build_review_user(finding: WatchdogFinding, ctx: ctx_mod.MarketContext) -> str:
    return (
        f"{ctx.to_prompt_block()}\n\n"
        f"[Watchdog Finding]\n"
        f"kind: {finding.kind}\n"
        f"symbol: {finding.symbol}\n"
        f"severity: {finding.severity}\n"
        f"detail: {finding.detail}\n"
        f"extra: {finding.extra}\n\n"
        f"Return the JSON action now."
    )


@dataclass
class WatchdogSummary:
    ts_ms: int
    btc: float
    btc_1m_pct: float
    btc_5m_pct: float
    findings: list[dict]
    reviews: list[dict]
    alerts_sent: int
    errors: list[str] = field(default_factory=list)


def run_watchdog(settings: Settings) -> WatchdogSummary:
    ctx = ctx_mod.collect(settings.positions_json_path, settings.state_json_path)
    btc_last, ch_1m, ch_5m = _btc_recent_changes()
    findings = scan(btc_last, ch_1m, ch_5m, ctx.open_positions)

    summary = WatchdogSummary(
        ts_ms=int(time.time() * 1000),
        btc=btc_last,
        btc_1m_pct=ch_1m,
        btc_5m_pct=ch_5m,
        findings=[f.__dict__ for f in findings],
        reviews=[],
        alerts_sent=0,
    )

    if not findings:
        return summary

    backend = get_backend(settings)
    for f in findings:
        try:
            d: AdvisorDecision = backend.decide(
                POSITION_REVIEW_PROMPT, _build_review_user(f, ctx), expect_json=True
            )
            journal.log_event(
                settings.journal_path,
                advisor="watchdog",
                model=backend.name,
                decision=AdvisorDecision(
                    decision=d.decision if d.decision else str(d.params or {}).get("action", "hold"),
                    confidence=d.confidence,
                    rationale=d.rationale,
                    params=d.params,
                    raw_text=d.raw_text,
                    model=d.model,
                    latency_ms=d.latency_ms,
                ),
                context=ctx,
            )
            summary.reviews.append({
                "kind": f.kind, "symbol": f.symbol, "severity": f.severity,
                "action": (d.params or {}).get("action") or d.decision,
                "confidence": d.confidence,
                "rationale": d.rationale,
                "params": d.params,
            })
        except ModelError as e:
            summary.errors.append(f"{f.kind} {f.symbol}: {e}")

    if settings.discord_webhook_url:
        msgs = _format_alert(btc_last, ch_1m, ch_5m, findings, summary.reviews)
        for m in msgs:
            try:
                send_alert(settings.discord_webhook_url, m)
                summary.alerts_sent += 1
            except Exception as e:
                summary.errors.append(f"discord: {e}")

    return summary


def _format_alert(btc: float, ch1: float, ch5: float, findings, reviews) -> list[str]:
    header = f"🚨 TAN WATCHDOG 🚨\nBTC ${btc:,.0f} | 1m {ch1:.2f}% | 5m {ch5:.2f}%"
    msgs = [header]
    for f, r in [(findings[i], (reviews[i] if i < len(reviews) else None)) for i in range(len(findings))]:
        line = f"\n• [{f.severity.upper()}] {f.kind} {f.symbol or ''}: {f.detail}"
        if r:
            line += f"\n  → advisor: {r.get('action','?')} (conf {r.get('confidence','?')}) — {r.get('rationale','')[:180]}"
        msgs.append(line)
    return [header + "\n" + "\n".join(msgs[1:])]
