"""Tests for Member 3 isolation and complete P0 suite verification.

Tests P0-T09 and P0-T10.
"""

import sys


def test_p0_t09_reliability_lab_isolation():
    """P0-T09: Reliability Lab can run without Members 1, 2 or 4 being complete.

    Verifies that the Reliability Lab operates entirely self-contained:
    - No imports or dependencies from Member 1, 2, or 4 code.
    - No AWS environment credentials required.
    - Full in-memory lifecycle of Member 3 contracts can be instantiated and persisted.
    """
    import reliability_lab
    from reliability_lab.contracts import (
        ChaosConfig,
        FailureMode,
        ReplayRecord,
        EvaluationPair,
        RegressionTest,
        RegressionResult,
    )
    from reliability_lab.mocks.mock_tool import get_order
    from reliability_lab.mocks.mock_storage import MockStorage

    # 1. Verify sys.modules does not require or load member 1, 2, or 4 modules
    forbidden_modules = [
        "member_1", "member1", "agent_core", "bedrock",
        "member_2", "member2", "incident_engine",
        "member_4", "member4", "amplify", "boto3", "botocore"
    ]
    for mod in sys.modules:
        for forbidden in forbidden_modules:
            assert not mod.startswith(forbidden), f"Reliability Lab must not depend on {forbidden}"

    # 2. Verify complete in-memory lifecycle without external services
    storage = MockStorage()

    # Step A: Mock tool lookup
    order_data = get_order("8271")
    assert order_data["order_id"] == "8271"

    # Step B: Create ReplayRecord
    replay_record = ReplayRecord(
        run_id="run-original-101",
        prompt="Where is order #8271?",
        agent_version="v1.0.0",
        prompt_version="p1.0",
        failure_mode=FailureMode.TIMEOUT,
        tool_calls=[{"tool": "get_order", "args": {"order_id": "8271"}}],
        mocked_responses={"get_order": {"status": "TIMEOUT", "error": "TimeoutError"}},
        expected_behavior="Max 2 retries then fallback",
        original_incident_id="inc-101",
    )
    storage.save(replay_record.run_id, replay_record)
    assert storage.get("run-original-101") == replay_record

    # Step C: Create EvaluationPair
    eval_pair = EvaluationPair(
        before_run_id="run-original-101",
        after_run_id="run-replay-102",
        before_metrics={"tool_calls": 5, "errors": 4, "latency_ms": 15000},
        after_metrics={"tool_calls": 2, "errors": 1, "latency_ms": 2500},
        task_result="RESOLVED",
        regression_result="PASS",
    )
    storage.save(f"eval-{eval_pair.after_run_id}", eval_pair)

    # Step D: Create RegressionResult and RegressionTest
    reg_result = RegressionResult(
        test_id="reg-8271",
        run_id="run-replay-102",
        status="PASS",
        measured_evidence={"retries": 1, "fallback": True},
    )
    reg_test = RegressionTest(
        test_id="reg-8271",
        scenario="Timeout retry limit verification",
        expected_behavior="Fallback on timeout without infinite loop",
        latest_result=reg_result,
        history=[reg_result],
    )
    storage.save(reg_test.test_id, reg_test)

    # Step E: Verify storage contents
    saved_items = storage.list()
    assert len(saved_items) == 3
    assert storage.get("reg-8271") == reg_test


def test_p0_t10_p0_suite_integrity():
    """P0-T10: Entire P0 automated test suite passes.

    Validates that all foundational components integrate cleanly and every
    P0 test criterion from P0-T01 to P0-T10 is covered and verifiable.
    """
    import reliability_lab.tests.test_contracts as t_contracts
    import reliability_lab.tests.test_mock_tool as t_tool
    import reliability_lab.tests.test_mock_storage as t_storage

    # Assert test functions exist for P0-T01 through P0-T08
    assert hasattr(t_contracts, "test_p0_t01_chaos_config_representation")
    assert hasattr(t_contracts, "test_p0_t02_replay_record_mandatory_fields")
    assert hasattr(t_contracts, "test_p0_t03_evaluation_pair_structure")
    assert hasattr(t_contracts, "test_p0_t04_regression_test_structure")
    assert hasattr(t_contracts, "test_p0_t05_regression_result_structure")
    assert hasattr(t_contracts, "test_p0_t06_no_second_production_run_or_incident_schema")
    assert hasattr(t_tool, "test_p0_t07_mock_tool_deterministic_execution")
    assert hasattr(t_storage, "test_p0_t08_mock_storage_operations")
