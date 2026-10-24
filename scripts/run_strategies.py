"""Start every DEPLOYED Kunal Quant strategy with one command (paper trading, real prices).

Run from C:\\Users\\USER\\Desktop\\Kunal\\kunal-quant-claude-version , (.venv) active, after the FYERS login:

    python scripts\\run_strategies.py
        starts the strategies deployed on the dashboard page "Strategies"
    python scripts\\run_strategies.py --deploy KTMI_UNI_LITE,GAP_REVERSAL
        saves that choice first (also: --deploy all, --deploy none), then starts them
    python scripts\\run_strategies.py --list
        shows every strategy and whether it is deployed, starts nothing

Each strategy runs as its own program in this window; its lines start with its name, e.g. [GAP_REVERSAL].
Ctrl+C stops all of them. Paper only: real orders still need the live switch AND --live-orders
(KTMI only, see docs/LIVE_ORDERS.md).
"""

from __future__ import annotations

import argparse
import subprocess
import sys
import threading
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from strategies.registry import STRATEGIES, DeploymentStore, parse_keys  # noqa: E402


def commands(keys, args) -> dict[str, list[str]]:
    out = {}
    for key in keys:
        cmd = [sys.executable, str(PROJECT_ROOT / STRATEGIES[key].script), "--data-folder", str(args.data_folder)]
        if args.credentials_folder:
            cmd += ["--credentials-folder", str(args.credentials_folder)]
        if args.stop_at:
            cmd += ["--stop-at", args.stop_at]
        if key == "KTMI_UNI_LITE":
            if args.index:
                cmd += ["--index", args.index]
            if args.live_orders:
                cmd += ["--live-orders"]
        out[key] = cmd
    return out


def _pump(name: str, stream) -> None:
    for line in iter(stream.readline, ""):
        print(f"[{name}] {line}", end="", flush=True)


def main(argv=None, *, popen=subprocess.Popen) -> int:
    p = argparse.ArgumentParser(description="Start every deployed strategy.")
    p.add_argument("--deploy", default=None, help="save the deployed strategies first: comma list, all or none")
    p.add_argument("--list", action="store_true", help="show the strategies and stop")
    p.add_argument("--data-folder", type=Path, default=PROJECT_ROOT / "data")
    p.add_argument("--credentials-folder", type=Path, default=None)
    p.add_argument("--index", default=None, help="KTMI: indexes to watch (default: all three)")
    p.add_argument("--live-orders", action="store_true", help="KTMI: real orders (also needs the live switch)")
    p.add_argument("--stop-at", default=None, help="stop every strategy at this IST time (HH:MM)")
    args = p.parse_args(argv)

    store = DeploymentStore(args.data_folder)
    if args.deploy is not None:
        try:
            store.set_deployed(parse_keys(args.deploy))
        except ValueError as exc:
            raise SystemExit(str(exc))
    deployed = store.deployed()
    print("=" * 72)
    print("KUNAL QUANT - STRATEGIES")
    for key, info in STRATEGIES.items():
        state = "DEPLOYED" if key in deployed else ("not deployed" if info.stage == "PAPER" else "research only")
        print(f"  {key:<15} {state:<14} {info.name}")
    print("=" * 72)
    if args.list:
        return 0
    if not deployed:
        print("Nothing is deployed. Deploy on the dashboard page 'Strategies' or with --deploy KTMI_UNI_LITE,GAP_REVERSAL")
        return 0

    procs = {}
    for key, cmd in commands(deployed, args).items():
        print(f"Starting {STRATEGIES[key].name} ...")
        procs[key] = popen(cmd, cwd=str(PROJECT_ROOT), stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
                           bufsize=1)
    threads = [threading.Thread(target=_pump, args=(k, proc.stdout), daemon=True) for k, proc in procs.items()]
    for t in threads:
        t.start()
    codes = {}
    try:
        for key, proc in procs.items():
            codes[key] = proc.wait()
    except KeyboardInterrupt:
        print("\nCtrl+C: stopping every strategy ...")
        for proc in procs.values():
            proc.terminate()
        for key, proc in procs.items():
            codes[key] = proc.wait()
    for t in threads:
        t.join(timeout=2)
    for key, code in codes.items():
        print(f"{STRATEGIES[key].name}: finished" + ("" if code == 0 else f" with an error (code {code})"))
    return 0 if all(c == 0 for c in codes.values()) else 1


if __name__ == "__main__":
    raise SystemExit(main())
