"""Market context collector for the advisor.

Read-only by design. Sources:
  - Binance USDT-M public futures API (price, 24h change, RSI proxy)
  - alternative.me Fear & Greed index
  - Live bot's positions.json + state.json (SHADOW READ ONLY — we never write)

If a source is unreachable, we degrade gracefully (None) rather than crash,
so the advisor still runs with partial context and fails closed if needed.
"""
from __future__ import annotations

import json
import time
from dataclasses import dataclass, asdict
from pathlib import Path

import httpx


@dataclass
class MarketContext:
    ts_ms: int
    btc_price: float
    btc_change_24h_pct: float
    btc_rsi_4h: float | None
    fear_greed: int | None
    fear_greed_label: str | None
    open_positions: list[dict]
    live_strategy_version: str | None
    notes: str = ""

    def to_prompt_block(self) -> str:
        pos_lines = []
        for p in self.open_positions:
            side = "LONG" if (p.get("side") or 0) > 0 else "SHORT"
            entry = p.get("entry_price") or p.get("last_add")
            pos_lines.append(
                f"  - {p.get('symbol')} {side} entry={entry} "
                f"trail_stop={p.get('trail_stop')} TP={p.get('take_profit_price')} "
                f"status={p.get('protection_status')}"
            )
        positions_str = "\n".join(pos_lines) if pos_lines else "  (no open positions)"
        rsi = f"{self.btc_rsi_4h}" if self.btc_rsi_4h is not None else "n/a"
        fg = f"{self.fear_greed} ({self.fear_greed_label})" if self.fear_greed is not None else "n/a"
        return (
            f"[MarketContext ts={self.ts_ms}]\n"
            f"BTC: ${self.btc_price:,.2f}  24h: {self.btc_change_24h_pct:+.2f}%  4h RSI~{rsi}\n"
            f"Fear&Greed: {fg}\n"
            f"Live strategy: {self.live_strategy_version or 'unknown'}\n"
            f"Open positions (shadow read, READ-ONLY):\n{positions_str}\n"
            f"Notes: {self.notes or 'none'}"
        )

    def to_dict(self) -> dict:
        return asdict(self)


def _binance_24h(symbol: str = "BTCUSDT") -> tuple[float, float]:
    r = httpx.get(f"https://fapi.binance.com/fapi/v1/ticker/24hr?symbol={symbol}", timeout=10)
    r.raise_for_status()
    d = r.json()
    return float(d["lastPrice"]), float(d["priceChangePercent"])


def _binance_rsi(symbol: str = "BTCUSDT", interval: str = "4h", period: int = 14) -> float | None:
    try:
        r = httpx.get(
            f"https://fapi.binance.com/fapi/v1/klines?symbol={symbol}&interval={interval}&limit={period + 2}",
            timeout=10,
        )
        r.raise_for_status()
        closes = [float(k[4]) for k in r.json()]
        if len(closes) < period + 1:
            return None
        gains, losses = [], []
        for i in range(1, len(closes)):
            ch = closes[i] - closes[i - 1]
            gains.append(max(0.0, ch))
            losses.append(max(0.0, -ch))
        avg_gain = sum(gains[-period:]) / period
        avg_loss = sum(losses[-period:]) / period
        if avg_loss == 0:
            return 100.0
        rs = avg_gain / avg_loss
        return round(100 - (100 / (1 + rs)), 1)
    except Exception:
        return None


def _fear_greed() -> tuple[int | None, str | None]:
    try:
        r = httpx.get("https://api.alternative.me/fng/?limit=1", timeout=8)
        r.raise_for_status()
        d = r.json()["data"][0]
        return int(d["value"]), d.get("value_classification")
    except Exception:
        return None, None


def _read_shadow_positions(positions_path: str, state_path: str) -> tuple[list[dict], str | None]:
    positions: list[dict] = []
    strat: str | None = None
    try:
        p = Path(positions_path)
        if p.exists():
            raw = json.loads(p.read_text(encoding="utf-8"))
            positions = list(raw.values()) if isinstance(raw, dict) else list(raw)
    except Exception:
        pass
    try:
        s = Path(state_path)
        if s.exists():
            st = json.loads(s.read_text(encoding="utf-8"))
            strat = (st.get("settings") or {}).get("strategy_version")
    except Exception:
        pass
    return positions, strat


def collect(positions_json_path: str, state_json_path: str) -> MarketContext:
    price, change = _binance_24h("BTCUSDT")
    rsi = _binance_rsi("BTCUSDT", "4h", 14)
    fg, fg_label = _fear_greed()
    positions, strat = _read_shadow_positions(positions_json_path, state_json_path)
    notes_parts = []
    if abs(change) > 8.0:
        notes_parts.append(f"BTC extreme 24h move ({change:+.1f}%)")
    return MarketContext(
        ts_ms=int(time.time() * 1000),
        btc_price=price,
        btc_change_24h_pct=change,
        btc_rsi_4h=rsi,
        fear_greed=fg,
        fear_greed_label=fg_label,
        open_positions=positions,
        live_strategy_version=strat,
        notes="; ".join(notes_parts),
    )
