"""Tests for Phase P5: Controlled Replay Engine.

Tests P5-T01 through P5-T10.
"""

from reliability_lab.contracts import ReplayRecord, FailureMode
from reliability_lab.mocks.mock_storage import MockStorage


def test_p5_t01_stored_replay_record_executes_successfully():
    """P5-T01: stored ReplayRecord executes successfully."""
    from reliability_lab.replay.engine import ReplayEngine

    storage = MockStorage()
    record = ReplayRecord(
        run_id="run-original-001",
        prompt="Where is order #8271?",
        agent_version="v1.0.0-failing",
        prompt_version="p1.0",
        failure_mode=FailureMode.TIMEOUT.value,
        tool_calls=[{"tool": "get_order", "args": {"order_id": "8271"}}],
        mocked_responses={"get_order": {"status": "TIMEOUT", "error": "TimeoutError"}},
        expected_behavior="Order lookup should fallback on timeout",
        original_incident_id="inc-001",
    )
    storage.save(record.run_id, record)

    engine = ReplayEngine(storage=storage)
    result = engine.replay(record)

    assert result is not None
    assert result.original_run_id == "run-original-001"
    assert result.failure_mode == "timeout"
    assert result.telemetry.outcome == "FAILED"


def test_p5_t02_replay_generates_fresh_run_id():
    """P5-T02: replay generates fresh run_id."""
    from reliability_lab.replay.engine import ReplayEngine

    storage = MockStorage()
    record = ReplayRecord(
        run_id="run-original-002",
        prompt="Where is order #8271?",
        agent_version="v1.0.0-failing",
        prompt_version="p1.0",
        failure_mode=FailureMode.TIMEOUT.value,
        tool_calls=[],
        mocked_responses={},
        expected_behavior="Fallback on timeout",
    )

    engine = ReplayEngine(storage=storage)
    result = engine.replay(record)

    # Strictly must not reuse original run_id
    assert result.replay_run_id != "run-original-002"
    assert result.replay_run_id.startswith("run-replay-")
    assert result.telemetry.run_id == result.replay_run_id


def test_p5_t03_original_incident_and_run_linkage_preserved():
    """P5-T03: original incident/run linkage remains available."""
    from reliability_lab.replay.engine import ReplayEngine

    storage = MockStorage()
    record = ReplayRecord(
        run_id="run-orig-link-003",
        prompt="Where is order #8271?",
        agent_version="v1.0.0-failing",
        prompt_version="p1.0",
        failure_mode=FailureMode.TIMEOUT.value,
        tool_calls=[],
        mocked_responses={},
        expected_behavior="Fallback on timeout",
        original_incident_id="inc-link-003",
    )

    engine = ReplayEngine(storage=storage)
    result = engine.replay(record)

    assert result.original_run_id == "run-orig-link-003"
    assert result.original_incident_id == "inc-link-003"


def test_p5_t04_stored_timeout_condition_is_reapplied():
    """P5-T04: stored timeout condition is reapplied."""
    from reliability_lab.replay.engine import ReplayEngine

    storage = MockStorage()
    record = ReplayRecord(
        run_id="run-timeout-004",
        prompt="Where is order #8271?",
        agent_version="v1.0.0-failing",
        prompt_version="p1.0",
        failure_mode=FailureMode.TIMEOUT.value,
        tool_calls=[{"tool": "get_order", "args": {"order_id": "8271"}}],
        mocked_responses={"get_order": {"status": "TIMEOUT"}},
        expected_behavior="Fallback on timeout",
    )

    engine = ReplayEngine(storage=storage)
    result = engine.replay(record)

    # Timeout must have occurred during replay
    assert any("timeout" in err.lower() for err in result.telemetry.errors)
    assert result.telemetry.outcome == "FAILED"


def test_p5_t05_required_controlled_mock_responses_reused():
    """P5-T05: required controlled mock responses are reused."""
    from reliability_lab.replay.engine import ReplayEngine

    storage = MockStorage()
    mock_resp = {"get_order": {"status": "RATE_LIMIT", "status_code": 429, "error": "Too Many Requests"}}
    record = ReplayRecord(
        run_id="run-429-005",
        prompt="Where is order #8271?",
        agent_version="v1.0.0-failing",
        prompt_version="p1.0",
        failure_mode=FailureMode.RATE_LIMIT.value,
        tool_calls=[{"tool": "get_order", "args": {"order_id": "8271"}}],
        mocked_responses=mock_resp,
        expected_behavior="Apply backoff",
    )

    engine = ReplayEngine(storage=storage)
    result = engine.replay(record)

    assert result.failure_mode == "rate_limit"
    assert any("429" in err or "rate limit" in err.lower() for err in result.telemetry.errors)


def test_p5_t06_prompt_version_context_reconstructed():
    """P5-T06: prompt/version context is reconstructed."""
    from reliability_lab.replay.engine import ReplayEngine

    storage = MockStorage()
    record = ReplayRecord(
        run_id="run-ctx-006",
        prompt="Where is order #8271?",
        agent_version="v1.0.0-failing",
        prompt_version="p1.0-test",
        failure_mode=FailureMode.TIMEOUT.value,
        tool_calls=[],
        mocked_responses={},
        expected_behavior="Fallback on timeout",
    )

    engine = ReplayEngine(storage=storage)
    result = engine.replay(record)

    assert result.telemetry.request == "Where is order #8271?"
    assert result.agent_version == "v1.0.0-failing"
    assert result.prompt_version == "p1.0-test"


def test_p5_t07_repeated_replay_reproduces_intended_controlled_condition():
    """P5-T07: repeated replay reproduces intended controlled condition."""
    from reliability_lab.replay.engine import ReplayEngine

    storage = MockStorage()
    record = ReplayRecord(
        run_id="run-repeat-007",
        prompt="Where is order #8271?",
        agent_version="v1.0.0-failing",
        prompt_version="p1.0",
        failure_mode=FailureMode.TIMEOUT.value,
        tool_calls=[],
        mocked_responses={},
        expected_behavior="Fallback on timeout",
    )

    engine = ReplayEngine(storage=storage)
    res1 = engine.replay(record)
    res2 = engine.replay(record)

    # Both replays must reproduce the timeout outcome
    assert res1.telemetry.outcome == "FAILED"
    assert res2.telemetry.outcome == "FAILED"

    # Both replays must have unique fresh run IDs
    assert res1.replay_run_id != res2.replay_run_id
    assert res1.replay_run_id != record.run_id
    assert res2.replay_run_id != record.run_id


def test_p5_t08_no_dependency_assumes_production_state_identical():
    """P5-T08: no dependency assumes production external state is identical."""
    from reliability_lab.replay.engine import ReplayEngine

    storage = MockStorage()
    # Record has its own isolated prompt and failure mode
    record = ReplayRecord(
        run_id="run-isolated-008",
        prompt="Where is order #8271?",
        agent_version="v1.0.0-failing",
        prompt_version="p1.0",
        failure_mode=FailureMode.NORMAL.value,
        tool_calls=[],
        mocked_responses={},
        expected_behavior="Immediate order status",
    )

    engine = ReplayEngine(storage=storage)
    result = engine.replay(record)

    # Executes completely self-contained in-memory without external calls
    assert result.telemetry.outcome == "SUCCESS"
    assert result.telemetry.response is not None
    assert result.telemetry.response["order_id"] == "8271"


def test_p5_t09_replay_goes_through_normal_execution_telemetry_path():
    """P5-T09: replay goes through normal execution/telemetry path."""
    from reliability_lab.replay.engine import ReplayEngine

    storage = MockStorage()
    record = ReplayRecord(
        run_id="run-path-009",
        prompt="Where is order #8271?",
        agent_version="v1.0.0-failing",
        prompt_version="p1.0",
        failure_mode=FailureMode.TIMEOUT.value,
        tool_calls=[],
        mocked_responses={},
        expected_behavior="Fallback on timeout",
    )

    engine = ReplayEngine(storage=storage)
    result = engine.replay(record)

    # Must contain real execution telemetry generated by ExecutionTracer
    assert len(result.telemetry.events) > 0
    assert result.telemetry.latency_ms >= 0
    assert result.telemetry.tokens > 0
    assert len(result.telemetry.tool_calls) == 5  # Failing agent retried 5 times


def test_p5_t10_original_run_id_replay_id_evidence_persistable():
    """P5-T10: original run ID + replay ID + replay evidence are persistable."""
    from reliability_lab.replay.engine import ReplayEngine, execute_replay

    storage = MockStorage()
    record = ReplayRecord(
        run_id="run-persist-010",
        prompt="Where is order #8271?",
        agent_version="v1.0.0-failing",
        prompt_version="p1.0",
        failure_mode=FailureMode.TIMEOUT.value,
        tool_calls=[],
        mocked_responses={},
        expected_behavior="Fallback on timeout",
        original_incident_id="inc-persist-010",
    )
    storage.save(record.run_id, record)

    # Execute via Member 4 callable
    output = execute_replay(record.run_id, storage=storage)

    assert output["status"] == "REPLAYED"
    assert output["original_run_id"] == "run-persist-010"
    assert output["original_incident_id"] == "inc-persist-010"
    assert "replay_run_id" in output
    assert "measured_telemetry" in output

    # Confirm replay result was persisted to storage
    replay_key = f"replay-res-{output['replay_run_id']}"
    assert storage.get(replay_key) is not None
