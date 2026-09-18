"""In-Memory Mock Storage Abstraction.

Provides a clean key-value persistence interface for Reliability Lab artifacts
such as ReplayRecords, EvaluationPairs, and RegressionTests.
Decoupled: Contains NO AWS, Boto3, or DynamoDB dependencies.
"""

from typing import Any, Optional


class MockStorage:
    """In-memory key-value store simulating persistence for Reliability Lab."""

    def __init__(self) -> None:
        self._store: dict[str, Any] = {}

    def save(self, key: str, item: Any) -> None:
        """Save or update an item by key.

        Args:
            key: Unique identifier for the stored entity.
            item: Object or dictionary to persist.
        """
        self._store[key] = item

    def get(self, key: str) -> Optional[Any]:
        """Retrieve an item by key.

        Args:
            key: Unique identifier to query.

        Returns:
            The stored item or None if not found.
        """
        return self._store.get(key)

    def list(self) -> list[Any]:
        """List all stored items.

        Returns:
            List of all stored values.
        """
        return list(self._store.values())

    def clear(self) -> None:
        """Clear all stored items."""
        self._store.clear()
