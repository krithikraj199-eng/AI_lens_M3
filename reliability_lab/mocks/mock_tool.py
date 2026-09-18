"""Deterministic Mock Tool for Reliability Lab.

Provides a synthetic business tool implementation for order status lookups.
Strictly decoupled: Contains NO retry logic, NO detector logic, NO RCA logic,
and NO chaos injection logic.
"""

from typing import Any


SYNTHETIC_ORDERS: dict[str, dict[str, Any]] = {
    "8271": {
        "order_id": "8271",
        "status": "IN_TRANSIT",
        "estimated_delivery": "2026-09-20",
        "items": [
            {"sku": "SKU-99", "name": "Wireless Noise-Cancelling Headphones", "quantity": 1, "price": 199.99}
        ],
        "carrier": "FedEx",
        "tracking_number": "TRK-987654",
        "destination": "Austin, TX",
    }
}


def get_order(order_id: str) -> dict[str, Any]:
    """Look up order information by order ID deterministically.

    Args:
        order_id: The ID of the order to look up.

    Returns:
        Deterministic dictionary containing order details or not found status.
    """
    if order_id in SYNTHETIC_ORDERS:
        return dict(SYNTHETIC_ORDERS[order_id])
    return {
        "order_id": order_id,
        "status": "NOT_FOUND",
        "error": f"Order {order_id} not found in database.",
    }


class MockOrderTool:
    """Callable wrapper for the synthetic order tool."""

    name: str = "get_order"
    description: str = "Look up shipping and fulfillment status for a given order ID."

    def execute(self, order_id: str) -> dict[str, Any]:
        """Execute the order lookup deterministically."""
        return get_order(order_id)
