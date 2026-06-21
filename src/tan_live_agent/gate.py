"""L1 entry gate advisor.

Given a proposed entry signal + market context, decides approve / reject / modify
with rationale. FAILS CLOSED on any error or ambiguous response.

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

Your ONLY job: decide whether a proposed crypto futures entry should be
APPROVED, REJECTED, or MODIFIED.

You are an advisor. You do not place orders. You do not modify live positions.
You only return a decision.

Decision framework (apply strictly):
1. Regime fit — Does this entry direction align with current BTC/market regime
   and Fear&Greed?
   - Extreme Greed (>75): be skeptical of new LONGs in altcoins.
   - Extreme Fear (<25): be skeptical of new SHORTs; LONGs may be value but risky.
2. Conviction — Is the signal's reward-to-cost and R-multiple sound?
   (baseline: entry_min_reward_to_cost=3.0, take_profit_r>=1.5)
3. Correlation exposure — Are open positions already correlated
   (multiple LONG alts during a BTC dump)?
4. Timing — If |BTC 24h change| > 8%, prefer REJECT or MODIFY (smaller size / wider stop).
5. Confidence calibration — confidence in [0,1]. Below 0.5 -> prefer REJECT or MODIFY.

Output STRICT JSON only (no prose, no markdown fences):
{
  "decision": "approve" | "reject" | "modify",
  "confidence": <float 0..1>,
  "rationale": "<=280 chars; cite regime + signal facts; no fluff>",
  "params": null
}

Rules:
- approve = proceed with entry as proposed.
- reject  = do not enter.
- modify  = enter only if params overridden (provide params: tp_r, trail_buffer_atr, size_factor).
- If uncertain, choose reject with low confidence. Capital preservation first.
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
