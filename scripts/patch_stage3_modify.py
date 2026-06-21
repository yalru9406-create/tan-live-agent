"""Stage 3 patch: advisor modify-params reflection into paper StrategyConfig.

Extends the stage-2 advisor gate in paper_engine/runner.py. When the advisor
returns decision="modify" with params, we override the per-entry StrategyConfig
via dataclasses.replace (take_profit_r, min_reward_to_cost, etc.) so winners
run further and entry quality tightens — exactly the profit-maximizing stance
the operator asked for. Reject still skips; approve still uses baseline.

Safe to re-run (idempotent). Run from /srv/hermes-os/paper.
"""
from __future__ import annotations
import sys
from pathlib import Path

P = Path("/srv/hermes-os/paper/src/paper_engine/runner.py")
t = P.read_text()

MARKER = "# stage3-modify-params"
if MARKER in t:
    print("stage3 modify-params already present, skipping")
    sys.exit(0)

# Anchor: the reject block we added in stage-2, immediately followed by the
# default open_position call. We insert the modify branch between them.
anchor = (
    '                        blocked += 1\n'
    '                        continue\n'
    '                except Exception as _e:\n'
    '                    ledger.append_block(block_from_signal(adapted_signal, "advisor_error", (str(_e)[:200],)))\n'
    '            position = ledger.open_position(adapted_signal, config.strategy)\n'
)
if anchor not in t:
    print("ERROR: stage-2 anchor not found (is advisor gate installed?)", file=sys.stderr)
    sys.exit(1)

modify_block = (
    '                        blocked += 1\n'
    '                        continue\n'
    '                except Exception as _e:\n'
    '                    ledger.append_block(block_from_signal(adapted_signal, "advisor_error", (str(_e)[:200],)))\n'
    '            # stage3-modify-params: apply advisor modify params per-entry (profit-max stance)\n'
    '            if _os.getenv("TAN_ADVISOR_PAPER") == "1" and _adv.get("decision") == "modify" and _adv.get("params"):\n'
    '                import dataclasses as _dc\n'
    '                _p = _adv["params"]\n'
    '                _override = {}\n'
    '                for _k in ("take_profit_r", "min_reward_to_cost", "breakout_atr_buffer", "max_initial_stop_distance_pct", "min_configured_take_profit_r"):\n'
    '                    if _k in _p:\n'
    '                        try:\n'
    '                            _override[_k] = float(_p[_k])\n'
    '                        except (TypeError, ValueError):\n'
    '                            pass\n'
    '                if _override:\n'
    '                    _strat = _dc.replace(config.strategy, **_override)\n'
    '                    ledger.append_block(block_from_signal(adapted_signal, "advisor_modify", (_adv.get("rationale", "")[:150], str(_override))))\n'
    '                    position = ledger.open_position(adapted_signal, _strat)\n'
    '                    if position is None:\n'
    '                        blocked += 1\n'
    '                    else:\n'
    '                        opened += 1\n'
    '                    continue\n'
    '            position = ledger.open_position(adapted_signal, config.strategy)\n'
)

t = t.replace(anchor, modify_block, 1)
P.write_text(t)
print("stage3 modify-params patch applied")
