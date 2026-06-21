#!/bin/bash
# tan-live-agent/scripts/daily_report.sh
# 매일 아침 9시 디스코드 #완료알림에 라이브/paper/advisor 일일 요약.
set -u
set -a; . /root/.hermes/secrets/consolidated.env; set +a
VPS_TZ_KST=1
export TAN_AGENT_MODEL_BACKEND=fcc

# --- 라이브 상태 ---
LIVE_POS=$(python3 -c "import json; p=json.load(open('/srv/hermes-os/tan/true_turtle_exact/true_turtle_bot_positions.json')); print(', '.join(list(p.keys())) if isinstance(p,dict) else 'none')")
LIVE_STATE=$(python3 -c "import json; s=json.load(open('/srv/hermes-os/tan/true_turtle_exact/true_turtle_bot_state.json')); print('auto=' + str(s.get('auto_enabled')), 'paused=' + str(s.get('bot_paused')))")
EXCLUDE=$(python3 -c "import json; s=json.load(open('/srv/hermes-os/tan/true_turtle_exact/true_turtle_bot_state.json')); print(', '.join((s.get('settings') or {}).get('entry_excluded_symbols',[])))")

# --- 라이브 PnL (실현, 최근) ---
LIVE_PNL=$(python3 -c "
import sqlite3
db=sqlite3.connect('file:/srv/hermes-os/tan/data/tan.db?mode=ro',uri=True)
try:
    r=db.execute('SELECT COUNT(*), ROUND(SUM(pnl_usd),2) FROM trades WHERE pnl_usd IS NOT NULL').fetchone()
    print(f'{r[0]}건 \${r[1]}')
except: print('n/a')
")

# --- paper 상태 ---
PAPER_TRADES=$(grep -c "exit_reason" /srv/hermes-os/paper/data/paper_trades.jsonl 2>/dev/null || echo "?")
GATE_VERDICT=$(cat /srv/hermes-os/tan-live-agent/data/gate_last_verdict.txt 2>/dev/null || echo "n/a")

# --- advisor 활동 ---
ADV_SUMMARY=$(cd /srv/hermes-os/tan-live-agent && .venv/bin/tan-live-agent journal-summary 2>/dev/null | python3 -c "
import sys,json
try:
    d=json.load(sys.stdin)
    print(f\"{d['total']}건 (approve/modify/reject 분포)\")
except: print('n/a')
")

# --- BTC 현재가 ---
BTC=$(curl -s --max-time 6 "https://fapi.binance.com/fapi/v1/ticker/price?symbol=BTCUSDT" | python3 -c "import sys,json; print('\$'+json.load(sys.stdin)['price'][:7])" 2>/dev/null || echo "n/a")

TODAY=$(TZ=Asia/Seoul date +%Y-%m-%d)

content="📅 **TAN 일일 리포트** · $TODAY

🟢 **라이브**
• 포지션: $LIVE_POS | $LIVE_STATE
• 실현 PnL: $LIVE_PNL
• 제외 심볼: $EXCLUDE (양방향 LONG·SHORT 유지)

🧬 **PAPER**
• paper trades: $PAPER_TRADES
• gate 판정: $GATE_VERDICT (PASS 시 별도 알림)

🤖 **ADVISOR (GLM-5.2)**
• 누적 결정: $ADV_SUMMARY

📊 BTC: $BTC"

/srv/hermes-os/tan-live-agent/.venv/bin/python - <<PYEOF
import os, httpx
TOKEN = os.environ["DISCORD_BOT_TOKEN"]
r = httpx.post("https://discord.com/api/v10/channels/1517589871383019701/messages",
    headers={"Authorization":"Bot "+TOKEN}, data={"content":"""$content"""}, timeout=15)
print("daily report:", r.status_code)
PYEOF
