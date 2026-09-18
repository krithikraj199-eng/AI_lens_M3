"""Tests for Phase P3: ReplayRecord Data Foundation and Controlled Fixtures.

Tests P3-T01 through P3-T12.
"""

from reliability_lab.contracts import FailureMode, ChaosConfig, ReplayRecord
from reliability_lab.fixtures.compat_fixtures import TestRunFixture, TestIncidentFixture


def test_p3_t01_replay_record_created_from_completed_scenario():
    """P3-T01: ReplayRecord can be created from completed scenario."""
    from reliability_lab.replay.factory import create_replay_record_from_execution
    from reliability_lab.adapters.telemetry_adapter import AgentExecutionResult

    execution_result = AgentExecutionResult(
        run_id="run-scenario-101",
        agent_version="v1.0.0-failing",
        prompt_version="p1.0",
        request="Where is order #8271?",
        response=None,
        events=[{"type": "tool_call_start", "tool": "get_order"}],
        tool_calls=[{"tool": "get_order", "args": {"order_id": "8271"}}],
        tokens=350,
        latency_ms=1200,
        errors=["TimeoutError: carrier service unreachable"],
        outcome="FAILED",
    )
    cfg = ChaosConfig(failure_mode=FailureMode.TIMEOUT)

    record = create_replay_record_from_execution(
        result=execution_result,
        config=cfg,
        expected_behavior="Order lookup with fallback on timeout",
        original_incident_id="inc-101",
    )

    assert isinstance(record, ReplayRecord)
    assert record.run_id == "run-scenario-101"
    assert record.failure_mode == FailureMode.TIMEOUT.value


def test_p3_t02_prompt_is_preserved():
    """P3-T02: prompt is preserved."""
    from reliability_lab.replay.factory import create_replay_candidate_from_incident

    run = TestRunFixture(
        run_id="run-202",
        agent_version="v1.0.0",
        prompt_version="p1.0",
        request="Where is order #8271?",
    )
    incident = TestIncidentFixture(
        incident_id="inc-202",
        run_id="run-202",
        failure_type="TIMEOUT",
        severity="HIGH",
    )

    candidate = create_replay_candidate_from_incident(incident=incident, run=run)
    assert candidate.prompt == "Where is order #8271?"


def test_p3_t03_agent_version_and_prompt_version_are_preserved():
    """P3-T03: agent_version and prompt_version are preserved."""
    from reliability_lab.replay.factory import create_replay_candidate_from_incident

    run = TestRunFixture(
        run_id="run-303",
        agent_version="v2.1.0-rc2",
        prompt_version="p2.5-prod",
        request="Where is order #8271?",
    )
    incident = TestIncidentFixture(
        incident_id="inc-303",
        run_id="run-303",
        failure_type="RATE_LIMIT",
        severity="MEDIUM",
    )

    candidate = create_replay_candidate_from_incident(incident=incident, run=run)
    assert candidate.agent_version == "v2.1.0-rc2"
    assert candidate.prompt_version == "p2.5-prod"


def test_p3_t04_failure_mode_configuration_preserved():
    """P3-T04: failure_mode/configuration is preserved."""
    from reliability_lab.replay.factory import create_replay_candidate_from_incident

    run = TestRunFixture(
        run_id="run-404",
        agent_version="v1.0",
        prompt_version="p1.0",
        request="Where is order #8271?",
    )
    incident = TestIncidentFixture(
        incident_id="inc-404",
        run_id="run-404",
        failure_type="TOOL_TIMEOUT_LOOP",
        severity="HIGH",
    )

    candidate = create_replay_candidate_from_incident(incident=incident, run=run)
    assert candidate.failure_mode == FailureMode.TIMEOUT.value


def test_p3_t05_relevant_tool_call_sequence_preserved():
    """P3-T05: relevant tool call sequence is preserved."""
    from reliability_lab.replay.factory import create_replay_candidate_from_incident

    tool_calls = [
        {"tool": "get_order", "args": {"order_id": "8271"}},
        {"tool": "get_order", "args": {"order_id": "8271"}},
    ]
    run = TestRunFixture(
        run_id="run-505",
        agent_version="v1.0",
        prompt_version="p1.0",
        request="Where is order #8271?",
        tool_calls=tool_calls,
    )
    incident = TestIncidentFixture(
        incident_id="inc-505",
        run_id="run-505",
        failure_type="TIMEOUT",
        severity="HIGH",
    )

    candidate = create_replay_candidate_from_incident(incident=incident, run=run)
    assert candidate.tool_calls == tool_calls
    assert len(candidate.tool_calls) == 2


def test_p3_t06_required_controlled_mock_responses_preserved():
    """P3-T06: required controlled mock responses are preserved."""
    from reliability_lab.replay.factory import create_replay_candidate_from_incident

    mocked = {"get_order": {"status": "TIMEOUT", "error": "carrier service unreachable"}}
    run = TestRunFixture(
        run_id="run-606",
        agent_version="v1.0",
        prompt_version="p1.0",
        request="Where is order #8271?",
    )
    incident = TestIncidentFixture(
        incident_id="inc-606",
        run_id="run-606",
        failure_type="TIMEOUT",
        severity="HIGH",
        evidence={"mocked_responses": mocked},
    )

    candidate = create_replay_candidate_from_incident(incident=incident, run=run, mocked_responses=mocked)
    assert candidate.mocked_responses == mocked
    assert "get_order" in candidate.mocked_responses


def test_p3_t07_expected_behavior_preserved():
    """P3-T07: expected_behavior is preserved."""
    from reliability_lab.replay.factory import create_replay_candidate_from_incident

    run = TestRunFixture(
        run_id="run-707",
        agent_version="v1.0",
        prompt_version="p1.0",
        request="Where is order #8271?",
    )
    incident = TestIncidentFixture(
        incident_id="inc-707",
        run_id="run-707",
        failure_type="TIMEOUT",
        severity="HIGH",
        recommended_fix="Implement MAX_RETRIES=2 and fallback to delayed status message.",
    )

    candidate = create_replay_candidate_from_incident(incident=incident, run=run)
    assert candidate.expected_behavior == "Implement MAX_RETRIES=2 and fallback to delayed status message."


def test_p3_t08_original_incident_id_preserved():
    """P3-T08: original_incident_id is preserved."""
    from reliability_lab.replay.factory import create_replay_candidate_from_incident

    run = TestRunFixture(
        run_id="run-808",
        agent_version="v1.0",
        prompt_version="p1.0",
        request="Where is order #8271?",
    )
    incident = TestIncidentFixture(
        incident_id="inc-808-canonical",
        run_id="run-808",
        failure_type="TIMEOUT",
        severity="HIGH",
    )

    candidate = create_replay_candidate_from_incident(incident=incident, run=run)
    assert candidate.original_incident_id == "inc-808-canonical"


def test_p3_t09_positive_fixtures_compatible_with_pipeline():
    """P3-T09: positive fixtures are compatible with Member 2's intended pipeline."""
    from reliability_lab.fixtures.replay_fixtures import (
        CANONICAL_TIMEOUT_FIXTURE,
        RATE_LIMIT_FIXTURE,
        EMPTY_RESULT_FIXTURE,
        SLOW_RESPONSE_FIXTURE,
        WRONG_TOOL_FIXTURE,
        NORMAL_FIXTURE,
    )

    fixtures = [
        CANONICAL_TIMEOUT_FIXTURE,
        RATE_LIMIT_FIXTURE,
        EMPTY_RESULT_FIXTURE,
        SLOW_RESPONSE_FIXTURE,
        WRONG_TOOL_FIXTURE,
        NORMAL_FIXTURE,
    ]

    for fx in fixtures:
        assert isinstance(fx.prompt, str)
        assert len(fx.prompt) > 0
        assert isinstance(fx.agent_version, str)
        assert isinstance(fx.prompt_version, str)
        assert isinstance(fx.failure_mode, FailureMode)
        assert isinstance(fx.expected_behavior, str)
        assert isinstance(fx.mocked_responses, dict)


def test_p3_t10_normal_fixture_not_converted_to_failure():
    """P3-T10: normal fixture is not converted into failure by Member 3 logic."""
    from reliability_lab.fixtures.replay_fixtures import NORMAL_FIXTURE
    from reliability_lab.chaos.proxy import ChaosProxy
    from reliability_lab.mocks.mock_tool import get_order

    proxy = ChaosProxy(get_order, config=ChaosConfig(failure_mode=NORMAL_FIXTURE.failure_mode))
    result = proxy("8271")

    # Normal fixture must execute normally and NOT produce a failure
    assert result["status"] == "IN_TRANSIT"
    assert result["order_id"] == "8271"


def test_p3_t11_no_detector_implementation_inside_reliability_lab():
    """P3-T11: no detector implementation exists inside Reliability Lab."""
    import reliability_lab.replay.factory as factory
    import reliability_lab.chaos.proxy as proxy

    # Check factory and proxy module source or attributes
    forbidden_tokens = [
        "detect_loop",
        "detect_timeout",
        "detect_anomaly",
        "detector_engine",
        "bedrock_rca",
    ]
    for mod in [factory, proxy]:
        mod_contents = dir(mod)
        for token in forbidden_tokens:
            assert token not in mod_contents, f"Reliability Lab must not contain {token}"


def test_p3_t12_incident_to_replay_requires_no_manual_reconstruction():
    """P3-T12: Incident -> Replay candidate requires no manual reconstruction."""
    from reliability_lab.replay.factory import create_replay_candidate_from_incident

    run = TestRunFixture(
        run_id="run-auto-999",
        agent_version="v1.0.0-failing",
        prompt_version="p1.0",
        request="Where is order #8271?",
        tool_calls=[{"tool": "get_order", "args": {"order_id": "8271"}}],
    )
    incident = TestIncidentFixture(
        incident_id="inc-auto-999",
        run_id="run-auto-999",
        failure_type="TOOL_TIMEOUT_LOOP",
        severity="CRITICAL",
        recommended_fix="Limit retries to 2 and add fallback.",
    )

    # Single one-line automated conversion
    candidate = create_replay_candidate_from_incident(incident=incident, run=run)

    assert candidate.run_id == "run-auto-999"
    assert candidate.original_incident_id == "inc-auto-999"
    assert candidate.prompt == "Where is order #8271?"
    assert candidate.failure_mode == FailureMode.TIMEOUT.value
    assert len(candidate.tool_calls) == 1
    assert candidate.expected_behavior == "Limit retries to 2 and add fallback."
