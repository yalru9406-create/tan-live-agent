"""tan-live-agent: LLM advisor layer for TAN trading.

Runs in paper/shadow mode. NEVER touches live orders or live services.

L1 = entry gate advisor  (approve / reject / modify a proposed entry)
L2 = parameter advisor   (suggest TP R / trail buffer / thresholds for paper testing)

Backends (switchable via TAN_AGENT_MODEL_BACKEND):
  - gemini  (default; works today as Gemini 2.5 Flash)
  - glm     (GLM 5.2; activate after Z.AI/Zhipu credit recharge)
  - gpt     (GPT-5.5 via Codex; activate on/after 6/25 token refill)
"""

__version__ = "0.1.0"
