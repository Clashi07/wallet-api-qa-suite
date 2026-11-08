"""Duplicate requests, retries and refunds: the classic payment bugs."""
import threading

import pytest

pytestmark = pytest.mark.api


def test_duplicate_request_charges_once(env):
    client, conn, _ = env
    first = client.transfer("customer-1", "customer-2", "100.00", "retry-1")
    second = client.transfer("customer-1", "customer-2", "100.00", "retry-1")
    assert first[0] == 201 and second[0] == 200
    assert first[1]["id"] == second[1]["id"]
    assert client.balance("customer-1") == "900.00"
    assert conn.execute("SELECT COUNT(*) FROM transactions").fetchone()[0] == 1


def test_reused_key_with_different_amount_conflicts(env):
    client, _, _ = env
    client.transfer("customer-1", "customer-2", "100.00", "retry-2")
    status, body = client.transfer("customer-1", "customer-2", "999.00", "retry-2")
    assert status == 409 and body["error"]["code"] == "IDEMPOTENCY_CONFLICT"


def test_concurrent_double_tap_charges_once(env):
    client, conn, _ = env
    results = []
    threads = [threading.Thread(target=lambda: results.append(
        client.transfer("customer-1", "customer-2", "300.00", "double-tap"))) for _ in range(5)]
    [t.start() for t in threads]
    [t.join() for t in threads]
    assert sorted(r[0] for r in results) == [200, 200, 200, 200, 201]
    assert client.balance("customer-1") == "700.00"


def test_concurrent_spends_never_overdraw(env):
    client, _, _ = env
    results = []
    threads = [threading.Thread(target=lambda i=i: results.append(
        client.transfer("customer-2", "customer-1", "20.00", f"spend-{i}"))) for i in range(5)]
    [t.start() for t in threads]
    [t.join() for t in threads]
    assert [r[0] for r in results].count(201) == 2      # 50.00 only covers two 20.00 spends
    assert client.balance("customer-2") == "10.00"


def test_refund_returns_full_amount_and_reverses_fee(env):
    client, _, _ = env
    _, txn = client.transfer("customer-1", "shop-1", "200.00", "pay-1", merchant=True)
    status, refund = client.request("POST", f"/v1/transfers/{txn['id']}/refund", idem="refund-1")
    assert status == 201 and refund["type"] == "REFUND"
    assert client.balance("customer-1") == "1000.00"
    assert client.balance("shop-1") == "0.00"
    assert client.balance("fee-wallet") == "0.00"


def test_double_refund_rejected(env):
    client, _, _ = env
    _, txn = client.transfer("customer-1", "shop-1", "50.00", "pay-2")
    client.request("POST", f"/v1/transfers/{txn['id']}/refund", idem="refund-2")
    status, body = client.request("POST", f"/v1/transfers/{txn['id']}/refund", idem="refund-3")
    assert status == 409 and body["error"]["code"] == "ALREADY_REFUNDED"
    assert client.balance("customer-1") == "1000.00"
