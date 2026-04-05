from __future__ import annotations

import csv
import datetime as dt
import json
import subprocess
import sys
from pathlib import Path


BASE_DIR = Path(__file__).resolve().parent
OUTPUT_ROOT = BASE_DIR / r"backtests\yearly_4pair_volume_1_50_study_2020_2026"
SYMBOLS = ["USDJPY", "GBPJPY", "EURJPY", "AUDJPY"]
START_DATE = dt.date(2020, 4, 3)
END_DATE = dt.date(2026, 4, 3)
INITIAL_EQUITY = 400.0
INITIAL_DEPOSIT = 400.0
PORTFOLIO_MARGIN_FRACTION = 0.25
WITHDRAWAL_TRIGGER = 800.0
FIRST_WITHDRAWAL = 400.0
FOLLOWUP_WITHDRAW_FRACTION = 0.25
SIGNAL_RELATIVE_VOLUME_THRESHOLD = 1.5


def run_command(command: list[str]) -> None:
    print("RUN:", " ".join(command))
    subprocess.run(command, cwd=str(BASE_DIR), check=True)


def summary_file_for(folder: Path) -> Path:
    matches = sorted(folder.glob("yearly_backtest_*_summary.json"))
    if len(matches) != 1:
        raise FileNotFoundError(f"Expected exactly one summary json in {folder}, found {len(matches)}")
    return matches[0]


def periods() -> list[tuple[dt.date, dt.date]]:
    windows: list[tuple[dt.date, dt.date]] = []
    current = START_DATE
    while current < END_DATE:
        windows.append((current, dt.date(current.year + 1, current.month, current.day)))
        current = dt.date(current.year + 1, current.month, current.day)
    return windows


def collect_row(period_label: str, summary_path: Path) -> dict[str, object]:
    summary = json.loads(summary_path.read_text(encoding="utf-8"))
    return {
        "period": period_label,
        "symbols": summary.get("Symbols"),
        "signal_relative_volume_threshold": SIGNAL_RELATIVE_VOLUME_THRESHOLD,
        "accepted_trades": summary.get("AcceptedTrades"),
        "win_rate_pct": summary.get("WinRatePct"),
        "profit_factor": summary.get("ProfitFactor"),
        "net_pnl_usd": summary.get("NetPnLUSD"),
        "total_withdrawn_usd": summary.get("TotalWithdrawnUSD"),
        "final_trading_equity_usd": summary.get("FinalTradingEquityUSD"),
        "ending_total_value_usd": summary.get("EndingTotalValueUSD"),
        "return_pct_on_initial": summary.get("ReturnPctOnInitial"),
        "max_drawdown_trading_pct": summary.get("MaxDrawdownTradingPct"),
        "max_drawdown_total_value_pct": summary.get("MaxDrawdownTotalValuePct"),
        "summary_json": str(summary_path),
    }


def main() -> None:
    OUTPUT_ROOT.mkdir(parents=True, exist_ok=True)
    rows: list[dict[str, object]] = []

    for start_date, end_date in periods():
        period_label = f"{start_date.year}-{end_date.year}"
        folder = OUTPUT_ROOT / period_label / "volume_rel_1_50"
        folder.mkdir(parents=True, exist_ok=True)

        backtest_cmd = [
            sys.executable,
            "main.py",
            "--env-file",
            ".env",
            "backtest",
            "--symbols",
            *SYMBOLS,
            "--from-date",
            start_date.isoformat(),
            "--to-date",
            end_date.isoformat(),
            "--initial-equity",
            str(INITIAL_EQUITY),
            "--portfolio-margin-fraction",
            str(PORTFOLIO_MARGIN_FRACTION),
            "--signal-relative-volume-threshold",
            str(SIGNAL_RELATIVE_VOLUME_THRESHOLD),
            "--output-dir",
            str(folder.relative_to(BASE_DIR)),
        ]
        run_command(backtest_cmd)

        export_cmd = [
            sys.executable,
            "export_yearly_backtest_package.py",
            "--env-file",
            ".env",
            "--input-csv",
            str((folder / "portfolio_trades.csv").resolve()),
            "--output-dir",
            str(folder.resolve()),
            "--symbols",
            *SYMBOLS,
            "--from-date",
            start_date.isoformat(),
            "--to-date",
            end_date.isoformat(),
            "--initial-deposit",
            str(INITIAL_DEPOSIT),
            "--dynamic-margin-fraction",
            str(PORTFOLIO_MARGIN_FRACTION),
            "--withdrawal-trigger",
            str(WITHDRAWAL_TRIGGER),
            "--first-withdrawal",
            str(FIRST_WITHDRAWAL),
            "--followup-withdraw-fraction",
            str(FOLLOWUP_WITHDRAW_FRACTION),
        ]
        run_command(export_cmd)

        summary_path = summary_file_for(folder)
        rows.append(collect_row(period_label, summary_path))

    csv_path = OUTPUT_ROOT / "comparison_summary.csv"
    json_path = OUTPUT_ROOT / "comparison_summary.json"
    if rows:
        with csv_path.open("w", newline="", encoding="utf-8") as handle:
            writer = csv.DictWriter(handle, fieldnames=list(rows[0].keys()))
            writer.writeheader()
            writer.writerows(rows)
        json_path.write_text(json.dumps(rows, indent=2), encoding="utf-8")
        print(f"Saved comparison CSV to {csv_path}")
        print(f"Saved comparison JSON to {json_path}")


if __name__ == "__main__":
    main()
