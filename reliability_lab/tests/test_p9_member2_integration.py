"""Tests for Phase P9: Optional Member 2 Change-to-Test and Grounding Integration.

Tests P9-T01 through P9-T07.
"""

import pytest

from reliability_lab.adapters.member2_adapter import (
    import_member2_scenario,
    validate_member2_scenario,
)
from reliability_lab.contracts import (
    FailureMode,
    RegressionResult,
    RegressionTest,
    ReplayRecord,
)
from reliability_lab.fixtures.replay_fixtures import (
    CANONICAL_TIMEOUT_FIXTURE,
    CONTROLLED_GROUNDING_FIXTURE,
)
from reliability_lab.mocks.mock_storage import MockStorage
from reliability_lab.regression.service import RegressionLibrary, RegressionRunner
from reliability_lab.replay.engine import ReplayEngine


def test_p9_t01_valid_generated_scenario_maps_to_regression_test():
    """P9-T01: valid generated scenario maps to RegressionTest."""
    store = MockStorage()

    m2_payload = {
        "scenario_id": "m2-c2t-order-carrier-rate-limit",
        "description": "Carrier API rate limit 429 response handling",
        "prompt": "Where is order #8271?",
        "expected_behavior": "Must apply backoff or invoke rate limit fallback",
        "failure_mode": "rate_limit",
        "mocked_responses": {
            "get_order": {"status_code": 429, "error": "Too Many Requests"}
        },
    }

    test = import_member2_scenario(m2_payload, storage=store)

    assert isinstance(test, RegressionTest)
    assert test.test_id == "m2-c2t-order-carrier-rate-limit"
    assert test.scenario == "Carrier API rate limit 429 response handling"
    assert test.expected_behavior == "Must apply backoff or invoke rate limit fallback"
    assert test.replay_record_id is not None

    # ReplayRecord was also persisted in existing storage
    record = store.get(test.replay_record_id)
    assert isinstance(record, ReplayRecord)
    assert record.failure_mode == FailureMode.RATE_LIMIT
    assert record.prompt == "Where is order #8271?"


def test_p9_t02_scenario_runs_through_existing_runner():
    """P9-T02: scenario runs through existing runner.

    The imported scenario executes directly via standard RegressionRunner and ReplayEngine.
    """
    store = MockStorage()
    lib = RegressionLibrary(storage=store)

    m2_payload = {
        "test_id": "m2-c2t-timeout-gate",
        "scenario": "Carrier service timeout under heavy load",
        "prompt": "Where is order #8271?",
        "expected_behavior": "FALLBACK",
        "failure_mode": "timeout",
        "mocked_responses": CANONICAL_TIMEOUT_FIXTURE.mocked_responses,
    }

    test = import_member2_scenario(m2_payload, storage=store)

    # Run through existing library / runner
    result = lib.run_test(test.test_id, agent_version="v1.0.1-fixed")

    assert isinstance(result, RegressionResult)
    assert result.test_id == "m2-c2t-timeout-gate"
    assert result.status == "PASS"
    assert result.run_id.startswith("run-replay-")
    assert result.measured_evidence["outcome"] == "FALLBACK"
    assert result.measured_evidence["tool_calls"] == 3


def test_p9_t03_existing_regression_result_is_produced():
    """P9-T03: existing RegressionResult is produced and history updated."""
    store = MockStorage()
    lib = RegressionLibrary(storage=store)

    m2_payload = {
        "test_id": "m2-c2t-result-check",
        "scenario": "Carrier timeout assertion test",
        "prompt": "Where is order #8271?",
        "expected_behavior": "FALLBACK",
        "failure_mode": "timeout",
    }

    test = import_member2_scenario(m2_payload, storage=store)
    res = lib.run_test(test.test_id, agent_version="v1.0.1-fixed")

    assert isinstance(res, RegressionResult)
    assert res.test_id == test.test_id
    assert res.status == "PASS"
    assert "tool_calls" in res.measured_evidence
    assert "outcome" in res.measured_evidence
    assert "timestamp" in res.__dict__

    # Verify history appended on existing RegressionTest
    assert test.latest_result == res
    assert len(test.history) == 1
    assert test.history[0] == res


def test_p9_t04_no_duplicate_regression_subsystem_is_introduced():
    """P9-T04: no duplicate regression subsystem is introduced.

    Storage only contains standard ReplayRecords and RegressionTests.
    No second database, semantic graph, or alternate test runner class exists.
    """
    store = MockStorage()
    m2_payload = {
        "test_id": "m2-subsystem-check",
        "scenario": "Check standard subsystem storage",
        "prompt": "Where is order #8271?",
        "expected_behavior": "Must handle normally",
    }

    test = import_member2_scenario(m2_payload, storage=store)

    # Inspect all items in storage
    stored_items = store.list()
    for item in stored_items:
        # Every item in storage must be an existing contract
        assert isinstance(item, (RegressionTest, ReplayRecord, RegressionResult)), (
            f"Unexpected item type in storage: {type(item).__name__}"
        )

    # Verify RegressionRunner is the existing single runner class
    runner = RegressionRunner(storage=store)
    assert hasattr(runner, "run")
    assert hasattr(runner, "replay_engine")


def test_p9_t05_invalid_generated_scenario_is_rejected():
    """P9-T05: invalid generated scenario is rejected with clear validation error."""
    # 1. Non-dict input
    with pytest.raises(TypeError, match="Expected dict"):
        validate_member2_scenario(["not", "a", "dict"])

    # 2. Missing test_id / scenario_id
    with pytest.raises(ValueError, match="test_id"):
        validate_member2_scenario({
            "scenario": "Some test",
            "prompt": "Where is order #8271?",
            "expected_behavior": "FALLBACK",
        })

    # 3. Missing scenario / description
    with pytest.raises(ValueError, match="scenario"):
        validate_member2_scenario({
            "test_id": "test-001",
            "prompt": "Where is order #8271?",
            "expected_behavior": "FALLBACK",
        })

    # 4. Missing prompt
    with pytest.raises(ValueError, match="prompt"):
        validate_member2_scenario({
            "test_id": "test-001",
            "scenario": "Some test",
            "expected_behavior": "FALLBACK",
        })

    # 5. Missing expected_behavior
    with pytest.raises(ValueError, match="expected_behavior"):
        validate_member2_scenario({
            "test_id": "test-001",
            "scenario": "Some test",
            "prompt": "Where is order #8271?",
        })

    # 6. Invalid failure_mode
    with pytest.raises(ValueError, match="Invalid failure_mode"):
        validate_member2_scenario({
            "test_id": "test-001",
            "scenario": "Some test",
            "prompt": "Where is order #8271?",
            "expected_behavior": "FALLBACK",
            "failure_mode": "hallucinated_unknown_mode",
        })


def test_p9_t06_grounding_fixture_calls_member2_output_rather_than_implementing_grounding():
    """P9-T06: grounding fixture calls Member 2 output rather than implementing grounding.

    Member 3 contains zero grounding detection models, embedding libraries, or RAG evaluation.
    Only the controlled scenario fixture representing Member 2 output is accepted.
    """
    assert CONTROLLED_GROUNDING_FIXTURE is not None
    assert CONTROLLED_GROUNDING_FIXTURE.name == "carrier_grounding_violation"
    assert "delivery" in CONTROLLED_GROUNDING_FIXTURE.expected_behavior.lower()

    # Verify Member 3 does NOT import or implement grounding detector modules
    import sys
    forbidden_grounding_modules = [
        "langchain", "llama_index", "ragas", "bert_score", "sentence_transformers",
        "grounding_detector", "hallucination_evaluator"
    ]
    for mod in sys.modules:
        for forbidden in forbidden_grounding_modules:
            assert forbidden not in mod.lower(), f"Member 3 must not import grounding detector: {forbidden}"

    # Verify grounding fixture can be ingested into existing regression library
    store = MockStorage()
    lib = RegressionLibrary(storage=store)

    grounding_test = import_member2_scenario(
        {
            "test_id": "m2-grounding-001",
            "scenario": CONTROLLED_GROUNDING_FIXTURE.name,
            "prompt": CONTROLLED_GROUNDING_FIXTURE.prompt,
            "expected_behavior": CONTROLLED_GROUNDING_FIXTURE.expected_behavior,
            "mocked_responses": CONTROLLED_GROUNDING_FIXTURE.mocked_responses,
        },
        storage=store,
    )

    assert grounding_test.test_id == "m2-grounding-001"
    scorecard = lib.get_scorecard()
    assert scorecard["total"] == 0  # Not yet run


def test_p9_t07_canonical_timeout_flow_is_unaffected():
    """P9-T07: canonical timeout flow is unaffected by Member 2 adapter."""
    store = MockStorage()
    engine = ReplayEngine(storage=store)

    record = ReplayRecord(
        run_id="run-canonical-p9-check",
        prompt=CANONICAL_TIMEOUT_FIXTURE.prompt,
        agent_version="v1.0.0-failing",
        prompt_version="p1.0",
        failure_mode=FailureMode.TIMEOUT,
        tool_calls=[{"tool": "get_order", "args": {"order_id": "8271"}}],
        mocked_responses=CANONICAL_TIMEOUT_FIXTURE.mocked_responses,
        expected_behavior=CANONICAL_TIMEOUT_FIXTURE.expected_behavior,
        original_incident_id="inc-canonical-timeout",
    )

    # Canonical timeout replay continues to produce exact expected telemetry
    res = engine.replay(record, agent_version_override="v1.0.1-fixed")

    assert res.telemetry.outcome == "FALLBACK"
    assert len(res.telemetry.tool_calls) == 3
    assert len(res.telemetry.errors) == 3
    assert res.telemetry.response is not None
    assert res.telemetry.response.get("fallback_triggered") is True
