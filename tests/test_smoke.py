"""Smoke tests — importable without network or secrets."""


def test_package_imports():
    import tan_live_agent
    from tan_live_agent import config, models, context, gate, params, journal, cli
    assert tan_live_agent.__version__
    assert config.Settings
    assert models.get_backend
    assert context.MarketContext
    assert gate.evaluate
    assert params.suggest
    assert journal.log_event
    assert cli.main


def test_json_lenient_parsing():
    from tan_live_agent.models import _parse_json_lenient
    assert _parse_json_lenient('{"decision":"approve"}') == {"decision": "approve"}
    assert _parse_json_lenient('```json\n{"decision":"reject"}\n```') == {"decision": "reject"}
    assert _parse_json_lenient('noise {"a":1} trailing') == {"a": 1}
    assert _parse_json_lenient("not json at all") is None
    assert _parse_json_lenient("") is None


def test_decision_ok_validation():
    from tan_live_agent.models import AdvisorDecision
    assert AdvisorDecision(decision="approve", confidence=0.8, rationale="x").ok
    assert not AdvisorDecision(decision="approve", confidence=1.5, rationale="x").ok
    assert not AdvisorDecision(decision="bogus", confidence=0.5, rationale="x").ok


def test_context_prompt_block_handles_empty():
    from tan_live_agent.context import MarketContext
    c = MarketContext(
        ts_ms=0, btc_price=100.0, btc_change_24h_pct=1.0, btc_rsi_4h=55.0,
        fear_greed=50, fear_greed_label="Neutral", open_positions=[],
        live_strategy_version="test",
    )
    s = c.to_prompt_block()
    assert "BTC" in s
    assert "no open positions" in s
