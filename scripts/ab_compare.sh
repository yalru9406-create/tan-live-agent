#!/bin/bash
# tan-live-agent/scripts/ab_compare.sh
# paper A/B 비교: advisor ON (paper/data) vs OFF (paper-baseline/data).
# 주간 cron. 데이터 축적 후 advisor 효과 수치 증명.
set -u
set -a; . /root/.hermes/secrets/consolidated.env; set +a

/srv/hermes-os/tan-live-agent/.venv/bin/python - <<'PYEOF'
import json, os, httpx

def stats(path):
    lines = 0
    closed = 0
    pnl = 0.0
    wins = 0
    try:
        for line in open(path):
            lines += 1
            try:
                t = json.loads(line)
                if t.get("exit_reason"):
                    closed += 1
                v = t.get("realized_pnl_usd") or t.get("pnl_usd") or t.get("realized_pnl")
                if isinstance(v, (int, float)):
                    pnl += v
                    if v > 0 and t.get("exit_reason"):
                        wins += 1
            except Exception:
                pass
    except FileNotFoundError:
        pass
    winrate = round(100 * wins / closed, 1) if closed else 0
    return {"lines": lines, "closed": closed, "pnl": round(pnl, 2), "wins": wins, "winrate": winrate}

ON = stats("/srv/hermes-os/paper/data/paper_trades.jsonl")
OFF = stats("/srv/hermes-os/paper-baseline/data/paper_trades.jsonl")
diff = round(ON["pnl"] - OFF["pnl"], 2)

content = f"""🧪 **paper A/B 비교 (advisor 효과 측정)**

• **advisor ON (실험군)**: {ON['closed']} closed / {ON['lines']} lines, PnL ${ON['pnl']}, 승률 {ON['winrate']}%
• **advisor OFF (대조군)**: {OFF['closed']} closed / {OFF['lines']} lines, PnL ${OFF['pnl']}, 승률 {OFF['winrate']}%

• **PnL 차이**: ${diff} ({'advisor가 +' if diff>0 else 'advisor가' if diff<0 else '동일'} {abs(diff)})

💡 충분한 데이터(각 30+ closed) 쌓이면 advisor 효과 통계적 증명 가능."""

r = httpx.post("https://discord.com/api/v10/channels/1517589871383019701/messages",
    headers={"Authorization": "Bot " + os.environ["DISCORD_BOT_TOKEN"]},
    data={"content": content}, timeout=15)
print("ab_compare:", r.status_code)
PYEOF
