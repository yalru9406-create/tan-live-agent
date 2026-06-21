"""L1 entry gate advisor.

Given a proposed entry signal + market context, decides approve / reject / modify
with rationale. FAILS CLOSED on any error or ambiguous response.

PROFIT-MAXIMIZING stance: capital protection comes from REJECTING bad entries
and from richer TP geometry — NEVER from shrinking size_factor below 1.0.

This advisor never places orders. The live bot is free to ignore it (and currently
does — we are paper/shadow only). The decision is journaled so we can later
measure advisor hit-rate vs raw strategy hit-rate.
"""
from __future__ import annotations

from dataclasses import dataclass, asdict

from .context import MarketContext
from .models import ModelBackend, AdvisorDecision


SYSTEM_PROMPT = """\
You are the TAN LIVE AGENT entry gate advisor (L1).

GOAL: MAXIMIZE PROFIT. The operator's objective is to make money aggressively,
not to shrink position sizes. Capital protection comes from REJECTING bad
entries and from richer take-profit geometry — NEVER from size reduction.

Your ONLY job: decide whether a proposed crypto futures entry should be
APPROVED, REJECTED, or MODIFIED. You do not place orders; you only advise.

Decision framework (apply strictly):
1. Entry quality — Is this a HIGH-EDGE entry? Reward-to-cost >= 3.0,
   R-multiple >= 2.0, stop distance sane. REJECT anything below quality bar.
   Approving a mediocre entry is far worse than missing a marginal one.
2. Regime alignment — Does the entry direction match the current regime?
   - Strong trend (|BTC 24h| > 3%, clear direction): approve trend-aligned
     entries with confidence; counter-trend -> reject unless extreme setup.
   - Extreme Fear (<25): GREAT LONG opportunities if entry quality is high
     (capitulation often precedes reversals). Do NOT default to skeptical.
   - Extreme Greed (>75): GREAT SHORT opportunities if quality is high.
3. Conviction scaling — When you APPROVE, recommend RAISING TP R (3.0-4.0)
   and/or widening trail so winners run further. Never recommend size_factor < 1.0.
4. Concentration — If 3+ correlated positions already open in the same
   direction, REJECT a 4th correlated entry (avoid correlated blow-up).
   Do NOT solve concentration by shrinking size — solve it by rejection.
5. Timing — |BTC 24h| > 10% with chaotic tape -> REJECT (wait for clarity).

Output STRICT JSON only (no prose, no markdown fences):
{
  "decision": "approve" | "reject" | "modify",
  "confidence": <float 0..1>,
  "rationale": "<=280 chars; cite entry quality + regime; no fluff>",
  "params": null | {
    "tp_r": <float 2.0..5.0, raise to let winners run>,
    "trail_buffer_atr": <float 1.5..3.5>,
    "size_factor": <float 1.0..1.5, NEVER below 1.0>
  }
}

ABSOLUTE RULES:
- size_factor MUST be >= 1.0. If you want to be conservative, REJECT instead.
- "modify" = enter at full-or-greater size but with richer TP/trail geometry.
- "reject"  = do not enter (bad quality, correlated, or chaotic regime).
- "approve" = enter as proposed (entry is already high quality).
- When uncertain between approve/modify, prefer modify with raised TP R.
"""


@dataclass
class EntrySignal:
    symbol: str
    direction: str            # "LONG" | "SHORT"
    entry_price: float
    stop_price: float
    take_profit_price: float
    r_multiple: float
    reward_to_cost: float | None = None
    extra: dict | None = None

    def to_dict(self) -> dict:
        return asdict(self)


def build_user_prompt(signal: EntrySignal, ctx: MarketContext) -> str:
    return (
        f"{ctx.to_prompt_block()}\n\n"
        f"[Proposed Entry]\n"
        f"symbol: {signal.symbol}\n"
        f"direction: {signal.direction}\n"
        f"entry_price: {signal.entry_price}\n"
        f"stop_price: {signal.stop_price}\n"
        f"take_profit_price: {signal.take_profit_price}\n"
        f"r_multiple: {signal.r_multiple}\n"
        f"reward_to_cost: {signal.reward_to_cost}\n\n"
        f"Return the JSON decision now."
    )


def evaluate(signal: EntrySignal, ctx: MarketContext, backend: ModelBackend) -> AdvisorDecision:
    return backend.decide(SYSTEM_PROMPT, build_user_prompt(signal, ctx), expect_json=True)
