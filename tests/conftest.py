import json
import threading
import urllib.error
import urllib.request

import pytest

from wallet.api import serve
from wallet.db import connect
from wallet.service import WalletService

API_KEY = "test-key"
_OPENER = urllib.request.build_opener(urllib.request.ProxyHandler({}))  # never proxy localhost


class Client:
    def __init__(self, base):
        self.base = base

    def request(self, method, path, body=None, key=API_KEY, idem=None, raw=None):
        data = raw if raw is not None else (json.dumps(body).encode() if body is not None else None)
        req = urllib.request.Request(self.base + path, data=data, method=method)
        req.add_header("Content-Type", "application/json")
        if key:
            req.add_header("X-API-Key", key)
        if idem:
            req.add_header("Idempotency-Key", idem)
        try:
            with _OPENER.open(req) as r:
                return r.status, json.loads(r.read())
        except urllib.error.HTTPError as e:
            return e.code, json.loads(e.read())

    def transfer(self, frm, to, amount, idem, merchant=False):
        return self.request("POST", "/v1/transfers",
                            {"from_wallet": frm, "to_wallet": to, "amount": amount, "merchant": merchant}, idem=idem)

    def balance(self, wallet_id):
        return self.request("GET", f"/v1/wallets/{wallet_id}")[1]["balance"]


@pytest.fixture
def env():
    conn = connect()
    service = WalletService(conn)
    service.create_wallet("customer-1", "Rahim", "1000.00")
    service.create_wallet("customer-2", "Karim", "50.00")
    service.create_wallet("shop-1", "Rahim Store", "0")
    server = serve(service, API_KEY)
    thread = threading.Thread(target=server.serve_forever, kwargs={"poll_interval": 0.01}, daemon=True)
    thread.start()
    client = Client(f"http://127.0.0.1:{server.server_address[1]}")
    yield client, conn, service
    server.shutdown()
    server.server_close()
    conn.close()
