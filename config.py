from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

from dotenv import load_dotenv
from app_paths import BASE_DIR, resolve_runtime_path
from market_hours import DEFAULT_WEEKEND_CLOSE_HOUR_UTC, DEFAULT_WEEKEND_CLOSE_MINUTE_UTC


DEFAULT_SYMBOLS = (
    "EURUSD",
    "GBPUSD",
    "USDJPY",
    "AUDUSD",
    "USDCAD",
    "USDCHF",
    "NZDUSD",
    "EURJPY",
    "GBPJPY",
    "AUDJPY",
)


@dataclass(slots=True)
class CapitalConfig:
    api_key: str
    identifier: str
    password: str
    base_url: str = "https://demo-api-capital.backend-capital.com/api/v1"
    timeout_seconds: int = 30


@dataclass(slots=True)
class TelegramConfig:
    bot_token: str = ""
    chat_id: str = ""
    enabled: bool = True
    mini_app_url: str = ""
    mini_app_button_text: str = "Open Dashboard"

    @property
    def is_enabled(self) -> bool:
        return self.enabled and bool(self.bot_token) and bool(self.chat_id)

    @property
    def has_mini_app(self) -> bool:
        return self.is_enabled and bool(self.mini_app_url)


@dataclass(slots=True)
class StrategyConfig:
    symbols: dict[str, str]
    atr_period: int = 14
    atr_filter_pct: float = 0.1
    tp_multiplier: float = 2.0
    target_margin_usd: float = 20.0
    min_free_margin_usd: float = 20.0
    session_start_hour_utc: int = 9
    asian_session_end_hour_utc: int = 8
    entry_start_hour_utc: int = 10
    entry_end_hour_utc: int = 23
    position_force_close_hour_utc: int = 8
    position_force_close_minute_utc: int = 59
    weekend_close_hour_utc: int = DEFAULT_WEEKEND_CLOSE_HOUR_UTC
    weekend_close_minute_utc: int = DEFAULT_WEEKEND_CLOSE_MINUTE_UTC
    loop_interval_seconds: int = 20
    history_candles: int = 250
    signal_relative_volume_threshold: float = 0.0
    regime_guard_enabled: bool = False
    regime_guard_lookback_trades: int = 6
    regime_guard_min_closed_trades: int = 5
    regime_guard_min_win_rate_pct: float = 34.0
    regime_guard_min_net_pnl: float = 0.0
    regime_guard_max_consecutive_losses: int = 3
    regime_guard_cooldown_days: int = 15
    target_leverage_by_type: dict[str, float] = field(
        default_factory=lambda: {
            "CURRENCIES": 100.0,
            "COMMODITIES": 10.0,
        }
    )


@dataclass(slots=True)
class BacktestConfig:
    candles: int = 1000
    output_dir: Path = Path("backtests")


@dataclass(slots=True)
class RuntimeConfig:
    state_file: Path = Path("state.json")
    runtime_state_file: Path = Path("runtime_state.json")
    order_audit_file: Path = Path("order_audit.jsonl")
    journal_json_file: Path = Path("performance_journal.json")
    journal_csv_file: Path = Path("performance_journal.csv")
    backtest_output_dir: Path = Path("backtests")


@dataclass(slots=True)
class AppConfig:
    base_dir: Path
    capital: CapitalConfig
    telegram: TelegramConfig
    strategy: StrategyConfig
    backtest: BacktestConfig
    runtime: RuntimeConfig


def _env(name: str, default: str | None = None, required: bool = False) -> str:
    value = os.getenv(name, default)
    if required and not value:
        raise ValueError(f"Missing required environment variable: {name}")
    return value or ""


def _env_float(name: str, default: float) -> float:
    value = os.getenv(name)
    return float(value) if value is not None else default


def _env_int(name: str, default: int) -> int:
    value = os.getenv(name)
    return int(value) if value is not None else default


def _env_bool(name: str, default: bool) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def _parse_symbols(raw_value: str | None) -> dict[str, str]:
    if not raw_value:
        return {symbol: symbol for symbol in DEFAULT_SYMBOLS}

    raw_items = [item.strip().upper() for item in raw_value.split(",") if item.strip()]
    if not raw_items:
        return {symbol: symbol for symbol in DEFAULT_SYMBOLS}
    return {symbol: symbol for symbol in raw_items}


def _load_env_file(env_path: Path) -> None:
    if not env_path.exists():
        return
    for raw_line in env_path.read_text(encoding="utf-8-sig").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip())


def load_config(env_path: str | Path = ".env") -> AppConfig:
    base_dir = BASE_DIR
    resolved_env_path = Path(env_path)
    if not resolved_env_path.is_absolute():
        resolved_env_path = base_dir / resolved_env_path
    _load_env_file(resolved_env_path)
    load_dotenv(dotenv_path=resolved_env_path, override=False)

    capital = CapitalConfig(
        api_key=_env("CAPITAL_API_KEY", required=True),
        identifier=_env("CAPITAL_IDENTIFIER", required=True),
        password=_env("CAPITAL_PASSWORD", required=True),
        base_url=_env(
            "CAPITAL_BASE_URL",
            "https://demo-api-capital.backend-capital.com/api/v1",
        ),
        timeout_seconds=_env_int("CAPITAL_TIMEOUT_SECONDS", 30),
    )

    telegram = TelegramConfig(
        bot_token=_env("TELEGRAM_BOT_TOKEN", ""),
        chat_id=_env("TELEGRAM_CHAT_ID", ""),
        enabled=_env_bool("AB_TELEGRAM_ENABLED", True),
        mini_app_url=_env("AB_TELEGRAM_MINI_APP_URL", ""),
        mini_app_button_text=_env("AB_TELEGRAM_MINI_APP_TEXT", "Open Dashboard"),
    )

    strategy = StrategyConfig(
        symbols=_parse_symbols(_env("AB_SYMBOLS", ",".join(DEFAULT_SYMBOLS))),
        atr_period=_env_int("AB_ATR_PERIOD", 14),
        atr_filter_pct=_env_float("AB_ATR_FILTER_PCT", 0.1),
        tp_multiplier=_env_float("AB_TP_MULTIPLIER", 2.0),
        target_margin_usd=_env_float("AB_TARGET_MARGIN_USD", 20.0),
        min_free_margin_usd=_env_float("AB_MIN_FREE_MARGIN_USD", 20.0),
        session_start_hour_utc=_env_int("AB_SESSION_START_HOUR_UTC", 9),
        asian_session_end_hour_utc=_env_int("AB_ASIAN_SESSION_END_HOUR_UTC", 8),
        entry_start_hour_utc=_env_int("AB_ENTRY_START_HOUR_UTC", 10),
        entry_end_hour_utc=_env_int("AB_ENTRY_END_HOUR_UTC", 23),
        position_force_close_hour_utc=_env_int("AB_FORCE_CLOSE_HOUR_UTC", 8),
        position_force_close_minute_utc=_env_int("AB_FORCE_CLOSE_MINUTE_UTC", 59),
        weekend_close_hour_utc=_env_int("AB_WEEKEND_CLOSE_HOUR_UTC", DEFAULT_WEEKEND_CLOSE_HOUR_UTC),
        weekend_close_minute_utc=_env_int("AB_WEEKEND_CLOSE_MINUTE_UTC", DEFAULT_WEEKEND_CLOSE_MINUTE_UTC),
        loop_interval_seconds=_env_int("AB_LOOP_INTERVAL_SECONDS", 20),
        history_candles=_env_int("AB_HISTORY_CANDLES", 250),
        signal_relative_volume_threshold=_env_float("AB_SIGNAL_RELATIVE_VOLUME_THRESHOLD", 0.0),
        regime_guard_enabled=_env_bool("AB_REGIME_GUARD_ENABLED", False),
        regime_guard_lookback_trades=_env_int("AB_REGIME_GUARD_LOOKBACK_TRADES", 6),
        regime_guard_min_closed_trades=_env_int("AB_REGIME_GUARD_MIN_CLOSED_TRADES", 5),
        regime_guard_min_win_rate_pct=_env_float("AB_REGIME_GUARD_MIN_WIN_RATE_PCT", 34.0),
        regime_guard_min_net_pnl=_env_float("AB_REGIME_GUARD_MIN_NET_PNL", 0.0),
        regime_guard_max_consecutive_losses=_env_int("AB_REGIME_GUARD_MAX_CONSECUTIVE_LOSSES", 3),
        regime_guard_cooldown_days=_env_int("AB_REGIME_GUARD_COOLDOWN_DAYS", 15),
    )

    runtime = RuntimeConfig(
        state_file=resolve_runtime_path("AB_STATE_FILE", "state.json"),
        runtime_state_file=resolve_runtime_path("AB_RUNTIME_STATE_FILE", "runtime_state.json"),
        order_audit_file=resolve_runtime_path("AB_ORDER_AUDIT_FILE", "order_audit.jsonl"),
        journal_json_file=resolve_runtime_path("AB_JOURNAL_JSON_FILE", "performance_journal.json"),
        journal_csv_file=resolve_runtime_path("AB_JOURNAL_CSV_FILE", "performance_journal.csv"),
        backtest_output_dir=resolve_runtime_path("AB_BACKTEST_OUTPUT_DIR", "backtests"),
    )

    backtest = BacktestConfig(
        candles=_env_int("AB_BACKTEST_CANDLES", 1000),
        output_dir=runtime.backtest_output_dir,
    )

    return AppConfig(
        base_dir=base_dir,
        capital=capital,
        telegram=telegram,
        strategy=strategy,
        backtest=backtest,
        runtime=runtime,
    )
