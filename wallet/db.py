"""SQLite ledger: wallets, transactions, and double-entry ledger lines."""
import sqlite3

SCHEMA = """
CREATE TABLE wallets (
    id TEXT PRIMARY KEY,
    owner TEXT NOT NULL,
    balance_paisa INTEGER NOT NULL CHECK (balance_paisa >= 0)
);
CREATE TABLE transactions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    idempotency_key TEXT UNIQUE NOT NULL,
    type TEXT NOT NULL CHECK (type IN ('TRANSFER', 'REFUND')),
    from_wallet TEXT NOT NULL REFERENCES wallets(id),
    to_wallet TEXT NOT NULL REFERENCES wallets(id),
    amount_paisa INTEGER NOT NULL CHECK (amount_paisa > 0),
    fee_paisa INTEGER NOT NULL DEFAULT 0,
    status TEXT NOT NULL CHECK (status IN ('SUCCESS', 'REFUNDED')),
    refund_of INTEGER REFERENCES transactions(id),
    settled INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE ledger (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    txn_id INTEGER NOT NULL REFERENCES transactions(id),
    wallet_id TEXT NOT NULL,
    amount_paisa INTEGER NOT NULL
);
"""

FEE_WALLET = "fee-wallet"


def connect(path=":memory:"):
    conn = sqlite3.connect(path, check_same_thread=False, isolation_level=None)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.executescript(SCHEMA)
    conn.execute("INSERT INTO wallets VALUES (?, ?, 0)", (FEE_WALLET, "system"))
    return conn
