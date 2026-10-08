import os
from dataclasses import dataclass
from dotenv import load_dotenv

load_dotenv()


@dataclass(frozen=True)
class Settings:
    api_key: str = os.getenv("ROOSTOO_API_KEY", "")
    secret_key: str = os.getenv("ROOSTOO_SECRET_KEY", "")
    live_trading: bool = os.getenv("LIVE_TRADING", "false").lower() == "true"
    poll_interval_seconds: int = int(os.getenv("POLL_INTERVAL_SECONDS", "60"))


settings = Settings()
