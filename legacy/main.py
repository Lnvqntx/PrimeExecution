from config import settings
from roostoo_client import RoostooClient


def main():
    print("=" * 60)
    print("PRIME EXECUTION — ROOSTOO CONNECTION TEST")
    print("=" * 60)
    print(f"Live trading enabled: {settings.live_trading}")
    print()

    if not settings.api_key or not settings.secret_key:
        raise RuntimeError("Roostoo API credentials are missing from .env")

    client = RoostooClient(settings.api_key, settings.secret_key)

    print("[1/4] Server time...")
    print(client.server_time())
    print()

    print("[2/4] Exchange info...")
    info = client.exchange_info()
    print(f"Exchange running: {info.get('IsRunning')}")
    pairs = list(info.get("TradePairs", {}).keys())
    print(f"Tradable pairs: {len(pairs)}")
    print(f"Sample pairs: {pairs[:10]}")
    print()

    print("[3/4] Market ticker...")
    ticker = client.ticker()
    data = ticker.get("Data", {})
    print(f"Ticker pairs returned: {len(data)}")
    for pair, values in list(data.items())[:5]:
        print(
            f"{pair}: last={values.get('LastPrice')} "
            f"bid={values.get('MaxBid')} ask={values.get('MinAsk')}"
        )
    print()

    print("[4/4] Competition account checks...")
    balance = client.signed_get("/v3/balance")
    print("Balance response received:", balance.get("Success"))
    print("Wallet:", balance.get("Wallet", {}))

    pending = client.signed_get("/v3/pending_count")
    print("Pending-order response:", pending)
    print()

    print("=" * 60)
    print("SAFE MODE — NO ORDERS WERE SUBMITTED")
    print("=" * 60)


if __name__ == "__main__":
    main()
