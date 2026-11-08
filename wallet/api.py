"""Minimal JSON HTTP API over WalletService (Python standard library only)."""
import json
import re
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from wallet.service import WalletError


def make_handler(service, api_key):
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def _send(self, status, body):
            data = json.dumps(body).encode()
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def _error(self, status, code, message):
            self._send(status, {"error": {"code": code, "message": message}})

        def _auth_ok(self):
            if self.headers.get("X-API-Key") != api_key:
                self._error(401, "UNAUTHORIZED", "missing or invalid API key")
                return False
            return True

        def _body(self):
            length = int(self.headers.get("Content-Length") or 0)
            try:
                body = json.loads(self.rfile.read(length) or b"{}")
            except json.JSONDecodeError:
                raise WalletError("INVALID_JSON", "request body is not valid JSON")
            if not isinstance(body, dict):
                raise WalletError("INVALID_JSON", "request body must be a JSON object")
            return body

        def _handle(self, fn):
            if not self._auth_ok():
                return
            try:
                fn()
            except WalletError as e:
                self._error(e.status, e.code, e.message)

        def do_GET(self):
            def run():
                m = re.fullmatch(r"/v1/wallets/([\w-]+)", self.path)
                if not m:
                    return self._error(404, "NOT_FOUND", "route not found")
                w = service.get_wallet(m.group(1))
                self._send(200, {"id": w["id"], "owner": w["owner"], "balance": f"{w['balance_paisa'] / 100:.2f}"})
            self._handle(run)

        def do_POST(self):
            def run():
                body = self._body()
                key = self.headers.get("Idempotency-Key")
                if self.path == "/v1/transfers":
                    missing = [f for f in ("from_wallet", "to_wallet", "amount") if f not in body]
                    if missing:
                        raise WalletError("MISSING_FIELD", f"missing field(s): {', '.join(missing)}")
                    txn, created = service.transfer(key, body["from_wallet"], body["to_wallet"],
                                                    body["amount"], merchant=bool(body.get("merchant")))
                    self._send(201 if created else 200, txn)
                elif re.fullmatch(r"/v1/transfers/\d+/refund", self.path):
                    txn_id = int(self.path.split("/")[3])
                    if not key:
                        raise WalletError("MISSING_IDEMPOTENCY_KEY", "Idempotency-Key is required")
                    self._send(201, service.refund(key, txn_id))
                elif re.fullmatch(r"/v1/merchants/[\w-]+/settle", self.path):
                    self._send(200, service.settle(self.path.split("/")[3]))
                else:
                    self._error(404, "NOT_FOUND", "route not found")
            self._handle(run)

    return Handler


def serve(service, api_key, port=0):
    server = ThreadingHTTPServer(("127.0.0.1", port), make_handler(service, api_key))
    return server
