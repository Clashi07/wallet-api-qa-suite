"""SQL checks: the database must agree with what the API says."""
import pytest

pytestmark = pytest.mark.db


def make_activity(client):
    client.transfer("customer-1", "customer-2", "120.00", "a-1")
    client.transfer("customer-1", "shop-1", "333.33", "a-2", merchant=True)
    client.transfer("customer-2", "shop-1", "45.50", "a-3", merchant=True)
    client.transfer("customer-2", "customer-1", "999.00", "a-4")   # fails: insufficient balance


def test_ledger_is_balanced_per_transaction(env):
    client, conn, _ = env
    make_activity(client)
    unbalanced = conn.execute(
        "SELECT txn_id, SUM(amount_paisa) s FROM ledger GROUP BY txn_id HAVING s != 0").fetchall()
    assert unbalanced == []


def test_wallet_balances_match_ledger_history(env):
    client, conn, _ = env
    make_activity(client)
    mismatches = conn.execute("""
        SELECT w.id, w.balance_paisa, o.opening + COALESCE(SUM(l.amount_paisa), 0) AS expected
        FROM wallets w
        JOIN (SELECT 'customer-1' id, 100000 opening UNION ALL SELECT 'customer-2', 5000
              UNION ALL SELECT 'shop-1', 0 UNION ALL SELECT 'fee-wallet', 0) o ON o.id = w.id
        LEFT JOIN ledger l ON l.wallet_id = w.id
        GROUP BY w.id HAVING w.balance_paisa != expected""").fetchall()
    assert [dict(r) for r in mismatches] == []


def test_total_money_is_conserved(env):
    client, conn, _ = env
    make_activity(client)
    total = conn.execute("SELECT SUM(balance_paisa) FROM wallets").fetchone()[0]
    assert total == 100000 + 5000


def test_failed_transfer_leaves_no_rows(env):
    client, conn, _ = env
    make_activity(client)
    assert conn.execute("SELECT COUNT(*) FROM transactions WHERE idempotency_key = 'a-4'").fetchone()[0] == 0


def test_no_negative_balances_and_db_constraint_holds(env):
    _, conn, _ = env
    assert conn.execute("SELECT COUNT(*) FROM wallets WHERE balance_paisa < 0").fetchone()[0] == 0
    with pytest.raises(Exception):
        conn.execute("UPDATE wallets SET balance_paisa = -1 WHERE id = 'customer-1'")


def test_fee_rounding_is_half_up_to_the_paisa(env):
    client, conn, _ = env
    make_activity(client)
    fees = [r[0] for r in conn.execute("SELECT fee_paisa FROM transactions WHERE fee_paisa > 0 ORDER BY id")]
    assert fees == [617, 84]   # 1.85% of 333.33 = 6.166 -> 6.17; of 45.50 = 0.84175 -> 0.84
