import hashlib
import hmac

import pytest
import requests

from prime.client import ApiError, OrderUncertain, RoostooClient

# Worked example from the official Roostoo API docs.
DOC_SECRET = "S1XP1e3UZj6A7H5fATj0jNhqPxxdSJYdInClVN65XAbvqqMKjVHjA7PZj4W12oep"
DOC_SIGNATURE = "20b7fd5550b67b3bf0c1684ed0f04885261db8fdabd38611e9e6af23c19b7fff"


def test_signature_matches_official_docs_example():
    c = RoostooClient("USEAPIKEYASMYID", DOC_SECRET, min_gap=0)
    total, headers = c.sign({"pair": "BNB/USD", "quantity": "2000", "side": "BUY",
                             "timestamp": "1580774512000", "type": "MARKET"})
    assert total == "pair=BNB/USD&quantity=2000&side=BUY&timestamp=1580774512000&type=MARKET"
    assert headers["MSG-SIGNATURE"] == DOC_SIGNATURE
    assert headers["RST-API-KEY"] == "USEAPIKEYASMYID"


def test_signature_is_independent_of_dict_order():
    c = RoostooClient("k", "s", min_gap=0)
    a, _ = c.sign({"b": "2", "a": "1"})
    b, _ = c.sign({"a": "1", "b": "2"})
    assert a == b == "a=1&b=2"


class _Resp:
    def __init__(self, status=200, payload=None):
        self.status_code, self._p = status, payload or {}
    def raise_for_status(self):
        if self.status_code >= 400:
            raise requests.HTTPError(str(self.status_code))
    def json(self):
        return self._p


class _Session:
    def __init__(self, post=None, get=None):
        self._post, self._get, self.posts = post, get, 0
    def post(self, *a, **k):
        self.posts += 1
        r = self._post
        if isinstance(r, Exception):
            raise r
        return r
    def get(self, *a, **k):
        r = self._get
        if isinstance(r, Exception):
            raise r
        return r


def test_post_timeout_is_uncertain_and_never_retried():
    s = _Session(post=requests.Timeout("slow"))
    c = RoostooClient("k", "s", min_gap=0, session=s)
    with pytest.raises(OrderUncertain):
        c.place_order("BTC/USD", "BUY", "1")
    assert s.posts == 1


def test_http_500_on_post_is_uncertain():
    c = RoostooClient("k", "s", min_gap=0, session=_Session(post=_Resp(502)))
    with pytest.raises(OrderUncertain):
        c.place_order("BTC/USD", "BUY", "1")


def test_success_false_raises_api_error_with_message():
    c = RoostooClient("k", "s", min_gap=0, session=_Session(post=_Resp(200, {"Success": False, "ErrMsg": "bad qty"})))
    with pytest.raises(ApiError, match="bad qty"):
        c.place_order("BTC/USD", "BUY", "1")


def test_short_endpoints_sign_only_listed_params(monkeypatch):
    seen = {}
    c = RoostooClient("k", "s", min_gap=0)
    monkeypatch.setattr(c, "_post", lambda path, params: seen.update(path=path, params=params) or {"Success": True})
    c.short_open("BTC/USD", 1000)
    assert seen["path"] == "/v6/short_open" and set(seen["params"]) == {"pair", "collateral"}
    c.short_close("BTC/USD", close_pct=50)
    assert seen["path"] == "/v6/short_close" and set(seen["params"]) == {"pair", "close_pct"}
