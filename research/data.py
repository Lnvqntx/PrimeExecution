"""Download Binance spot daily klines (public dump) and build a price/volume panel.

Source: the public Binance data dump (data.binance.vision). Files are fetched from the
bucket's S3 endpoint, which serves the same objects as https://data.binance.vision.

Universe (no look-ahead): the 30 USDT pairs with the highest median daily quote volume
over the PRE-window 2024-07..2024-09, excluding stablecoins and leveraged tokens. The
pre-window is used only for this ranking and for indicator warm-up; every P&L number
comes from 2024-10..2026-09.

Zips are parsed in memory (never extracted to disk) and kept under research/data/raw/
(git-ignored). Usage:  python -m research.data
"""
from __future__ import annotations

import csv
import hashlib
import io
import json
import re
import time
import urllib.parse
import urllib.request
import zipfile
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from xml.etree import ElementTree

BUCKET = "https://s3-ap-northeast-1.amazonaws.com/data.binance.vision"
PREFIX = "data/spot/monthly/klines/"
ROOT = Path(__file__).resolve().parent
RAW = ROOT / "data" / "raw"
PANEL = ROOT / "data" / "klines_1d.csv"
UNIVERSE = ROOT / "universe.json"

RANK_MONTHS = ["2024-07", "2024-08", "2024-09"]
WINDOW_END = "2026-09"  # P&L window starts 2024-10 (research/run.py)
N_PAIRS = 30

STABLES = {"USDC", "FDUSD", "TUSD", "USDP", "DAI", "BUSD", "EUR", "EURI", "AEUR", "PAX", "USDS", "PYUSD",
           "USDE", "XUSD", "BFUSD", "USD1", "UST", "GBP", "PAXG", "WBTC", "WBETH", "BNSOL"}
UNVERIFIED: list[str] = []  # files whose published checksum could not be fetched
LEVERAGED = re.compile(r"(UP|DOWN|BULL|BEAR)USDT$")


def _get(url: str, tries: int = 5) -> bytes:
    """Fetch with backoff. Only called for objects the bucket listing says exist, so a 404
    (which the endpoint occasionally returns under load) is retried like any other error."""
    for i in range(tries):
        try:
            with urllib.request.urlopen(url, timeout=30) as r:
                return r.read()
        except OSError:
            time.sleep(2 ** i)
    raise RuntimeError(f"failed to fetch {url}")


def _list(prefix: str) -> tuple[list[str], list[str]]:
    """(sub-prefixes, object keys) under `prefix`, following pagination."""
    ns = "{http://s3.amazonaws.com/doc/2006-03-01/}"
    dirs, keys, marker = [], [], ""
    while True:
        url = f"{BUCKET}?delimiter=/&prefix={urllib.parse.quote(prefix)}&marker={urllib.parse.quote(marker)}"
        root = ElementTree.fromstring(_get(url))
        page_dirs = [p.find(f"{ns}Prefix").text for p in root.iter(f"{ns}CommonPrefixes")]
        page_keys = [c.find(f"{ns}Key").text for c in root.iter(f"{ns}Contents")]
        dirs += page_dirs
        keys += page_keys
        if root.find(f"{ns}IsTruncated").text != "true":
            return dirs, keys
        nxt = root.find(f"{ns}NextMarker")
        marker = nxt.text if nxt is not None else (page_keys or page_dirs)[-1]


def list_usdt_symbols() -> list[str]:
    dirs, _ = _list(PREFIX)
    out = [d[len(PREFIX):].strip("/") for d in dirs]
    return sorted(
        s for s in out
        if s.endswith("USDT") and not LEVERAGED.search(s) and s[:-4] not in STABLES
        and s.isascii() and s[:-4].isalnum()
    )


def available_months(symbol: str) -> set[str]:
    _, keys = _list(f"{PREFIX}{symbol}/1d/")
    return {k.rsplit("-1d-", 1)[1][:-4] for k in keys if k.endswith(".zip")}


def months(start: str, end: str) -> list[str]:
    y, m = map(int, start.split("-"))
    ey, em = map(int, end.split("-"))
    out = []
    while (y, m) <= (ey, em):
        out.append(f"{y:04d}-{m:02d}")
        y, m = (y + 1, 1) if m == 12 else (y, m + 1)
    return out


def fetch(symbol: str, month: str) -> Path:
    """Download one monthly zip (cached) and verify it against the published SHA-256."""
    path = RAW / symbol / f"{symbol}-1d-{month}.zip"
    if path.exists():
        return path
    url = f"{BUCKET}/{PREFIX}{symbol}/1d/{symbol}-1d-{month}.zip"
    blob = _get(url)
    try:
        checksum = _get(url + ".CHECKSUM", tries=3)
    except RuntimeError:  # a few listed .CHECKSUM objects are not served; note and continue
        UNVERIFIED.append(f"{symbol}-{month}")
    else:
        if checksum.split()[0].decode() != hashlib.sha256(blob).hexdigest():
            raise RuntimeError(f"checksum mismatch for {url}")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(blob)
    return path


def read_zip(path: Path) -> list[dict]:
    """Parse one monthly kline zip in memory. Open times are ms (<=2024) or us (2025+)."""
    rows = []
    with zipfile.ZipFile(path) as zf:
        for name in zf.namelist():
            if not name.endswith(".csv") or "/" in name or ".." in name:
                continue
            for rec in csv.reader(io.TextIOWrapper(zf.open(name), encoding="ascii")):
                if not rec or not rec[0].isdigit():
                    continue  # header line in some files
                t = int(rec[0])
                t = t // 1000 if t > 10**14 else t  # us -> ms
                rows.append({
                    "date": time.strftime("%Y-%m-%d", time.gmtime(t / 1000)),
                    "open": float(rec[1]), "high": float(rec[2]), "low": float(rec[3]),
                    "close": float(rec[4]), "quote_volume": float(rec[7]),
                })
    return rows


def _fetch_all(jobs: list[tuple[str, str]], strict: bool = True) -> list[Path | None]:
    """strict=False returns None for files that cannot be fetched (used only for ranking)."""
    def one(job):
        try:
            return fetch(*job)
        except RuntimeError:
            if strict:
                raise
            print(f"warning: could not fetch {job[0]} {job[1]}; excluded from ranking")
            return None
    with ThreadPoolExecutor(6) as ex:
        return list(ex.map(one, jobs))


def rank_universe(symbols: list[str]) -> list[dict]:
    with ThreadPoolExecutor(6) as ex:
        avail = dict(zip(symbols, ex.map(available_months, symbols)))
    # only pairs with all three ranking months published can be ranked
    jobs = [(s, m) for s in symbols for m in RANK_MONTHS if set(RANK_MONTHS) <= avail[s]]
    vols: dict[str, list[float]] = {}
    for (s, _), p in zip(jobs, _fetch_all(jobs, strict=False)):
        if p is None:
            continue
        vols.setdefault(s, []).extend(r["quote_volume"] for r in read_zip(p))
    scored = []
    for s, v in vols.items():
        if len(v) < 80:  # must have traded through (almost) the whole ranking window
            continue
        v = sorted(v)
        scored.append({"symbol": s, "median_quote_volume_usd": round(v[len(v) // 2], 0)})
    scored.sort(key=lambda d: d["median_quote_volume_usd"], reverse=True)
    return scored[:N_PAIRS]


def build_panel(universe: list[str]) -> None:
    all_months = months(RANK_MONTHS[0], WINDOW_END)
    with ThreadPoolExecutor(6) as ex:
        avail = dict(zip(universe, ex.map(available_months, universe)))
    jobs = [(s, m) for s in universe for m in all_months if m in avail[s]]
    PANEL.parent.mkdir(parents=True, exist_ok=True)
    with PANEL.open("w", newline="") as f:
        w = csv.DictWriter(f, ["symbol", "date", "open", "high", "low", "close", "quote_volume"])
        w.writeheader()
        for (s, _), p in zip(jobs, _fetch_all(jobs)):
            for r in read_zip(p):
                w.writerow({"symbol": s, **r})


def main() -> None:
    symbols = list_usdt_symbols()
    print(f"{len(symbols)} candidate USDT symbols in the dump")
    top = rank_universe(symbols)
    UNIVERSE.write_text(json.dumps({
        "rule": f"top {N_PAIRS} USDT pairs by median daily quote volume over {RANK_MONTHS[0]}..{RANK_MONTHS[-1]} "
                "(pre-window), excluding stablecoins/wrapped/leveraged tokens",
        "pairs": top,
    }, indent=1) + "\n")
    print("universe:", ", ".join(d["symbol"] for d in top))
    build_panel([d["symbol"] for d in top])
    print(f"wrote {PANEL}")
    print(f"{len(UNVERIFIED)} files without a fetchable checksum: {sorted(UNVERIFIED)}")


if __name__ == "__main__":
    main()
