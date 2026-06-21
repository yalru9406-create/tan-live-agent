"""tan-live-agent CLI.

Examples:
  tan-live-agent test-model
  tan-live-agent ctx
  tan-live-agent gate-eval --symbol TRXUSDT --direction LONG \\
      --entry 0.327 --stop 0.323 --tp 0.335 --r 2.0
  tan-live-agent params
  tan-live-agent paper-poll              # one-shot paper poll (L1+L2), used by timer
  tan-live-agent journal-recent --advisor gate --limit 30
  tan-live-agent journal-summary

All commands run in paper/shadow mode. No command writes to live state.
"""
from __future__ import annotations

import argparse
import json
import os
import sys

from .config import Settings
from . import context as ctx_mod
from . import gate, params, journal
from .models import get_backend, ModelError


def _print_json(obj) -> None:
    print(json.dumps(obj, ensure_ascii=False, indent=2, default=str))


def cmd_test_model(args, settings: Settings) -> int:
    b = get_backend(settings)
    try:
        d = b.decide(
            system="Reply with the exact JSON requested.",
            user='Return exactly this JSON: {"decision":"approve","confidence":0.9,"rationale":"smoke test ok"}',
            expect_json=True,
            max_tokens=128,
        )
    except ModelError as e:
        _print_json({"backend": b.name, "ok": False, "error": str(e)})
        return 2
    _print_json({
        "backend": b.name,
        "ok": d.ok,
        "decision": d.decision,
        "confidence": d.confidence,
        "rationale": d.rationale,
        "latency_ms": d.latency_ms,
    })
    return 0 if d.ok else 1


def cmd_ctx(args, settings: Settings) -> int:
    c = ctx_mod.collect(settings.positions_json_path, settings.state_json_path)
    print(c.to_prompt_block())
    return 0


def cmd_gate_eval(args, settings: Settings) -> int:
    sig = gate.EntrySignal(
        symbol=args.symbol,
        direction=args.direction,
        entry_price=args.entry,
        stop_price=args.stop,
        take_profit_price=args.tp,
        r_multiple=args.r,
        reward_to_cost=args.reward_to_cost,
    )
    c = ctx_mod.collect(settings.positions_json_path, settings.state_json_path)
    b = get_backend(settings)
    try:
        d = gate.evaluate(sig, c, b)
    except ModelError as e:
        _print_json({"error": str(e), "backend": b.name})
        return 2
    eid = journal.log_event(
        settings.journal_path, advisor="gate", model=b.name,
        decision=d, context=c, signal=sig,
    )
    _print_json({
        "event_id": eid,
        "backend": d.model,
        "decision": d.decision,
        "confidence": d.confidence,
        "rationale": d.rationale,
        "params": d.params,
        "latency_ms": d.latency_ms,
    })
    return 0


def cmd_params(args, settings: Settings) -> int:
    c = ctx_mod.collect(settings.positions_json_path, settings.state_json_path)
    b = get_backend(settings)
    try:
        d = params.suggest(c, b)
    except ModelError as e:
        _print_json({"error": str(e), "backend": b.name})
        return 2
    journal.log_event(
        settings.journal_path, advisor="params", model=b.name,
        decision=d, context=c,
    )
    _print_json({
        "backend": d.model,
        "decision": d.decision,
        "confidence": d.confidence,
        "rationale": d.rationale,
        "params": d.params,
        "latency_ms": d.latency_ms,
    })
    return 0


def cmd_paper_poll(args, settings: Settings) -> int:
    from .poller import run_paper_poll

    summary = run_paper_poll(settings)
    _print_json(summary)
    return 0 if not summary.get("errors") else 1


def cmd_journal_recent(args, settings: Settings) -> int:
    rows = journal.recent(settings.journal_path, advisor=args.advisor, limit=args.limit)
    _print_json(rows)
    return 0


def cmd_journal_summary(args, settings: Settings) -> int:
    _print_json(journal.summarize(settings.journal_path, advisor=args.advisor))
    return 0


def main(argv=None) -> int:
    p = argparse.ArgumentParser(prog="tan-live-agent")
    p.add_argument("--backend", default=None, help="override TAN_AGENT_MODEL_BACKEND (gemini|glm|gpt)")
    sub = p.add_subparsers(dest="cmd", required=True)

    sub.add_parser("test-model", help="smoke-test the active backend").set_defaults(func=cmd_test_model)
    sub.add_parser("ctx", help="print current market context").set_defaults(func=cmd_ctx)

    g = sub.add_parser("gate-eval", help="L1 entry gate evaluation")
    g.add_argument("--symbol", required=True)
    g.add_argument("--direction", required=True, choices=["LONG", "SHORT"])
    g.add_argument("--entry", type=float, required=True)
    g.add_argument("--stop", type=float, required=True)
    g.add_argument("--tp", type=float, required=True)
    g.add_argument("--r", type=float, required=True)
    g.add_argument("--reward-to-cost", type=float, default=None)
    g.set_defaults(func=cmd_gate_eval)

    sub.add_parser("params", help="L2 parameter suggestion").set_defaults(func=cmd_params)

    sub.add_parser(
        "paper-poll",
        help="one-shot paper poll (L1 over open positions + L2 params); used by systemd timer",
    ).set_defaults(func=cmd_paper_poll)

    j = sub.add_parser("journal-recent", help="recent advisor events")
    j.add_argument("--advisor", default=None, choices=["gate", "params"])
    j.add_argument("--limit", type=int, default=30)
    j.set_defaults(func=cmd_journal_recent)

    s = sub.add_parser("journal-summary", help="aggregate advisor counts")
    s.add_argument("--advisor", default=None, choices=["gate", "params"])
    s.set_defaults(func=cmd_journal_summary)

    args = p.parse_args(argv)
    if args.backend:
        os.environ["TAN_AGENT_MODEL_BACKEND"] = args.backend
    settings = Settings()
    return args.func(args, settings)


if __name__ == "__main__":
    sys.exit(main())
