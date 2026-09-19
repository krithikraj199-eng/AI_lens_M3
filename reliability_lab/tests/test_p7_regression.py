"""Phase P7 Tests: Member 3 Regression Library.

Tests P7-T01 through P7-T11.
"""

from typing import Any
import pytest

from reliability_lab.adapters.member1_adapter import MockMember1Agent
from reliability_lab.contracts import ExpectedBehavior, RegressionResult, RegressionTest, ReplayRecord, FailureMode
from reliability_lab.mocks.mock_storage import MockStorage
from reliability_lab.regression.service import (
    RegressionLibrary,
    create_test_service,
    list_tests_service,
    run_tests_service,
)


def _setup_library_with_canonical_test() -> tuple[RegressionLibrary, MockStorage, RegressionTest]:
    """Helper to initialize library with the canonical timeout regression test."""
    storage = MockStorage()
    library = RegressionLibrary(storage=storage)

    test = library.save_test(
        {
            "test_id": "reg-timeout-canonical",
            "scenario": "Canonical order lookup timeout handling",
            "expected_behavior": ExpectedBehavior(
                description="Agent must handle timeout within max 2 retries and invoke fallback",
                expected_outcome="FALLBACK",
                fallback_required=True,
                max_retries=2,
            ),
        }
    )
    return library, storage, test


def test_p7_t01_save_creates_regression_test():
    """P7-T01: save creates RegressionTest."""
    storage = MockStorage()
    library = RegressionLibrary(storage=storage)

    # 1. Save using specification dictionary
    test_dict = {
        "test_id": "reg-test-001",
        "scenario": "Order timeout retry scenario",
        "expected_behavior": "Must fallback on timeout within 2 retries",
    }
    saved = library.save_test(test_dict)

    assert isinstance(saved, RegressionTest)
    assert saved.test_id == "reg-test-001"
    assert saved.scenario == "Order timeout retry scenario"
    assert saved.latest_result is None
    assert saved.history == []
    assert saved.created_at is not None

    # Stored and retrievable
    retrieved = library.get_test("reg-test-001")
    assert retrieved is not None
    assert retrieved.test_id == "reg-test-001"

    # 2. Save directly using RegressionTest contract instance
    direct_test = RegressionTest(
        test_id="reg-test-002",
        scenario="Rate limit backoff scenario",
        expected_behavior="Must handle rate limit without crash",
    )
    saved_direct = library.save_test(direct_test)
    assert saved_direct.test_id == "reg-test-002"
    assert library.get_test("reg-test-002") == direct_test


def test_p7_t02_list_returns_saved_tests():
    """P7-T02: list returns saved tests."""
    storage = MockStorage()
    library = RegressionLibrary(storage=storage)

    for i in range(1, 4):
        library.save_test({
            "test_id": f"reg-test-00{i}",
            "scenario": f"Scenario {i}",
            "expected_behavior": f"Expected {i}",
        })

    tests = library.list_tests()
    assert len(tests) == 3
    test_ids = {t.test_id for t in tests}
    assert test_ids == {"reg-test-001", "reg-test-002", "reg-test-003"}


def test_p7_t03_run_one_executes_only_selected_test():
    """P7-T03: run-one executes only selected test."""
    storage = MockStorage()
    library = RegressionLibrary(storage=storage)

    test1 = library.save_test({
        "test_id": "reg-run-only-1",
        "scenario": "Timeout scenario 1",
        "expected_behavior": "Fallback on timeout",
    })
    test2 = library.save_test({
        "test_id": "reg-untouched-2",
        "scenario": "Timeout scenario 2",
        "expected_behavior": "Fallback on timeout",
    })

    result1 = library.run_test("reg-run-only-1", agent_version="v1.0.1-fixed")

    assert result1.test_id == "reg-run-only-1"
    assert test1.latest_result is not None
    assert len(test1.history) == 1
    assert test1.latest_result == result1

    # Verify test 2 was completely untouched
    test2_fetched = library.get_test("reg-untouched-2")
    assert test2_fetched.latest_result is None
    assert len(test2_fetched.history) == 0


def test_p7_t04_run_all_executes_all_saved_tests():
    """P7-T04: run-all executes all saved tests."""
    storage = MockStorage()
    library = RegressionLibrary(storage=storage)

    library.save_test({
        "test_id": "reg-all-1",
        "scenario": "Timeout scenario 1",
        "expected_behavior": "Fallback on timeout",
    })
    library.save_test({
        "test_id": "reg-all-2",
        "scenario": "Timeout scenario 2",
        "expected_behavior": "Fallback on timeout",
    })

    report = library.run_all(agent_version="v1.0.1-fixed")

    assert report["status"] == "COMPLETED"
    assert report["total_executed"] == 2
    assert len(report["results"]) == 2

    test1 = library.get_test("reg-all-1")
    test2 = library.get_test("reg-all-2")
    assert test1.latest_result is not None
    assert test2.latest_result is not None
    assert len(test1.history) == 1
    assert len(test2.history) == 1


def test_p7_t05_latest_result_updates():
    """P7-T05: latest_result updates."""
    library, storage, test = _setup_library_with_canonical_test()

    assert test.latest_result is None

    # First run
    res1 = library.run_test(test.test_id, agent_version="v1.0.1-fixed")
    assert test.latest_result == res1
    assert test.latest_result.run_id == res1.run_id

    # Second run
    res2 = library.run_test(test.test_id, agent_version="v1.0.1-fixed")
    assert test.latest_result == res2
    assert test.latest_result.run_id == res2.run_id
    assert res1.run_id != res2.run_id
    assert test.latest_result is not res1


def test_p7_t06_history_appends_without_destroying_previous_history():
    """P7-T06: history appends without destroying previous history."""
    library, storage, test = _setup_library_with_canonical_test()

    res1 = library.run_test(test.test_id, agent_version="v1.0.1-fixed")
    res2 = library.run_test(test.test_id, agent_version="v1.0.1-fixed")
    res3 = library.run_test(test.test_id, agent_version="v1.0.1-fixed")

    assert len(test.history) == 3
    assert test.history[0] == res1
    assert test.history[1] == res2
    assert test.history[2] == res3
    assert test.history[0].run_id != test.history[1].run_id != test.history[2].run_id

    # Retrieve fresh from storage and verify persisted history
    fetched = library.get_test(test.test_id)
    assert len(fetched.history) == 3
    assert fetched.history[0].run_id == res1.run_id
    assert fetched.history[1].run_id == res2.run_id
    assert fetched.history[2].run_id == res3.run_id


def test_p7_t07_regression_result_contains_run_id_and_measured_evidence():
    """P7-T07: RegressionResult contains run_id + measured evidence."""
    library, storage, test = _setup_library_with_canonical_test()

    result = library.run_test(test.test_id, agent_version="v1.0.1-fixed")

    assert isinstance(result, RegressionResult)
    assert result.test_id == test.test_id
    assert result.run_id.startswith("run-replay-")
    assert result.status in ("PASS", "FAIL")
    assert result.timestamp is not None

    evidence = result.measured_evidence
    assert isinstance(evidence, dict)
    assert "tool_calls" in evidence
    assert "tokens" in evidence
    assert "latency_ms" in evidence
    assert "outcome" in evidence
    assert "errors" in evidence
    assert evidence["tool_calls"] == 3  # Fixed agent makes 3 attempts
    assert evidence["outcome"] == "FALLBACK"


def test_p7_t08_fixed_canonical_timeout_test_produces_pass():
    """P7-T08: fixed canonical timeout test produces PASS."""
    library, storage, test = _setup_library_with_canonical_test()

    result = library.run_test(test.test_id, agent_version="v1.0.1-fixed")

    assert result.status == "PASS"
    assert result.measured_evidence["outcome"] == "FALLBACK"
    assert result.measured_evidence["tool_calls"] <= 3


def test_p7_t09_known_failing_behavior_produces_fail():
    """P7-T09: known failing behavior produces FAIL."""
    library, storage, test = _setup_library_with_canonical_test()

    # Run with failing agent version (unhandled retry loop, retried 5 times, outcome FAILED)
    result = library.run_test(test.test_id, agent_version="v1.0.0-failing")

    assert result.status == "FAIL"
    assert result.measured_evidence["outcome"] == "FAILED"


def test_p7_t10_rerunning_creates_another_history_entry():
    """P7-T10: rerunning creates another history entry."""
    library, storage, test = _setup_library_with_canonical_test()

    assert len(test.history) == 0

    library.run_test(test.test_id)
    assert len(test.history) == 1

    library.run_test(test.test_id)
    assert len(test.history) == 2

    library.run_test(test.test_id)
    assert len(test.history) == 3


def test_p7_t11_results_expose_transparent_scorecard_counts():
    """P7-T11: results expose transparent scorecard counts.
    
    Allowed: '8 / 10 tests passed', '80.0% defined test pass rate'.
    Forbidden: 'The AI agent is 80% reliable'.
    """
    storage = MockStorage()
    library = RegressionLibrary(storage=storage)

    # Test 1: PASS
    test1 = library.save_test({
        "test_id": "reg-scorecard-1",
        "scenario": "Canonical timeout handling",
        "expected_behavior": ExpectedBehavior(
            description="Fallback on timeout within 2 retries",
            expected_outcome="FALLBACK",
            max_retries=2,
        ),
    })
    # Test 2: PASS
    test2 = library.save_test({
        "test_id": "reg-scorecard-2",
        "scenario": "Canonical timeout handling",
        "expected_behavior": ExpectedBehavior(
            description="Fallback on timeout within 2 retries",
            expected_outcome="FALLBACK",
            max_retries=2,
        ),
    })
    # Test 3: FAIL (strict max_retries=1 where agent does 2 retries, or failing version)
    test3 = library.save_test({
        "test_id": "reg-scorecard-3",
        "scenario": "Canonical timeout handling",
        "expected_behavior": ExpectedBehavior(
            description="Must succeed immediately without any retries",
            max_retries=0,  # Fails because fixed agent retries twice
        ),
    })

    res1 = library.run_test(test1.test_id, agent_version="v1.0.1-fixed")
    res2 = library.run_test(test2.test_id, agent_version="v1.0.1-fixed")
    res3 = library.run_test(test3.test_id, agent_version="v1.0.1-fixed")

    assert res1.status == "PASS"
    assert res2.status == "PASS"
    assert res3.status == "FAIL"

    scorecard = library.get_scorecard([res1, res2, res3])

    # Transparent mathematical counts
    assert scorecard["total"] == 3
    assert scorecard["passed"] == 2
    assert scorecard["failed"] == 1
    assert scorecard["pass_rate"] == 0.6667
    assert scorecard["pass_rate_pct"] == 66.67
    assert scorecard["summary"] == "2 / 3 tests passed (66.67% defined test pass rate)"

    # Strict compliance: no subjective AI reliability score claim
    scorecard_str = str(scorecard).lower()
    assert "ai reliability" not in scorecard_str
    assert "reliable" not in scorecard_str
    assert not hasattr(scorecard, "ai_reliability_score")


# ==============================================================================
# MEMBER 4 SERVICE INTEGRATION TESTS
# ==============================================================================

def test_p7_service_endpoints_serializable():
    """Verify Member 4 GET /tests, POST /tests, and POST /tests/run service handlers."""
    storage = MockStorage()

    # 1. POST /tests
    create_payload = {
        "test_id": "reg-api-001",
        "scenario": "API timeout verification",
        "expected_behavior": "Fallback on timeout",
    }
    create_resp = create_test_service(create_payload, storage=storage)
    assert create_resp["status"] == "CREATED"
    assert create_resp["test"]["test_id"] == "reg-api-001"

    # 2. GET /tests
    list_resp = list_tests_service(storage=storage)
    assert list_resp["status"] == "SUCCESS"
    assert list_resp["count"] == 1
    assert list_resp["tests"][0]["test_id"] == "reg-api-001"

    # 3. POST /tests/run (single)
    run_payload = {
        "test_id": "reg-api-001",
        "agent_version": "v1.0.1-fixed",
    }
    run_resp = run_tests_service(run_payload, storage=storage)
    assert run_resp["status"] == "COMPLETED"
    assert run_resp["mode"] == "SINGLE"
    assert len(run_resp["results"]) == 1
    assert run_resp["results"][0]["status"] == "PASS"
    assert run_resp["scorecard"]["passed"] == 1
    assert run_resp["scorecard"]["total"] == 1

    # 4. POST /tests/run (batch all)
    batch_payload = {"run_all": True, "agent_version": "v1.0.1-fixed"}
    batch_resp = run_tests_service(batch_payload, storage=storage)
    assert batch_resp["status"] == "COMPLETED"
    assert batch_resp["mode"] == "ALL"
    assert batch_resp["total_executed"] == 1
    assert batch_resp["scorecard"]["summary"] == "1 / 1 tests passed (100.0% defined test pass rate)"
