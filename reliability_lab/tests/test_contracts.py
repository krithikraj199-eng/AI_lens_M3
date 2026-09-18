"""Tests for Member 3 Reliability Lab contracts.

Tests P0-T01 through P0-T06.
"""

from dataclasses import is_dataclass, fields


def test_p0_t01_chaos_config_representation():
    """P0-T01: ChaosConfig correctly represents its required configuration.

    Supports failure modes: normal, timeout, rate_limit, empty_result, slow_response, wrong_tool.
    """
    from reliability_lab.contracts import ChaosConfig, FailureMode

    # 1. Default normal configuration
    cfg_normal = ChaosConfig()
    assert cfg_normal.failure_mode == FailureMode.NORMAL
    assert cfg_normal.delay_ms == 0
    assert cfg_normal.error_message is None
    assert cfg_normal.status_code == 200

    # 2. Timeout failure mode
    cfg_timeout = ChaosConfig(failure_mode=FailureMode.TIMEOUT, target_tool="get_order")
    assert cfg_timeout.failure_mode == FailureMode.TIMEOUT
    assert cfg_timeout.target_tool == "get_order"

    # 3. Rate limit / 429 failure mode
    cfg_rate_limit = ChaosConfig(
        failure_mode=FailureMode.RATE_LIMIT,
        status_code=429,
        error_message="Too Many Requests"
    )
    assert cfg_rate_limit.failure_mode == FailureMode.RATE_LIMIT
    assert cfg_rate_limit.status_code == 429
    assert cfg_rate_limit.error_message == "Too Many Requests"

    # 4. Empty result failure mode
    cfg_empty = ChaosConfig(failure_mode=FailureMode.EMPTY_RESULT)
    assert cfg_empty.failure_mode == FailureMode.EMPTY_RESULT

    # 5. Slow response failure mode
    cfg_slow = ChaosConfig(failure_mode=FailureMode.SLOW_RESPONSE, delay_ms=3000)
    assert cfg_slow.failure_mode == FailureMode.SLOW_RESPONSE
    assert cfg_slow.delay_ms == 3000

    # 6. Wrong tool failure mode
    cfg_wrong = ChaosConfig(failure_mode=FailureMode.WRONG_TOOL)
    assert cfg_wrong.failure_mode == FailureMode.WRONG_TOOL

    # 7. Check string value compatibility of FailureMode
    assert FailureMode.NORMAL.value == "normal"
    assert FailureMode.TIMEOUT.value == "timeout"
    assert FailureMode.RATE_LIMIT.value == "rate_limit"
    assert FailureMode.EMPTY_RESULT.value == "empty_result"
    assert FailureMode.SLOW_RESPONSE.value == "slow_response"
    assert FailureMode.WRONG_TOOL.value == "wrong_tool"


def test_p0_t02_replay_record_mandatory_fields():
    """P0-T02: ReplayRecord contains every mandatory field:

    run_id, prompt, agent_version, prompt_version, failure_mode,
    tool_calls, mocked_responses, expected_behavior, original_incident_id.
    """
    from reliability_lab.contracts import ReplayRecord, FailureMode

    record = ReplayRecord(
        run_id="run-original-001",
        prompt="Where is order #8271?",
        agent_version="v1.0.0",
        prompt_version="p1.0",
        failure_mode=FailureMode.TIMEOUT,
        tool_calls=[{"tool": "get_order", "args": {"order_id": "8271"}}],
        mocked_responses={"get_order": {"error": "TimeoutError"}},
        expected_behavior="Order status returned with max 2 retries or fallback",
        original_incident_id="inc-999",
    )

    assert record.run_id == "run-original-001"
    assert record.prompt == "Where is order #8271?"
    assert record.agent_version == "v1.0.0"
    assert record.prompt_version == "p1.0"
    assert record.failure_mode == FailureMode.TIMEOUT
    assert len(record.tool_calls) == 1
    assert record.mocked_responses == {"get_order": {"error": "TimeoutError"}}
    assert record.expected_behavior == "Order status returned with max 2 retries or fallback"
    assert record.original_incident_id == "inc-999"
    assert hasattr(record, "created_at")
    assert record.created_at is not None

    # Verify dataclass introspection
    assert is_dataclass(record)
    field_names = {f.name for f in fields(record)}
    mandatory_fields = {
        "run_id",
        "prompt",
        "agent_version",
        "prompt_version",
        "failure_mode",
        "tool_calls",
        "mocked_responses",
        "expected_behavior",
        "original_incident_id",
    }
    assert mandatory_fields.issubset(field_names)


def test_p0_t03_evaluation_pair_structure():
    """P0-T03: EvaluationPair supports before and after run IDs and actual metric/result structures."""
    from reliability_lab.contracts import EvaluationPair

    before_metrics = {
        "tool_calls": 5,
        "tokens": 1250,
        "latency_ms": 12500,
        "errors": ["TimeoutError: Connection timed out"] * 4,
    }
    after_metrics = {
        "tool_calls": 2,
        "tokens": 420,
        "latency_ms": 2100,
        "errors": ["TimeoutError: Connection timed out"],
    }

    eval_pair = EvaluationPair(
        before_run_id="run-before-001",
        after_run_id="run-after-002",
        before_metrics=before_metrics,
        after_metrics=after_metrics,
        task_result="RESOLVED",
        regression_result="PASS",
    )

    assert eval_pair.before_run_id == "run-before-001"
    assert eval_pair.after_run_id == "run-after-002"
    assert eval_pair.before_metrics == before_metrics
    assert eval_pair.after_metrics == after_metrics
    assert eval_pair.task_result == "RESOLVED"
    assert eval_pair.regression_result == "PASS"
    assert hasattr(eval_pair, "evaluated_at")
    assert eval_pair.evaluated_at is not None

    # Check that before and after run IDs are distinctly different (replay generates new run_id)
    assert eval_pair.before_run_id != eval_pair.after_run_id


def test_p0_t04_regression_test_structure():
    """P0-T04: RegressionTest contains test_id, scenario, expected_behavior, latest_result, history."""
    from reliability_lab.contracts import RegressionTest, RegressionResult

    reg_result = RegressionResult(
        test_id="reg-001",
        run_id="run-replay-002",
        status="PASS",
        measured_evidence={"retries": 1, "status": "fallback_invoked", "latency_ms": 2100},
    )

    reg_test = RegressionTest(
        test_id="reg-001",
        scenario="get_order timeout with retry limit",
        expected_behavior="Must not exceed 2 retries and should invoke fallback gracefully",
        latest_result=reg_result,
        history=[reg_result],
    )

    assert reg_test.test_id == "reg-001"
    assert reg_test.scenario == "get_order timeout with retry limit"
    assert reg_test.expected_behavior == "Must not exceed 2 retries and should invoke fallback gracefully"
    assert reg_test.latest_result == reg_result
    assert len(reg_test.history) == 1
    assert reg_test.history[0].status == "PASS"
    assert hasattr(reg_test, "created_at")

    field_names = {f.name for f in fields(reg_test)}
    assert {"test_id", "scenario", "expected_behavior", "latest_result", "history"}.issubset(field_names)


def test_p0_t05_regression_result_structure():
    """P0-T05: RegressionResult contains test_id, run_id, PASS/FAIL, measured_evidence, timestamp/history entry."""
    from reliability_lab.contracts import RegressionResult

    evidence = {
        "tool_calls": 2,
        "tokens": 420,
        "latency_ms": 2100,
        "errors": ["TimeoutError"],
        "fallback_triggered": True,
    }

    result = RegressionResult(
        test_id="reg-test-8271",
        run_id="run-replay-002",
        status="PASS",
        measured_evidence=evidence,
    )

    assert result.test_id == "reg-test-8271"
    assert result.run_id == "run-replay-002"
    assert result.status == "PASS"
    assert result.measured_evidence == evidence
    assert hasattr(result, "timestamp")
    assert result.timestamp is not None

    field_names = {f.name for f in fields(result)}
    assert {"test_id", "run_id", "status", "measured_evidence", "timestamp"}.issubset(field_names)


def test_p0_t06_no_second_production_run_or_incident_schema():
    """P0-T06: No second production Run or Incident schema is created.

    Verify that reliability_lab.contracts does not export competing Run or Incident schemas.
    Verify that compatibility fixtures in reliability_lab.fixtures.compat_fixtures
    are clearly labeled test-only fixtures conforming to the shared contracts.
    """
    import reliability_lab.contracts as contracts
    from reliability_lab.fixtures.compat_fixtures import TestRunFixture, TestIncidentFixture

    # 1. Verify contracts module does NOT define or export a production Run or Incident class
    assert not hasattr(contracts, "Run"), "contracts.py must not create a competing production Run class"
    assert not hasattr(contracts, "Incident"), "contracts.py must not create a competing production Incident class"

    # 2. Verify compatibility fixtures conform to the agreed shared schema
    run_fixture = TestRunFixture(
        run_id="run-test-001",
        agent_version="v1.0.0",
        prompt_version="p1.0",
        request="Where is order #8271?",
        events=[{"type": "tool_call", "name": "get_order"}],
        tool_calls=[{"tool": "get_order", "args": {"order_id": "8271"}}],
        tokens=350,
        latency_ms=1800,
        errors=[],
        outcome="SUCCESS",
        detected_failures=[],
    )
    run_fields = {f.name for f in fields(run_fixture)}
    expected_run_fields = {
        "run_id", "agent_version", "prompt_version", "request", "events",
        "tool_calls", "tokens", "latency_ms", "errors", "outcome", "detected_failures"
    }
    assert expected_run_fields.issubset(run_fields)

    incident_fixture = TestIncidentFixture(
        incident_id="inc-test-001",
        run_id="run-test-001",
        failure_type="TOOL_TIMEOUT_LOOP",
        severity="HIGH",
        evidence={"retries": 5, "last_error": "TimeoutError"},
        rca_status="ANALYZED",
        recommended_fix="Implement MAX_RETRIES=2 and exponential backoff or fallback.",
    )
    inc_fields = {f.name for f in fields(incident_fixture)}
    expected_inc_fields = {
        "incident_id", "run_id", "failure_type", "severity", "evidence",
        "rca_status", "recommended_fix"
    }
    assert expected_inc_fields.issubset(inc_fields)
