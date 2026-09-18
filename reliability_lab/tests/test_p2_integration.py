"""Tests for Phase P2: Connect ChaosProxy to Member 1 Tool Boundary.

Tests P2-T01 through P2-T10.
"""

from reliability_lab.contracts import ChaosConfig, FailureMode
from reliability_lab.chaos.proxy import ChaosProxy
from reliability_lab.mocks.mock_tool import get_order, get_inventory


def test_p2_t01_run_id_correlated_throughout_execution():
    """P2-T01: run_id remains correlated throughout controlled execution."""
    from reliability_lab.adapters.member1_adapter import MockMember1Agent

    proxy = ChaosProxy(get_order)
    agent = MockMember1Agent(order_tool=proxy)

    custom_run_id = "run-canonical-8271"
    result = agent.run("Where is order #8271?", run_id=custom_run_id)

    assert result.run_id == custom_run_id
    # Every event in the execution trace must carry the same run_id
    assert len(result.events) > 0
    for event in result.events:
        assert event["run_id"] == custom_run_id


def test_p2_t02_failure_mode_metadata_available_for_evidence():
    """P2-T02: failure_mode metadata is available for evidence/replay."""
    from reliability_lab.adapters.member1_adapter import MockMember1Agent
    from reliability_lab.evidence.recorder import EvidenceRecorder
    from reliability_lab.mocks.mock_storage import MockStorage

    storage = MockStorage()
    recorder = EvidenceRecorder(storage=storage)

    cfg = ChaosConfig(failure_mode=FailureMode.TIMEOUT)
    proxy = ChaosProxy(get_order, config=cfg)
    agent = MockMember1Agent(version="v1.0.0-failing", order_tool=proxy)

    run_id = "run-evidence-002"
    result = agent.run("Where is order #8271?", run_id=run_id)

    record = recorder.record_execution(run_id=run_id, config=cfg, result=result)

    assert record.run_id == run_id
    assert record.failure_mode == FailureMode.TIMEOUT.value
    assert record.config.failure_mode == FailureMode.TIMEOUT
    assert storage.get(run_id) == record


def test_p2_t03_timeout_appears_as_ordinary_tool_telemetry():
    """P2-T03: timeout appears as ordinary tool failure telemetry."""
    from reliability_lab.adapters.member1_adapter import MockMember1Agent

    cfg = ChaosConfig(failure_mode=FailureMode.TIMEOUT)
    proxy = ChaosProxy(get_order, config=cfg)
    agent = MockMember1Agent(version="v1.0.0-failing", order_tool=proxy)

    result = agent.run("Where is order #8271?", run_id="run-telemetry-003")

    # Error must appear as standard tool error in events and errors list
    assert result.outcome == "FAILED"
    assert len(result.errors) > 0
    assert any("timeout" in err.lower() for err in result.errors)

    tool_error_events = [e for e in result.events if e.get("type") == "tool_call_error"]
    assert len(tool_error_events) > 0
    assert "timeout" in tool_error_events[0]["error"].lower()


def test_p2_t04_chaos_proxy_contains_no_detector_hooks():
    """P2-T04: ChaosProxy contains no detector-specific hooks."""
    proxy_methods = dir(ChaosProxy)
    forbidden_terms = ["detector", "detect", "incident", "rca", "bedrock", "telemetry"]

    for method in proxy_methods:
        for term in forbidden_terms:
            assert term not in method.lower(), f"ChaosProxy must not contain detector hook: {method}"


def test_p2_t05_member1_tool_boundary_uses_chaos_proxy():
    """P2-T05: Member 1 agent/tool boundary can use ChaosProxy."""
    from reliability_lab.adapters.member1_adapter import MockMember1Agent

    proxy = ChaosProxy(get_order)
    agent = MockMember1Agent(order_tool=proxy)

    assert agent.order_tool == proxy
    result = agent.run("Where is order #8271?")
    assert result.outcome == "SUCCESS"
    assert result.response["status"] == "IN_TRANSIT"


def test_p2_t06_canonical_order_lookup_deterministic_timeout():
    """P2-T06: canonical order lookup deterministically receives timeout."""
    from reliability_lab.adapters.member1_adapter import MockMember1Agent

    cfg = ChaosConfig(failure_mode=FailureMode.TIMEOUT, target_tool="get_order")
    proxy = ChaosProxy(get_order, config=cfg)
    agent = MockMember1Agent(version="v1.0.0-failing", order_tool=proxy)

    # 3 repeated runs must all deterministically fail with timeout
    for i in range(3):
        result = agent.run("Where is order #8271?", run_id=f"run-timeout-canon-{i}")
        assert result.outcome == "FAILED"
        assert any("timeout" in err.lower() for err in result.errors)


def test_p2_t07_failing_agent_exposes_retry_behavior():
    """P2-T07: Member 1 failing agent can expose retry behavior without Member 3 implementing retries."""
    from reliability_lab.adapters.member1_adapter import MockMember1Agent

    cfg = ChaosConfig(failure_mode=FailureMode.TIMEOUT)
    proxy = ChaosProxy(get_order, config=cfg)
    failing_agent = MockMember1Agent(version="v1.0.0-failing", order_tool=proxy)

    result = failing_agent.run("Where is order #8271?", run_id="run-retry-007")

    # Member 1's failing agent retries up to 5 times
    tool_calls = [e for e in result.events if e.get("type") == "tool_call_start"]
    assert len(tool_calls) == 5, f"Failing agent was expected to retry 5 times, got {len(tool_calls)}"
    assert result.outcome == "FAILED"


def test_p2_t08_controlled_wrong_tool_uses_normal_execution_path():
    """P2-T08: controlled wrong-tool scenario uses normal execution path."""
    from reliability_lab.adapters.member1_adapter import MockMember1Agent

    cfg = ChaosConfig(failure_mode=FailureMode.WRONG_TOOL)
    proxy = ChaosProxy(get_order, config=cfg, wrong_tool_target=get_inventory)
    agent = MockMember1Agent(version="v1.0.0-failing", order_tool=proxy)

    result = agent.run("Where is order #8271?", run_id="run-wrongtool-008")

    # Telemetry should record the tool call through the normal path
    assert len(result.events) > 0
    tool_success = [e for e in result.events if e.get("type") == "tool_call_success"]
    assert len(tool_success) == 1
    # Returns inventory schema instead of order schema
    assert "inventory_id" in tool_success[0]["data"]


def test_p2_t09_same_scenario_succeeds_when_chaos_normal():
    """P2-T09: same scenario succeeds when chaos=normal."""
    from reliability_lab.adapters.member1_adapter import MockMember1Agent

    # First run in timeout chaos
    proxy = ChaosProxy(get_order, config=ChaosConfig(failure_mode=FailureMode.TIMEOUT))
    agent = MockMember1Agent(version="v1.0.0-failing", order_tool=proxy)
    fail_result = agent.run("Where is order #8271?")
    assert fail_result.outcome == "FAILED"

    # Reset proxy to NORMAL
    proxy.reset()
    success_result = agent.run("Where is order #8271?")
    assert success_result.outcome == "SUCCESS"
    assert success_result.response["order_id"] == "8271"
    assert success_result.response["status"] == "IN_TRANSIT"


def test_p2_t10_run_id_and_chaos_config_evidence_retained():
    """P2-T10: run_id + ChaosConfig evidence can be retained."""
    from reliability_lab.adapters.member1_adapter import MockMember1Agent
    from reliability_lab.evidence.recorder import EvidenceRecorder
    from reliability_lab.mocks.mock_storage import MockStorage

    storage = MockStorage()
    recorder = EvidenceRecorder(storage=storage)

    cfg = ChaosConfig(failure_mode=FailureMode.TIMEOUT, error_message="Demo Timeout")
    proxy = ChaosProxy(get_order, config=cfg)
    agent = MockMember1Agent(version="v1.0.0-failing", order_tool=proxy)

    run_id = "run-retained-010"
    result = agent.run("Where is order #8271?", run_id=run_id)

    record = recorder.record_execution(run_id=run_id, config=cfg, result=result)

    # Verify retrieval from storage
    retrieved = storage.get(run_id)
    assert retrieved is not None
    assert retrieved.run_id == run_id
    assert retrieved.config.error_message == "Demo Timeout"
    assert retrieved.result.outcome == "FAILED"
    assert len(storage.list()) == 1
