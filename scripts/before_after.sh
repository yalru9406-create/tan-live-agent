#!/bin/bash
# tan-live-agent/scripts/before_after.sh
# 손실심볼 exclude 적용(2026-06-21 23:13 KST = 14:13 UTC) 전후 라이브 PnL 비교.
# tan.db trades의 entry_ts 기준. 디스코드에 주간 요약으로도 활용.
set -u
set -a; . /root/.hermes/secrets/consolidated.env; set +a

RESULT=$(/srv/hermes-os/tan-live-agent/.venv/bin/python - <<'PYEOF'
import sqlite3, json
# CUTOFF: 2026-06-21 14:13 UTC = exclude 적용 시점
import datetime
cutoff_dt = datetime.datetime(2026, 6, 21, 14, 13, 0, tzinfo=datetime.timezone.utc)
CUTOFF_MS = int(cutoff_dt.timestamp() * 1000)

db = sqlite3.connect("file:/srv/hermes-os/tan/data/tan.db?mode=ro", uri=True)
db.row_factory = sqlite3.Row

def stats(rows, label):
    filled = [r for r in rows if r["pnl_usd"] is not None]
    n = len(filled)
    s = round(sum(r["pnl_usd"] for r in filled), 2) if filled else 0
    avg = round(s/n, 2) if n else 0
    return f"{label}: {len(rows)}건(filled {n}), PnL ${s} (avg ${avg})"

all_rows = list(db.execute("SELECT * FROM trades"))
before = [r for r in all_rows if r["entry_ts"] < CUTOFF_MS]
after = [r for r in all_rows if r["entry_ts"] >= CUTOFF_MS]

# after에서 exclude 심볼이 실제로 안 들어왔는지 확인
EXCLUDE = {"BTCUSDT", "WLDUSDT", "SUIUSDT", "SOLUSDT", "ETHUSDT", "1000PEPEUSDT"}
def norm(sym):
    return str(sym or "").replace("/", "").replace(":USDT", "").upper()
after_excluded_leak = [r["symbol"] for r in after if any(e in norm(r["symbol"]) for e in EXCLUDE)]

print(json.dumps({
    "cutoff_utc": cutoff_dt.isoformat(),
    "before": {"total": len(before), "filled": len([r for r in before if r["pnl_usd"] is not None]),
               "pnl": round(sum(r["pnl_usd"] for r in before if r["pnl_usd"] is not None), 2)},
    "after": {"total": len(after), "filled": len([r for r in after if r["pnl_usd"] is not None]),
              "pnl": round(sum(r["pnl_usd"] for r in after if r["pnl_usd"] is not None), 2)},
    "after_excluded_leak": after_excluded_leak,
}, ensure_ascii=False))
PYEOF
)

echo "$RESULT" | /srv/hermes-os/tan-live-agent/.venv/bin/python -c "
import sys, json, os, httpx
d = json.loads(sys.stdin.read())
b = d['before']; a = d['after']
content = f\"\"\"📊 **손실심볼 exclude before/after** (적용: {d['cutoff_utc']})

• **적용 전**: {b['filled']}건, PnL \${b['pnl']}
• **적용 후**: {a['filled']}건, PnL \${a['pnl']}
• exclude 심볼 누수: {len(d['after_excluded_leak'])}건 {d['after_excluded_leak'][:3]}

💡 적용 후 데이터가 쌓이면(며칠) exclude 효과 수치로 증명\"\"\"
TOKEN = os.environ['DISCORD_BOT_TOKEN']
r = httpx.post('https://discord.com/api/v10/channels/1517589871383019701/messages',
    headers={'Authorization':'Bot '+TOKEN}, data={'content':content}, timeout=15)
print('before/after report:', r.status_code)
"
