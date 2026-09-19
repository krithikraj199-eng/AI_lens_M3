"""Tests for Phase P8: Core Reliability Lab Integration & Truthful Outputs.

Tests P8-T01 through P8-T11.
"""

from dataclasses import is_dataclass
import json

from reliability_lab.adapters.member1_adapter import MockMember1Agent
from reliability_lab.benchmark.runner import (
    RepeatabilityBenchmark,
    serialize_benchmark_report,
)
from reliability_lab.chaos.service import ChaosService
from reliability_lab.contracts import (
    ChaosConfig,
    EvaluationPair,
    FailureMode,
    RegressionResult,
    RegressionTest,
    ReplayRecord,
)
from reliability_lab.evaluation.evaluator import (
    BeforeAfterEvaluator,
    build_before_after_panel,
    execute_evaluation,
)
from reliability_lab.evidence.bundle import (
    EvidenceBundle,
    build_canonical_evidence_bundle,
    serialize_evidence_bundle,
)
from reliability_lab.fixtures.replay_fixtures import CANONICAL_TIMEOUT_FIXTURE
from reliability_lab.mocks.mock_storage import MockStorage
from reliability_lab.regression.service import (
    RegressionLibrary,
    _serialize_regression_test,
)
from reliability_lab.replay.engine import ReplayEngine
from reliability_lab.timeline import (
    ReplayTimeline,
    TimelineEvent,
    build_replay_timeline,
    serialize_replay_timeline,
)


def test_p8_t01_timeline_events_ordered_correctly():
    """P8-T01: timeline events are ordered correctly.

    Conceptual order: user -> agent -> tool -> response/error -> retry/fallback -> agent_end.
    Timestamps must be non-decreasing, and step numbers must be sequentially ordered.
    """
    store = MockStorage()
    engine = ReplayEngine(storage=store)

    record = ReplayRecord(
        run_id="run-orig-p8-01",
        prompt="Where is order #8271?",
        agent_version="v1.0.0-failing",
        prompt_version="p1.0",
        failure_mode=FailureMode.TIMEOUT,
        tool_calls=[{"tool": "get_order", "args": {"order_id": "8271"}}],
        mocked_responses=CANONICAL_TIMEOUT_FIXTURE.mocked_responses,
        expected_behavior=CANONICAL_TIMEOUT_FIXTURE.expected_behavior,
        original_incident_id="inc-p8-01",
    )

    # Replay with fixed agent produces bounded retries and fallback
    replay_res = engine.replay(record, agent_version_override="v1.0.1-fixed")
    timeline = build_replay_timeline(replay_res)

    assert isinstance(timeline, ReplayTimeline)
    assert timeline.total_events >= 6
    assert len(timeline.events) == timeline.total_events

    # Verify sequential step numbers and non-decreasing timestamps
    for i in range(len(timeline.events)):
        assert timeline.events[i].step_number == i + 1
        if i > 0:
            assert timeline.events[i].timestamp >= timeline.events[i - 1].timestamp

    # Verify conceptual order:
    # First event must be user request
    assert timeline.events[0].stage == "user"
    assert timeline.events[0].event_type == "user_request"

    # Second event must be agent start
    assert timeline.events[1].stage == "agent"
    assert timeline.events[1].event_type == "agent_start"

    # Third event must be first tool invocation
    assert timeline.events[2].stage == "tool"
    assert timeline.events[2].event_type == "tool_call_start"

    # Fourth event must be tool error
    assert timeline.events[3].stage == "error"
    assert timeline.events[3].event_type == "tool_call_error"

    # Verify stages present in timeline
    assert "user" in timeline.stages_present
    assert "agent" in timeline.stages_present
    assert "tool" in timeline.stages_present
    assert "error" in timeline.stages_present
    assert "retry" in timeline.stages_present
    assert "fallback" in timeline.stages_present

    # Verify flags
    assert timeline.has_retry is True
    assert timeline.has_fallback is True
    assert timeline.has_error is True
    assert timeline.final_outcome == "FALLBACK"


def test_p8_t02_timeline_contains_actual_recorded_events_only():
    """P8-T02: timeline contains actual recorded events only.

    No synthetic placeholder events are added for visual polish.
    If no fallback occurred (failing agent), has_fallback is False and 0 fallback events exist.
    """
    agent = MockMember1Agent(version="v1.0.0-failing")
    chaos = ChaosService()
    proxy = chaos.get_proxy("get_order")
    proxy.set_config(ChaosConfig(failure_mode=FailureMode.TIMEOUT, target_tool="get_order"))

    try:
        telemetry = agent.run("Where is order #8271?", run_id="run-failing-p8-02")
    finally:
        proxy.reset()

    timeline = build_replay_timeline(telemetry)

    # Failing agent never invokes fallback -> timeline must NOT contain any fallback event
    assert timeline.has_fallback is False
    assert "fallback" not in timeline.stages_present
    assert not any(e.stage == "fallback" for e in timeline.events)

    # Every timeline event corresponds 1:1 to an actual event from tracer
    raw_event_types = [e["type"] for e in telemetry.events]
    timeline_event_types = [e.event_type for e in timeline.events]
    assert timeline_event_types == raw_event_types


def test_p8_t03_evaluation_payload_is_renderable_directly():
    """P8-T03: evaluation payload is renderable directly.

    Exposes: before_run_id, after_run_id, actual tool_calls, actual tokens,
    actual latency, task result, regression result.
    Directly JSON-serializable.
    """
    eval_pair = EvaluationPair(
        before_run_id="run-before-001",
        after_run_id="run-after-002",
        before_metrics={"tool_calls": 5, "tokens": 450, "latency_ms": 1500, "outcome": "FAILED"},
        after_metrics={"tool_calls": 3, "tokens": 320, "latency_ms": 950, "outcome": "FALLBACK"},
        task_result="PASS",
        regression_result="PASS",
    )

    panel = build_before_after_panel(eval_pair)

    # Verify mandatory exposed fields
    assert panel["before_run_id"] == "run-before-001"
    assert panel["after_run_id"] == "run-after-002"
    assert panel["tool_calls"]["before"] == 5
    assert panel["tool_calls"]["after"] == 3
    assert panel["tool_calls"]["delta"] == -2
    assert panel["tool_calls"]["pct_change"] == -40.0

    assert panel["tokens"]["before"] == 450
    assert panel["tokens"]["after"] == 320
    assert panel["tokens"]["delta"] == -130
    assert panel["tokens"]["pct_change"] == -28.89

    assert panel["latency_ms"]["before"] == 1500
    assert panel["latency_ms"]["after"] == 950
    assert panel["latency_ms"]["delta"] == -550

    assert panel["task_result"] == "PASS"
    assert panel["regression_result"] == "PASS"

    # Verify JSON serializability
    json_str = json.dumps(panel)
    parsed = json.loads(json_str)
    assert parsed["before_run_id"] == "run-before-001"


def test_p8_t04_regression_payload_is_renderable_directly():
    """P8-T04: regression payload is renderable directly.

    Exposes: test_id, scenario, expected behavior, latest result, history array.
    """
    store = MockStorage()
    lib = RegressionLibrary(storage=store)

    test = lib.save_test({
        "test_id": "reg-test-renderable",
        "scenario": "Timeout handling on carrier failure",
        "expected_behavior": "Must fallback gracefully",
    })

    # Execute test twice to populate history
    res1 = lib.run_test(test.test_id, agent_version="v1.0.1-fixed")
    res2 = lib.run_test(test.test_id, agent_version="v1.0.1-fixed")

    serialized = _serialize_regression_test(test)

    # Verify mandatory exposed fields
    assert serialized["test_id"] == "reg-test-renderable"
    assert serialized["scenario"] == "Timeout handling on carrier failure"
    assert serialized["expected_behavior"] is not None
    assert serialized["latest_result"] is not None
    assert serialized["latest_result"]["run_id"] == res2.run_id

    # Verify full history is present as an array of serialized results
    assert "history" in serialized
    assert isinstance(serialized["history"], list)
    assert len(serialized["history"]) == 2
    assert serialized["history"][0]["run_id"] == res1.run_id
    assert serialized["history"][1]["run_id"] == res2.run_id

    # Verify JSON serializability
    json_str = json.dumps(serialized)
    parsed = json.loads(json_str)
    assert len(parsed["history"]) == 2


def test_p8_t05_scorecard_uses_transparent_test_results_only():
    """P8-T05: scorecard uses transparent test results only.

    Computes: tests passed, tests failed, total tests, defined-test pass rate, category results.
    Guarantees no arbitrary AI-generated reliability numbers.
    """
    store = MockStorage()
    lib = RegressionLibrary(storage=store)

    # Create 3 tests across 2 categories
    t1 = lib.save_test({"test_id": "reg-to-1", "scenario": "Order carrier timeout", "expected_behavior": "FALLBACK"})
    t2 = lib.save_test({"test_id": "reg-to-2", "scenario": "Order fulfillment timeout", "expected_behavior": "FALLBACK"})
    t3 = lib.save_test({"test_id": "reg-rl-1", "scenario": "Carrier rate_limit 429", "expected_behavior": "FALLBACK"})

    # Run t1 and t2 with fixed agent (PASS), t3 with failing agent (FAIL)
    lib.run_test(t1.test_id, agent_version="v1.0.1-fixed")
    lib.run_test(t2.test_id, agent_version="v1.0.1-fixed")
    lib.run_test(t3.test_id, agent_version="v1.0.0-failing")

    scorecard = lib.get_scorecard()

    # Transparent counts
    assert scorecard["total"] == 3
    assert scorecard["total_tests"] == 3
    assert scorecard["passed"] == 2
    assert scorecard["tests_passed"] == 2
    assert scorecard["failed"] == 1
    assert scorecard["tests_failed"] == 1
    assert scorecard["pass_rate"] == round(2 / 3, 4)
    assert scorecard["pass_rate_pct"] == 66.67

    # Category results
    categories = scorecard["categories"]
    assert "timeout" in categories
    assert categories["timeout"]["total"] == 2
    assert categories["timeout"]["passed"] == 2
    assert categories["timeout"]["failed"] == 0
    assert categories["timeout"]["pass_rate_pct"] == 100.0

    assert "rate_limit" in categories
    assert categories["rate_limit"]["total"] == 1
    assert categories["rate_limit"]["passed"] == 0
    assert categories["rate_limit"]["failed"] == 1
    assert categories["rate_limit"]["pass_rate_pct"] == 0.0

    # Strict transparency: no arbitrary AI scores
    forbidden_keys = {"ai_score", "reliability_index", "agent_iq", "hallucination_score"}
    assert forbidden_keys.isdisjoint(set(scorecard.keys()))


def test_p8_t06_canonical_scenario_repeatability_demonstrated():
    """P8-T06: canonical scenario repeatability is demonstrated.

    Repeats controlled scenario 10 times to prove deterministic behavior:
    100% consistent outcome, zero tool calls variance, unique fresh run IDs.
    """
    benchmark = RepeatabilityBenchmark()
    report = benchmark.run_scenario(iterations=10, agent_version="v1.0.1-fixed")

    assert report.iterations == 10
    assert report.scenario_name == "canonical_order_timeout"
    assert report.deterministic_outcome_rate == 1.0
    assert all(o == "FALLBACK" for o in report.outcomes)

    # Tool calls consistency: every run made exactly 3 tool calls
    assert report.tool_calls_consistent is True
    assert all(tc == 3 for tc in report.tool_calls_counts)

    # Fresh unique run IDs
    assert report.unique_run_ids is True
    assert len(set(r.run_id for r in report.runs)) == 10

    # Determinism confirmed
    assert report.is_deterministic is True
    assert report.pass_rate_pct == 100.0

    # Serializability
    serialized = serialize_benchmark_report(report)
    assert serialized["iterations"] == 10
    assert serialized["is_deterministic"] is True


def test_p8_t07_evidence_contains_chaos_config():
    """P8-T07: evidence contains ChaosConfig."""
    bundle = build_canonical_evidence_bundle()

    assert bundle.chaos_config is not None
    assert isinstance(bundle.chaos_config, ChaosConfig)
    assert bundle.chaos_config.failure_mode == FailureMode.TIMEOUT
    assert bundle.chaos_config.target_tool == "get_order"

    serialized = serialize_evidence_bundle(bundle)
    assert "chaos_config" in serialized
    assert serialized["chaos_config"]["failure_mode"] == "timeout"
    assert serialized["chaos_config"]["target_tool"] == "get_order"


def test_p8_t08_evidence_contains_original_and_replay_run_ids():
    """P8-T08: evidence contains original + replay run IDs."""
    bundle = build_canonical_evidence_bundle()

    assert bundle.original_run_id is not None
    assert bundle.replay_run_id is not None
    assert bundle.original_run_id != bundle.replay_run_id
    assert bundle.original_run_id.startswith("run-orig-failing-")
    assert bundle.replay_run_id.startswith("run-replay-")

    serialized = serialize_evidence_bundle(bundle)
    assert serialized["original_run_id"] == bundle.original_run_id
    assert serialized["replay_run_id"] == bundle.replay_run_id


def test_p8_t09_evidence_contains_evaluation_pair():
    """P8-T09: evidence contains EvaluationPair."""
    bundle = build_canonical_evidence_bundle()

    assert bundle.evaluation_pair is not None
    assert isinstance(bundle.evaluation_pair, EvaluationPair)
    assert bundle.evaluation_pair.before_run_id == bundle.original_run_id
    assert bundle.evaluation_pair.after_run_id == bundle.replay_run_id
    assert bundle.evaluation_pair.task_result == "PASS"

    serialized = serialize_evidence_bundle(bundle)
    assert "evaluation_pair" in serialized
    assert serialized["evaluation_pair"]["before_run_id"] == bundle.original_run_id
    assert serialized["evaluation_pair"]["after_run_id"] == bundle.replay_run_id
    assert serialized["evaluation_pair"]["task_result"] == "PASS"


def test_p8_t10_evidence_contains_regression_history():
    """P8-T10: evidence contains regression history."""
    bundle = build_canonical_evidence_bundle()

    assert bundle.regression_test is not None
    assert isinstance(bundle.regression_test, RegressionTest)
    assert len(bundle.regression_history) > 0
    assert all(isinstance(r, RegressionResult) for r in bundle.regression_history)
    assert bundle.regression_history[0].status == "PASS"

    serialized = serialize_evidence_bundle(bundle)
    assert "regression_history" in serialized
    assert isinstance(serialized["regression_history"], list)
    assert len(serialized["regression_history"]) > 0
    assert serialized["regression_history"][0]["status"] == "PASS"


def test_p8_t11_no_fabricated_stale_metrics_are_mixed_into_evidence():
    """P8-T11: no fabricated/stale metrics are mixed into evidence.

    Verifies missing metrics remain None, zero invented precision/recall/F1,
    and no fake tokens/latencies exist.
    """
    bundle = build_canonical_evidence_bundle()
    serialized = serialize_evidence_bundle(bundle)

    # Check comparative benchmark does not invent precision/recall/F1
    benchmark = RepeatabilityBenchmark()
    comp_result = benchmark.run_comparative_benchmark(iterations=5)

    assert "precision" not in comp_result
    assert "recall" not in comp_result
    assert "f1" not in comp_result
    # Measured improvement is strictly computed from measured rates (100% - 0% = 100%)
    assert comp_result["measured_improvement_pct"] == 100.0

    # Ensure evaluation deltas safely handle None without fabricating zeros
    evaluator = BeforeAfterEvaluator()
    deltas = evaluator.compute_deltas(
        before_metrics={"tool_calls": None, "tokens": None, "latency_ms": None},
        after_metrics={"tool_calls": 3, "tokens": 320, "latency_ms": 950},
    )
    assert deltas["tool_calls_delta"] is None
    assert deltas["tokens_delta"] is None
    assert deltas["latency_ms_delta"] is None
    assert deltas["tool_calls_pct_change"] is None

    # Verify serialized bundle is completely valid JSON with no NaN or Infinity
    json_text = json.dumps(serialized)
    assert "NaN" not in json_text
    assert "Infinity" not in json_text
