"""Run every strategy test on the FYERS data in one go and save one report. No login, no orders.

Run from C:\\Users\\USER\\Desktop\\Kunal\\kunal-quant-claude-version, AFTER  python scripts\\fetch_data.py :

    python scripts\\prove_strategies.py
    python scripts\\prove_strategies.py --skip tsl        (leave out a part: ktmi, tsl, gap, ohol)

Parts (each one also saves its own CSV files, as when run alone):
  data  the data check (what is clean, what is missing)           scripts\\data_audit.py
  ktmi  KTMI Uni Lite signal accuracy (indexes, 3 and 5 min)        scripts\\ktmi_accuracy.py --source fyers
  tsl   every trailing stop on every KTMI signal (incl. BETA rows)  scripts\\tsl_lab.py --source fyers
  gap   Gap Reversal, every F&O stock, 1-min and 5-min candles      scripts\\gap_reversal_backtest.py --source cache
  ohol  Open High Low, same stocks and candles                      scripts\\open_high_low_backtest.py
CLEAN DAYS ONLY (owner 26 Oct 2026): indexes use the days scripts\\fetch_data.py marked clean, stocks the clean
days of market_data/clean_days.py. Results use the settings saved from the dashboard. A part that fails is reported; the others still run.
Everything printed is also saved in data\\research\\proof_report.txt (send that file to Claude).
"""

from __future__ import annotations

import argparse
import sys
import traceback
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

IST = ZoneInfo("Asia/Kolkata")


class Tee:
    """Print to the window AND keep a copy for the report file."""

    def __init__(self, stream, handle):
        self.stream, self.handle = stream, handle

    def write(self, text):
        self.stream.write(text)
        self.handle.write(text)
        return len(text)

    def flush(self):
        self.stream.flush()
        self.handle.flush()


def parts(data: Path) -> list[tuple[str, str, object]]:
    from scripts import data_audit, gap_reversal_backtest, ktmi_accuracy, open_high_low_backtest, tsl_lab
    folder = ["--data-folder", str(data)]
    return [
        ("data", "Data check: clean days and what is missing", lambda: data_audit.main(folder)),
        ("ktmi", "KTMI Uni Lite signal accuracy (indexes)",
         lambda: ktmi_accuracy.main(["--source", "fyers", *folder])),
        ("tsl", "Trailing stops on every KTMI signal (TSL Lab)",
         lambda: tsl_lab.main(["--source", "fyers", *folder])),
        ("gap", "Gap Reversal, 1-minute candles (clean days)",
         lambda: gap_reversal_backtest.main(["--source", "cache", "--cache-source", "fyers", "--interval", "1m",
                                             *folder])),
        ("gap", "Gap Reversal, 5-minute candles (clean days)",
         lambda: gap_reversal_backtest.main(["--source", "cache", "--cache-source", "fyers", "--interval", "5m",
                                             *folder])),
        ("ohol", "Open High Low, 1-minute candles (clean days)",
         lambda: open_high_low_backtest.main(["--cache-source", "fyers", "--interval", "1m", *folder])),
        ("ohol", "Open High Low, 5-minute candles (clean days)",
         lambda: open_high_low_backtest.main(["--cache-source", "fyers", "--interval", "5m", *folder])),
    ]


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description="Run every strategy test on the FYERS data, one report.")
    p.add_argument("--skip", default="", help="comma list of parts to leave out: data, ktmi, tsl, gap, ohol")
    p.add_argument("--data-folder", type=Path, default=PROJECT_ROOT / "data")
    args = p.parse_args(argv)
    skip = {x.strip().lower() for x in args.skip.split(",") if x.strip()}
    report = args.data_folder / "research" / "proof_report.txt"
    report.parent.mkdir(parents=True, exist_ok=True)
    failed = []
    with report.open("w", encoding="utf-8") as handle:
        old = sys.stdout
        sys.stdout = Tee(old, handle)
        try:
            print(f"KUNAL QUANT - STRATEGY PROOF REPORT  {datetime.now(IST):%Y-%m-%d %H:%M}  (FYERS data, paper maths)")
            todo = [x for x in parts(args.data_folder) if x[0] not in skip]
            for n, (key, title, run) in enumerate(todo, 1):
                print("\n" + "=" * 100)
                print(f"PART {n} of {len(todo)}: {title}")
                print("=" * 100, flush=True)
                try:
                    code = run()
                    if code:
                        failed.append(f"{title}: finished with code {code} (see the lines above)")
                except SystemExit as exc:               # the scripts stop with a plain message when data is missing
                    failed.append(f"{title}: {exc}")
                    print(f"STOPPED: {exc}")
                except Exception as exc:
                    failed.append(f"{title}: {exc}")
                    traceback.print_exc(file=sys.stdout)
            print("\n" + "=" * 100)
            print("NOT DONE: " + "; ".join(failed) if failed else "All parts done.")
            print(f"Report saved: {report}")
        finally:
            sys.stdout = old
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
