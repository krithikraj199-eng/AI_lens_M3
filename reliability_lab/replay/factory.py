"""Replay Candidate and Record Factory.

Generates deterministic ReplayRecords from completed scenario runs or automatically
converts Member 2 Incident + Run pairs into ReplayRecord candidates with zero manual copy/paste.
"""

from typing import Any, Optional
from reliability_lab.contracts import ReplayRecord, FailureMode, ChaosConfig


def sanitize_data(data: Any) -> Any:
    """Recursively strip sensitive keys (API keys, authorization headers, passwords)."""
    if isinstance(data, dict):
        sanitized = {}
        forbidden_keys = {"authorization", "bearer", "api_key", "secret", "password", "token"}
        for k, v in data.items():
            if any(forbidden in k.lower() for forbidden in forbidden_keys):
                continue
            sanitized[k] = sanitize_data(v)
        return sanitized
    if isinstance(data, list):
        return [sanitize_data(item) for item in data]
    return data


def normalize_failure_type(failure_type: str) -> str:
    """Map Member 2 failure types to canonical Member 3 FailureMode values."""
    ft_lower = failure_type.lower()
    if "timeout" in ft_lower or "loop" in ft_lower:
        return FailureMode.TIMEOUT.value
    if "rate_limit" in ft_lower or "429" in ft_lower:
        return FailureMode.RATE_LIMIT.value
    if "empty" in ft_lower:
        return FailureMode.EMPTY_RESULT.value
    if "slow" in ft_lower or "latency" in ft_lower:
        return FailureMode.SLOW_RESPONSE.value
    if "wrong" in ft_lower:
        return FailureMode.WRONG_TOOL.value
    return FailureMode.NORMAL.value


def create_replay_record_from_execution(
    result: Any,
    config: ChaosConfig,
    expected_behavior: str,
    original_incident_id: Optional[str] = None,
    mocked_responses: Optional[dict[str, Any]] = None,
) -> ReplayRecord:
    """Create a ReplayRecord directly from a completed agent execution result.

    Args:
        result: AgentExecutionResult instance.
        config: ChaosConfig active during the run.
        expected_behavior: Expected behavior statement.
        original_incident_id: Optional incident ID.
        mocked_responses: Optional mocked tool response dictionary.

    Returns:
        Populated ReplayRecord.
    """
    mode_val = config.failure_mode.value if hasattr(config.failure_mode, "value") else str(config.failure_mode)

    # Build mocked response if not provided
    if mocked_responses is None:
        mocked_responses = {}
        if mode_val == FailureMode.TIMEOUT.value:
            mocked_responses["get_order"] = {
                "status": "TIMEOUT",
                "error": config.error_message or "Controlled chaos timeout",
            }
        elif mode_val == FailureMode.RATE_LIMIT.value:
            mocked_responses["get_order"] = {
                "status_code": config.status_code or 429,
                "error": config.error_message or "Too Many Requests: rate limit exceeded",
            }
        elif mode_val == FailureMode.EMPTY_RESULT.value:
            mocked_responses["get_order"] = {}

    return ReplayRecord(
        run_id=result.run_id,
        prompt=result.request,
        agent_version=result.agent_version,
        prompt_version=result.prompt_version,
        failure_mode=mode_val,
        tool_calls=sanitize_data(result.tool_calls),
        mocked_responses=sanitize_data(mocked_responses),
        expected_behavior=expected_behavior,
        original_incident_id=original_incident_id,
    )


def create_replay_candidate_from_incident(
    incident: Any,
    run: Any,
    expected_behavior: Optional[str] = None,
    mocked_responses: Optional[dict[str, Any]] = None,
) -> ReplayRecord:
    """Automatically convert a Member 2 Incident + Run pair into a ReplayRecord.

    Preserves linkage to original incident and run without manual reconstruction.

    Args:
        incident: Member 2 Incident structure (or TestIncidentFixture).
        run: Member 2 Run structure (or TestRunFixture).
        expected_behavior: Optional expected behavior override.
        mocked_responses: Optional mocked response dictionary.

    Returns:
        Populated ReplayRecord candidate ready for storage and replay.
    """
    failure_mode = normalize_failure_type(getattr(incident, "failure_type", "TIMEOUT"))

    # Resolve expected behavior from recommended fix or default
    if expected_behavior is None:
        rec_fix = getattr(incident, "recommended_fix", None)
        if rec_fix:
            expected_behavior = rec_fix
        else:
            expected_behavior = f"Agent must handle {failure_mode} gracefully with bounded retries or fallback."

    # Extract or synthesize mocked responses
    if mocked_responses is None:
        evidence = getattr(incident, "evidence", {}) or {}
        if "mocked_responses" in evidence:
            mocked_responses = evidence["mocked_responses"]
        else:
            mocked_responses = {}
            if failure_mode == FailureMode.TIMEOUT.value:
                mocked_responses["get_order"] = {
                    "status": "TIMEOUT",
                    "error": evidence.get("last_error", "TimeoutError: carrier service unreachable"),
                }
            elif failure_mode == FailureMode.RATE_LIMIT.value:
                mocked_responses["get_order"] = {
                    "status_code": 429,
                    "error": "Too Many Requests",
                }

    tool_calls = getattr(run, "tool_calls", []) or []

    return ReplayRecord(
        run_id=getattr(run, "run_id"),
        prompt=getattr(run, "request", ""),
        agent_version=getattr(run, "agent_version", "unknown"),
        prompt_version=getattr(run, "prompt_version", "unknown"),
        failure_mode=failure_mode,
        tool_calls=sanitize_data(tool_calls),
        mocked_responses=sanitize_data(mocked_responses),
        expected_behavior=expected_behavior,
        original_incident_id=getattr(incident, "incident_id"),
    )
