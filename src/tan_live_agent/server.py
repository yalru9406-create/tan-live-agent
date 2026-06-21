"""HTTP advisor service for paper-engine integration (stage 2 infra).

The paper engine lives in a separate venv (/srv/hermes-os/paper/.venv) and
must not cross-import tan-live-agent. Instead it calls this tiny localhost
HTTP service:

    POST /gate   {symbol,direction,entry_price,stop_price,take_profit_price,r_multiple}
                 -> {decision,confidence,rationale,params,model}
    POST /params {}
                 -> {decision,confidence,rationale,params}
    GET  /health -> {status:"ok"}

Run:  tan-live-agent serve [--host 127.0.0.1] [--port 8090]
Systemd unit mounts this behind a timer-free always-on service when stage 2
is promoted (after the 30-sample gate). Until then it is optional infra.
"""
from __future__ import annotations

import json
import os
import socketserver
import threading
from http.server import BaseHTTPRequestHandler

from . import context as ctx_mod, gate, params, journal
from .config import Settings
from .models import get_backend, ModelError


_GATE_REQUIRED = ("symbol", "direction", "entry_price", "stop_price", "take_profit_price", "r_multiple")


def _build_settings() -> Settings:
    return Settings()


class AdvisorHandler(BaseHTTPRequestHandler):
    settings: Settings = _build_settings()

    def _send_json(self, code: int, obj: dict) -> None:
        body = json.dumps(obj, ensure_ascii=False, default=str).encode("utf-8")
        self.send_response(code)
        self.send_header("content-type", "application/json; charset=utf-8")
        self.send_header("content-length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _read_body(self) -> dict:
        length = int(self.headers.get("content-length", "0") or "0")
        raw = self.rfile.read(length) if length > 0 else b"{}"
        try:
            return json.loads(raw) if raw else {}
        except json.JSONDecodeError:
            return {}

    def do_GET(self):  # noqa: N802
        if self.path == "/health":
            self._send_json(200, {"status": "ok", "backend": self.settings.model_backend})
        else:
            self._send_json(404, {"error": "unknown path"})

    def do_POST(self):  # noqa: N802
        payload = self._read_body()
        if self.path == "/gate":
            self._handle_gate(payload)
        elif self.path == "/params":
            self._handle_params(payload)
        else:
            self._send_json(404, {"error": "unknown path"})

    def _handle_gate(self, payload: dict) -> None:
        missing = [k for k in _GATE_REQUIRED if k not in payload]
        if missing:
            self._send_json(400, {"error": "missing fields", "missing": missing})
            return
        try:
            sig = gate.EntrySignal(
                symbol=str(payload["symbol"]),
                direction=str(payload["direction"]),
                entry_price=float(payload["entry_price"]),
                stop_price=float(payload["stop_price"]),
                take_profit_price=float(payload["take_profit_price"]),
                r_multiple=float(payload["r_multiple"]),
                reward_to_cost=payload.get("reward_to_cost"),
            )
            ctx = ctx_mod.collect(self.settings.positions_json_path, self.settings.state_json_path)
            backend = get_backend(self.settings)
            d = gate.evaluate(sig, ctx, backend)
            journal.log_event(
                self.settings.journal_path,
                advisor="gate", model=backend.name,
                decision=d, context=ctx, signal=sig,
            )
            self._send_json(200, {
                "decision": d.decision,
                "confidence": d.confidence,
                "rationale": d.rationale,
                "params": d.params,
                "model": d.model,
                "latency_ms": d.latency_ms,
            })
        except ModelError as e:
            self._send_json(502, {"error": str(e)})
        except Exception as e:  # pragma: no cover - defensive
            self._send_json(500, {"error": f"{type(e).__name__}: {e}"})

    def _handle_params(self, payload: dict) -> None:
        try:
            ctx = ctx_mod.collect(self.settings.positions_json_path, self.settings.state_json_path)
            backend = get_backend(self.settings)
            d = params.suggest(ctx, backend)
            journal.log_event(
                self.settings.journal_path,
                advisor="params", model=backend.name,
                decision=d, context=ctx,
            )
            self._send_json(200, {
                "decision": d.decision,
                "confidence": d.confidence,
                "rationale": d.rationale,
                "params": d.params,
                "model": d.model,
                "latency_ms": d.latency_ms,
            })
        except ModelError as e:
            self._send_json(502, {"error": str(e)})
        except Exception as e:  # pragma: no cover - defensive
            self._send_json(500, {"error": f"{type(e).__name__}: {e}"})

    def log_message(self, *args):  # silence default stderr spam
        pass


class _ThreadingServer(socketserver.ThreadingTCPServer):
    allow_reuse_address = True
    daemon_threads = True


def serve(host: str = "127.0.0.1", port: int = 8090) -> None:
    # Refresh settings at serve time so env overrides applied post-import take effect.
    AdvisorHandler.settings = _build_settings()
    with _ThreadingServer((host, port), AdvisorHandler) as srv:
        print(f"tan-live-agent advisor serving on http://{host}:{port} (backend={AdvisorHandler.settings.model_backend})", flush=True)
        srv.serve_forever()
