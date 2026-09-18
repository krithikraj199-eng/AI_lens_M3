"""Deterministic Mock Tool for Reliability Lab.

Provides a synthetic business tool implementation for order status lookups
and secondary mock tools for controlled failure testing (e.g. wrong-tool mapping).
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

SYNTHETIC_INVENTORY: dict[str, dict[str, Any]] = {
    "8271": {
        "inventory_id": "INV-8271",
        "tool": "get_inventory",
        "stock_count": 42,
        "warehouse": "Dallas-WH1",
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


def get_inventory(item_id: str) -> dict[str, Any]:
    """Look up inventory information deterministically (for wrong-tool scenarios).

    Args:
        item_id: The ID of the item to query.

    Returns:
        Deterministic dictionary containing inventory details.
    """
    if item_id in SYNTHETIC_INVENTORY:
        return dict(SYNTHETIC_INVENTORY[item_id])
    return {
        "inventory_id": item_id,
        "tool": "get_inventory",
        "stock_count": 0,
        "warehouse": "UNKNOWN",
    }


class MockOrderTool:
    """Callable wrapper for the synthetic order tool."""

    name: str = "get_order"
    description: str = "Look up shipping and fulfillment status for a given order ID."

    def execute(self, order_id: str) -> dict[str, Any]:
        """Execute the order lookup deterministically."""
        return get_order(order_id)


class MockInventoryTool:
    """Callable wrapper for synthetic inventory tool."""

    name: str = "get_inventory"
    description: str = "Look up warehouse inventory stock."

    def execute(self, item_id: str) -> dict[str, Any]:
        """Execute the inventory lookup deterministically."""
        return get_inventory(item_id)
