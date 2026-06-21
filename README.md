# tan-live-agent

LLM advisor layer for TAN trading. Runs in **paper/shadow mode only** and never
touches live orders or live services. Independent of the live `tan-live` bot.

## Advisors

- **L1 — entry gate**: `approve` / `reject` / `modify` a proposed entry. Fails
  closed (returns `reject` on any error or ambiguous response).
- **L2 — parameter**: suggests TP R, trail buffer, entry thresholds for paper
  testing. Never applied to live without a promotion bundle (30+ samples).

## Backends (switchable)

| Backend | Env | Status |
|---|---|---|
| `gemini` | `TAN_AGENT_MODEL_BACKEND=gemini` | Default; Gemini 2.5 Flash (works today) |
| `glm` | `TAN_AGENT_MODEL_BACKEND=glm` | GLM 5.2; activate after Z.AI/Zhipu credit recharge |
| `gpt` | `TAN_AGENT_MODEL_BACKEND=gpt` | GPT-5.5 via Codex; activate on/after 6/25 |

## Install (VPS)

```bash
# from repo root
python -m pip install -e . --user
# or: uv tool install . --from /srv/hermes-os/tan-live-agent
```

## Usage

```bash
export GEMINI_API_KEY=...
# smoke test
tan-live-agent test-model
# current market context (shadow read of live bot state)
tan-live-agent ctx
# L1 gate eval on a hypothetical entry
tan-live-agent gate-eval --symbol TRXUSDT --direction LONG \
    --entry 0.327 --stop 0.323 --tp 0.335 --r 2.0
# L2 parameter suggestion
tan-live-agent params
# validation views
tan-live-agent journal-recent --advisor gate --limit 30
tan-live-agent journal-summary
```

## Safety contract

- This package is paper/shadow only. `paper_mode = True` always.
- It only READS `true_turtle_bot_positions.json` / `true_turtle_bot_state.json`.
- It never imports or calls the live bot, never writes to Binance, never
  restarts any `tan-*` service.
- All advisor decisions are journaled to `data/advisor_journal.sqlite3` for
  offline hit-rate validation.
