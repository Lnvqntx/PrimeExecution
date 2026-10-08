"""The real RoostooClient over real HTTP against a signature-verifying local server,
driven through the actual command-line entrypoint."""
import json

from prime.bot import main
from tests.fake_exchange import FakeExchange
from tests.mock_server import KEY, SECRET, make_server


def run(monkeypatch, tmp_path, live_env, live_flag):
    ex = FakeExchange()
    srv, log = make_server(ex)
    import prime.client as client_mod
    monkeypatch.setattr(client_mod, "BASE_URL", f"http://127.0.0.1:{srv.server_port}")
    monkeypatch.setattr("prime.bot.RoostooClient.__init__.__defaults__",
                        (f"", "", f"http://127.0.0.1:{srv.server_port}", 0.0, 10.0, None))
    monkeypatch.setenv("ROOSTOO_API_KEY", KEY)
    monkeypatch.setenv("ROOSTOO_SECRET_KEY", SECRET)
    monkeypatch.setenv("LIVE_TRADING", "true" if live_env else "false")
    monkeypatch.setenv("PRIME_LOG_DIR", str(tmp_path / "logs"))
    code = main(["--once"] + (["--live"] if live_flag else []))
    srv.shutdown()
    return code, ex, log


def test_live_cli_places_signed_orders_over_http(monkeypatch, tmp_path):
    code, ex, log = run(monkeypatch, tmp_path, True, True)
    assert code == 0 and log["bad_signature"] == 0
    assert log["orders"] == 10 and len({o["pair"] for o in ex.orders}) == 10
    rows = [json.loads(l) for l in (tmp_path / "logs" / "orders.jsonl").read_text().splitlines()]
    assert all(r["outcome"] == "filled" and r["live"] for r in rows)


def test_dry_cli_over_http_sends_nothing(monkeypatch, tmp_path):
    code, ex, log = run(monkeypatch, tmp_path, True, False)       # --live not given
    assert code == 0 and ex.orders == [] and log["orders"] == 0 and log["bad_signature"] == 0


def test_wrong_secret_fails_preflight_cleanly(monkeypatch, tmp_path):
    ex = FakeExchange()
    srv, log = make_server(ex)
    monkeypatch.setattr("prime.bot.RoostooClient.__init__.__defaults__",
                        ("", "", f"http://127.0.0.1:{srv.server_port}", 0.0, 10.0, None))
    monkeypatch.setenv("ROOSTOO_API_KEY", KEY)
    monkeypatch.setenv("ROOSTOO_SECRET_KEY", "WRONG")
    monkeypatch.setenv("PRIME_LOG_DIR", str(tmp_path / "logs"))
    assert main(["--once"]) == 3 and ex.orders == []
    srv.shutdown()
