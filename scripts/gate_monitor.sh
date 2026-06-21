#!/bin/bash
# tan-live-agent/scripts/gate_monitor.sh
# paper research-gate 를 평가하고, 판정이 PROMOTE(전체 PASS)로 바뀌면 디스코드 알림.
# 거짓 PASS 없음: gate의 실제 판정만 관찰. cron 매 시간 실행.
set -u
PAPER=/srv/hermes-os/paper
STATE_FILE=/srv/hermes-os/tan-live-agent/data/gate_last_verdict.txt
mkdir -p "$(dirname "$STATE_FILE")"

cd "$PAPER" || exit 0
RESULT=$(/root/.local/bin/uv run paper research-gate --data-dir data 2>&1)
VERDICT=$(echo "$RESULT" | grep -oE "paper_gate_verdict: [A-Z_]+" | head -1 | awk "{print \$2}")
[ -z "$VERDICT" ] && VERDICT="UNKNOWN"
FAIL_COUNT=$(echo "$RESULT" | grep -c "FAIL")
PASS_COUNT=$(echo "$RESULT" | grep -c "PASS")

PREV="NONE"
[ -f "$STATE_FILE" ] && PREV=$(cat "$STATE_FILE" 2>/dev/null || echo "NONE")
echo "$VERDICT" > "$STATE_FILE"

# PROMOTE 판정 = 전체 PASS (실제로 전략/검증 통과한 경우만)
if [ "$VERDICT" = "PROMOTE" ] || [ "$VERDICT" = "PASS" ]; then
  if [ "$PREV" != "$VERDICT" ]; then
    set -a; . /root/.hermes/secrets/consolidated.env; set +a
    /srv/hermes-os/tan-live-agent/.venv/bin/python - <<PYEOF
import os, httpx
TOKEN = os.environ["DISCORD_BOT_TOKEN"]
content = """🟢 **PAPER GATE PASS - 라이브 승격 가능**

판정: $VERDICT (PASS $PASS_COUNT / FAIL $FAIL_COUNT)

paper 전략이 승격 게이트를 통과했습니다 (sample>=30, 양수 PnL, validation/costs/regime/overfit/factor 전부 PASS).

다음: 사용자 승인 시 라이브 승격 진행."""
httpx.post("https://discord.com/api/v10/channels/1517589871383019701/messages",
    headers={"Authorization":"Bot "+TOKEN}, data={"content":content}, timeout=15)
PYEOF
    echo "$(date): GATE PASS 알림 전송 ($VERDICT)"
  fi
else
  echo "$(date): gate=$VERDICT PASS=$PASS_COUNT FAIL=$FAIL_COUNT (변경 시에만 알림)"
fi
