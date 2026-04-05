from __future__ import annotations

import requests

from config import TelegramConfig


class TelegramNotifier:
    def __init__(self, config: TelegramConfig) -> None:
        self.config = config
        self.session = requests.Session()
        self.session.trust_env = False
        self._menu_button_configured = False

    @property
    def enabled(self) -> bool:
        return self.config.is_enabled

    def _api_url(self, method: str) -> str:
        return f"https://api.telegram.org/bot{self.config.bot_token}/{method}"

    def _mini_app_reply_markup(self) -> dict | None:
        if not self.config.has_mini_app:
            return None
        return {
            "inline_keyboard": [
                [
                    {
                        "text": self.config.mini_app_button_text,
                        "web_app": {
                            "url": self.config.mini_app_url,
                        },
                    }
                ]
            ]
        }

    def ensure_menu_button(self) -> None:
        if not self.config.has_mini_app or self._menu_button_configured:
            return
        try:
            self.session.post(
                self._api_url("setChatMenuButton"),
                json={
                    "menu_button": {
                        "type": "web_app",
                        "text": self.config.mini_app_button_text,
                        "web_app": {
                            "url": self.config.mini_app_url,
                        },
                    }
                },
                timeout=15,
            )
            self._menu_button_configured = True
        except Exception:  # noqa: BLE001
            return

    def send(self, message: str) -> None:
        if not self.enabled:
            return
        self.ensure_menu_button()
        try:
            payload = {
                "chat_id": self.config.chat_id,
                "text": message,
                "parse_mode": "HTML",
            }
            reply_markup = self._mini_app_reply_markup()
            if reply_markup is not None:
                payload["reply_markup"] = reply_markup
            self.session.post(self._api_url("sendMessage"), json=payload, timeout=15)
        except Exception:  # noqa: BLE001
            return
