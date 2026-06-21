"""Model backend abstraction.

Default today: Gemini 2.5 Flash (verified working).
Switch paths:
  - GLM 5.2  : set TAN_AGENT_MODEL_BACKEND=glm  (after Z.AI/Zhipu credit recharge)
  - GPT-5.5  : set TAN_AGENT_MODEL_BACKEND=gpt  (after 6/25 Codex token refill)

Every advisor call MUST return a structured AdvisorDecision. On any error or
non-JSON response, we fail CLOSED (decision=reject, confidence=0.0) so that
capital preservation wins and the live bot is never silently green-lit.
"""
from __future__ import annotations

import abc
import json
import re
from dataclasses import dataclass
from typing import Any

import httpx

from .config import Settings


@dataclass
class AdvisorDecision:
    decision: str            # "approve" | "reject" | "modify"
    confidence: float        # 0.0..1.0
    rationale: str
    params: dict[str, Any] | None = None
    raw_text: str = ""
    model: str = ""
    latency_ms: int = 0

    @property
    def ok(self) -> bool:
        return (
            self.decision in {"approve", "reject", "modify"}
            and 0.0 <= self.confidence <= 1.0
        )


class ModelError(Exception):
    pass


def _parse_json_lenient(text: str) -> dict | None:
    text = (text or "").strip()
    if not text:
        return None
    if text.startswith("```"):
        text = re.sub(r"^```[a-zA-Z]*\n?", "", text)
        text = re.sub(r"\n?```$", "", text).strip()
    try:
        return json.loads(text)
    except Exception:
        pass
    m = re.search(r"\{.*\}", text, re.DOTALL)
    if m:
        try:
            return json.loads(m.group(0))
        except Exception:
            return None
    return None


class ModelBackend(abc.ABC):
    name: str = "abstract"

    def __init__(self, settings: Settings):
        self.settings = settings

    @abc.abstractmethod
    def _complete(self, system: str, user: str, max_tokens: int) -> tuple[str, int]:
        """Return (text, latency_ms)."""

    def decide(self, system: str, user: str, *, expect_json: bool = True, max_tokens: int | None = None) -> AdvisorDecision:
        max_tokens = max_tokens or self.settings.advisor_max_tokens
        text, latency = self._complete(system, user, max_tokens)
        if not expect_json:
            return AdvisorDecision(
                decision="approve", confidence=1.0, rationale=text,
                raw_text=text, model=self.name, latency_ms=latency,
            )
        data = _parse_json_lenient(text)
        if data is None:
            return AdvisorDecision(
                decision="reject", confidence=0.0,
                rationale=f"LLM returned non-JSON; failing closed. Head: {text[:200]!r}",
                raw_text=text, model=self.name, latency_ms=latency,
            )
        try:
            conf = float(data.get("confidence", 0.0))
        except (TypeError, ValueError):
            conf = 0.0
        conf = max(0.0, min(1.0, conf))
        return AdvisorDecision(
            decision=str(data.get("decision", "reject")).lower().strip(),
            confidence=conf,
            rationale=str(data.get("rationale", ""))[:2000],
            params=data.get("params"),
            raw_text=text,
            model=self.name,
            latency_ms=latency,
        )


class GeminiBackend(ModelBackend):
    name = "gemini-2.5-flash"

    def _complete(self, system, user, max_tokens):
        if not self.settings.gemini_api_key:
            raise ModelError("GEMINI_API_KEY is not set")
        url = (
            "https://generativelanguage.googleapis.com/v1beta/models/"
            f"{self.settings.gemini_model}:generateContent?key={self.settings.gemini_api_key}"
        )
        body = {
            "systemInstruction": {"parts": [{"text": system}]},
            "contents": [{"role": "user", "parts": [{"text": user}]}],
            "generationConfig": {
                "temperature": self.settings.advisor_temperature,
                "maxOutputTokens": max_tokens,
                "thinkingConfig": {"thinkingBudget": self.settings.thinking_budget},
                "responseMimeType": "application/json",
            },
        }
        with httpx.Client(timeout=self.settings.advisor_timeout_s) as c:
            r = c.post(url, json=body)
            latency = int(r.elapsed.total_seconds() * 1000)
            if r.status_code != 200:
                raise ModelError(f"Gemini HTTP {r.status_code}: {r.text[:300]}")
            data = r.json()
        try:
            text = data["candidates"][0]["content"]["parts"][0]["text"]
        except (KeyError, IndexError):
            raise ModelError(f"Gemini empty response: {json.dumps(data)[:300]}")
        self.name = data.get("modelVersion", self.settings.gemini_model)
        return text, latency


class GlmBackend(ModelBackend):
    name = "glm-5.2"

    def _complete(self, system, user, max_tokens):
        if not self.settings.glm_api_key:
            raise ModelError("GLM_API_KEY is not set")
        url = self.settings.glm_endpoint
        body = {
            "model": self.settings.glm_model,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            "temperature": self.settings.advisor_temperature,
            "max_tokens": max_tokens,
            "response_format": {"type": "json_object"},
        }
        headers = {
            "Authorization": f"Bearer {self.settings.glm_api_key}",
            "Content-Type": "application/json",
        }
        with httpx.Client(timeout=self.settings.advisor_timeout_s) as c:
            r = c.post(url, json=body, headers=headers)
            latency = int(r.elapsed.total_seconds() * 1000)
            if r.status_code != 200:
                raise ModelError(f"GLM HTTP {r.status_code}: {r.text[:300]}")
            data = r.json()
        try:
            text = data["choices"][0]["message"]["content"]
        except (KeyError, IndexError):
            raise ModelError(f"GLM empty response: {json.dumps(data)[:300]}")
        self.name = self.settings.glm_model
        return text, latency


class GptBackend(ModelBackend):
    """GPT-5.5 backend via Codex subscription. Activates on/after 6/25.

    Until then this raises so accidental selection fails loudly instead of
    silently routing to a different provider.
    """
    name = "gpt-5.5"

    def _complete(self, system, user, max_tokens):
        raise ModelError(
            "GPT-5.5 backend not active until 6/25 (Codex token refill). "
            "Set TAN_AGENT_MODEL_BACKEND=gemini (now) or =glm (after Z.AI recharge)."
        )


_BACKENDS: dict[str, type[ModelBackend]] = {
    "gemini": GeminiBackend,
    "glm": GlmBackend,
    "gpt": GptBackend,
    "gpt-5.5": GptBackend,
    "gpt5.5": GptBackend,
}


def get_backend(settings: Settings | None = None) -> ModelBackend:
    settings = settings or Settings()
    name = settings.model_backend.lower()
    cls = _BACKENDS.get(name)
    if cls is None:
        raise ModelError(f"Unknown backend {name!r}. Available: {sorted(_BACKENDS)}")
    return cls(settings)
