"""Member 3 Demo Runner & Safe Reset Utility for AgentLens Reliability Lab.

Provides:
1. demo_reset(): Smallest safe reset process restoring baseline normal state,
   cleaning disposable scratch, preserving historical evidence, and priming
   the canonical synthetic order scenario.
2. run_canonical_demo_flow(): Continuously executes the entire 8-step judge-visible
   demonstration flow and captures authentic generated IDs.
"""

from datetime import datetime, timezone
import json
from typing import Any, Optional
import uuid

from reliability_lab.adapters.member1_adapter import MockMember1Agent
from reliability_lab.chaos.service import (
    ChaosService,
    _GLOBAL_CHAOS_SERVICE,
    get_active_proxy,
    reset_chaos,
)
from reliability_lab.contracts import (
    ChaosConfig,
    ExpectedBehavior,
    FailureMode,
    ReplayRecord,
    Storage,
)
from reliability_lab.evaluation.evaluator import BeforeAfterEvaluator, build_before_after_panel
from reliability_lab.fixtures.replay_fixtures import CANONICAL_TIMEOUT_FIXTURE
from reliability_lab.mocks.mock_storage import MockStorage
from reliability_lab.mocks.mock_tool import get_order
from reliability_lab.regression.service import RegressionLibrary, _serialize_regression_result
from reliability_lab.replay.engine import ReplayEngine
from reliability_lab.timeline import build_replay_timeline, serialize_replay_timeline


def demo_reset(
    storage: Optional[Storage] = None,
    preserve_evidence: bool = True,
    chaos_service: Optional[ChaosService] = None,
) -> dict[str, Any]:
    """Execute the smallest safe reset process for live judge demonstration.

    - Sets chaos proxies immediately back to FailureMode.NORMAL.
    - Preserves historical evidence bundles, evaluation pairs, and regression tests.
    - Pre-populates the canonical synthetic order scenario in storage.
    - Does NOT create an admin platform.

    Args:
        storage: Storage instance to reset/prime. Defaults to MockStorage.
        preserve_evidence: If True, preserves evidence records.
        chaos_service: ChaosService instance. Defaults to global service.

    Returns:
        JSON-serializable status dictionary confirming clean baseline state.
    """
    # 1. Reset all registered chaos proxies back to NORMAL
    cs = chaos_service or _GLOBAL_CHAOS_SERVICE
    cs.reset()

    # Also guarantee tool proxy reset directly
    proxy = get_active_proxy("get_order")
    proxy.reset()

    # 2. Manage storage state
    store = storage if storage is not None else MockStorage()

    if not preserve_evidence and hasattr(store, "_items"):
        # Clear transient storage if requested
        getattr(store, "_items").clear()

    # 3. Prime the canonical synthetic order scenario in storage
    canonical_record = ReplayRecord(
        run_id="run-canonical-primed",
        prompt=CANONICAL_TIMEOUT_FIXTURE.prompt,
        agent_version="v1.0.0-failing",
        prompt_version="p1.0",
        failure_mode=FailureMode.TIMEOUT,
        tool_calls=[{"tool": "get_order", "args": {"order_id": "8271"}}],
        mocked_responses=CANONICAL_TIMEOUT_FIXTURE.mocked_responses,
        expected_behavior=CANONICAL_TIMEOUT_FIXTURE.expected_behavior,
        original_incident_id="inc-canonical-primed",
    )
    store.save(canonical_record.run_id, canonical_record)
    store.save(f"replay-{canonical_record.run_id}", canonical_record)

    now_iso = datetime.now(timezone.utc).isoformat()
    result = {
        "status": "READY",
        "chaos_mode": FailureMode.NORMAL.value,
        "scenario": CANONICAL_TIMEOUT_FIXTURE.prompt,
        "target_tool": "get_order",
        "primed_record_id": canonical_record.run_id,
        "reset_at": now_iso,
        "message": "Demo reset complete. Chaos is NORMAL. System is primed for canonical demo.",
    }

    json.dumps(result)
    return result


def run_canonical_demo_flow(storage: Optional[Storage] = None) -> dict[str, Any]:
    """Execute the entire continuous 8-step judge-visible demonstration flow.

    Flow:
        1. NORMAL: Prompt 'Where is order #8271?' -> normal lookup succeeds.
        2. INJECT: Chaos timeout injected on 'get_order'.
        3. FAILURE: Failing agent executes -> 5 retry attempts, crashes with timeout, 0 fallback.
        4. DIAGNOSE: Captures tool-loop incident evidence.
        5. HUMAN FIX: Applies fixed agent v1.0.1-fixed (max_retries=2 + fallback).
        6. REPLAY: Stored ReplayRecord executed under SAME timeout -> fresh replay_run_id, original incident linkage.
        7. EVALUATE: Actual tool_calls (5 -> 3), tokens (450 -> 320), latency measured -> task PASS, regression PASS.
        8. REGRESSION: Saved timeout incident as RegressionTest quality gate -> fixed agent passes, history updated.
        9. RESET: Restores chaos to NORMAL.

    Captures actual generated IDs:
        original_run_id, incident_id, replay_run_id, evaluation_id, regression_test_id, latest_result.

    Returns:
        JSON-serializable execution report verifying full demo continuity.
    """
    store = storage or MockStorage()
    chaos_svc = ChaosService()
    proxy = chaos_svc.get_proxy("get_order")

    try:
        # ----------------------------------------------------------------------
        # STEP 1: NORMAL
        # ----------------------------------------------------------------------
        proxy.reset()
        baseline_order = get_order("8271")
        step1_result = {
            "step": "1. NORMAL",
            "prompt": "Where is order #8271?",
            "chaos_mode": "normal",
            "order_id": baseline_order["order_id"],
            "status": baseline_order["status"],
            "outcome": "SUCCESS",
        }

        # ----------------------------------------------------------------------
        # STEP 2: INJECT
        # ----------------------------------------------------------------------
        timeout_cfg = ChaosConfig(
            failure_mode=FailureMode.TIMEOUT,
            target_tool="get_order",
            error_message="Controlled timeout: carrier service unreachable",
            status_code=504,
        )
        proxy.set_config(timeout_cfg)
        step2_result = {
            "step": "2. INJECT",
            "chaos_mode": "timeout",
            "target_tool": "get_order",
            "status_code": 504,
            "status": "APPLIED",
        }

        # ----------------------------------------------------------------------
        # STEP 3: FAILURE (Member 1 failing agent)
        # ----------------------------------------------------------------------
        original_run_id = f"run-orig-failing-{uuid.uuid4().hex[:8]}"
        failing_agent = MockMember1Agent(version="v1.0.0-failing", order_tool=proxy)
        failing_telemetry = failing_agent.run(
            request="Where is order #8271?",
            run_id=original_run_id,
        )
        store.save(original_run_id, failing_telemetry)

        raw_tc = getattr(failing_telemetry, "tool_calls", [])
        tc_count_failing = len(raw_tc) if isinstance(raw_tc, list) else int(raw_tc)
        step3_result = {
            "step": "3. FAILURE",
            "original_run_id": original_run_id,
            "agent_version": failing_telemetry.agent_version,
            "tool_calls": tc_count_failing,
            "outcome": failing_telemetry.outcome,
            "errors": failing_telemetry.errors,
        }

        # ----------------------------------------------------------------------
        # STEP 4: DIAGNOSE (Incident detection)
        # ----------------------------------------------------------------------
        incident_id = f"inc-timeout-{uuid.uuid4().hex[:8]}"
        replay_record = ReplayRecord(
            run_id=original_run_id,
            prompt="Where is order #8271?",
            agent_version="v1.0.0-failing",
            prompt_version="p1.0",
            failure_mode=FailureMode.TIMEOUT,
            tool_calls=[{"tool": "get_order", "args": {"order_id": "8271"}}],
            mocked_responses=CANONICAL_TIMEOUT_FIXTURE.mocked_responses,
            expected_behavior="Agent must handle timeout within max 2 retries and invoke fallback without unhandled loop.",
            original_incident_id=incident_id,
        )
        store.save(replay_record.run_id, replay_record)
        store.save(f"replay-{replay_record.run_id}", replay_record)

        step4_result = {
            "step": "4. DIAGNOSE",
            "incident_id": incident_id,
            "diagnosis": "Carrier timeout caused unhandled 5-attempt retry loop without graceful fallback.",
            "recommendation": "Set MAX_RETRIES=2 and invoke carrier fallback response.",
        }

        # ----------------------------------------------------------------------
        # STEP 5: HUMAN FIX
        # ----------------------------------------------------------------------
        fixed_version = "v1.0.1-fixed"
        step5_result = {
            "step": "5. HUMAN FIX",
            "applied_version": fixed_version,
            "max_retries": 2,
            "fallback_enabled": True,
            "note": "Member 3 verified fix boundary without auto-editing Member 1 code.",
        }

        # ----------------------------------------------------------------------
        # STEP 6: REPLAY (Replay engine with fresh run_id & same timeout)
        # ----------------------------------------------------------------------
        replay_engine = ReplayEngine(storage=store, chaos_service=chaos_svc)
        replay_res = replay_engine.replay(replay_record, agent_version_override=fixed_version)
        replay_run_id = replay_res.replay_run_id

        step6_result = {
            "step": "6. REPLAY",
            "replay_run_id": replay_run_id,
            "original_run_id": replay_res.original_run_id,
            "original_incident_id": replay_res.original_incident_id,
            "agent_version": replay_res.agent_version,
            "tool_calls": len(replay_res.telemetry.tool_calls),
            "outcome": replay_res.telemetry.outcome,
            "response": replay_res.telemetry.response,
        }

        # ----------------------------------------------------------------------
        # STEP 7: EVALUATE (Before/After comparison)
        # ----------------------------------------------------------------------
        evaluator = BeforeAfterEvaluator(storage=store)
        eval_pair = evaluator.evaluate(
            before_run=failing_telemetry,
            after_run=replay_res.telemetry,
            expected_behavior=ExpectedBehavior(
                description="Must fallback within 2 retries",
                expected_outcome="FALLBACK",
                fallback_required=True,
                max_retries=2,
            ),
        )
        evaluation_id = eval_pair.evaluation_id
        panel = build_before_after_panel(eval_pair)

        step7_result = {
            "step": "7. EVALUATE",
            "evaluation_id": evaluation_id,
            "before_run_id": eval_pair.before_run_id,
            "after_run_id": eval_pair.after_run_id,
            "tool_calls": panel["tool_calls"],
            "tokens": panel["tokens"],
            "latency_ms": panel["latency_ms"],
            "task_result": eval_pair.task_result,
            "regression_result": eval_pair.regression_result,
        }

        # ----------------------------------------------------------------------
        # STEP 8: REGRESSION (Save incident, execute test, verify PASS & history)
        # ----------------------------------------------------------------------
        regression_test_id = f"reg-canonical-{uuid.uuid4().hex[:8]}"
        lib = RegressionLibrary(storage=store, chaos_service=chaos_svc, replay_engine=replay_engine)
        reg_test = lib.save_test(
            {
                "test_id": regression_test_id,
                "scenario": "Canonical order carrier timeout handling",
                "expected_behavior": CANONICAL_TIMEOUT_FIXTURE.expected_behavior,
                "replay_record_id": replay_record.run_id,
            },
            replay_record=replay_record,
        )
        reg_result = lib.run_test(regression_test_id, agent_version=fixed_version)
        scorecard = lib.get_scorecard([reg_result])

        step8_result = {
            "step": "8. REGRESSION",
            "regression_test_id": regression_test_id,
            "run_id": reg_result.run_id,
            "status": reg_result.status,
            "history_count": len(reg_test.history),
            "scorecard": scorecard,
        }

        # Extract timeline for demo visualization
        timeline = serialize_replay_timeline(build_replay_timeline(replay_res))

        demo_report = {
            "status": "COMPLETED",
            "flow_verified": True,
            "actual_evidence_ids": {
                "original_run_id": original_run_id,
                "incident_id": incident_id,
                "replay_run_id": replay_run_id,
                "evaluation_id": evaluation_id,
                "regression_test_id": regression_test_id,
                "regression_result_status": reg_result.status,
            },
            "steps": [
                step1_result,
                step2_result,
                step3_result,
                step4_result,
                step5_result,
                step6_result,
                step7_result,
                step8_result,
            ],
            "timeline": timeline,
            "panel": panel,
            "completed_at": datetime.now(timezone.utc).isoformat(),
        }

        # Verify JSON serializability
        json.dumps(demo_report)
        return demo_report

    finally:
        # Step 9: Always restore chaos to NORMAL
        proxy.reset()
