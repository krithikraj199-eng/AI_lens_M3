"""Chaos Control Service for Member 4 API Gateway / Lambda Integration.

Provides a robust, standardized service boundary for POST /chaos, enabling
dynamic configuration, validation, status inspection, and safe reset of controlled failure modes.
"""

from datetime import datetime, timezone
from typing import Any, Optional
from reliability_lab.contracts import ChaosConfig, FailureMode
from reliability_lab.chaos.proxy import ChaosProxy
from reliability_lab.mocks.mock_tool import get_order, get_inventory


class ChaosService:
    """Manages active tool proxies and applies incoming chaos configurations."""

    def __init__(self) -> None:
        self._proxies: dict[str, ChaosProxy] = {}
        # Pre-initialize canonical get_order proxy
        canonical_proxy = ChaosProxy(
            tool=get_order,
            config=ChaosConfig(failure_mode=FailureMode.NORMAL),
            wrong_tool_target=get_inventory,
        )
        self.register_proxy("get_order", canonical_proxy)
        self._active_mode: str = FailureMode.NORMAL.value
        self._active_config: ChaosConfig = ChaosConfig(failure_mode=FailureMode.NORMAL)

    def register_proxy(self, name: str, proxy: ChaosProxy) -> None:
        """Register an approved tool proxy under a tool identifier."""
        self._proxies[name] = proxy

    def get_proxy(self, name: str = "get_order") -> ChaosProxy:
        """Retrieve the active proxy for a given tool name."""
        if name not in self._proxies:
            # Auto-wrap if tool is get_order
            if name == "get_order":
                proxy = ChaosProxy(
                    tool=get_order,
                    config=ChaosConfig(failure_mode=FailureMode.NORMAL),
                    wrong_tool_target=get_inventory,
                )
                self._proxies["get_order"] = proxy
                return proxy
            raise KeyError(f"No proxy registered for tool '{name}'.")
        return self._proxies[name]

    def handle_request(self, payload: dict[str, Any]) -> dict[str, Any]:
        """Process incoming payload for POST /chaos, validate, and apply.

        Args:
            payload: JSON request body dictionary.

        Returns:
            JSON-serializable response dictionary.
        """
        if not isinstance(payload, dict):
            return {
                "status": "ERROR",
                "error": "Request payload must be a JSON object / dictionary.",
                "active_failure_mode": self._active_mode,
            }

        raw_mode = payload.get("failure_mode", "").lower().strip()
        valid_modes = [m.value for m in FailureMode]

        if not raw_mode or raw_mode not in valid_modes:
            return {
                "status": "ERROR",
                "error": f"Invalid failure_mode '{raw_mode}'. Must be one of {valid_modes}.",
                "active_failure_mode": self._active_mode,
            }

        failure_mode_enum = FailureMode(raw_mode)

        # Handle reset/normal
        if failure_mode_enum == FailureMode.NORMAL:
            return self.reset()

        target_tool = payload.get("target_tool") or "get_order"
        delay_ms = payload.get("delay_ms", 0)
        try:
            delay_ms = max(int(delay_ms), 0)
        except (ValueError, TypeError):
            delay_ms = 0

        error_message = payload.get("error_message")
        status_code = payload.get("status_code", 429 if failure_mode_enum == FailureMode.RATE_LIMIT else 200)
        try:
            status_code = int(status_code)
        except (ValueError, TypeError):
            status_code = 429 if failure_mode_enum == FailureMode.RATE_LIMIT else 200

        config = ChaosConfig(
            failure_mode=failure_mode_enum,
            target_tool=target_tool,
            delay_ms=delay_ms,
            error_message=error_message,
            status_code=status_code,
        )

        # Apply to target proxy
        if target_tool in self._proxies:
            self._proxies[target_tool].set_config(config)
        else:
            # Apply to default get_order proxy
            self._proxies["get_order"].set_config(config)

        self._active_mode = raw_mode
        self._active_config = config
        now_iso = datetime.now(timezone.utc).isoformat()

        return {
            "status": "APPLIED",
            "active_failure_mode": raw_mode,
            "active_config": {
                "failure_mode": raw_mode,
                "target_tool": target_tool,
                "delay_ms": delay_ms,
                "error_message": error_message,
                "status_code": status_code,
            },
            "applied_at": now_iso,
            "message": f"Chaos mode '{raw_mode}' successfully activated on tool '{target_tool}'.",
        }

    def reset(self) -> dict[str, Any]:
        """Reset all registered proxies immediately to FailureMode.NORMAL.

        Guarantees that the demo never remains stuck in a failure state.

        Returns:
            JSON-serializable reset response dictionary.
        """
        normal_config = ChaosConfig(failure_mode=FailureMode.NORMAL)
        for proxy in self._proxies.values():
            proxy.reset()

        self._active_mode = FailureMode.NORMAL.value
        self._active_config = normal_config
        now_iso = datetime.now(timezone.utc).isoformat()

        return {
            "status": "RESET",
            "active_failure_mode": FailureMode.NORMAL.value,
            "active_config": {
                "failure_mode": FailureMode.NORMAL.value,
                "target_tool": None,
                "delay_ms": 0,
                "error_message": None,
                "status_code": 200,
            },
            "applied_at": now_iso,
            "message": "Chaos reset to NORMAL. All tools operating in baseline mode.",
        }

    def get_status(self) -> dict[str, Any]:
        """Query currently active chaos configuration."""
        return {
            "active_failure_mode": self._active_mode,
            "active_config": {
                "failure_mode": self._active_mode,
                "target_tool": self._active_config.target_tool,
                "delay_ms": self._active_config.delay_ms,
                "error_message": self._active_config.error_message,
                "status_code": self._active_config.status_code,
            },
        }


# Global singleton instance for local runtime and tests
_GLOBAL_CHAOS_SERVICE: ChaosService = ChaosService()


def handle_chaos_request(payload: dict[str, Any]) -> dict[str, Any]:
    """Top-level handler for Member 4 POST /chaos Lambda invocation."""
    return _GLOBAL_CHAOS_SERVICE.handle_request(payload)


def reset_chaos() -> dict[str, Any]:
    """Top-level handler for resetting all chaos modes to NORMAL."""
    return _GLOBAL_CHAOS_SERVICE.reset()


def get_chaos_status() -> dict[str, Any]:
    """Top-level inspector for active chaos status."""
    return _GLOBAL_CHAOS_SERVICE.get_status()


def get_active_proxy(name: str = "get_order") -> ChaosProxy:
    """Retrieve active tool proxy instance."""
    return _GLOBAL_CHAOS_SERVICE.get_proxy(name)
