"""Final Hardening Tests for Member 3 Reliability Lab (Phase P10).

Tests P10-T01 through P10-T14 verifying correctness, repeatability, integration,
and live judge demonstration continuity.
"""

from dataclasses import fields, is_dataclass
import json
import pytest

from reliability_lab.adapters.member1_adapter import MockMember1Agent
from reliability_lab.chaos.proxy import ChaosProxy
from reliability_lab.chaos.service import ChaosService, reset_chaos
from reliability_lab.contracts import (
    ChaosConfig,
    EvaluationPair,
    ExpectedBehavior,
    FailureMode,
    RegressionResult,
    RegressionTest,
    ReplayRecord,
)
from reliability_lab.demo import demo_reset, run_canonical_demo_flow
from reliability_lab.evaluation.evaluator import (
    BeforeAfterEvaluator,
    build_before_after_panel,
)
from reliability_lab.fixtures.replay_fixtures import (
    CANONICAL_TIMEOUT_FIXTURE,
    EMPTY_RESULT_FIXTURE,
    NORMAL_FIXTURE,
    RATE_LIMIT_FIXTURE,
    SLOW_RESPONSE_FIXTURE,
    WRONG_TOOL_FIXTURE,
)
from reliability_lab.mocks.mock_storage import MockStorage
from reliability_lab.mocks.mock_tool import get_inventory, get_order
from reliability_lab.regression.service import RegressionLibrary
from reliability_lab.replay.engine import ReplayEngine


def test_p10_t01_normal_run_succeeds():
    """P10-T01: normal run succeeds.

    Prompt: 'Where is order #8271?' + Chaos: normal -> normal lookup succeeds.
    """
    demo_reset()
    order_data = get_order("8271")
    assert order_data["order_id"] == "8271"
    assert order_data["status"] == "IN_TRANSIT"

    agent = MockMember1Agent(version="v1.0.0-failing")
    telemetry = agent.run("Where is order #8271?", run_id="run-p10-normal")

    assert telemetry.outcome == "SUCCESS"
    assert len(telemetry.tool_calls) == 1
    assert len(telemetry.errors) == 0
    assert telemetry.response is not None
    assert telemetry.response["order_id"] == "8271"


def test_p10_t02_timeout_injection_is_deterministic():
    """P10-T02: timeout injection is deterministic across repeated calls."""
    chaos = ChaosService()
    proxy = chaos.get_proxy("get_order")
    proxy.set_config(
        ChaosConfig(
            failure_mode=FailureMode.TIMEOUT,
            target_tool="get_order",
            error_message="Controlled timeout: carrier service unreachable",
        )
    )

    try:
        for _ in range(5):
            with pytest.raises(Exception) as exc_info:
                proxy.execute("8271")
            assert "timeout" in str(exc_info.value).lower()
    finally:
        proxy.reset()


def test_p10_t03_timeout_travels_through_correct_evidence_path():
    """P10-T03: timeout travels through correct evidence path without internal leaks."""
    chaos = ChaosService()
    proxy = chaos.get_proxy("get_order")
    proxy.set_config(ChaosConfig(failure_mode=FailureMode.TIMEOUT, target_tool="get_order"))

    try:
        agent = MockMember1Agent(version="v1.0.0-failing", order_tool=proxy)
        telemetry = agent.run("Where is order #8271?", run_id="run-p10-evidence")

        assert telemetry.outcome == "FAILED"
        assert len(telemetry.errors) > 0
        assert any("timeout" in err.lower() for err in telemetry.errors)

        # Appears as standard tool error in events
        tool_error_events = [e for e in telemetry.events if e.get("type") == "tool_call_error"]
        assert len(tool_error_events) > 0
        assert "timeout" in str(tool_error_events[0]["error"]).lower()
    finally:
        proxy.reset()


def test_p10_t04_replay_record_is_complete():
    """P10-T04: ReplayRecord contains every mandatory field."""
    record = ReplayRecord(
        run_id="run-p10-mandatory",
        prompt="Where is order #8271?",
        agent_version="v1.0.0-failing",
        prompt_version="p1.0",
        failure_mode=FailureMode.TIMEOUT,
        tool_calls=[{"tool": "get_order", "args": {"order_id": "8271"}}],
        mocked_responses=CANONICAL_TIMEOUT_FIXTURE.mocked_responses,
        expected_behavior="Must fallback gracefully",
        original_incident_id="inc-p10-001",
    )

    assert is_dataclass(record)
    field_names = {f.name for f in fields(record)}
    mandatory = {
        "run_id", "prompt", "agent_version", "prompt_version",
        "failure_mode", "tool_calls", "mocked_responses",
        "expected_behavior", "original_incident_id", "created_at"
    }
    assert mandatory.issubset(field_names)
    assert record.created_at is not None


def test_p10_t05_replay_creates_fresh_run_id():
    """P10-T05: replay creates fresh run_id."""
    store = MockStorage()
    engine = ReplayEngine(storage=store)

    record = ReplayRecord(
        run_id="run-original-anchor",
        prompt="Where is order #8271?",
        agent_version="v1.0.0-failing",
        prompt_version="p1.0",
        failure_mode=FailureMode.TIMEOUT,
        tool_calls=[{"tool": "get_order", "args": {"order_id": "8271"}}],
        mocked_responses=CANONICAL_TIMEOUT_FIXTURE.mocked_responses,
        expected_behavior="Must fallback gracefully",
        original_incident_id="inc-p10-anchor",
    )

    res1 = engine.replay(record, agent_version_override="v1.0.1-fixed")
    res2 = engine.replay(record, agent_version_override="v1.0.1-fixed")

    assert res1.replay_run_id != record.run_id
    assert res2.replay_run_id != record.run_id
    assert res1.replay_run_id != res2.replay_run_id


def test_p10_t06_original_incident_linkage_survives():
    """P10-T06: original incident linkage survives replay and evaluation."""
    store = MockStorage()
    engine = ReplayEngine(storage=store)

    record = ReplayRecord(
        run_id="run-orig-p10-link",
        prompt="Where is order #8271?",
        agent_version="v1.0.0-failing",
        prompt_version="p1.0",
        failure_mode=FailureMode.TIMEOUT,
        tool_calls=[{"tool": "get_order", "args": {"order_id": "8271"}}],
        mocked_responses=CANONICAL_TIMEOUT_FIXTURE.mocked_responses,
        expected_behavior="Must fallback gracefully",
        original_incident_id="inc-p10-preservation-001",
    )

    res = engine.replay(record, agent_version_override="v1.0.1-fixed")

    assert res.original_run_id == "run-orig-p10-link"
    assert res.original_incident_id == "inc-p10-preservation-001"


def test_p10_t07_before_after_contains_real_values_only():
    """P10-T07: before/after contains real values only (zero metric fabrication)."""
    eval_pair = EvaluationPair(
        before_run_id="run-b-01",
        after_run_id="run-a-02",
        before_metrics={"tool_calls": 5, "tokens": 450, "latency_ms": 1500, "outcome": "FAILED"},
        after_metrics={"tool_calls": 3, "tokens": 320, "latency_ms": 950, "outcome": "FALLBACK"},
        task_result="PASS",
        regression_result="PASS",
    )

    panel = build_before_after_panel(eval_pair)

    assert panel["tool_calls"]["before"] == 5
    assert panel["tool_calls"]["after"] == 3
    assert panel["tool_calls"]["delta"] == -2
    assert panel["tool_calls"]["pct_change"] == -40.0

    assert panel["tokens"]["before"] == 450
    assert panel["tokens"]["after"] == 320
    assert panel["tokens"]["delta"] == -130

    assert panel["latency_ms"]["before"] == 1500
    assert panel["latency_ms"]["after"] == 950
    assert panel["latency_ms"]["delta"] == -550

    assert panel["task_result"] == "PASS"
    assert panel["regression_result"] == "PASS"


def test_p10_t08_incident_can_be_saved_as_regression():
    """P10-T08: incident can be saved as regression test."""
    store = MockStorage()
    lib = RegressionLibrary(storage=store)

    test = lib.save_test({
        "test_id": "reg-p10-incident-test",
        "scenario": "Timeout on order lookup",
        "expected_behavior": "Must fallback within max 2 retries",
    })

    assert isinstance(test, RegressionTest)
    assert test.test_id == "reg-p10-incident-test"
    assert lib.get_test(test.test_id) == test


def test_p10_t09_fixed_scenario_passes_saved_regression():
    """P10-T09: fixed scenario passes saved regression."""
    store = MockStorage()
    lib = RegressionLibrary(storage=store)

    test = lib.save_test({
        "test_id": "reg-p10-pass-check",
        "scenario": "Order carrier timeout handling",
        "expected_behavior": "FALLBACK",
    })

    result = lib.run_test(test.test_id, agent_version="v1.0.1-fixed")

    assert result.status == "PASS"
    assert result.measured_evidence["outcome"] == "FALLBACK"
    assert result.measured_evidence["tool_calls"] == 3


def test_p10_t10_regression_history_updates():
    """P10-T10: regression history updates without destroying prior history."""
    store = MockStorage()
    lib = RegressionLibrary(storage=store)

    test = lib.save_test({
        "test_id": "reg-p10-history-check",
        "scenario": "Order carrier timeout handling",
        "expected_behavior": "FALLBACK",
    })

    assert len(test.history) == 0

    lib.run_test(test.test_id, agent_version="v1.0.1-fixed")
    assert len(test.history) == 1

    lib.run_test(test.test_id, agent_version="v1.0.1-fixed")
    assert len(test.history) == 2


def test_p10_t11_chaos_can_reliably_reset_to_normal():
    """P10-T11: chaos can reliably reset to normal."""
    chaos = ChaosService()
    proxy = chaos.get_proxy("get_order")

    # Inject timeout
    proxy.set_config(ChaosConfig(failure_mode=FailureMode.TIMEOUT, target_tool="get_order"))
    with pytest.raises(Exception):
        proxy.execute("8271")

    # Reset via demo_reset
    status = demo_reset(chaos_service=chaos)
    assert status["status"] == "READY"
    assert status["chaos_mode"] == "normal"

    # Execution immediately succeeds
    result = proxy.execute("8271")
    assert result["order_id"] == "8271"
    assert result["status"] == "IN_TRANSIT"


def test_p10_t12_secondary_chaos_modes_pass_smoke_checks():
    """P10-T12: secondary chaos modes pass smoke checks."""
    chaos = ChaosService()
    proxy = chaos.get_proxy("get_order")

    # 1. Rate limit (429)
    proxy.set_config(RATE_LIMIT_FIXTURE.chaos_config)
    with pytest.raises(Exception) as exc:
        proxy.execute("8271")
    assert "rate limit" in str(exc.value).lower() or getattr(exc.value, "status_code", None) == 429

    # 2. Empty result
    proxy.set_config(EMPTY_RESULT_FIXTURE.chaos_config)
    assert proxy.execute("8271") == {}

    # 3. Slow response
    proxy.set_config(ChaosConfig(failure_mode=FailureMode.SLOW_RESPONSE, delay_ms=10))
    res_slow = proxy.execute("8271")
    assert res_slow["order_id"] == "8271"

    # 4. Wrong tool
    proxy.set_config(ChaosConfig(failure_mode=FailureMode.WRONG_TOOL, target_tool="get_inventory"))
    res_wrong = proxy.execute("8271")
    assert "inventory_id" in res_wrong

    # 5. Normal
    proxy.set_config(NORMAL_FIXTURE.chaos_config)
    res_normal = proxy.execute("8271")
    assert res_normal["order_id"] == "8271"

    proxy.reset()


def test_p10_t13_production_fault_injection_remains_impossible():
    """P10-T13: production fault injection remains impossible."""
    # 1. Unproxied tool functions cannot be intercepted
    assert not hasattr(get_inventory, "set_config")
    direct_order = get_order("8271")
    assert direct_order["order_id"] == "8271"

    # 2. Invalid failure mode is safely rejected
    proxy = ChaosProxy(get_order)
    with pytest.raises(ValueError):
        proxy.set_config(ChaosConfig(failure_mode="unsupported_invalid_mode"))


def test_p10_t14_scorecard_uses_test_counts_and_results_only():
    """P10-T14: scorecard uses test counts and results only."""
    store = MockStorage()
    lib = RegressionLibrary(storage=store)

    t1 = lib.save_test({"test_id": "reg-sc-1", "scenario": "Timeout test", "expected_behavior": "FALLBACK"})
    t2 = lib.save_test({"test_id": "reg-sc-2", "scenario": "Normal test", "expected_behavior": "SUCCESS"})

    lib.run_test(t1.test_id, agent_version="v1.0.1-fixed")
    lib.run_test(t2.test_id, agent_version="v1.0.1-fixed")

    scorecard = lib.get_scorecard()

    # Verify counts
    assert scorecard["total"] == 2
    assert scorecard["passed"] == 2
    assert scorecard["failed"] == 0
    assert scorecard["pass_rate_pct"] == 100.0
    assert "categories" in scorecard

    # Ensure no arbitrary AI scores exist
    for key in scorecard.keys():
        assert key not in ("ai_score", "reliability_index", "hallucination_rating")

    # Verify run_canonical_demo_flow continuity
    demo_flow = run_canonical_demo_flow(storage=store)
    assert demo_flow["status"] == "COMPLETED"
    assert demo_flow["flow_verified"] is True
    assert len(demo_flow["steps"]) == 8

    # Verify actual generated IDs are captured
    ids = demo_flow["actual_evidence_ids"]
    assert ids["original_run_id"].startswith("run-orig-failing-")
    assert ids["incident_id"].startswith("inc-timeout-")
    assert ids["replay_run_id"].startswith("run-replay-")
    assert ids["evaluation_id"].startswith("eval-")
    assert ids["regression_test_id"].startswith("reg-canonical-")
    assert ids["regression_result_status"] == "PASS"
