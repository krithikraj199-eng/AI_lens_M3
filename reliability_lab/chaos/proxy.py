"""Deterministic Chaos Proxy.

Intercepts tool calls at the proxy boundary between caller/agent and tool,
injecting controlled deterministic failure modes without modifying agent or tool code.
"""

import time
from typing import Any, Callable, Optional

from reliability_lab.contracts import ChaosConfig, FailureMode
from reliability_lab.chaos.exceptions import (
    ChaosTimeoutError,
    ChaosRateLimitError,
)
from reliability_lab.chaos.safety import assert_approved_test_tool


class ChaosProxy:
    """Deterministic tool proxy for controlled chaos engineering.

    Architecture:
        caller/agent -> ChaosProxy -> tool
    """

    def __init__(
        self,
        tool: Callable[..., Any] | Any,
        config: Optional[ChaosConfig] = None,
        wrong_tool_target: Optional[Callable[..., Any] | Any] = None,
    ) -> None:
        """Initialize ChaosProxy with production safety boundary enforcement.

        Args:
            tool: The underlying approved test tool.
            config: Initial ChaosConfig. Defaults to NORMAL mode.
            wrong_tool_target: Optional alternative test tool for WRONG_TOOL mode.
        """
        assert_approved_test_tool(tool)
        if wrong_tool_target is not None:
            assert_approved_test_tool(wrong_tool_target)

        self.tool = tool
        self.wrong_tool_target = wrong_tool_target
        self.tool_name = getattr(tool, "__name__", "") or getattr(tool, "name", str(tool))
        self.config: ChaosConfig = ChaosConfig(failure_mode=FailureMode.NORMAL)

        if config is not None:
            self.set_config(config)

    def set_config(self, config: ChaosConfig) -> None:
        """Set or update the active chaos configuration.

        Args:
            config: ChaosConfig specifying failure mode and parameters.

        Raises:
            ValueError: If failure_mode is not a valid FailureMode.
        """
        mode = config.failure_mode
        valid_modes = {m.value for m in FailureMode}
        mode_val = mode.value if isinstance(mode, FailureMode) else str(mode)

        if mode_val not in valid_modes:
            raise ValueError(f"Invalid failure mode: '{mode}'. Must be one of {valid_modes}")

        self.config = config

    def reset(self) -> None:
        """Reset proxy to NORMAL failure mode."""
        self.config = ChaosConfig(failure_mode=FailureMode.NORMAL)

    def _invoke(self, target: Any, *args: Any, **kwargs: Any) -> Any:
        """Invoke underlying tool callable or class execute method."""
        if hasattr(target, "execute") and callable(target.execute):
            return target.execute(*args, **kwargs)
        if callable(target):
            return target(*args, **kwargs)
        raise TypeError(f"Target '{target}' is not callable.")

    def execute(self, *args: Any, **kwargs: Any) -> Any:
        """Execute method proxying tool calls."""
        return self(*args, **kwargs)

    def __call__(self, *args: Any, **kwargs: Any) -> Any:
        """Intercept invocation and apply controlled deterministic behavior."""
        mode = self.config.failure_mode
        mode_val = mode.value if isinstance(mode, FailureMode) else str(mode)

        # 1. NORMAL
        if mode_val == FailureMode.NORMAL.value:
            return self._invoke(self.tool, *args, **kwargs)

        # 2. TIMEOUT
        if mode_val == FailureMode.TIMEOUT.value:
            msg = self.config.error_message or f"Controlled chaos timeout on tool '{self.tool_name}'."
            raise ChaosTimeoutError(msg)

        # 3. RATE_LIMIT
        if mode_val == FailureMode.RATE_LIMIT.value:
            status_code = self.config.status_code or 429
            msg = self.config.error_message or f"Controlled chaos 429: Too Many Requests on '{self.tool_name}'."
            raise ChaosRateLimitError(message=msg, status_code=status_code)

        # 4. EMPTY_RESULT
        if mode_val == FailureMode.EMPTY_RESULT.value:
            return {}

        # 5. SLOW_RESPONSE
        if mode_val == FailureMode.SLOW_RESPONSE.value:
            delay_sec = max(self.config.delay_ms, 0) / 1000.0
            if delay_sec > 0:
                time.sleep(delay_sec)
            return self._invoke(self.tool, *args, **kwargs)

        # 6. WRONG_TOOL
        if mode_val == FailureMode.WRONG_TOOL.value:
            if self.wrong_tool_target is not None:
                return self._invoke(self.wrong_tool_target, *args, **kwargs)
            return {
                "tool": "wrong_tool",
                "status": "UNEXPECTED_TOOL_RESULT",
                "data": {},
            }

        # Fallback for unexpected mode value
        raise ValueError(f"Unsupported failure mode: '{mode_val}'")
