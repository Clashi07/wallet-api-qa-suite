"""API tests: positive, negative and edge cases for transfers."""
import pytest

pytestmark = pytest.mark.api


def test_transfer_success_updates_both_balances(env):
    client, _, _ = env
    status, txn = client.transfer("customer-1", "customer-2", "150.00", "k-1")
    assert status == 201
    assert txn["status"] == "SUCCESS" and txn["amount_paisa"] == 15000
    assert client.balance("customer-1") == "850.00"
    assert client.balance("customer-2") == "200.00"


def test_merchant_payment_deducts_fee(env):
    client, _, _ = env
    status, txn = client.transfer("customer-1", "shop-1", "200.00", "k-2", merchant=True)
    assert status == 201
    assert txn["fee_paisa"] == 370          # 1.85% of 200.00
    assert client.balance("shop-1") == "196.30"
    assert client.balance("fee-wallet") == "3.70"


@pytest.mark.parametrize("amount, code", [
    ("0", "INVALID_AMOUNT"),
    ("-10", "INVALID_AMOUNT"),
    ("10.555", "INVALID_AMOUNT"),
    ("abc", "INVALID_AMOUNT"),
    ("25000.01", "LIMIT_EXCEEDED"),
])
def test_invalid_amounts_rejected(env, amount, code):
    client, _, _ = env
    status, body = client.transfer("customer-1", "customer-2", amount, f"k-{amount}")
    assert status == 400
    assert body["error"]["code"] == code
    assert client.balance("customer-1") == "1000.00"


@pytest.mark.parametrize("amount", ["0.01", "1000.00"])
def test_boundary_amounts_accepted(env, amount):
    client, _, _ = env
    status, _ = client.transfer("customer-1", "customer-2", amount, f"b-{amount}")
    assert status == 201


def test_insufficient_balance_returns_422_and_moves_nothing(env):
    client, _, _ = env
    status, body = client.transfer("customer-2", "customer-1", "50.01", "k-3")
    assert status == 422 and body["error"]["code"] == "INSUFFICIENT_BALANCE"
    assert client.balance("customer-2") == "50.00"


def test_same_wallet_transfer_rejected(env):
    client, _, _ = env
    status, body = client.transfer("customer-1", "customer-1", "10", "k-4")
    assert status == 400 and body["error"]["code"] == "SAME_WALLET"


def test_unknown_wallet_returns_404(env):
    client, _, _ = env
    status, body = client.transfer("customer-1", "ghost", "10", "k-5")
    assert status == 404 and body["error"]["code"] == "WALLET_NOT_FOUND"


def test_missing_fields_reported(env):
    client, _, _ = env
    status, body = client.request("POST", "/v1/transfers", {"from_wallet": "customer-1"}, idem="k-6")
    assert status == 400
    assert "to_wallet" in body["error"]["message"] and "amount" in body["error"]["message"]


def test_malformed_json_rejected(env):
    client, _, _ = env
    status, body = client.request("POST", "/v1/transfers", raw=b"{not json", idem="k-7")
    assert status == 400 and body["error"]["code"] == "INVALID_JSON"


@pytest.mark.parametrize("key", [None, "wrong-key"])
def test_auth_required(env, key):
    client, _, _ = env
    status, body = client.request("GET", "/v1/wallets/customer-1", key=key)
    assert status == 401 and body["error"]["code"] == "UNAUTHORIZED"


def test_missing_idempotency_key_rejected(env):
    client, _, _ = env
    status, body = client.transfer("customer-1", "customer-2", "10", idem=None)
    assert status == 400 and body["error"]["code"] == "MISSING_IDEMPOTENCY_KEY"
