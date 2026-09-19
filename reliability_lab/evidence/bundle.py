"""Member 3 Hackathon Evidence Bundle for AgentLens.

Constructs canonical timeout evidence packages retaining the complete causal chain:
    original run_id
    incident_id
    ChaosConfig
    ReplayRecord
    replay run_id
    EvaluationPair
    RegressionTest
    RegressionResult / history

Strictly uses measured telemetry and real execution results with zero fabrication.
"""

from dataclasses import asdict, dataclass, field, is_dataclass
from datetime import datetime, timezone
import json
from typing import Any, Optional
import uuid

from reliability_lab.adapters.member1_adapter import MockMember1Agent
from reliability_lab.chaos.service import ChaosService
from reliability_lab.contracts import (
    ChaosConfig,
    EvaluationPair,
    ExpectedBehavior,
    FailureMode,
    RegressionResult,
    RegressionTest,
    ReplayRecord,
    Storage,
)
from reliability_lab.evaluation.evaluator import BeforeAfterEvaluator
from reliability_lab.fixtures.replay_fixtures import CANONICAL_TIMEOUT_FIXTURE
from reliability_lab.mocks.mock_storage import MockStorage
from reliability_lab.regression.service import RegressionLibrary, _serialize_regression_result
from reliability_lab.replay.engine import ReplayEngine
from reliability_lab.timeline import ReplayTimeline, build_replay_timeline, serialize_replay_timeline


@dataclass
class EvidenceBundle:
    """Canonical hackathon evidence package preserving full causal provenance."""
    bundle_id: str
    incident_id: str
    original_run_id: str
    replay_run_id: str
    chaos_config: ChaosConfig
    replay_record: ReplayRecord
    evaluation_pair: EvaluationPair
    regression_test: RegressionTest
    regression_history: list[RegressionResult]
    timeline: Optional[ReplayTimeline] = None
    created_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())


def build_canonical_evidence_bundle(storage: Optional[Storage] = None) -> EvidenceBundle:
    """Execute canonical timeout scenario and generate an auditable EvidenceBundle.

    1. Executes failing agent under controlled timeout -> original run
    2. Retains active ChaosConfig
    3. Creates ReplayRecord linking original run_id and incident_id
    4. Executes replay with fixed agent -> fresh replay run
    5. Generates EvaluationPair comparing original and replay
    6. Registers RegressionTest quality gate
    7. Executes regression test and captures full history
    8. Extracts chronological ReplayTimeline
    9. Persists and returns EvidenceBundle
    """
    store = storage or MockStorage()
    chaos_service = ChaosService()
    replay_engine = ReplayEngine(storage=store, chaos_service=chaos_service)
    evaluator = BeforeAfterEvaluator(storage=store)
    regression_lib = RegressionLibrary(storage=store, chaos_service=chaos_service, replay_engine=replay_engine)

    # 1. Incident correlation identifiers
    incident_id = f"inc-canonical-{uuid.uuid4().hex[:8]}"
    original_run_id = f"run-orig-failing-{uuid.uuid4().hex[:8]}"

    # 2. Chaos configuration for canonical timeout
    chaos_cfg = ChaosConfig(
        failure_mode=FailureMode.TIMEOUT,
        target_tool="get_order",
        error_message="Controlled timeout: carrier service unreachable",
        delay_ms=0,
        status_code=504,
    )

    # 3. Execute original failing agent under controlled chaos
    proxy = chaos_service.get_proxy("get_order")
    proxy.set_config(chaos_cfg)
    try:
        failing_agent = MockMember1Agent(version="v1.0.0-failing")
        orig_telemetry = failing_agent.run(
            request=CANONICAL_TIMEOUT_FIXTURE.prompt,
            run_id=original_run_id,
        )
    finally:
        proxy.reset()

    store.save(original_run_id, orig_telemetry)

    # 4. Create ReplayRecord preserving original linkages
    replay_record = ReplayRecord(
        run_id=original_run_id,
        prompt=CANONICAL_TIMEOUT_FIXTURE.prompt,
        agent_version="v1.0.0-failing",
        prompt_version="p1.0",
        failure_mode=FailureMode.TIMEOUT,
        tool_calls=[{"tool": "get_order", "args": {"order_id": "8271"}}],
        mocked_responses=CANONICAL_TIMEOUT_FIXTURE.mocked_responses,
        expected_behavior=CANONICAL_TIMEOUT_FIXTURE.expected_behavior,
        original_incident_id=incident_id,
    )
    store.save(replay_record.run_id, replay_record)
    store.save(f"replay-{replay_record.run_id}", replay_record)

    # 5. Execute controlled replay with candidate fixed agent
    replay_res = replay_engine.replay(replay_record, agent_version_override="v1.0.1-fixed")
    replay_run_id = replay_res.replay_run_id

    # 6. Evaluate before/after pair
    eb = ExpectedBehavior.from_val(CANONICAL_TIMEOUT_FIXTURE.expected_behavior)
    eval_pair = evaluator.evaluate(
        before_run=orig_telemetry,
        after_run=replay_res.telemetry,
        expected_behavior=eb,
        expected_prompt=CANONICAL_TIMEOUT_FIXTURE.prompt,
        expected_failure_mode="timeout",
    )

    # 7. Register and execute Regression Test
    reg_test = regression_lib.save_test(
        {
            "test_id": f"reg-test-{uuid.uuid4().hex[:8]}",
            "scenario": "Canonical order carrier timeout handling",
            "expected_behavior": CANONICAL_TIMEOUT_FIXTURE.expected_behavior,
            "replay_record_id": replay_record.run_id,
        },
        replay_record=replay_record,
    )
    reg_result = regression_lib.run_test(reg_test.test_id, agent_version="v1.0.1-fixed")

    # 8. Build chronological replay timeline from replay telemetry
    timeline = build_replay_timeline(replay_res)

    # 9. Assemble bundle
    bundle_id = f"bundle-{uuid.uuid4().hex[:10]}"
    bundle = EvidenceBundle(
        bundle_id=bundle_id,
        incident_id=incident_id,
        original_run_id=original_run_id,
        replay_run_id=replay_run_id,
        chaos_config=chaos_cfg,
        replay_record=replay_record,
        evaluation_pair=eval_pair,
        regression_test=reg_test,
        regression_history=list(reg_test.history),
        timeline=timeline,
    )

    store.save(bundle.bundle_id, bundle)
    return bundle


def serialize_evidence_bundle(bundle: EvidenceBundle) -> dict[str, Any]:
    """Convert an EvidenceBundle into a JSON-serializable dictionary for Member 4 / Hackathon export."""
    # ChaosConfig
    cfg_dict = {
        "failure_mode": bundle.chaos_config.failure_mode.value if hasattr(bundle.chaos_config.failure_mode, "value") else str(bundle.chaos_config.failure_mode),
        "target_tool": bundle.chaos_config.target_tool,
        "delay_ms": bundle.chaos_config.delay_ms,
        "error_message": bundle.chaos_config.error_message,
        "status_code": bundle.chaos_config.status_code,
    }

    # ReplayRecord
    fm_val = bundle.replay_record.failure_mode.value if hasattr(bundle.replay_record.failure_mode, "value") else str(bundle.replay_record.failure_mode)
    raw_eb = bundle.replay_record.expected_behavior
    rec_dict = {
        "run_id": bundle.replay_record.run_id,
        "prompt": bundle.replay_record.prompt,
        "agent_version": bundle.replay_record.agent_version,
        "prompt_version": bundle.replay_record.prompt_version,
        "failure_mode": fm_val,
        "tool_calls": bundle.replay_record.tool_calls,
        "mocked_responses": bundle.replay_record.mocked_responses,
        "expected_behavior": asdict(raw_eb) if is_dataclass(raw_eb) else str(raw_eb),
        "original_incident_id": bundle.replay_record.original_incident_id,
        "created_at": bundle.replay_record.created_at,
    }

    # EvaluationPair
    eval_dict = {
        "evaluation_id": bundle.evaluation_pair.evaluation_id,
        "before_run_id": bundle.evaluation_pair.before_run_id,
        "after_run_id": bundle.evaluation_pair.after_run_id,
        "before_metrics": bundle.evaluation_pair.before_metrics,
        "after_metrics": bundle.evaluation_pair.after_metrics,
        "task_result": bundle.evaluation_pair.task_result,
        "regression_result": bundle.evaluation_pair.regression_result,
        "evaluated_at": bundle.evaluation_pair.evaluated_at,
    }

    # RegressionTest & History
    test_eb = bundle.regression_test.expected_behavior
    test_dict = {
        "test_id": bundle.regression_test.test_id,
        "scenario": bundle.regression_test.scenario,
        "expected_behavior": asdict(test_eb) if is_dataclass(test_eb) else str(test_eb),
        "replay_record_id": bundle.regression_test.replay_record_id,
        "latest_result": _serialize_regression_result(bundle.regression_test.latest_result),
        "history": [_serialize_regression_result(r) for r in bundle.regression_history],
        "created_at": bundle.regression_test.created_at,
    }

    timeline_dict = serialize_replay_timeline(bundle.timeline) if bundle.timeline else None

    result = {
        "bundle_id": bundle.bundle_id,
        "incident_id": bundle.incident_id,
        "original_run_id": bundle.original_run_id,
        "replay_run_id": bundle.replay_run_id,
        "chaos_config": cfg_dict,
        "replay_record": rec_dict,
        "evaluation_pair": eval_dict,
        "regression_test": test_dict,
        "regression_history": [_serialize_regression_result(r) for r in bundle.regression_history],
        "timeline": timeline_dict,
        "created_at": bundle.created_at,
    }

    # Ensure JSON serializability
    json.dumps(result)
    return result
