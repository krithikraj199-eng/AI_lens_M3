"""Telemetry Adapter for capturing and formatting normal execution traces.

Generates telemetry matching the shared Member 2 Run contract without embedding
detectors or internal chaos hooks.
"""

from dataclasses import dataclass, field
import time
from typing import Any, Optional
import uuid


@dataclass
class AgentExecutionResult:
    """Represents the execution result and trace of an agent scenario."""
    run_id: str
    agent_version: str
    prompt_version: str
    request: str
    response: Optional[dict[str, Any]]
    events: list[dict[str, Any]] = field(default_factory=list)
    tool_calls: list[dict[str, Any]] = field(default_factory=list)
    tokens: int = 0
    latency_ms: int = 0
    errors: list[str] = field(default_factory=list)
    outcome: str = "SUCCESS"  # "SUCCESS" | "FAILED" | "FALLBACK"
    detected_failures: list[str] = field(default_factory=list)


class ExecutionTracer:
    """Tracks execution events, timing, and tool calls during an agent run."""

    def __init__(self, run_id: Optional[str] = None, agent_version: str = "v1.0.0", prompt_version: str = "p1.0") -> None:
        self.run_id = run_id or f"run-{uuid.uuid4().hex[:8]}"
        self.agent_version = agent_version
        self.prompt_version = prompt_version
        self.events: list[dict[str, Any]] = []
        self.tool_calls: list[dict[str, Any]] = []
        self.errors: list[str] = []
        self.start_time: float = time.perf_counter()

    def record_event(self, event_type: str, **kwargs: Any) -> dict[str, Any]:
        """Record an execution lifecycle or tool event correlated with run_id."""
        event = {
            "run_id": self.run_id,
            "type": event_type,
            "timestamp": time.time(),
            **kwargs,
        }
        self.events.append(event)
        return event

    def record_tool_call(self, tool_name: str, args: dict[str, Any]) -> None:
        """Record a tool call invocation."""
        call = {
            "run_id": self.run_id,
            "tool": tool_name,
            "args": args,
            "timestamp": time.time(),
        }
        self.tool_calls.append(call)
        self.record_event("tool_call_start", tool=tool_name, args=args)

    def record_tool_success(self, tool_name: str, data: Any) -> None:
        """Record successful tool return."""
        self.record_event("tool_call_success", tool=tool_name, data=data)

    def record_tool_error(self, tool_name: str, error: Exception | str) -> None:
        """Record tool error event."""
        err_msg = str(error)
        self.errors.append(err_msg)
        self.record_event("tool_call_error", tool=tool_name, error=err_msg)

    def finalize(self, request: str, response: Optional[dict[str, Any]], outcome: str, tokens: int = 150) -> AgentExecutionResult:
        """Produce final AgentExecutionResult."""
        latency_ms = int((time.perf_counter() - self.start_time) * 1000)
        self.record_event("agent_end", outcome=outcome, latency_ms=latency_ms)
        return AgentExecutionResult(
            run_id=self.run_id,
            agent_version=self.agent_version,
            prompt_version=self.prompt_version,
            request=request,
            response=response,
            events=self.events,
            tool_calls=self.tool_calls,
            tokens=tokens,
            latency_ms=latency_ms,
            errors=self.errors,
            outcome=outcome,
        )
