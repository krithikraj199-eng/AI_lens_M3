"""Tests for Phase P6: Member 3 Before/After Evaluator.

Tests P6-T01 through P6-T11.
"""

import json
import pytest

from reliability_lab.adapters.member1_adapter import MockMember1Agent
from reliability_lab.chaos.service import ChaosService
from reliability_lab.contracts import ChaosConfig, EvaluationPair, FailureMode, RegressionResult
from reliability_lab.evaluation.evaluator import (
    BeforeAfterEvaluator,
    evaluate_pair,
    execute_evaluation,
)
from reliability_lab.fixtures.compat_fixtures import TestRunFixture
from reliability_lab.mocks.mock_storage import MockStorage


def _setup_controlled_runs():
    """Helper to generate actual controlled before and after runs under identical timeout chaos."""
    chaos_service = ChaosService()
    proxy = chaos_service.get_proxy("get_order")
    proxy.set_config(
        ChaosConfig(
            failure_mode=FailureMode.TIMEOUT,
            target_tool="get_order",
            error_message="Controlled timeout on tool 'get_order'.",
        )
    )

    try:
        failing_agent = MockMember1Agent(version="v1.0.0-failing", order_tool=proxy)
        fixed_agent = MockMember1Agent(version="v1.0.1-fixed", order_tool=proxy)

        prompt = "Where is order #8271?"
        before_res = failing_agent.run(request=prompt, run_id="run-before-001")
        after_res = fixed_agent.run(request=prompt, run_id="run-after-002")
        return before_res, after_res
    finally:
        proxy.reset()


def test_p6_t01_before_after_run_ids_retained():
    """P6-T01: before/after run IDs retained and verified distinct."""
    before_res, after_res = _setup_controlled_runs()

    evaluator = BeforeAfterEvaluator()
    pair = evaluator.evaluate(
        before_run=before_res,
        after_run=after_res,
        expected_behavior="Fallback on timeout",
    )

    assert pair.before_run_id == "run-before-001"
    assert pair.after_run_id == "run-after-002"
    assert pair.before_run_id != pair.after_run_id

    # Non-distinct run IDs must be rejected
    with pytest.raises(ValueError, match="must be distinct"):
        evaluator.evaluate(before_run=before_res, after_run=before_res)


def test_p6_t02_pair_represents_equivalent_controlled_scenario():
    """P6-T02: pair represents equivalent intended controlled scenario."""
    before_res, after_res = _setup_controlled_runs()
    evaluator = BeforeAfterEvaluator()

    # Valid equivalent pair matches scenario
    pair = evaluator.evaluate(
        before_run=before_res,
        after_run=after_res,
        expected_prompt="Where is order #8271?",
        expected_failure_mode="timeout",
    )
    assert pair is not None

    # Mismatched prompt must be rejected
    mismatched_prompt_run = TestRunFixture(
        run_id="run-after-mismatched-prompt",
        agent_version="v1.0.1-fixed",
        prompt_version="p1.0",
        request="Cancel order #9999",
        outcome="FALLBACK",
    )
    with pytest.raises(ValueError, match="Scenario mismatch|does not match"):
        evaluator.evaluate(before_run=before_res, after_run=mismatched_prompt_run)

    # Mismatched failure mode must be rejected
    before_dict = {
        "run_id": "run-b-timeout",
        "request": "Where is order #8271?",
        "failure_mode": "timeout",
        "outcome": "FAILED",
        "agent_version": "v1.0.0-failing",
    }
    after_dict_rate_limit = {
        "run_id": "run-a-rate-limit",
        "request": "Where is order #8271?",
        "failure_mode": "rate_limit",
        "outcome": "FALLBACK",
        "agent_version": "v1.0.1-fixed",
    }
    with pytest.raises(ValueError, match="Scenario mismatch|failure_mode"):
        evaluator.evaluate(before_run=before_dict, after_run=after_dict_rate_limit)


def test_p6_t03_tool_calls_read_from_actual_runs():
    """P6-T03: tool_calls read from actual runs."""
    before_res, after_res = _setup_controlled_runs()

    evaluator = BeforeAfterEvaluator()
    pair = evaluator.evaluate(before_run=before_res, after_run=after_res)

    # Failing agent made 5 retries; fixed agent made 3 attempts (1 initial + 2 retries)
    assert pair.before_metrics["tool_calls"] == 5
    assert pair.after_metrics["tool_calls"] == 3
    assert pair.before_metrics["tool_calls"] == len(before_res.tool_calls)
    assert pair.after_metrics["tool_calls"] == len(after_res.tool_calls)


def test_p6_t04_tokens_read_from_actual_runs():
    """P6-T04: tokens read from actual runs."""
    before_res, after_res = _setup_controlled_runs()

    evaluator = BeforeAfterEvaluator()
    pair = evaluator.evaluate(before_run=before_res, after_run=after_res)

    assert pair.before_metrics["tokens"] == before_res.tokens
    assert pair.after_metrics["tokens"] == after_res.tokens
    assert isinstance(pair.before_metrics["tokens"], int)
    assert isinstance(pair.after_metrics["tokens"], int)


def test_p6_t05_latency_read_from_actual_runs():
    """P6-T05: latency read from actual runs."""
    before_res, after_res = _setup_controlled_runs()

    evaluator = BeforeAfterEvaluator()
    pair = evaluator.evaluate(before_run=before_res, after_run=after_res)

    assert pair.before_metrics["latency_ms"] == before_res.latency_ms
    assert pair.after_metrics["latency_ms"] == after_res.latency_ms
    assert pair.before_metrics["latency_ms"] >= 0
    assert pair.after_metrics["latency_ms"] >= 0


def test_p6_t06_task_result_derived_from_defined_expected_behavior():
    """P6-T06: task result derived from defined expected behavior.

    Verifies that PASS/FAIL is based on expected behavior fulfillment, NOT whether
    every numeric metric decreased.
    """
    before_res, after_res = _setup_controlled_runs()
    evaluator = BeforeAfterEvaluator()

    # Fixed agent satisfies expected fallback behavior -> PASS
    pair = evaluator.evaluate(
        before_run=before_res,
        after_run=after_res,
        expected_behavior="Order lookup should fallback gracefully on timeout",
    )
    assert pair.task_result == "PASS"

    # If after run failed to handle timeout and crashed -> FAIL
    crashed_after = TestRunFixture(
        run_id="run-after-crashed",
        agent_version="v1.0.1-fixed",
        prompt_version="p1.0",
        request="Where is order #8271?",
        outcome="FAILED",
        errors=["TimeoutError: unhandled exception"],
    )
    fail_pair = evaluator.evaluate(
        before_run=before_res,
        after_run=crashed_after,
        expected_behavior="Order lookup should fallback gracefully on timeout",
    )
    assert fail_pair.task_result == "FAIL"

    # Analytical rule verification:
    # Even if after run consumes MORE tokens and MORE latency (e.g. creating a support ticket),
    # task_result is PASS if expected behavior is met.
    verbose_after = TestRunFixture(
        run_id="run-after-verbose",
        agent_version="v1.0.1-fixed",
        prompt_version="p1.0",
        request="Where is order #8271?",
        outcome="FALLBACK",
        tokens=before_res.tokens + 500,  # More tokens!
        latency_ms=before_res.latency_ms + 1000,  # Higher latency!
        tool_calls=[{"tool": "get_order"}] * 3,
    )
    verbose_pair = evaluator.evaluate(
        before_run=before_res,
        after_run=verbose_after,
        expected_behavior="Order lookup should fallback gracefully on timeout",
    )
    assert verbose_pair.task_result == "PASS"
    assert verbose_pair.after_metrics["tokens"] > verbose_pair.before_metrics["tokens"]


def test_p6_t07_regression_result_uses_actual_regression_evidence():
    """P6-T07: regression result uses actual regression evidence when available."""
    before_res, after_res = _setup_controlled_runs()
    evaluator = BeforeAfterEvaluator()

    # 1. Evidence PASS
    reg_pass = RegressionResult(
        test_id="reg-001",
        run_id=after_res.run_id,
        status="PASS",
        measured_evidence={"retries": 2, "fallback": True},
    )
    pair1 = evaluator.evaluate(before_run=before_res, after_run=after_res, regression_result=reg_pass)
    assert pair1.regression_result == "PASS"

    # 2. Evidence FAIL
    reg_fail = RegressionResult(
        test_id="reg-002",
        run_id=after_res.run_id,
        status="FAIL",
        measured_evidence={"retries": 5, "fallback": False},
    )
    pair2 = evaluator.evaluate(before_run=before_res, after_run=after_res, regression_result=reg_fail)
    assert pair2.regression_result == "FAIL"

    # 3. No regression evidence available -> NOT_EVALUATED (Never fabricate "PASS")
    pair3 = evaluator.evaluate(before_run=before_res, after_run=after_res, regression_result=None)
    assert pair3.regression_result == "NOT_EVALUATED"


def test_p6_t08_no_fabricated_hardcoded_metrics_exist():
    """P6-T08: no fabricated/hardcoded metrics exist; missing metrics handled honestly."""
    evaluator = BeforeAfterEvaluator()

    # Run with missing tokens and latency
    partial_before = {
        "run_id": "run-b-partial",
        "request": "Where is order #8271?",
        "outcome": "FAILED",
        "agent_version": "v1.0.0-failing",
        "tool_calls": [{"tool": "get_order"}] * 5,
        "tokens": None,
        "latency_ms": None,
    }
    partial_after = {
        "run_id": "run-a-partial",
        "request": "Where is order #8271?",
        "outcome": "FALLBACK",
        "agent_version": "v1.0.1-fixed",
        "tool_calls": [{"tool": "get_order"}] * 3,
        "tokens": None,
        "latency_ms": None,
    }

    pair = evaluator.evaluate(before_run=partial_before, after_run=partial_after)

    # Missing metrics must be None, NOT zero or fabricated defaults
    assert pair.before_metrics["tokens"] is None
    assert pair.before_metrics["latency_ms"] is None
    assert pair.after_metrics["tokens"] is None
    assert pair.after_metrics["latency_ms"] is None

    # Deltas and percent changes must be None when operands are missing
    deltas = evaluator.compute_deltas(pair.before_metrics, pair.after_metrics)
    assert deltas["tokens_delta"] is None
    assert deltas["tokens_pct_change"] is None
    assert deltas["latency_ms_delta"] is None
    assert deltas["latency_ms_pct_change"] is None

    # Valid tool_calls deltas are computed
    assert deltas["tool_calls_delta"] == -2
    assert deltas["tool_calls_pct_change"] == -40.0

    # Zero divisor handled safely without ZeroDivisionError
    zero_before = {"tool_calls": 0, "tokens": 0, "latency_ms": 0}
    positive_after = {"tool_calls": 2, "tokens": 100, "latency_ms": 50}
    zero_deltas = evaluator.compute_deltas(zero_before, positive_after)
    assert zero_deltas["tool_calls_delta"] == 2
    assert zero_deltas["tool_calls_pct_change"] is None  # Div by 0 is None

    # Ensure no universal AI reliability score attribute exists
    assert not hasattr(pair, "ai_reliability_score")
    assert not hasattr(pair, "universal_score")


def test_p6_t09_before_represents_failing_execution():
    """P6-T09: before represents failing execution."""
    evaluator = BeforeAfterEvaluator()

    passing_before = TestRunFixture(
        run_id="run-before-passing",
        agent_version="v1.0.1-fixed",
        prompt_version="p1.0",
        request="Where is order #8271?",
        outcome="SUCCESS",
        errors=[],
    )
    valid_after = TestRunFixture(
        run_id="run-after-valid",
        agent_version="v1.0.1-fixed",
        prompt_version="p1.0",
        request="Where is order #8271?",
        outcome="FALLBACK",
    )

    # Must reject a passing execution as before_run
    with pytest.raises(ValueError, match="does not represent a failing execution"):
        evaluator.evaluate(before_run=passing_before, after_run=valid_after)


def test_p6_t10_after_represents_fixed_execution():
    """P6-T10: after represents fixed execution under identical controlled chaos."""
    before_res, after_res = _setup_controlled_runs()

    assert "failing" in before_res.agent_version.lower()
    assert "fixed" in after_res.agent_version.lower()
    assert before_res.outcome == "FAILED"
    assert after_res.outcome == "FALLBACK"

    pair = evaluate_pair(
        before_run=before_res,
        after_run=after_res,
        expected_behavior="Order lookup should fallback on timeout",
    )

    assert pair.task_result == "PASS"
    assert pair.after_metrics["outcome"] == "FALLBACK"


def test_p6_t11_evaluation_result_serializable_for_member4():
    """P6-T11: evaluation result is serializable for Member 4."""
    before_res, after_res = _setup_controlled_runs()
    storage = MockStorage()
    storage.save("run-before-001", before_res)
    storage.save("run-after-002", after_res)

    # Trusted regression evidence saved in storage
    reg_result = RegressionResult(
        test_id="reg-001",
        run_id="run-after-002",
        status="PASS",
        measured_evidence={"retries": 2, "fallback": True},
    )
    storage.save("reg-001", reg_result)

    payload = {
        "before_run_id": "run-before-001",
        "after_run_id": "run-after-002",
        "prompt": "Where is order #8271?",
        "failure_mode": "timeout",
        "expected_behavior": "Order lookup should fallback on timeout",
        "regression_result_id": "reg-001",
    }

    result = execute_evaluation(payload, storage=storage)

    assert result["status"] == "EVALUATED"
    assert "evaluation_id" in result
    assert result["evaluation_id"].startswith("eval-")
    assert result["before_run_id"] == "run-before-001"
    assert result["after_run_id"] == "run-after-002"
    assert result["task_result"] == "PASS"
    assert result["regression_result"] == "PASS"
    assert "metrics" in result
    assert "deltas" in result["metrics"]

    # Verify complete JSON serializability for AWS Lambda / API Gateway
    json_str = json.dumps(result)
    assert isinstance(json_str, str)
    decoded = json.loads(json_str)
    assert decoded["status"] == "EVALUATED"
    assert decoded["evaluation_id"] == result["evaluation_id"]
    assert decoded["metrics"]["deltas"]["tool_calls_delta"] == -2


# ==============================================================================
# P6 HARDENING CORRECTIONS: P6-FIX-T01 through P6-FIX-T13
# ==============================================================================

def test_p6_fix_t01_raw_caller_string_pass_not_trusted():
    """P6-FIX-T01: Raw caller string 'PASS' cannot become trusted regression PASS."""
    before_res, after_res = _setup_controlled_runs()
    evaluator = BeforeAfterEvaluator()
    pair = evaluator.evaluate(
        before_run=before_res,
        after_run=after_res,
        regression_result="PASS",
    )
    assert pair.regression_result == "NOT_EVALUATED"

    # Also test raw "FAIL"
    pair_fail = evaluator.evaluate(
        before_run=before_res,
        after_run=after_res,
        regression_result="FAIL",
    )
    assert pair_fail.regression_result == "NOT_EVALUATED"

    # Also test via execute_evaluation
    storage = MockStorage()
    storage.save("b1", before_res)
    storage.save("a1", after_res)
    payload = {
        "before_run_id": "b1",
        "after_run_id": "a1",
        "regression_result": "PASS",
    }
    res = execute_evaluation(payload, storage=storage)
    assert res["regression_result"] == "NOT_EVALUATED"


def test_p6_fix_t02_real_regression_result_pass_accepted():
    """P6-FIX-T02: Real RegressionResult PASS is accepted."""
    before_res, after_res = _setup_controlled_runs()
    evaluator = BeforeAfterEvaluator()
    reg_pass = RegressionResult(
        test_id="reg-timeout-001",
        run_id=after_res.run_id,
        status="PASS",
        measured_evidence={"retries": 2, "fallback": True},
    )
    pair = evaluator.evaluate(
        before_run=before_res,
        after_run=after_res,
        regression_result=reg_pass,
    )
    assert pair.regression_result == "PASS"


def test_p6_fix_t03_regression_result_wrong_run_not_trusted():
    """P6-FIX-T03: Regression result linked to wrong run is rejected or not trusted."""
    before_res, after_res = _setup_controlled_runs()
    evaluator = BeforeAfterEvaluator()
    reg_wrong_run = RegressionResult(
        test_id="reg-timeout-001",
        run_id="run-different-run-999",
        status="PASS",
        measured_evidence={"retries": 2, "fallback": True},
    )
    pair = evaluator.evaluate(
        before_run=before_res,
        after_run=after_res,
        regression_result=reg_wrong_run,
    )
    assert pair.regression_result == "NOT_EVALUATED"


def test_p6_fix_t04_no_regression_evidence_produces_not_evaluated():
    """P6-FIX-T04: No regression evidence produces NOT_EVALUATED."""
    before_res, after_res = _setup_controlled_runs()
    evaluator = BeforeAfterEvaluator()
    pair = evaluator.evaluate(
        before_run=before_res,
        after_run=after_res,
        regression_result=None,
    )
    assert pair.regression_result == "NOT_EVALUATED"


def test_p6_fix_t05_public_evaluator_does_not_depend_on_mock_storage():
    """P6-FIX-T05: Public evaluator does not depend specifically on MockStorage."""
    from typing import Any, Optional
    from reliability_lab.contracts import Storage

    class CustomDictStorage:
        """Custom persistence adapter satisfying Storage protocol without MockStorage."""
        def __init__(self):
            self.data = {}
        def save(self, key: str, item: Any) -> None:
            self.data[key] = item
        def get(self, key: str) -> Optional[Any]:
            return self.data.get(key)
        def list(self) -> list[Any]:
            return list(self.data.values())

    custom_storage = CustomDictStorage()
    assert isinstance(custom_storage, Storage)

    before_res, after_res = _setup_controlled_runs()
    custom_storage.save("b-cust", before_res)
    custom_storage.save("a-cust", after_res)

    evaluator = BeforeAfterEvaluator(storage=custom_storage)
    pair = evaluator.evaluate(before_run="b-cust", after_run="a-cust")
    assert pair.before_run_id == "run-before-001"
    assert pair.after_run_id == "run-after-002"
    assert custom_storage.get(pair.evaluation_id) == pair


def test_p6_fix_t06_every_evaluation_has_unique_evaluation_id():
    """P6-FIX-T06: Every evaluation has a unique evaluation_id."""
    before_res, after_res = _setup_controlled_runs()
    evaluator = BeforeAfterEvaluator()

    pair1 = evaluator.evaluate(before_run=before_res, after_run=after_res)
    pair2 = evaluator.evaluate(before_run=before_res, after_run=after_res)

    assert pair1.evaluation_id is not None
    assert pair2.evaluation_id is not None
    assert pair1.evaluation_id != pair2.evaluation_id
    assert pair1.evaluation_id.startswith("eval-")
    assert pair2.evaluation_id.startswith("eval-")


def test_p6_fix_t07_repeated_evaluation_does_not_destroy_previous_evidence():
    """P6-FIX-T07: Repeated evaluation of identical run IDs does not destroy previous evidence."""
    before_res, after_res = _setup_controlled_runs()
    storage = MockStorage()
    evaluator = BeforeAfterEvaluator(storage=storage)

    pair1 = evaluator.evaluate(before_run=before_res, after_run=after_res)
    pair2 = evaluator.evaluate(before_run=before_res, after_run=after_res)

    stored_1 = storage.get(pair1.evaluation_id)
    stored_2 = storage.get(pair2.evaluation_id)

    assert stored_1 is not None
    assert stored_2 is not None
    assert stored_1.evaluation_id == pair1.evaluation_id
    assert stored_2.evaluation_id == pair2.evaluation_id
    assert stored_1 is not stored_2
    assert len(storage.list()) >= 2


def test_p6_fix_t08_expected_behavior_structured_assertions():
    """P6-FIX-T08: Expected behavior supports deterministic structured assertions."""
    from reliability_lab.contracts import ExpectedBehavior
    before_res, after_res = _setup_controlled_runs()
    evaluator = BeforeAfterEvaluator()

    # 1. Matching structured assertions pass
    valid_eb = ExpectedBehavior(
        description="Canonical timeout handling",
        expected_outcome="FALLBACK",
        fallback_required=True,
        max_retries=2,
        forbidden_failures=["ConnectionResetError"],
    )
    pair = evaluator.evaluate(before_run=before_res, after_run=after_res, expected_behavior=valid_eb)
    assert pair.task_result == "PASS"

    # 2. Max retries exceeded fails (fixed agent did 2 retries; max_retries=1 fails)
    strict_retries_eb = ExpectedBehavior(max_retries=1)
    pair_strict = evaluator.evaluate(before_run=before_res, after_run=after_res, expected_behavior=strict_retries_eb)
    assert pair_strict.task_result == "FAIL"

    # 3. Fallback required assertion fails if outcome is SUCCESS
    success_after = TestRunFixture(
        run_id="run-after-success",
        agent_version="v1.0.1-fixed",
        prompt_version="p1.0",
        request="Where is order #8271?",
        outcome="SUCCESS",
    )
    fallback_req_eb = ExpectedBehavior(fallback_required=True)
    pair_no_fb = evaluator.evaluate(before_run=before_res, after_run=success_after, expected_behavior=fallback_req_eb)
    assert pair_no_fb.task_result == "FAIL"

    # 4. Forbidden failure present fails
    error_after = TestRunFixture(
        run_id="run-after-error",
        agent_version="v1.0.1-fixed",
        prompt_version="p1.0",
        request="Where is order #8271?",
        outcome="FALLBACK",
        errors=["Unhandled DatabaseDeadlock error"],
    )
    forbidden_eb = ExpectedBehavior(forbidden_failures=["DatabaseDeadlock"])
    pair_forbidden = evaluator.evaluate(before_run=before_res, after_run=error_after, expected_behavior=forbidden_eb)
    assert pair_forbidden.task_result == "FAIL"


def test_p6_fix_t09_task_result_no_llm_or_free_text_interpretation():
    """P6-FIX-T09: Task PASS/FAIL does not depend on LLM/free-text interpretation."""
    before_res, after_res = _setup_controlled_runs()
    evaluator = BeforeAfterEvaluator()

    # Even with arbitrary description text with no keywords, deterministic outcome determines result
    pair1 = evaluator.evaluate(
        before_run=before_res,
        after_run=after_res,
        expected_behavior="Arbitrary string with zero domain keywords XYZ123",
    )
    assert pair1.task_result == "PASS"

    # Conversely, having domain keywords in error/response text will NOT cause a failing run to pass
    crashed_after = TestRunFixture(
        run_id="run-after-crashed",
        agent_version="v1.0.1-fixed",
        prompt_version="p1.0",
        request="Where is order #8271?",
        outcome="FAILED",
        errors=["Fatal carrier timeout on ticket #123"],
    )
    pair2 = evaluator.evaluate(
        before_run=before_res,
        after_run=crashed_after,
        expected_behavior="carrier ticket fallback fixed should pass",
    )
    assert pair2.task_result == "FAIL"


def test_p6_fix_t10_missing_metrics_remain_null():
    """P6-FIX-T10: Missing metrics remain null/None without fabrication."""
    evaluator = BeforeAfterEvaluator()
    bare_before = {
        "run_id": "run-bare-b",
        "request": "Where is order #8271?",
        "outcome": "FAILED",
        "agent_version": "v1.0.0-failing",
    }
    bare_after = {
        "run_id": "run-bare-a",
        "request": "Where is order #8271?",
        "outcome": "FALLBACK",
        "agent_version": "v1.0.1-fixed",
    }
    pair = evaluator.evaluate(before_run=bare_before, after_run=bare_after)
    assert pair.before_metrics["tool_calls"] is None
    assert pair.before_metrics["tokens"] is None
    assert pair.before_metrics["latency_ms"] is None
    assert pair.after_metrics["tool_calls"] is None
    assert pair.after_metrics["tokens"] is None
    assert pair.after_metrics["latency_ms"] is None

    deltas = evaluator.compute_deltas(pair.before_metrics, pair.after_metrics)
    assert deltas["tool_calls_delta"] is None
    assert deltas["tool_calls_pct_change"] is None
    assert deltas["tokens_delta"] is None
    assert deltas["tokens_pct_change"] is None


def test_p6_fix_t11_zero_denominator_safe():
    """P6-FIX-T11: Zero denominator percentage calculation is safe (returns None)."""
    evaluator = BeforeAfterEvaluator()
    before_metrics = {"tool_calls": 0, "tokens": 0, "latency_ms": 0}
    after_metrics = {"tool_calls": 5, "tokens": 200, "latency_ms": 500}

    deltas = evaluator.compute_deltas(before_metrics, after_metrics)
    assert deltas["tool_calls_delta"] == 5
    assert deltas["tool_calls_pct_change"] is None
    assert deltas["tokens_delta"] == 200
    assert deltas["tokens_pct_change"] is None
    assert deltas["latency_ms_delta"] == 500
    assert deltas["latency_ms_pct_change"] is None


def test_p6_fix_t12_shared_run_contract_unchanged():
    """P6-FIX-T12: Shared Run contract remains unchanged."""
    import reliability_lab.contracts as contracts
    assert not hasattr(contracts, "Run"), "contracts.py must not create a competing Run schema"
    assert not hasattr(contracts, "Incident"), "contracts.py must not create a competing Incident schema"

    # Evaluator cleanly handles Run where tool_calls is an integer count
    run_int_tool_calls = {
        "run_id": "run-int-tc-after",
        "request": "Where is order #8271?",
        "outcome": "FALLBACK",
        "agent_version": "v1.0.1-fixed",
        "tool_calls": 3,  # Numeric count, not a list
        "tokens": 250,
        "latency_ms": 800,
    }
    evaluator = BeforeAfterEvaluator()
    metrics = evaluator.extract_metrics(run_int_tool_calls)
    assert metrics["tool_calls"] == 3


def test_p6_fix_t13_all_previous_tests_pass():
    """P6-FIX-T13: All previous P0-P6 tests still pass."""
    from reliability_lab.tests.test_suite_p6 import test_p6_t12_full_p0_through_p6_suite_integrity
    test_p6_t12_full_p0_through_p6_suite_integrity()
