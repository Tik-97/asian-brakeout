from __future__ import annotations

import csv
import json
import subprocess
import sys
from pathlib import Path


BASE_DIR = Path(__file__).resolve().parent
OUTPUT_ROOT = BASE_DIR / r"backtests\long_volume_filter_study_2020_2026"
SYMBOLS = ["EURJPY", "GBPJPY"]
START_DATE = "2020-04-03"
END_DATE = "2026-04-03"


def run_command(command: list[str]) -> None:
    print("RUN:", " ".join(command))
    subprocess.run(command, cwd=str(BASE_DIR), check=True)


def summary_file_for(folder: Path) -> Path:
    matches = sorted(folder.glob("yearly_backtest_*_summary.json"))
    if len(matches) != 1:
        raise FileNotFoundError(f"Expected exactly one summary json in {folder}, found {len(matches)}")
    return matches[0]


def collect_row(variant: str, summary_path: Path) -> dict[str, object]:
    summary = json.loads(summary_path.read_text(encoding="utf-8"))
    return {
        "variant": variant,
        "signal_relative_volume_threshold": summary.get("SignalRelativeVolumeThreshold"),
        "accepted_trades": summary.get("AcceptedTrades"),
        "win_rate_pct": summary.get("WinRatePct"),
        "profit_factor": summary.get("ProfitFactor"),
        "net_pnl_usd": summary.get("NetPnLUSD"),
        "total_withdrawn_usd": summary.get("TotalWithdrawnUSD"),
        "ending_trading_equity_usd": summary.get("EndingTradingEquityUSD"),
        "ending_total_value_usd": summary.get("EndingTotalValueUSD"),
        "return_pct_on_initial": summary.get("ReturnPctOnInitial"),
        "max_drawdown_trading_pct": summary.get("MaxDrawdownTradingPct"),
        "max_drawdown_total_value_pct": summary.get("MaxDrawdownTotalValuePct"),
        "summary_json": str(summary_path),
    }


def main() -> None:
    OUTPUT_ROOT.mkdir(parents=True, exist_ok=True)
    rows: list[dict[str, object]] = []
    variants = [
        ("base", 0.0),
        ("volume_rel_1_50", 1.5),
    ]

    for variant_name, threshold in variants:
        folder = OUTPUT_ROOT / variant_name
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
            START_DATE,
            "--to-date",
            END_DATE,
            "--initial-equity",
            "400",
            "--portfolio-margin-fraction",
            "0.25",
            "--output-dir",
            str(folder.relative_to(BASE_DIR)),
        ]
        if threshold > 0:
            backtest_cmd.extend(
                [
                    "--signal-relative-volume-threshold",
                    str(threshold),
                ]
            )
        run_command(backtest_cmd)

        export_cmd = [
            sys.executable,
            "export_yearly_backtest_package.py",
            "--env-file",
            ".env",
            "--input-csv",
            str(folder / "portfolio_trades.csv"),
            "--output-dir",
            str(folder),
            "--symbols",
            *SYMBOLS,
            "--from-date",
            START_DATE,
            "--to-date",
            END_DATE,
            "--initial-deposit",
            "400",
            "--dynamic-margin-fraction",
            "0.25",
            "--withdrawal-trigger",
            "800",
            "--first-withdrawal",
            "400",
            "--followup-withdraw-fraction",
            "0.25",
        ]
        run_command(export_cmd)

        summary_path = summary_file_for(folder)
        rows.append(collect_row(variant_name, summary_path))

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
