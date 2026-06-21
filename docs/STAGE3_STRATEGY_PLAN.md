# Stage 3 — true_turtle strategy improvement plan (paper → live)

**Diagnosis (from tan.db, 40 realized trades):** TP 1 vs SL 27, realized PnL
−$64.47. The strategy *enters often and gets stopped out often*; winners do
not run far enough. This is a strategy problem, not an infrastructure problem.

## Root-cause hypotheses (ranked)

1. **Trail too tight** — ATR_2N trailing stop exits winners before they run.
   Evidence: 27 stops vs 1 TP means the trail catches price noise.
2. **Entry quality too low** — `entry_min_reward_to_cost=3.0` lets marginal
   entries through. Many entries are immediately underwater.
3. **No regime filter** — same entries in trending, choppy, and panic markets.
   In chop/panic, breakout entries get faded into stops.
4. **TP geometry too small** — `take_profit_r=2.0` caps winners at 2R while the
   27 losers average more than −1R each. Negative expectancy.

## Improvement experiments (paper-first, each isolated)

Run each as a separate paper config variant. Measure over >=30 paper trades
vs the v1 baseline. Promote only the variant that beats baseline expectancy.

### Exp A — Widen the trail (address hypothesis 1)
- `trail_buffer_atr`: 2.0 → **2.5**
- Everything else unchanged.
- Pass criterion: TP/SL ratio improves from 1:27 to >= 1:8, expectancy > 0.

### Exp B — Raise entry quality (address hypothesis 2)
- `entry_min_reward_to_cost`: 3.0 → **4.0**
- `entry_min_configured_take_profit_r`: 1.5 → 2.0
- Everything else unchanged.
- Pass criterion: entry count drops ~40%, win rate >= 40%.

### Exp C — Regime filter (address hypothesis 3)
- Skip entries when `|BTC 24h change| < 1.5%` AND Fear&Greed in [35, 65]
  (dead-chop zone).
- Skip entries when `|BTC 24h change| > 8%` (chaos zone).
- Pass criterion: skipped entries would have been net-negative; kept entries'
  expectancy > baseline.

### Exp D — Let winners run (address hypothesis 4)
- `take_profit_r`: 2.0 → **3.0**
- Trail from Exp A (2.5 ATR).
- Pass criterion: avg winner >= 2.5R, expectancy > 0 with widened trail.

### Exp E — Combined best-of (only after A–D each measured)
- Stack the winners of A–D into one config variant.
- Measure over >=30 trades. Promote to live only if expectancy > 0 AND
  max drawdown < 6% (matches `max_heat`).

## How to run

Each experiment = a new paper config file under `/srv/hermes-os/paper/`:
```
config_paper_exp_a_trail25.yaml
config_paper_exp_b_quality40.yaml
...
```
Run them under separate paper-engine instances (or sequentially via a paper
A/B harness). The advisor (stage 2) evaluates every entry shadow so we can
also measure "advisor-approved subset" vs raw.

## Live promotion gate (hard rules)
1. >= 30 paper trades per variant.
2. Positive expectancy (R-weighted).
3. Max drawdown within `max_heat` (6%).
4. TP/SL ratio >= 1:5 (vs current 1:27).
5. Operator (yalru) explicit approval on the promotion bundle.

Until all 5 pass: **no live change**. The live true_turtle bot keeps running
its current config; only the paper variants change.

## Live safety envelope (when promoted)
- Apply via config_live_aggressive_200to5k.yaml replacement only.
- Keep `tan-live-risk-manager.service` (dry-run) watching.
- Keep `C5_LIVE_RISK_ACTIVATION.md` envelope (reduce_only, no new leverage).
- First 24h after promotion: watchdog alerts on every position change.
