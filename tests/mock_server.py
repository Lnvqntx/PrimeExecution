"""A local HTTP server that behaves like Roostoo, including signature verification
exactly as the official docs describe (HMAC-SHA256 over the raw sorted `k=v&k=v`)."""
from __future__ import annotations

import hashlib
import hmac
import json
import threading
import time
from http.server import BaseHTTPRequestHandler, HTTPServer
from urllib.parse import parse_qsl, urlparse

from prime.client import ApiError
from tests.fake_exchange import FakeExchange

KEY, SECRET = "TESTKEY", "TESTSECRET"


def make_server(ex: FakeExchange):
    log = {"bad_signature": 0, "orders": 0}

    class H(BaseHTTPRequestHandler):
        def log_message(self, *a): pass

        def _send(self, obj):
            body = json.dumps(obj).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def _verify(self, raw: str) -> dict | None:
            params = dict(parse_qsl(raw, keep_blank_values=True))     # server decodes, then signs raw
            expect = hmac.new(SECRET.encode(), "&".join(f"{k}={params[k]}" for k in sorted(params)).encode(),
                              hashlib.sha256).hexdigest()
            ok = (self.headers.get("RST-API-KEY") == KEY and self.headers.get("MSG-SIGNATURE") == expect
                  and abs(int(params.get("timestamp", 0)) - int(time.time() * 1000)) <= 60_000)
            if not ok:
                log["bad_signature"] += 1
                self._send({"Success": False, "ErrMsg": "bad signature"})
                return None
            return params

        def do_GET(self):
            u = urlparse(self.path)
            if u.path == "/v3/serverTime":
                return self._send({"ServerTime": int(time.time() * 1000)})
            if u.path == "/v3/exchangeInfo":
                return self._send(ex.exchange_info())
            if u.path == "/v3/ticker":
                return self._send(ex.ticker())
            if u.path == "/v3/balance":
                if self._verify(u.query) is None:
                    return
                return self._send(ex.balance())
            self._send({"Success": False, "ErrMsg": "unknown"})

        def do_POST(self):
            raw = self.rfile.read(int(self.headers.get("Content-Length", 0))).decode()
            params = self._verify(raw)
            if params is None:
                return
            if self.path == "/v3/place_order":
                try:
                    log["orders"] += 1
                    return self._send(ex.place_order(params["pair"], params["side"], params["quantity"], params["type"]))
                except ApiError as e:
                    return self._send({"Success": False, "ErrMsg": str(e)})
            self._send({"Success": False, "ErrMsg": "unknown"})

    srv = HTTPServer(("127.0.0.1", 0), H)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv, log
