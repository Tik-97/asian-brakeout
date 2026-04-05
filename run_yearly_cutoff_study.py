from __future__ import annotations

import argparse
import csv
import datetime as dt
import json
import subprocess
import sys
from pathlib import Path


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run yearly Asian Breakout backtests for base vs entry cutoff variants."
    )
    parser.add_argument("--env-file", default=".env")
    parser.add_argument("--symbols", nargs="+", default=["EURJPY", "GBPJPY"])
    parser.add_argument("--start-year", type=int, default=2020, help="First yearly window start year")
    parser.add_argument("--end-year", type=int, default=2026, help="Final calendar year covered by the study")
    parser.add_argument("--start-month", type=int, default=4)
    parser.add_argument("--start-day", type=int, default=3)
    parser.add_argument("--initial-equity", type=float, default=400.0)
    parser.add_argument("--initial-deposit", type=float, default=400.0)
    parser.add_argument("--portfolio-margin-fraction", type=float, default=0.25)
    parser.add_argument("--withdrawal-trigger", type=float, default=800.0)
    parser.add_argument("--first-withdrawal", type=float, default=400.0)
    parser.add_argument("--followup-withdraw-fraction", type=float, default=0.25)
    parser.add_argument("--cutoff-hour", type=int, default=14, help="Exclusive UTC hour cutoff for cutoff variant")
    parser.add_argument(
        "--cutoff-weekdays",
        default="",
        help="Optional comma-separated weekdays to limit the cutoff rule, for example Mon,Tue",
    )
    parser.add_argument(
        "--variant-name",
        default="",
        help="Optional custom variant folder name. If omitted, it is built from cutoff settings.",
    )
    parser.add_argument(
        "--output-root",
        default=r"backtests\yearly_cutoff_study_2020_2026",
        help="Directory for all yearly result folders",
    )
    parser.add_argument(
        "--no-resume",
        action="store_true",
        help="Re-run even if a variant folder already contains a packaged yearly summary",
    )
    return parser.parse_args()


def run_command(command: list[str], *, cwd: Path) -> None:
    print("RUN:", " ".join(command))
    subprocess.run(command, cwd=str(cwd), check=True)


def yearly_windows(
    *,
    start_year: int,
    end_year: int,
    start_month: int,
    start_day: int,
) -> list[tuple[dt.date, dt.date]]:
    windows: list[tuple[dt.date, dt.date]] = []
    for year in range(start_year, end_year):
        windows.append(
            (
                dt.date(year, start_month, start_day),
                dt.date(year + 1, start_month, start_day),
            )
        )
    return windows


def summary_file_for(folder: Path) -> Path:
    matches = sorted(folder.glob("yearly_backtest_*_summary.json"))
    if len(matches) != 1:
        raise FileNotFoundError(f"Expected exactly one summary json in {folder}, found {len(matches)}")
    return matches[0]


def summary_row_from_file(
    *,
    summary_path: Path,
    period_label: str,
    variant_name: str,
    start_date: dt.date,
    end_date: dt.date,
    cutoff_hour: int | None,
) -> dict[str, object]:
    summary = json.loads(summary_path.read_text(encoding="utf-8"))
    return {
        "period": period_label,
        "variant": variant_name,
        "from_date": start_date.isoformat(),
        "to_date": end_date.isoformat(),
        "entry_signal_cutoff_hour_utc": cutoff_hour,
        "accepted_trades": summary.get("AcceptedTrades"),
        "win_rate_pct": summary.get("WinRatePct"),
        "profit_factor": summary.get("ProfitFactor"),
        "net_pnl_usd": summary.get("NetPnLUSD"),
        "total_withdrawn_usd": summary.get("TotalWithdrawnUSD"),
        "ending_total_value_usd": summary.get("EndingTotalValueUSD"),
        "return_pct_on_initial": summary.get("ReturnPctOnInitial"),
        "max_drawdown_trading_pct": summary.get("MaxDrawdownTradingPct"),
        "max_drawdown_total_value_pct": summary.get("MaxDrawdownTotalValuePct"),
        "summary_json": str(summary_path),
    }


def main() -> None:
    args = parse_args()
    base_dir = Path(__file__).resolve().parent
    output_root = (base_dir / args.output_root).resolve()
    output_root.mkdir(parents=True, exist_ok=True)
    resume = not args.no_resume

    variants = [
        ("base", None),
        (
            (
                args.variant_name
                if args.variant_name
                else (
                    f"cutoff_{args.cutoff_hour:02d}utc_{args.cutoff_weekdays.lower().replace(',', '_')}"
                    if args.cutoff_weekdays
                    else f"cutoff_{args.cutoff_hour:02d}utc"
                )
            ),
            args.cutoff_hour,
        ),
    ]
    rows: list[dict[str, object]] = []

    for start_date, end_date in yearly_windows(
        start_year=args.start_year,
        end_year=args.end_year,
        start_month=args.start_month,
        start_day=args.start_day,
    ):
        label = f"{start_date.year}-{end_date.year}"
        for variant_name, cutoff_hour in variants:
            folder = output_root / label / variant_name
            folder.mkdir(parents=True, exist_ok=True)
            existing_summary_path = None
            try:
                existing_summary_path = summary_file_for(folder)
            except FileNotFoundError:
                existing_summary_path = None
            if resume and existing_summary_path is not None:
                print(f"SKIP complete: {folder}")
                rows.append(
                    summary_row_from_file(
                        summary_path=existing_summary_path,
                        period_label=label,
                        variant_name=variant_name,
                        start_date=start_date,
                        end_date=end_date,
                        cutoff_hour=cutoff_hour,
                    )
                )
                continue

            backtest_command = [
                sys.executable,
                "main.py",
                "--env-file",
                args.env_file,
                "backtest",
                "--symbols",
                *args.symbols,
                "--from-date",
                start_date.isoformat(),
                "--to-date",
                end_date.isoformat(),
                "--initial-equity",
                str(args.initial_equity),
                "--portfolio-margin-fraction",
                str(args.portfolio_margin_fraction),
                "--output-dir",
                str(folder.relative_to(base_dir)),
            ]
            if cutoff_hour is not None:
                backtest_command.extend(
                    [
                        "--entry-signal-cutoff-hour-utc",
                        str(cutoff_hour),
                    ]
                )
                if args.cutoff_weekdays:
                    backtest_command.extend(
                        [
                            "--entry-signal-cutoff-weekdays-utc",
                            args.cutoff_weekdays,
                        ]
                    )
            run_command(backtest_command, cwd=base_dir)

            export_command = [
                sys.executable,
                "export_yearly_backtest_package.py",
                "--env-file",
                args.env_file,
                "--input-csv",
                str(folder / "portfolio_trades.csv"),
                "--output-dir",
                str(folder),
                "--symbols",
                *args.symbols,
                "--from-date",
                start_date.isoformat(),
                "--to-date",
                end_date.isoformat(),
                "--initial-deposit",
                str(args.initial_deposit),
                "--dynamic-margin-fraction",
                str(args.portfolio_margin_fraction),
                "--withdrawal-trigger",
                str(args.withdrawal_trigger),
                "--first-withdrawal",
                str(args.first_withdrawal),
                "--followup-withdraw-fraction",
                str(args.followup_withdraw_fraction),
            ]
            run_command(export_command, cwd=base_dir)

            summary_path = summary_file_for(folder)
            rows.append(
                summary_row_from_file(
                    summary_path=summary_path,
                    period_label=label,
                    variant_name=variant_name,
                    start_date=start_date,
                    end_date=end_date,
                    cutoff_hour=cutoff_hour,
                )
            )

    csv_path = output_root / "comparison_summary.csv"
    json_path = output_root / "comparison_summary.json"
    fieldnames = list(rows[0].keys()) if rows else []
    if fieldnames:
        with csv_path.open("w", newline="", encoding="utf-8") as handle:
            writer = csv.DictWriter(handle, fieldnames=fieldnames)
            writer.writeheader()
            writer.writerows(rows)
        json_path.write_text(json.dumps(rows, indent=2), encoding="utf-8")
        print(f"Saved comparison CSV to {csv_path}")
        print(f"Saved comparison JSON to {json_path}")


if __name__ == "__main__":
    main()
