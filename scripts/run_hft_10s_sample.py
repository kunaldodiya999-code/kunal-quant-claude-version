"""Run the HFT 10S one-day validation workflow.

This is intentionally a small gate before bulk acquisition:
1. build targeted FYERS contract manifest
2. validate exactly 12 options + 1 futures + 1 index per day
3. download only the first N jobs (14 jobs for one day)

Use --run to perform real FYERS acquisition. Without --run the downloader is dry-run.
"""
from __future__ import annotations

import argparse
import subprocess
import sys

def run(command: list[str]) -> None:
    print("\n>>> " + " ".join(command))
    completed = subprocess.run(command, check=False)
    if completed.returncode != 0:
        raise SystemExit(completed.returncode)

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--from", dest="start", default="2026-08-21")
    parser.add_argument("--to", dest="end", default="2026-08-21")
    parser.add_argument("--run", action="store_true", help="Actually download FYERS data.")
    parser.add_argument("--limit", type=int, default=14)
    args = parser.parse_args()

    manifest = "data/reports/hft_10s_manifest.csv"
    summary = "data/reports/hft_10s_manifest_summary.json"

    run([sys.executable, "scripts/build_hft_10s_manifest.py",
         "--from", args.start, "--to", args.end,
         "--output", manifest, "--json", summary])

    run([sys.executable, "scripts/validate_hft_manifest.py",
         "--manifest", manifest])

    command = [sys.executable, "scripts/download_hft_10s_data.py",
               "--manifest", manifest, "--limit", str(args.limit)]
    if args.run:
        command.append("--run")
    run(command)

if __name__ == "__main__":
    main()
