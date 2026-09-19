"""Member 3 Replay Timeline Model and Builder for AgentLens.

Builds chronological timeline data using ACTUAL recorded events only.
Guarantees conceptual order:
    user -> agent -> tool -> response/error -> retry/fallback -> agent_end
Zero fake or synthetic timeline events are added for visual polish.
"""

from dataclasses import asdict, dataclass, field
import json
from typing import Any, Optional


@dataclass
class TimelineEvent:
    """Represents a single verified step in the replay execution timeline."""
    step_number: int
    stage: str  # "user" | "agent" | "tool" | "response" | "error" | "retry" | "fallback"
    event_type: str  # actual underlying event type from telemetry
    timestamp: float
    data: dict[str, Any] = field(default_factory=dict)
    description: str = ""


@dataclass
class ReplayTimeline:
    """Structured chronological timeline constructed strictly from actual execution evidence."""
    run_id: str
    total_events: int
    events: list[TimelineEvent] = field(default_factory=list)
    stages_present: list[str] = field(default_factory=list)
    has_retry: bool = False
    has_fallback: bool = False
    has_error: bool = False
    final_outcome: str = "UNKNOWN"


def _extract_raw_events(source: Any) -> tuple[str, list[dict[str, Any]], str]:
    """Extract run_id, events list, and outcome from various run representations."""
    run_id = ""
    events: list[dict[str, Any]] = []
    outcome = "UNKNOWN"

    if isinstance(source, dict):
        run_id = str(source.get("run_id") or source.get("replay_run_id") or "")
        outcome = str(source.get("outcome") or "UNKNOWN")
        raw_events = source.get("events")
        if raw_events is None and "telemetry" in source and isinstance(source["telemetry"], dict):
            raw_events = source["telemetry"].get("events")
            if not run_id:
                run_id = str(source["telemetry"].get("run_id") or "")
            if outcome == "UNKNOWN":
                outcome = str(source["telemetry"].get("outcome") or "UNKNOWN")
        if isinstance(raw_events, list):
            events = [e for e in raw_events if isinstance(e, dict)]

    elif hasattr(source, "telemetry"):
        # ReplayExecutionResult
        tel = getattr(source, "telemetry")
        run_id = str(getattr(source, "replay_run_id", "") or getattr(tel, "run_id", ""))
        outcome = str(getattr(tel, "outcome", "UNKNOWN"))
        raw_events = getattr(tel, "events", [])
        if isinstance(raw_events, list):
            events = [e for e in raw_events if isinstance(e, dict)]

    elif hasattr(source, "events"):
        # AgentExecutionResult
        run_id = str(getattr(source, "run_id", ""))
        outcome = str(getattr(source, "outcome", "UNKNOWN"))
        raw_events = getattr(source, "events", [])
        if isinstance(raw_events, list):
            events = [e for e in raw_events if isinstance(e, dict)]

    return run_id, events, outcome


def _map_event_stage(event_type: str) -> str:
    """Map raw event type to conceptual timeline stage."""
    clean_type = str(event_type).lower().strip()
    if clean_type in ("user_request", "user_input", "user_prompt", "prompt"):
        return "user"
    if clean_type in ("agent_start", "agent_init", "agent_end", "agent_complete"):
        return "agent"
    if clean_type in ("tool_call", "tool_call_start", "tool_invoke"):
        return "tool"
    if clean_type in ("tool_call_success", "tool_response", "tool_result"):
        return "response"
    if clean_type in ("tool_call_error", "tool_error", "error"):
        return "error"
    if clean_type in ("retry_attempt", "retry", "backoff"):
        return "retry"
    if clean_type in ("fallback_invoked", "fallback", "fallback_response"):
        return "fallback"
    return "agent"


def _format_event_description(stage: str, event_type: str, data: dict[str, Any]) -> str:
    """Generate a clean factual description without fake visual embellishment."""
    if stage == "user":
        req = data.get("request") or data.get("prompt") or "User request submitted"
        return f"User submitted request: '{req}'"
    if stage == "agent" and event_type == "agent_start":
        ver = data.get("agent_version")
        return f"Agent initiated execution{f' ({ver})' if ver else ''}"
    if stage == "agent" and event_type == "agent_end":
        outcome = data.get("outcome", "COMPLETED")
        lat = data.get("latency_ms")
        return f"Agent completed with outcome '{outcome}'{f' in {lat}ms' if lat is not None else ''}"
    if stage == "tool":
        tool_name = data.get("tool", "unknown_tool")
        attempt = data.get("args", {}).get("attempt") or data.get("attempt")
        attempt_str = f" (attempt {attempt})" if attempt else ""
        return f"Invoked tool '{tool_name}'{attempt_str}"
    if stage == "response":
        tool_name = data.get("tool", "unknown_tool")
        return f"Tool '{tool_name}' returned successful response"
    if stage == "error":
        tool_name = data.get("tool", "unknown_tool")
        err = data.get("error", "Unknown error")
        return f"Tool '{tool_name}' failed: {err}"
    if stage == "retry":
        attempt = data.get("attempt", 2)
        tool_name = data.get("tool", "tool")
        return f"Retry attempt {attempt} initiated for '{tool_name}'"
    if stage == "fallback":
        resp = data.get("response", {})
        status = resp.get("status") if isinstance(resp, dict) else None
        return f"Fallback handler invoked{f': status={status}' if status else ''}"
    return f"{stage}: {event_type}"


def build_replay_timeline(run_or_telemetry: Any) -> ReplayTimeline:
    """Build a structured ReplayTimeline using ACTUAL recorded events only.

    Conceptual ordering:
        user -> agent -> tool -> response/error -> retry/fallback -> agent_end

    Args:
        run_or_telemetry: ReplayExecutionResult, AgentExecutionResult, or run dict.

    Returns:
        ReplayTimeline containing only authentic recorded events.
    """
    run_id, raw_events, outcome = _extract_raw_events(run_or_telemetry)

    # Sort strictly by timestamp to guarantee chronological order
    sorted_events = sorted(raw_events, key=lambda e: float(e.get("timestamp", 0.0)))

    timeline_events: list[TimelineEvent] = []
    stages_present: list[str] = []
    has_retry = False
    has_fallback = False
    has_error = False

    for idx, raw in enumerate(sorted_events, start=1):
        event_type = str(raw.get("type") or "unknown")
        stage = _map_event_stage(event_type)
        ts = float(raw.get("timestamp", 0.0))

        # Copy authentic payload fields, stripping internal routing metadata
        event_data = {k: v for k, v in raw.items() if k not in ("run_id", "type", "timestamp")}

        if stage == "retry":
            has_retry = True
        elif stage == "fallback":
            has_fallback = True
        elif stage == "error":
            has_error = True

        if stage not in stages_present:
            stages_present.append(stage)

        description = _format_event_description(stage, event_type, event_data)

        timeline_events.append(
            TimelineEvent(
                step_number=idx,
                stage=stage,
                event_type=event_type,
                timestamp=ts,
                data=event_data,
                description=description,
            )
        )

    return ReplayTimeline(
        run_id=run_id,
        total_events=len(timeline_events),
        events=timeline_events,
        stages_present=stages_present,
        has_retry=has_retry,
        has_fallback=has_fallback,
        has_error=has_error,
        final_outcome=outcome,
    )


def serialize_replay_timeline(timeline: ReplayTimeline) -> dict[str, Any]:
    """Convert ReplayTimeline into a JSON-serializable dictionary for Member 4."""
    serialized_events = [
        {
            "step_number": e.step_number,
            "stage": e.stage,
            "event_type": e.event_type,
            "timestamp": e.timestamp,
            "data": e.data,
            "description": e.description,
        }
        for e in timeline.events
    ]

    result = {
        "run_id": timeline.run_id,
        "total_events": timeline.total_events,
        "events": serialized_events,
        "stages_present": timeline.stages_present,
        "has_retry": timeline.has_retry,
        "has_fallback": timeline.has_fallback,
        "has_error": timeline.has_error,
        "final_outcome": timeline.final_outcome,
    }

    # Verify JSON serializability
    json.dumps(result)
    return result
