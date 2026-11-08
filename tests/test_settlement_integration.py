"""End-to-end: payments -> refund -> settlement -> reconciliation."""
import pytest

pytestmark = pytest.mark.integration


def test_settlement_reconciles_with_transactions(env):
    client, conn, _ = env
    _, t1 = client.transfer("customer-1", "shop-1", "500.00", "s-1", merchant=True)
    client.transfer("customer-2", "shop-1", "40.00", "s-2", merchant=True)
    _, t3 = client.transfer("customer-1", "shop-1", "100.00", "s-3", merchant=True)
    client.request("POST", f"/v1/transfers/{t3['id']}/refund", idem="s-r3")

    status, summary = client.request("POST", "/v1/merchants/shop-1/settle")
    assert status == 200
    assert summary["count"] == 2                      # refunded payment excluded
    assert summary["gross_paisa"] == 54000
    assert summary["net_paisa"] == summary["gross_paisa"] - summary["fee_paisa"]

    shop_balance = conn.execute("SELECT balance_paisa FROM wallets WHERE id = 'shop-1'").fetchone()[0]
    assert shop_balance == summary["net_paisa"]


def test_settlement_is_not_repeated(env):
    client, _, _ = env
    client.transfer("customer-1", "shop-1", "10.00", "s-4", merchant=True)
    client.request("POST", "/v1/merchants/shop-1/settle")
    _, again = client.request("POST", "/v1/merchants/shop-1/settle")
    assert again["count"] == 0 and again["net_paisa"] == 0


def test_settled_payment_cannot_be_refunded(env):
    client, _, _ = env
    _, txn = client.transfer("customer-1", "shop-1", "10.00", "s-5", merchant=True)
    client.request("POST", "/v1/merchants/shop-1/settle")
    status, body = client.request("POST", f"/v1/transfers/{txn['id']}/refund", idem="s-r5")
    assert status == 409 and body["error"]["code"] == "ALREADY_SETTLED"
