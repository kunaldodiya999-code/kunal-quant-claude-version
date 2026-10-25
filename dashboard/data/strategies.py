"""Strategies page data: the registry, which strategies are deployed, and whether each one is running."""

from __future__ import annotations

import time

from .gap_reversal import gap_dir, status as gap_status, store as gap_store
from .open_high_low import ohol_dir, status as ohol_status, store as ohol_store
from .live import INDEX_KEYS, load_status, paper_root, status_age_seconds, trade_store
from strategies.registry import STRATEGIES, DeploymentStore

RUNNING_WITHIN_SECONDS = 120
COMMAND = r"python scripts\run_strategies.py"


def deployment() -> DeploymentStore:
    return DeploymentStore(paper_root().parent, gap_folder=gap_dir(), ohol_folder=ohol_dir())


def exit_plan_text(key: str) -> str:
    if key == "GAP_REVERSAL":
        s = gap_store().settings
        return f"SHORT: {s.short.exit_plan().describe()} | LONG: {s.long.exit_plan().describe()}"
    if key == "OPEN_HIGH_LOW":
        s = ohol_store().settings
        return (f"{s.instrument}, top {s.top_n} at {s.scan_at}. LONG: {s.long.exit_plan().describe()} | "
                f"SHORT: {s.short.exit_plan().describe()}")
    if key == "KTMI_UNI_LITE":
        parts = []
        for index in INDEX_KEYS:
            tm = trade_store(index).settings
            target = f"target 1:{tm.exit_target_rr:g}" if tm.exit_target_rr else (
                f"partial {tm.partial_pct:g}% at {tm.partial_r:g}R, then TSL" if tm.partial_enabled else "no fixed target")
            tsl = tm.tsl_method if tm.tsl_enabled else "no TSL"
            parts.append(f"{index}: {target}, {tsl}")
        return " | ".join(parts)
    return "-"


def running(key: str, now: float | None = None) -> str:
    now = time.time() if now is None else now
    if key == "KTMI_UNI_LITE":
        ages = [status_age_seconds(load_status(i), now) for i in INDEX_KEYS]
        live = [a for a in ages if a is not None and a <= RUNNING_WITHIN_SECONDS]
        return "running" if live else "not running"
    if key == "OPEN_HIGH_LOW":
        st = ohol_status()
        if st and now - float(st.get("updated_epoch", 0)) <= RUNNING_WITHIN_SECONDS:
            return "running"
        return "not running"
    if key == "GAP_REVERSAL":
        st = gap_status()
        if st and now - float(st.get("updated_epoch", 0)) <= RUNNING_WITHIN_SECONDS:
            return "running"
        return "not running"
    return "-"


def rows(now: float | None = None) -> list[dict]:
    dep = deployment()
    out = []
    for key, info in STRATEGIES.items():
        out.append({"key": key, "name": info.name, "market": info.market, "stage": info.stage,
                    "deployed": dep.is_deployed(key), "now": running(key, now), "exit plan": exit_plan_text(key),
                    "exit settings": info.exit_settings, "guide": info.guide})
    return out


__all__ = ["COMMAND", "deployment", "exit_plan_text", "rows", "running"]
