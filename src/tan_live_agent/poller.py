"""Periodic paper poll.

Runs every N minutes (via systemd timer) and produces advisor output INDEPENDENTLY
of the live bot. It does not place orders. It does not modify live state.

Each poll:
  1. Collects market context (BTC, RSI, Fear&Greed, shadow open positions).
  2. For each currently-open position on the live bot, asks L1 "if this entry
     were proposed fresh right now, would you approve it?" -> journals the answer.
     This lets us measure advisor agreement vs live bot's actual entries.
  3. Asks L2 for regime-fitted parameter suggestions -> journals them.
  4. Prints a compact summary.

Over time this auto-builds the 30+ sample corpus needed for promotion validation.
"""
from __future__ import annotations

import json
import time
from dataclasses import asdict
from pathlib import Path

from . import context as ctx_mod
from . import gate, params, journal
from .config import Settings
from .models import get_backend, ModelError, AdvisorDecision


def _entry_signal_from_position(pos: dict, r_default: float = 2.0) -> gate.EntrySignal | None:
    """Build a hypothetical EntrySignal from a live open position (shadow read)."""
    try:
        symbol = pos.get("symbol")
        side = pos.get("side", 0)
        direction = "LONG" if side > 0 else "SHORT"
        entry = float(pos.get("last_add") or pos.get("entry_price") or 0.0)
        stop = pos.get("trail_stop")
        tp = pos.get("take_profit_price")
        if not symbol or not entry or stop is None or tp is None:
            return None
        stop_f = float(stop)
        tp_f = float(tp)
        risk = abs(entry - stop_f)
        reward = abs(tp_f - entry)
        r_mult = round(reward / risk, 3) if risk > 0 else r_default
        return gate.EntrySignal(
            symbol=symbol,
            direction=direction,
            entry_price=entry,
            stop_price=stop_f,
            take_profit_price=tp_f,
            r_multiple=r_mult,
            reward_to_cost=None,
        )
    except (TypeError, ValueError):
        return None


def run_paper_poll(settings: Settings) -> dict:
    ctx = ctx_mod.collect(settings.positions_json_path, settings.state_json_path)
    backend = get_backend(settings)
    summary: dict = {
        "ts_ms": ctx.ts_ms,
        "backend": backend.name,
        "btc": ctx.btc_price,
        "btc_24h_pct": ctx.btc_change_24h_pct,
        "fear_greed": ctx.fear_greed,
        "l1": [],
        "l2": None,
        "errors": [],
    }

    # L1: evaluate each open position as a hypothetical fresh entry.
    for pos in ctx.open_positions:
        sig = _entry_signal_from_position(pos)
        if sig is None:
            continue
        try:
            d: AdvisorDecision = gate.evaluate(sig, ctx, backend)
            journal.log_event(
                settings.journal_path,
                advisor="gate",
                model=backend.name,
                decision=d,
                context=ctx,
                signal=sig,
            )
            summary["l1"].append({
                "symbol": sig.symbol,
                "direction": sig.direction,
                "decision": d.decision,
                "confidence": d.confidence,
                "rationale": d.rationale,
                "params": d.params,
                "latency_ms": d.latency_ms,
            })
        except ModelError as e:
            summary["errors"].append(f"L1 {sig.symbol}: {e}")

    # L2: always suggest regime-fitted parameters.
    try:
        d2 = params.suggest(ctx, backend)
        journal.log_event(
            settings.journal_path,
            advisor="params",
            model=backend.name,
            decision=d2,
            context=ctx,
        )
        summary["l2"] = {
            "decision": d2.decision,
            "confidence": d2.confidence,
            "rationale": d2.rationale,
            "params": d2.params,
            "latency_ms": d2.latency_ms,
        }
    except ModelError as e:
        summary["errors"].append(f"L2: {e}")

    return summary
