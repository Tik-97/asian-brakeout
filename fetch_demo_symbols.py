from __future__ import annotations

from auth import CapitalSessionManager
from capital_api import CapitalAPI
from config import load_config


def fetch_demo_symbols() -> None:
    config = load_config()
    api = CapitalAPI(CapitalSessionManager(config.capital))
    response = api.request("GET", "/markets").json()
    markets = response.get("markets", []) if isinstance(response, dict) else []

    rows = [
        f"{market.get('instrumentName', '')} - {market.get('epic', '')}"
        for market in markets
        if market.get("marketStatus") == "TRADEABLE"
    ]
    print("\n".join(rows))


if __name__ == "__main__":
    fetch_demo_symbols()
