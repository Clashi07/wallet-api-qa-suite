"""Wallet business rules: transfers, fees, refunds, idempotency, settlement."""
import threading
from decimal import ROUND_HALF_UP, Decimal

from wallet.db import FEE_WALLET

FEE_RATE = Decimal("0.0185")   # 1.85% merchant fee
MAX_TRANSFER_PAISA = 25_000_00  # 25,000 BDT per transaction


class WalletError(Exception):
    def __init__(self, code, message, status=400):
        super().__init__(message)
        self.code, self.message, self.status = code, message, status


def to_paisa(amount):
    """'100.50' or 100.5 -> 10050. Rejects more than 2 decimals."""
    try:
        d = Decimal(str(amount))
    except Exception:
        raise WalletError("INVALID_AMOUNT", "amount must be a number")
    if d != d.quantize(Decimal("0.01")):
        raise WalletError("INVALID_AMOUNT", "amount can have at most 2 decimals")
    return int(d * 100)


def fee_for(amount_paisa):
    return int((Decimal(amount_paisa) * FEE_RATE).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


class WalletService:
    def __init__(self, conn):
        self.conn = conn
        self.lock = threading.Lock()

    def create_wallet(self, wallet_id, owner, opening_balance="0"):
        bal = to_paisa(opening_balance)
        if bal < 0:
            raise WalletError("INVALID_AMOUNT", "opening balance cannot be negative")
        self.conn.execute("INSERT INTO wallets VALUES (?, ?, ?)", (wallet_id, owner, bal))
        return self.get_wallet(wallet_id)

    def get_wallet(self, wallet_id):
        row = self.conn.execute("SELECT * FROM wallets WHERE id = ?", (wallet_id,)).fetchone()
        if row is None:
            raise WalletError("WALLET_NOT_FOUND", f"wallet {wallet_id} not found", 404)
        return dict(row)

    def _txn(self, txn_id):
        return dict(self.conn.execute("SELECT * FROM transactions WHERE id = ?", (txn_id,)).fetchone())

    def transfer(self, idempotency_key, from_id, to_id, amount, merchant=False):
        if not idempotency_key:
            raise WalletError("MISSING_IDEMPOTENCY_KEY", "Idempotency-Key is required")
        amount_paisa = to_paisa(amount)
        if amount_paisa <= 0:
            raise WalletError("INVALID_AMOUNT", "amount must be greater than 0")
        if amount_paisa > MAX_TRANSFER_PAISA:
            raise WalletError("LIMIT_EXCEEDED", "amount exceeds per-transaction limit")
        if from_id == to_id:
            raise WalletError("SAME_WALLET", "cannot transfer to the same wallet")
        with self.lock:
            existing = self.conn.execute(
                "SELECT * FROM transactions WHERE idempotency_key = ?", (idempotency_key,)).fetchone()
            if existing:
                same = (existing["from_wallet"], existing["to_wallet"], existing["amount_paisa"]) == (from_id, to_id, amount_paisa)
                if not same:
                    raise WalletError("IDEMPOTENCY_CONFLICT", "key reused with different request", 409)
                return dict(existing), False
            sender = self.get_wallet(from_id)
            self.get_wallet(to_id)
            fee = fee_for(amount_paisa) if merchant else 0
            if sender["balance_paisa"] < amount_paisa:
                raise WalletError("INSUFFICIENT_BALANCE", "insufficient balance", 422)
            c = self.conn
            c.execute("BEGIN")
            try:
                cur = c.execute(
                    "INSERT INTO transactions (idempotency_key, type, from_wallet, to_wallet, amount_paisa, fee_paisa, status)"
                    " VALUES (?, 'TRANSFER', ?, ?, ?, ?, 'SUCCESS')",
                    (idempotency_key, from_id, to_id, amount_paisa, fee))
                txn_id = cur.lastrowid
                self._post(txn_id, from_id, -amount_paisa)
                self._post(txn_id, to_id, amount_paisa - fee)
                if fee:
                    self._post(txn_id, FEE_WALLET, fee)
                c.execute("COMMIT")
            except Exception:
                c.execute("ROLLBACK")
                raise
            return self._txn(txn_id), True

    def refund(self, idempotency_key, txn_id):
        with self.lock:
            row = self.conn.execute("SELECT * FROM transactions WHERE id = ?", (txn_id,)).fetchone()
            if row is None:
                raise WalletError("TXN_NOT_FOUND", "transaction not found", 404)
            if row["status"] == "REFUNDED":
                raise WalletError("ALREADY_REFUNDED", "transaction already refunded", 409)
            if row["settled"]:
                raise WalletError("ALREADY_SETTLED", "settled transactions cannot be refunded", 409)
            merchant = self.get_wallet(row["to_wallet"])
            net = row["amount_paisa"] - row["fee_paisa"]
            if merchant["balance_paisa"] < net:
                raise WalletError("INSUFFICIENT_BALANCE", "merchant balance too low for refund", 422)
            c = self.conn
            c.execute("BEGIN")
            try:
                cur = c.execute(
                    "INSERT INTO transactions (idempotency_key, type, from_wallet, to_wallet, amount_paisa, fee_paisa, status, refund_of)"
                    " VALUES (?, 'REFUND', ?, ?, ?, ?, 'SUCCESS', ?)",
                    (idempotency_key, row["to_wallet"], row["from_wallet"], row["amount_paisa"], row["fee_paisa"], txn_id))
                rid = cur.lastrowid
                self._post(rid, row["to_wallet"], -net)
                if row["fee_paisa"]:
                    self._post(rid, FEE_WALLET, -row["fee_paisa"])
                self._post(rid, row["from_wallet"], row["amount_paisa"])
                c.execute("UPDATE transactions SET status = 'REFUNDED' WHERE id = ?", (txn_id,))
                c.execute("COMMIT")
            except Exception:
                c.execute("ROLLBACK")
                raise
            return self._txn(rid)

    def settle(self, merchant_id):
        """Mark a merchant's unsettled transfers as settled; return the settlement summary."""
        with self.lock:
            rows = self.conn.execute(
                "SELECT id, amount_paisa, fee_paisa FROM transactions WHERE to_wallet = ? AND type = 'TRANSFER'"
                " AND status = 'SUCCESS' AND settled = 0", (merchant_id,)).fetchall()
            gross = sum(r["amount_paisa"] for r in rows)
            fees = sum(r["fee_paisa"] for r in rows)
            ids = [r["id"] for r in rows]
            self.conn.executemany("UPDATE transactions SET settled = 1 WHERE id = ?", [(i,) for i in ids])
            return {"merchant": merchant_id, "count": len(ids), "gross_paisa": gross,
                    "fee_paisa": fees, "net_paisa": gross - fees}

    def _post(self, txn_id, wallet_id, delta):
        self.conn.execute("INSERT INTO ledger (txn_id, wallet_id, amount_paisa) VALUES (?, ?, ?)", (txn_id, wallet_id, delta))
        self.conn.execute("UPDATE wallets SET balance_paisa = balance_paisa + ? WHERE id = ?", (delta, wallet_id))
