"""The live-orders switch. OFF unless the owner arms it, and only for one day."""

from __future__ import annotations

import json
from datetime import date, datetime
from pathlib import Path
from zoneinfo import ZoneInfo

IST = ZoneInfo("Asia/Kolkata")
SWITCH_FILE = "live_switch.json"
CONFIRM_PHRASE = "I ACCEPT REAL MONEY RISK"


class LiveSwitch:
    def __init__(self, folder: str | Path) -> None:
        self.path = Path(folder) / SWITCH_FILE

    def armed_for(self, today: date) -> bool:
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return False          # missing or unreadable file = OFF
        return data.get("armed_for") == today.isoformat() and data.get("phrase") == CONFIRM_PHRASE

    def arm(self, today: date, phrase: str) -> None:
        if phrase.strip() != CONFIRM_PHRASE:
            raise ValueError(f'Not armed. You must type exactly: {CONFIRM_PHRASE}')
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps({
            "armed_for": today.isoformat(), "phrase": CONFIRM_PHRASE,
            "armed_at": datetime.now(IST).isoformat(timespec="seconds"),
        }, indent=2), encoding="utf-8")

    def disarm(self) -> None:
        if self.path.exists():
            self.path.unlink()


__all__ = ["CONFIRM_PHRASE", "LiveSwitch", "SWITCH_FILE"]
