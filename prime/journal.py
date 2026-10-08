"""Append-only JSONL journals. Every decision and every order is recorded with its
reason, which is what the judges' 'trade log integrity' screen and our own
slippage measurements rely on."""
from __future__ import annotations

import json
import logging
import time
from logging.handlers import RotatingFileHandler
from pathlib import Path


class Journal:
    def __init__(self, log_dir: Path):
        self.dir = Path(log_dir)
        self.dir.mkdir(parents=True, exist_ok=True)

    def write(self, stream: str, **fields) -> None:
        rec = {"ts": round(time.time(), 3), **fields}
        with (self.dir / f"{stream}.jsonl").open("a") as f:
            f.write(json.dumps(rec, default=str) + "\n")
            f.flush()


def setup_logging(log_dir: Path) -> logging.Logger:
    log_dir = Path(log_dir)
    log_dir.mkdir(parents=True, exist_ok=True)
    logger = logging.getLogger("prime")
    if logger.handlers:
        return logger
    logger.setLevel(logging.INFO)
    fmt = logging.Formatter("%(asctime)s %(levelname)s %(message)s")
    fh = RotatingFileHandler(log_dir / "bot.log", maxBytes=5_000_000, backupCount=5)
    fh.setFormatter(fmt)
    sh = logging.StreamHandler()
    sh.setFormatter(fmt)
    logger.addHandler(fh)
    logger.addHandler(sh)
    return logger
