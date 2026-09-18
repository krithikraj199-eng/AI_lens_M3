"""Controlled Chaos Injection Module for Reliability Lab.

Provides deterministic tool proxies, failure simulation modes, production safety boundaries,
and the service interface for Member 4's POST /chaos endpoint.
"""

from reliability_lab.chaos.exceptions import (
    ChaosError,
    ChaosTimeoutError,
    ChaosRateLimitError,
    UnapprovedToolError,
)
from reliability_lab.chaos.safety import (
    APPROVED_TEST_TOOLS,
    is_approved_test_tool,
    assert_approved_test_tool,
)
from reliability_lab.chaos.proxy import ChaosProxy
from reliability_lab.chaos.service import (
    ChaosService,
    handle_chaos_request,
    reset_chaos,
    get_chaos_status,
    get_active_proxy,
)

__all__ = [
    "ChaosProxy",
    "ChaosError",
    "ChaosTimeoutError",
    "ChaosRateLimitError",
    "UnapprovedToolError",
    "APPROVED_TEST_TOOLS",
    "is_approved_test_tool",
    "assert_approved_test_tool",
    "ChaosService",
    "handle_chaos_request",
    "reset_chaos",
    "get_chaos_status",
    "get_active_proxy",
]
