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

## Validation & backend switching

### 30-sample promotion gate
Both timers accumulate advisor decisions into `data/advisor_journal.sqlite3`.
Check progress any time:
```bash
tan-live-agent journal-summary                  # total + by-decision + avg confidence
tan-live-agent journal-summary --advisor gate   # L1 only
tan-live-agent journal-summary --advisor params # L2 only
tan-live-agent journal-recent --advisor watchdog --limit 20
```
Promotion path to live (stage 2/3) opens once each advisor has 30+ samples
with a non-degenerate decision distribution. Until then the advisor stays
shadow (read+alert only, never acts).

### Backend switch (no code change)
| When | Env | Notes |
|---|---|---|
| **Now (recommended)** | `TAN_AGENT_MODEL_BACKEND=fcc` | GLM-5.2 via z.ai coding subscription (fcc-server @ 127.0.0.1:8082). No per-token billing; uses 5h/weekly quota. |
| Gemini fallback | `TAN_AGENT_MODEL_BACKEND=gemini` | Gemini 2.5 Flash. Free-tier 429s under burst. |
| GLM direct (pay-as-you-go) | `TAN_AGENT_MODEL_BACKEND=glm` | `GLM_API_KEY` direct to z.ai/bigmodel. Requires credit recharge. |
| On/after 6/25 (Codex refill) | `TAN_AGENT_MODEL_BACKEND=gpt` | GPT-5.5 via Codex subscription. |
Switch is a single env var in the systemd unit (`tan-live-agent-watchdog.service`
and `tan-live-agent-poll.service`), then `systemctl daemon-reload`. No code edit.

### What the advisor does NOT do (by design)
- It does not place orders, reduce sizes below baseline, or restart live services.
- Watchdog alerts are read-only observations (`hold` / `tighten-protection` /
  `exit` suggestions). The live bot is free to ignore them.
- Action labels are normalized from rationale keywords (`reject` from the model
  is mapped to `hold` on an existing position unless the rationale says exit).
