"""Small persistent state. The exchange remains the source of truth for holdings;
this file only remembers scheduling and risk bookkeeping across restarts."""
from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass, fields
from pathlib import Path


@dataclass
class State:
    peak_equity: float = 0.0
    breaker_until: float = 0.0
    last_rebalance_day: str = ""     # HKT day of the last scheduled rebalance
    last_trade_day: str = ""         # HKT day of the last filled order
    watchdog_day: str = ""           # HKT day the tight-tolerance pass already ran
    last_scale: float = 1.0
    halted_until: float = 0.0
    reject_streak: int = 0

    @classmethod
    def load(cls, path: Path) -> "State":
        path = Path(path)
        if path.exists():
            try:
                raw = json.loads(path.read_text())
                known = {f.name for f in fields(cls)}
                return cls(**{k: v for k, v in raw.items() if k in known})
            except (ValueError, TypeError):
                pass
        return cls()

    def save(self, path: Path) -> None:
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(path.suffix + ".tmp")
        tmp.write_text(json.dumps(asdict(self), indent=2))
        os.replace(tmp, path)
