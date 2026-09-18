"""Production-Safety Boundary for Controlled Chaos Injection.

Guarantees that ChaosProxy can ONLY be attached to approved synthetic,
mock, or lab tools, strictly preventing fault injection against production services.
"""

from typing import Any
from reliability_lab.chaos.exceptions import UnapprovedToolError

APPROVED_TEST_TOOLS: set[str] = {
    "get_order",
    "MockOrderTool",
    "get_inventory",
    "MockInventoryTool",
    "mock_tool",
    "synthetic_tool",
}


def is_approved_test_tool(tool: Any) -> bool:
    """Check if the given tool is an approved synthetic/test tool.

    Args:
        tool: The tool function or callable object.

    Returns:
        True if the tool is approved for controlled chaos injection, False otherwise.
    """
    if tool is None:
        return False

    # 1. Explicit synthetic marker attribute
    if getattr(tool, "_is_synthetic", False) or getattr(tool, "is_mock", False):
        return True

    # 2. Module membership in reliability_lab.mocks
    tool_module = getattr(tool, "__module__", "") or ""
    if "reliability_lab.mocks" in tool_module:
        return True

    # 3. Name or class name in approved registry
    tool_name = getattr(tool, "__name__", "") or getattr(tool, "name", "")
    class_name = tool.__class__.__name__ if hasattr(tool, "__class__") else ""

    if tool_name in APPROVED_TEST_TOOLS or class_name in APPROVED_TEST_TOOLS:
        return True

    return False


def assert_approved_test_tool(tool: Any) -> None:
    """Assert that a tool is approved, raising UnapprovedToolError if not.

    Args:
        tool: The tool function or callable object.

    Raises:
        UnapprovedToolError: If tool is not on the approved test tool whitelist.
    """
    if not is_approved_test_tool(tool):
        tool_desc = getattr(tool, "__name__", str(tool))
        raise UnapprovedToolError(
            f"Cannot attach ChaosProxy to unapproved tool '{tool_desc}'. "
            "Chaos injection is strictly restricted to approved synthetic/mock lab tools."
        )
