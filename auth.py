from __future__ import annotations

import time

import requests

from config import CapitalConfig


class CapitalSessionManager:
    def __init__(self, config: CapitalConfig) -> None:
        self.config = config
        self.session = requests.Session()
        self.session.trust_env = False
        self.cst: str | None = None
        self.security_token: str | None = None
        self.next_login_allowed_at = 0.0

    def login(self, force: bool = False) -> tuple[str, str]:
        if not force and self.cst and self.security_token:
            return self.cst, self.security_token

        backoff_schedule = (0, 10, 30)
        last_error: str | None = None
        for attempt, backoff_seconds in enumerate(backoff_schedule):
            now = time.time()
            if now < self.next_login_allowed_at:
                time.sleep(max(self.next_login_allowed_at - now, 0))
            if backoff_seconds:
                time.sleep(backoff_seconds)

            response = self.session.post(
                f"{self.config.base_url}/session",
                json={
                    "identifier": self.config.identifier,
                    "password": self.config.password,
                    "encryptedPassword": False,
                },
                headers={
                    "X-CAP-API-KEY": self.config.api_key,
                    "Content-Type": "application/json",
                },
                timeout=self.config.timeout_seconds,
            )
            if response.status_code == 429:
                self.next_login_allowed_at = time.time() + 30
                last_error = f"429 {response.text}"
                continue
            if response.status_code != 200:
                raise RuntimeError(f"Login failed: {response.status_code} {response.text}")

            self.cst = response.headers.get("CST")
            self.security_token = response.headers.get("X-SECURITY-TOKEN")
            self.next_login_allowed_at = 0.0
            if not self.cst or not self.security_token:
                raise RuntimeError("CST / X-SECURITY-TOKEN missing")
            return self.cst, self.security_token

        raise RuntimeError(f"Login failed: {last_error or 'unknown error'}")

    def refresh(self) -> tuple[str, str]:
        self.cst = None
        self.security_token = None
        return self.login(force=True)

    def headers(self) -> dict[str, str]:
        if not self.cst or not self.security_token:
            self.login()
        return {
            "X-CAP-API-KEY": self.config.api_key,
            "CST": self.cst or "",
            "X-SECURITY-TOKEN": self.security_token or "",
            "Content-Type": "application/json",
        }
