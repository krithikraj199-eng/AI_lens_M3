"""Mock Member 1 Agent Adapter.

Provides a clean test adapter modeling Member 1's agent behavior at the tool boundary.
Exposes both failing behavior (unhandled retry loop) and fixed behavior (bounded retry + fallback)
without Member 3 owning production agent logic.
"""

import re
from typing import Any, Optional
from reliability_lab.adapters.telemetry_adapter import AgentExecutionResult, ExecutionTracer
from reliability_lab.mocks.mock_tool import get_order


class MockMember1Agent:
    """Simulates Member 1 agent at the tool boundary for controlled scenario testing."""

    def __init__(
        self,
        version: str = "v1.0.0-failing",
        prompt_version: str = "p1.0",
        order_tool: Optional[Any] = None,
    ) -> None:
        self.version = version
        self.prompt_version = prompt_version
        self.order_tool = order_tool or get_order

    def _extract_order_id(self, request: str) -> str:
        """Extract order ID from user prompt or default to 8271."""
        match = re.search(r"#?(\d{4,})", request)
        if match:
            return match.group(1)
        return "8271"

    def _call_tool(self, tool: Any, order_id: str) -> Any:
        """Invoke tool callable or execute method."""
        if hasattr(tool, "execute") and callable(tool.execute):
            return tool.execute(order_id)
        return tool(order_id)

    def run(self, request: str, run_id: Optional[str] = None) -> AgentExecutionResult:
        """Execute the order lookup prompt through the tool boundary."""
        tracer = ExecutionTracer(
            run_id=run_id,
            agent_version=self.version,
            prompt_version=self.prompt_version,
        )
        tracer.record_event("user_request", request=request)
        tracer.record_event("agent_start", request=request)

        order_id = self._extract_order_id(request)
        is_fixed = "fixed" in self.version.lower()
        max_attempts = 3 if is_fixed else 5  # 1 initial + 2 retries (fixed) vs 5 attempts (failing)

        last_error: Optional[Exception] = None
        tool_result: Optional[dict[str, Any]] = None

        for attempt in range(1, max_attempts + 1):
            if attempt > 1:
                tracer.record_event("retry_attempt", attempt=attempt, tool="get_order")
            tracer.record_tool_call("get_order", {"order_id": order_id, "attempt": attempt})
            try:
                result = self._call_tool(self.order_tool, order_id)
                tracer.record_tool_success("get_order", result)
                tool_result = result
                last_error = None
                break
            except Exception as exc:
                last_error = exc
                tracer.record_tool_error("get_order", exc)

        # Determine outcome and response
        if tool_result is not None:
            return tracer.finalize(
                request=request,
                response=tool_result,
                outcome="SUCCESS",
                tokens=200,
            )

        if is_fixed:
            # Fixed agent invokes fallback response on exhausted retries
            fallback_response = {
                "order_id": order_id,
                "status": "CARRIER_DELAYED",
                "message": f"Carrier communication timed out for order #{order_id}. A support ticket has been created.",
                "fallback_triggered": True,
            }
            tracer.record_event("fallback_invoked", response=fallback_response)
            return tracer.finalize(
                request=request,
                response=fallback_response,
                outcome="FALLBACK",
                tokens=320,
            )

        # Failing agent terminates with failure without fallback
        return tracer.finalize(
            request=request,
            response=None,
            outcome="FAILED",
            tokens=450,
        )
