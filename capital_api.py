from __future__ import annotations

import time
from typing import Any

import requests

from auth import CapitalSessionManager


class CapitalAPI:
    def __init__(self, session_manager: CapitalSessionManager) -> None:
        self.session_manager = session_manager
        self.session = requests.Session()
        self.session.trust_env = False
        self.candle_cache: dict[tuple[str, str, int], dict[str, Any]] = {}
        self.candle_cache_ttl_seconds = 30
        self.stale_candle_fallback_seconds = 15 * 60

    def request(
        self,
        method: str,
        path: str,
        *,
        params: dict[str, Any] | None = None,
        json_payload: dict[str, Any] | None = None,
        timeout: int | None = None,
        relogin_on_401: bool = True,
    ) -> requests.Response:
        url = f"{self.session_manager.config.base_url}{path}"
        response = None
        for attempt, backoff_seconds in enumerate((0, 5, 15)):
            if backoff_seconds:
                time.sleep(backoff_seconds)
            response = self.session.request(
                method=method,
                url=url,
                headers=self.session_manager.headers(),
                params=params,
                json=json_payload,
                timeout=timeout or self.session_manager.config.timeout_seconds,
            )
            if response.status_code == 401 and relogin_on_401:
                self.session_manager.refresh()
                response = self.session.request(
                    method=method,
                    url=url,
                    headers=self.session_manager.headers(),
                    params=params,
                    json=json_payload,
                    timeout=timeout or self.session_manager.config.timeout_seconds,
                )
            if response.status_code != 429 or attempt == 2:
                break
        response.raise_for_status()
        return response

    def get_candles(self, symbol: str, resolution: str = "HOUR", max_candles: int = 200) -> dict[str, Any]:
        max_candles = min(int(max_candles), 1000)
        cache_key = (str(symbol), str(resolution), int(max_candles))
        now = time.time()
        cached = self.candle_cache.get(cache_key)
        if cached and now - cached["timestamp"] < self.candle_cache_ttl_seconds:
            return cached["data"]

        try:
            response = self.request(
                "GET",
                f"/prices/{symbol}",
                params={"resolution": resolution, "max": max_candles},
            )
            data = response.json()
            self.candle_cache[cache_key] = {"timestamp": now, "data": data}
            return data
        except requests.HTTPError as error:
            response = getattr(error, "response", None)
            if (
                response is not None
                and response.status_code == 429
                and cached
                and now - cached["timestamp"] < self.stale_candle_fallback_seconds
            ):
                return cached["data"]
            raise

    def get_confirm(self, deal_reference: str, retries: int = 8, delay: int = 2) -> dict[str, Any]:
        last_error: str | None = None
        for _ in range(retries):
            try:
                response = self.request("GET", f"/confirms/{deal_reference}", timeout=20)
                if response.status_code == 200:
                    return response.json()
                last_error = f"{response.status_code} {response.text}"
            except Exception as error:  # noqa: BLE001
                last_error = str(error)
            time.sleep(delay)
        raise RuntimeError(f"Confirm failed: {last_error}")

    def get_market_info(self, symbol: str) -> dict[str, Any]:
        return self.request("GET", f"/markets/{symbol}").json()

    def get_market_details(self, symbol: str) -> dict[str, Any]:
        return self.get_market_info(symbol)

    def get_open_positions(self) -> list[dict[str, Any]]:
        payload = self.request("GET", "/positions").json()
        if isinstance(payload, dict):
            return payload.get("positions", [])
        return []

    def get_working_orders(self, symbol: str | None = None) -> list[dict[str, Any]]:
        params = {"epic": symbol} if symbol else None
        payload = self.request("GET", "/workingorders", params=params).json()
        if isinstance(payload, dict):
            return payload.get("workingOrders", [])
        return []

    def place_market_order(self, symbol: str, direction: str, sl: float, tp: float, size: float) -> dict[str, Any]:
        submit = self.request(
            "POST",
            "/positions",
            json_payload={
                "epic": symbol,
                "direction": direction,
                "size": size,
                "orderType": "MARKET",
                "stopLevel": sl,
                "profitLevel": tp,
                "guaranteedStop": False,
            },
        ).json()
        deal_reference = submit.get("dealReference")
        if not deal_reference:
            raise RuntimeError(f"No dealReference returned: {submit}")
        confirm = self.get_confirm(deal_reference)
        return {
            "submit": submit,
            "confirm": confirm,
            "dealReference": deal_reference,
            "confirmDealId": confirm.get("dealId"),
            "status": confirm.get("status"),
            "reason": confirm.get("reason"),
            "level": confirm.get("level"),
            "affectedDeals": confirm.get("affectedDeals", []),
        }

    def place_working_order(
        self,
        symbol: str,
        direction: str,
        price: float,
        sl: float,
        tp: float,
        size: float,
        order_type: str = "LIMIT",
    ) -> dict[str, Any]:
        submit = self.request(
            "POST",
            "/workingorders",
            json_payload={
                "epic": symbol,
                "direction": direction,
                "size": size,
                "level": price,
                "type": order_type,
                "stopLevel": sl,
                "profitLevel": tp,
                "guaranteedStop": False,
            },
        ).json()
        deal_reference = submit.get("dealReference")
        if not deal_reference:
            raise RuntimeError(f"No dealReference returned: {submit}")
        confirm = self.get_confirm(deal_reference)
        return {
            "submit": submit,
            "confirm": confirm,
            "dealReference": deal_reference,
            "dealId": confirm.get("dealId"),
            "status": confirm.get("status"),
            "reason": confirm.get("reason"),
            "orderType": order_type,
        }

    def close_position(self, deal_id: str) -> dict[str, Any]:
        positions = self.get_open_positions()
        found = next((item for item in positions if item.get("position", {}).get("dealId") == deal_id), None)
        if found is None:
            all_ids = [item.get("position", {}).get("dealId") for item in positions]
            raise RuntimeError(
                f"Open position not found for dealId={deal_id}. Available open dealIds={all_ids}"
            )

        position = found.get("position", {})
        submit = self.request(
            "DELETE",
            "/positions",
            json_payload={
                "dealId": deal_id,
                "direction": "SELL" if position.get("direction") == "BUY" else "BUY",
                "size": position.get("size"),
                "orderType": "MARKET",
            },
        ).json()
        deal_reference = submit.get("dealReference")
        if not deal_reference:
            return {
                "submit": submit,
                "confirm": None,
                "dealReference": None,
                "status": "UNKNOWN",
                "reason": None,
            }
        confirm = self.get_confirm(deal_reference)
        return {
            "submit": submit,
            "confirm": confirm,
            "dealReference": deal_reference,
            "status": confirm.get("status"),
            "reason": confirm.get("reason"),
        }

    def cancel_working_order(self, order_id: str) -> dict[str, Any]:
        response = self.request("DELETE", f"/workingorders/{order_id}")
        try:
            return response.json()
        except Exception:  # noqa: BLE001
            return {"status_code": response.status_code, "text": response.text}

    def get_account_info(self) -> dict[str, Any]:
        return self.request("GET", "/accounts").json()

    def get_account_preferences(self) -> dict[str, Any]:
        return self.request("GET", "/accounts/preferences").json()

    def get_transactions(
        self,
        *,
        last_period: int | None = None,
        from_date: str | None = None,
        to_date: str | None = None,
        tx_type: str | None = None,
    ) -> list[dict[str, Any]]:
        params: dict[str, Any] = {}
        if from_date:
            params["from"] = from_date
        if to_date:
            params["to"] = to_date
        if last_period is not None:
            params["lastPeriod"] = last_period
        if tx_type:
            params["type"] = tx_type
        payload = self.request("GET", "/history/transactions", params=params or None).json()
        if isinstance(payload, dict):
            return payload.get("transactions", [])
        return []

    def find_open_position_by_epic(self, epic: str) -> dict[str, Any] | None:
        for item in self.get_open_positions():
            position = item.get("position", {})
            market = item.get("market", {})
            if market.get("epic") == epic:
                return {
                    "dealId": position.get("dealId"),
                    "direction": position.get("direction"),
                    "size": position.get("size"),
                    "epic": market.get("epic"),
                    "raw": item,
                }
        return None

    def find_working_order_by_epic(self, epic: str) -> dict[str, Any] | None:
        for item in self.get_working_orders(symbol=epic):
            market_data = item.get("marketData", {})
            if item.get("epic") == epic or market_data.get("epic") == epic:
                return {
                    "dealId": item.get("dealId"),
                    "direction": item.get("direction"),
                    "level": item.get("level"),
                    "raw": item,
                }
        return None

    def find_real_open_position(
        self,
        *,
        epic: str | None = None,
        direction: str | None = None,
        wait_seconds: int = 10,
    ) -> dict[str, Any] | None:
        for _ in range(wait_seconds):
            for item in self.get_open_positions():
                position = item.get("position", {})
                market = item.get("market", {})
                if epic and market.get("epic") != epic:
                    continue
                if direction and position.get("direction") != direction:
                    continue
                return {
                    "dealId": position.get("dealId"),
                    "direction": position.get("direction"),
                    "size": position.get("size"),
                    "epic": market.get("epic"),
                    "raw": item,
                }
            time.sleep(1)
        return None
