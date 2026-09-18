"""Tests for Member 3 deterministic mock tool.

Test P0-T07.
"""



def test_p0_t07_mock_tool_deterministic_execution():
    """P0-T07: Mock tool executes deterministically.

    Verify get_order("8271") returns synthetic order information deterministically.
    Verify tool does NOT contain retry logic, detector logic, RCA logic, or chaos logic.
    """
    from reliability_lab.mocks.mock_tool import MockOrderTool, get_order

    # 1. Direct function call returns expected synthetic data
    result = get_order("8271")
    assert isinstance(result, dict)
    assert result["order_id"] == "8271"
    assert result["status"] == "IN_TRANSIT"
    assert "estimated_delivery" in result
    assert "items" in result
    assert "carrier" in result
    assert "tracking_number" in result

    # 2. Assert 100% determinism over 10 repeated executions
    first_run = get_order("8271")
    for _ in range(10):
        subsequent_run = get_order("8271")
        assert subsequent_run == first_run, "Mock tool must produce identical, deterministic results"

    # 3. Assert non-existent order handling is also deterministic
    not_found = get_order("99999")
    assert not_found["status"] == "NOT_FOUND"
    assert not_found["order_id"] == "99999"

    # 4. Verify class instance method executes identically
    tool_instance = MockOrderTool()
    assert tool_instance.execute("8271") == first_run

    # 5. Verify MockOrderTool contains NO retry, detector, RCA, or chaos attributes
    tool_attrs = dir(tool_instance)
    forbidden_terms = ["retry", "retries", "detector", "rca", "chaos", "inject"]
    for attr in tool_attrs:
        for term in forbidden_terms:
            assert term not in attr.lower(), f"Mock tool must not contain {term} logic (found {attr})"
