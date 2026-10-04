from config import settings
from roostoo_client import RoostooClient


def main():
    print("Prime Execution — Roostoo connectivity test")
    print(f"Live trading enabled: {settings.live_trading}")

    client = RoostooClient(settings.api_key, settings.secret_key)
    print("Server:", client.server_time())
    print("Ticker sample:", client.ticker())

    if not settings.live_trading:
        print("SAFE MODE: no orders will be submitted.")


if __name__ == "__main__":
    main()
