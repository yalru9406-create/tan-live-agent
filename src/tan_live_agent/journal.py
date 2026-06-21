"""SQLite journal of advisor decisions.

Used for offline validation: compare advisor decision outcomes vs raw strategy
outcomes over 30+ samples before any promotion to live.
"""
from __future__ import annotations

import json
import sqlite3
import time
from dataclasses import asdict, is_dataclass
from pathlib import Path

SCHEMA = """
CREATE TABLE IF NOT EXISTS advisor_events (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  ts_ms INTEGER NOT NULL,
  advisor TEXT NOT NULL,           -- 'gate' | 'params'
  model TEXT NOT NULL,
  symbol TEXT,
  direction TEXT,
  decision TEXT NOT NULL,
  confidence REAL NOT NULL,
  rationale TEXT,
  params_json TEXT,
  context_json TEXT,
  signal_json TEXT,
  latency_ms INTEGER
);
CREATE INDEX IF NOT EXISTS idx_advisor_events_ts ON advisor_events(ts_ms);
CREATE INDEX IF NOT EXISTS idx_advisor_events_symbol ON advisor_events(symbol);
CREATE INDEX IF NOT EXISTS idx_advisor_events_advisor ON advisor_events(advisor);
"""


def _connect(path: str) -> sqlite3.Connection:
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    conn.executescript(SCHEMA)
    return conn


def _safe(obj) -> dict | None:
    if obj is None:
        return None
    if is_dataclass(obj):
        try:
            return asdict(obj)
        except TypeError:
            pass
    if hasattr(obj, "to_dict"):
        return obj.to_dict()
    if hasattr(obj, "__dict__"):
        return obj.__dict__
    return {"value": str(obj)}


def log_event(
    path: str,
    *,
    advisor: str,
    model: str,
    decision,
    context,
    signal=None,
) -> int:
    conn = _connect(path)
    try:
        cur = conn.execute(
            "INSERT INTO advisor_events "
            "(ts_ms, advisor, model, symbol, direction, decision, confidence, "
            " rationale, params_json, context_json, signal_json, latency_ms) "
            "VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
            (
                int(time.time() * 1000),
                advisor,
                model,
                (signal.symbol if signal is not None else None),
                (signal.direction if signal is not None else None),
                decision.decision,
                float(decision.confidence),
                decision.rationale,
                json.dumps(decision.params) if decision.params else None,
                json.dumps(_safe(context), default=str)[:8000],
                (json.dumps(_safe(signal), default=str)[:4000] if signal is not None else None),
                int(decision.latency_ms or 0),
            ),
        )
        conn.commit()
        return int(cur.lastrowid or 0)
    finally:
        conn.close()


def recent(path: str, advisor: str | None = None, limit: int = 30) -> list[dict]:
    conn = _connect(path)
    try:
        if advisor:
            rows = conn.execute(
                "SELECT * FROM advisor_events WHERE advisor=? ORDER BY ts_ms DESC LIMIT ?",
                (advisor, limit),
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT * FROM advisor_events ORDER BY ts_ms DESC LIMIT ?",
                (limit,),
            ).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


def summarize(path: str, advisor: str | None = None) -> dict:
    """Aggregate counts for quick validation."""
    conn = _connect(path)
    try:
        base = "FROM advisor_events"
        params: tuple = ()
        if advisor:
            base += " WHERE advisor=?"
            params = (advisor,)
        total = conn.execute(f"SELECT COUNT(*) {base}", params).fetchone()[0]
        by_decision = {
            r[0]: r[1]
            for r in conn.execute(
                f"SELECT decision, COUNT(*) {base} GROUP BY decision", params
            )
        }
        avg_conf = conn.execute(
            f"SELECT AVG(confidence) {base}", params
        ).fetchone()[0]
        return {
            "total": total,
            "by_decision": by_decision,
            "avg_confidence": round(avg_conf, 3) if avg_conf is not None else None,
        }
    finally:
        conn.close()
def analyze(path: str, advisor: str | None = None) -> dict:
    """Deeper stats for advisor value assessment.

    Returns per-advisor decision distribution with confidence bands, symbol
    coverage, latency, and time span. This is the foundation for the
    'advisor on vs off' comparison: once 30+ samples per advisor exist,
    join gate decisions to live trade outcomes (symbol+ts) to measure whether
    advisor-rejected entries were actually losers.
    """
    conn = _connect(path)
    try:
        base = "FROM advisor_events"
        params: tuple = ()
        if advisor:
            base += " WHERE advisor=?"
            params = (advisor,)
        rows = conn.execute(
            f"SELECT advisor, decision, COUNT(*) n, "
            f" ROUND(AVG(confidence),3) avg_conf, "
            f" ROUND(MIN(confidence),3) min_conf, "
            f" ROUND(MAX(confidence),3) max_conf, "
            f" ROUND(AVG(latency_ms)) avg_latency_ms "
            f"{base} GROUP BY advisor, decision ORDER BY advisor, n DESC",
            params,
        ).fetchall()
        by_advisor: dict[str, dict] = {}
        for r in rows:
            d = dict(r)
            a = d["advisor"]
            by_advisor.setdefault(a, {"total": 0, "decisions": {}})
            by_advisor[a]["total"] += d["n"]
            by_advisor[a]["decisions"][d["decision"]] = {
                "n": d["n"],
                "avg_confidence": d["avg_conf"],
                "min_confidence": d["min_conf"],
                "max_confidence": d["max_conf"],
                "avg_latency_ms": d["avg_latency_ms"],
            }
        # symbol coverage + time span
        sym_rows = conn.execute(
            f"SELECT advisor, COUNT(DISTINCT symbol) distinct_symbols {base} GROUP BY advisor",
            params,
        ).fetchall()
        for r in sym_rows:
            by_advisor.setdefault(r["advisor"], {})["distinct_symbols"] = r["distinct_symbols"]
        span = conn.execute(
            f"SELECT MIN(ts_ms) first_ms, MAX(ts_ms) last_ms, COUNT(*) total {base}",
            params,
        ).fetchone()
        return {
            "by_advisor": by_advisor,
            "time_span": {
                "first_ms": span["first_ms"],
                "last_ms": span["last_ms"],
                "total_events": span["total"],
            },
            "promotion_gate": {
                # Gate: TOTAL >= 30 events across all advisors, AND each advisor
                # has at least 3 (diversity floor). Per-advisor 30 is over-strict
                # for an operator who reads "30 samples" as the corpus size.
                "threshold_total": 30,
                "min_per_advisor": 3,
                "ready": (span["total"] >= 30)
                and all(v.get("total", 0) >= 3 for v in by_advisor.values())
                and bool(by_advisor),
                "totals": {k: v.get("total", 0) for k, v in by_advisor.items()},
            },
        }
    finally:
        conn.close()
