"""Tests for Member 3 in-memory mock storage abstraction.

Test P0-T08.
"""

import pytest


def test_p0_t08_mock_storage_operations():
    """P0-T08: Mock storage can save/get/list records.

    Verifies save, get, list, and clear operations on in-memory storage abstraction.
    Confirms no AWS/DynamoDB coupling.
    """
    from reliability_lab.mocks.mock_storage import MockStorage

    storage = MockStorage()

    # 1. Initially empty
    assert storage.list() == []
    assert storage.get("non-existent") is None

    # 2. Save items
    item1 = {"test_id": "reg-001", "name": "timeout scenario"}
    item2 = {"test_id": "reg-002", "name": "rate_limit scenario"}

    storage.save("reg-001", item1)
    storage.save("reg-002", item2)

    # 3. Get item by key
    retrieved = storage.get("reg-001")
    assert retrieved == item1
    assert storage.get("reg-002") == item2

    # 4. List items
    all_items = storage.list()
    assert len(all_items) == 2
    assert item1 in all_items
    assert item2 in all_items

    # 5. Overwrite/update item
    updated_item1 = {"test_id": "reg-001", "name": "timeout scenario updated"}
    storage.save("reg-001", updated_item1)
    assert storage.get("reg-001") == updated_item1
    assert len(storage.list()) == 2

    # 6. Clear storage
    storage.clear()
    assert storage.list() == []
    assert storage.get("reg-001") is None
