"""Configuration for tan-live-agent.

All knobs are env-overridable so the same package runs locally and on the VPS
without code edits. Live state is only ever READ (shadow), never written.
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path


def _env(name: str, default: str) -> str:
    return os.getenv(name, default)


@dataclass(frozen=True)
class Settings:
    # --- Backend selection ---
    model_backend: str = field(default_factory=lambda: _env("TAN_AGENT_MODEL_BACKEND", "gemini").lower())

    # Gemini
    gemini_api_key: str = field(default_factory=lambda: _env("GEMINI_API_KEY", ""))
    gemini_model: str = field(default_factory=lambda: _env("TAN_AGENT_GEMINI_MODEL", "gemini-2.5-flash"))

    # GLM (Z.AI / Zhipu)
    glm_api_key: str = field(default_factory=lambda: _env("GLM_API_KEY", _env("ZAI_API_KEY", "")))
    glm_model: str = field(default_factory=lambda: _env("TAN_AGENT_GLM_MODEL", _env("YALRU_GLM_MODEL", "glm-5.2")))
    glm_endpoint: str = field(default_factory=lambda: _env("TAN_AGENT_GLM_ENDPOINT", "https://open.bigmodel.cn/api/paas/v4/chat/completions"))

    # GPT (Codex subscription) — activates 6/25
    gpt_model: str = field(default_factory=lambda: _env("TAN_AGENT_GPT_MODEL", "gpt-5.5"))

    # --- LLM behavior ---
    advisor_temperature: float = field(default_factory=lambda: float(_env("TAN_AGENT_TEMPERATURE", "0.2")))
    advisor_max_tokens: int = field(default_factory=lambda: int(_env("TAN_AGENT_MAX_TOKENS", "1024")))
    advisor_timeout_s: float = field(default_factory=lambda: float(_env("TAN_AGENT_TIMEOUT_S", "30")))
    thinking_budget: int = field(default_factory=lambda: int(_env("TAN_AGENT_THINKING_BUDGET", "512")))

    # --- Live state (READ-ONLY shadow reads) ---
    positions_json_path: str = field(default_factory=lambda: _env("TAN_AGENT_POSITIONS_JSON", "/srv/hermes-os/tan/true_turtle_exact/true_turtle_bot_positions.json"))
    state_json_path: str = field(default_factory=lambda: _env("TAN_AGENT_STATE_JSON", "/srv/hermes-os/tan/true_turtle_exact/true_turtle_bot_state.json"))

    # --- Journal ---
    journal_path: str = field(default_factory=lambda: _env("TAN_AGENT_JOURNAL", "/srv/hermes-os/tan-live-agent/data/advisor_journal.sqlite3"))

    # --- Discord (optional) ---
    discord_webhook_url: str = field(default_factory=lambda: _env("TAN_AGENT_DISCORD_WEBHOOK", ""))
    discord_min_confidence: float = field(default_factory=lambda: float(_env("TAN_AGENT_DISCORD_MIN_CONF", "0.6")))
    discord_bot_token: str = field(default_factory=lambda: _env("DISCORD_BOT_TOKEN", ""))
    discord_watchdog_channel_id: str = field(default_factory=lambda: _env("TAN_WATCHDOG_DISCORD_CHANNEL_ID", ""))
    discord_paper_channel_id: str = field(default_factory=lambda: _env("TAN_PAPER_DISCORD_CHANNEL_ID", ""))

    # --- Safety ---
    paper_mode: bool = True  # Always True. This package is paper/shadow only.

    @property
    def is_vps(self) -> bool:
        return Path("/srv/hermes-os").exists()


def load() -> Settings:
    return Settings()
