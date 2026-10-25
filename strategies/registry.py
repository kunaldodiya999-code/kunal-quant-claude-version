"""Every Kunal Quant strategy in one list, and which ones are DEPLOYED (owner rule, 25 Oct 2026).

The owner deploys a single strategy, several, or all of them, as the market needs. One command starts
every deployed strategy (``scripts/run_strategies.py``); the dashboard page "Strategies" switches them.

Stages:
  PAPER     runs live on real prices with simulated (paper) trades; can be deployed
  RESEARCH  backtest only, not wired to live prices yet; cannot be deployed

Every strategy uses the same exit plan (strategies/exit_plan.py): Reward 1:[box], empty box = TSL exit.

Where the deploy choice is saved:
  KTMI_UNI_LITE   data/strategies.json
  GAP_REVERSAL    its own "Strategy ON" switch (data/gap_reversal/settings.json), so the Gap Reversal
                  page and the Strategies page always agree
  OPEN_HIGH_LOW   the same, data/open_high_low/settings.json
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

DEPLOY_FILE = "strategies.json"


@dataclass(frozen=True)
class StrategyInfo:
    key: str
    name: str
    market: str
    stage: str                      # PAPER or RESEARCH
    script: str                     # live runner (PAPER) or backtest (RESEARCH), relative to the project
    exit_settings: str              # where the owner sets the exit plan
    guide: str
    default_deployed: bool = False


STRATEGIES: dict[str, StrategyInfo] = {s.key: s for s in (
    StrategyInfo("KTMI_UNI_LITE", "KTMI Uni Lite (index options)", "NIFTY, BANK NIFTY, SENSEX options (buy CE / PE)",
                 "PAPER", "scripts/run_paper_session.py",
                 "Live Paper Trading page > Trade management (per index)", "docs/MONDAY_GUIDE.md", True),
    StrategyInfo("GAP_REVERSAL", "Gap Reversal (stocks)", "All F&O stocks (+ indexes): gap >= 3% reversal",
                 "PAPER", "scripts/run_gap_reversal.py", "Gap Reversal page > Settings (SHORT and LONG)",
                 "docs/GAP_REVERSAL_STRATEGY.md", False),
    StrategyInfo("OPEN_HIGH_LOW", "Open High Low (stocks)",
                 "F&O stocks: open = low / high on spot + futures + 22 options, top 5 by score and liquidity",
                 "PAPER", "scripts/run_open_high_low.py", "Open High Low page > Settings (LONG and SHORT)",
                 "docs/OPEN_HIGH_LOW_STRATEGY.md", False),
    StrategyInfo("OPENING_SCALP", "Opening Scalp (index)", "NIFTY opening range scalp", "RESEARCH",
                 "scripts/opening_scalp_backtest.py", "Exit plan is added when it goes live",
                 "docs/OPENING_SCALP_AND_DATA.md"),
    StrategyInfo("HFT_GAP_OPEN", "HFT Gap-Open (index options)", "NIFTY gap open, 10-second data", "RESEARCH",
                 "scripts/run_hft_10s_sample.py", "Exit plan is added when it goes live", "docs/HFT_GAP_OPEN_AUDIT.md"),
)}
PAPER_KEYS = tuple(k for k, s in STRATEGIES.items() if s.stage == "PAPER")


def parse_keys(text: str | Iterable[str]) -> list[str]:
    """'KTMI_UNI_LITE,GAP_REVERSAL', 'all' or 'none' -> keys (checked)."""
    items = [x.strip().upper() for x in (text.split(",") if isinstance(text, str) else text) if x and x.strip()]
    if items in (["ALL"],):
        return list(PAPER_KEYS)
    if items in (["NONE"], []):
        return []
    for key in items:
        if key not in STRATEGIES:
            raise ValueError(f"unknown strategy {key!r}; choose from {', '.join(STRATEGIES)} (or all / none)")
        if STRATEGIES[key].stage != "PAPER":
            raise ValueError(f"{STRATEGIES[key].name} is research only (backtest), it cannot be deployed yet")
    return list(dict.fromkeys(items))


class DeploymentStore:
    """Which strategies are deployed. ``data_folder`` = the project's data folder."""

    def __init__(self, data_folder: str | Path, gap_folder: str | Path | None = None,
                 ohol_folder: str | Path | None = None) -> None:
        self.data_folder = Path(data_folder)
        self.path = self.data_folder / DEPLOY_FILE
        self.gap_folder = Path(gap_folder) if gap_folder else self.data_folder / "gap_reversal"
        self.ohol_folder = Path(ohol_folder) if ohol_folder else self.data_folder / "open_high_low"

    def _file(self) -> dict:
        if not self.path.exists():
            return {}
        try:
            return json.loads(self.path.read_text(encoding="utf-8")).get("deployed", {})
        except (ValueError, OSError, AttributeError):
            return {}

    def _own_store(self, key: str):
        """Strategies whose deploy flag is their own "Strategy ON" setting (None for the others)."""
        if key == "GAP_REVERSAL":
            from strategies.gap_reversal import GapReversalStore
            return GapReversalStore(self.gap_folder)
        if key == "OPEN_HIGH_LOW":
            from strategies.open_high_low import OpenHighLowStore
            return OpenHighLowStore(self.ohol_folder)
        return None

    def is_deployed(self, key: str) -> bool:
        own = self._own_store(key)
        if own is not None:
            return bool(own.settings.enabled)
        info = STRATEGIES[key]
        return info.stage == "PAPER" and bool(self._file().get(key, info.default_deployed))

    def deployed(self) -> list[str]:
        return [k for k in PAPER_KEYS if self.is_deployed(k)]

    def set_deployed(self, keys: Iterable[str]) -> list[str]:
        chosen = parse_keys(list(keys))
        saved = {k: (k in chosen) for k in PAPER_KEYS if self._own_store(k) is None}
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps({"deployed": saved}, indent=2), encoding="utf-8")
        for key in PAPER_KEYS:
            own = self._own_store(key)
            if own is not None and own.settings.enabled != (key in chosen):
                own.update(enabled=key in chosen)
        return self.deployed()


__all__ = ["DEPLOY_FILE", "DeploymentStore", "PAPER_KEYS", "STRATEGIES", "StrategyInfo", "parse_keys"]
