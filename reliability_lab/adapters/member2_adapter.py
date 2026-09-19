"""Member 2 Scenario Ingestion Adapter for Member 3 Reliability Lab.

Provides a clean boundary adapter accepting generated test scenarios from Member 2
(Change-to-Test engine & Grounding findings) into the EXISTING Member 3 regression pipeline.

Strict Boundary Guarantees:
- Member 2 owns grounding detection and Change-to-Test generation.
- Member 3 ONLY validates and ingests their resulting scenarios into existing contracts.
- Strictly NO separate test engine, NO requirements database, NO semantic graphs,
  and NO fine-tuned models or RAG evaluation.
"""

from typing import Any, Optional
import uuid

from reliability_lab.contracts import (
    ExpectedBehavior,
    FailureMode,
    RegressionTest,
    ReplayRecord,
    Storage,
)
from reliability_lab.mocks.mock_storage import MockStorage
from reliability_lab.regression.service import RegressionLibrary


VALID_FAILURE_MODES = {m.value for m in FailureMode}


def validate_member2_scenario(payload: Any) -> dict[str, Any]:
    """Validate incoming scenario payload from Member 2.

    Enforces mandatory schema requirements and rejects malformed inputs.

    Args:
        payload: Dictionary representing Member 2 generated scenario.

    Returns:
        Normalized dictionary containing validated fields.

    Raises:
        TypeError: If payload is not a dictionary.
        ValueError: If mandatory fields are missing, empty, or invalid.
    """
    if not isinstance(payload, dict):
        raise TypeError(f"Expected dict scenario payload, got {type(payload).__name__}")

    # 1. Validate test_id / scenario_id
    test_id = payload.get("test_id") or payload.get("scenario_id")
    if not test_id or not isinstance(test_id, str) or not test_id.strip():
        raise ValueError("Member 2 scenario must specify a non-empty 'test_id' or 'scenario_id'.")
    clean_test_id = test_id.strip()

    # 2. Validate scenario / description
    scenario = payload.get("scenario") or payload.get("description")
    if not scenario or not isinstance(scenario, str) or not scenario.strip():
        raise ValueError("Member 2 scenario must specify a non-empty 'scenario' or 'description'.")
    clean_scenario = scenario.strip()

    # 3. Validate user prompt
    prompt = payload.get("prompt")
    if not prompt or not isinstance(prompt, str) or not prompt.strip():
        raise ValueError("Member 2 scenario must specify a non-empty 'prompt'.")
    clean_prompt = prompt.strip()

    # 4. Validate expected_behavior
    raw_eb = payload.get("expected_behavior")
    if raw_eb is None:
        raise ValueError("Member 2 scenario must specify 'expected_behavior'.")
    if isinstance(raw_eb, str) and not raw_eb.strip():
        raise ValueError("Member 2 scenario 'expected_behavior' string must not be empty.")

    # 5. Validate failure_mode if specified
    raw_fm = payload.get("failure_mode", FailureMode.NORMAL.value)
    if isinstance(raw_fm, FailureMode):
        clean_fm = raw_fm
    elif isinstance(raw_fm, str):
        fm_str = raw_fm.strip().lower()
        if fm_str not in VALID_FAILURE_MODES:
            raise ValueError(
                f"Invalid failure_mode '{raw_fm}'. Must be one of: {sorted(list(VALID_FAILURE_MODES))}"
            )
        clean_fm = FailureMode(fm_str)
    else:
        raise ValueError(f"Invalid failure_mode type: {type(raw_fm).__name__}")

    # 6. Tool calls and mocked responses
    tool_calls = payload.get("tool_calls", [{"tool": "get_order", "args": {"order_id": "8271"}}])
    if not isinstance(tool_calls, list):
        raise ValueError("tool_calls must be a list of tool invocations.")

    mocked_responses = payload.get("mocked_responses", {})
    if not isinstance(mocked_responses, dict):
        raise ValueError("mocked_responses must be a dictionary.")

    return {
        "test_id": clean_test_id,
        "scenario": clean_scenario,
        "prompt": clean_prompt,
        "expected_behavior": raw_eb,
        "failure_mode": clean_fm,
        "tool_calls": tool_calls,
        "mocked_responses": mocked_responses,
        "agent_version": payload.get("agent_version", "v1.0.0-failing"),
        "prompt_version": payload.get("prompt_version", "p1.0"),
        "original_incident_id": payload.get("original_incident_id") or payload.get("incident_id"),
    }


def import_member2_scenario(
    payload: Any,
    storage: Optional[Storage] = None,
) -> RegressionTest:
    """Convert Member 2 generated scenario into existing RegressionTest and persist.

    Reuses existing ReplayRecord, existing RegressionLibrary, and existing Storage.
    Does NOT create duplicate test engines, databases, or semantic graphs.

    Args:
        payload: Raw Member 2 scenario payload dictionary.
        storage: Optional Storage adapter adhering to Storage protocol.

    Returns:
        Persisted RegressionTest instance ready for execution by existing RegressionRunner.
    """
    validated = validate_member2_scenario(payload)
    store = storage or MockStorage()
    lib = RegressionLibrary(storage=store)

    # 1. Construct existing ReplayRecord domain contract
    replay_run_id = f"run-m2-{uuid.uuid4().hex[:8]}"
    replay_record = ReplayRecord(
        run_id=replay_run_id,
        prompt=validated["prompt"],
        agent_version=validated["agent_version"],
        prompt_version=validated["prompt_version"],
        failure_mode=validated["failure_mode"],
        tool_calls=validated["tool_calls"],
        mocked_responses=validated["mocked_responses"],
        expected_behavior=validated["expected_behavior"],
        original_incident_id=validated["original_incident_id"],
    )
    store.save(replay_record.run_id, replay_record)
    store.save(f"replay-{replay_record.run_id}", replay_record)

    # 2. Register into existing RegressionLibrary as an authentic RegressionTest
    test = lib.save_test(
        {
            "test_id": validated["test_id"],
            "scenario": validated["scenario"],
            "expected_behavior": validated["expected_behavior"],
            "replay_record_id": replay_record.run_id,
        },
        replay_record=replay_record,
    )

    return test
