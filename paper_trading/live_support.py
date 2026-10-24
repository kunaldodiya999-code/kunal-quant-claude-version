"""Helpers for a live paper session: option contracts and the status file.

- ``sync_nifty_option_contracts``: register today's NIFTY option contracts
  from the public FYERS symbol master into this working copy's own database
  (the original KunalQuant database is never touched). Returns lot size and
  nearest expiry, read from FYERS, never assumed.
- ``build_status`` / ``write_status``: a small JSON file the dashboard reads
  every few seconds (``live_status.json``).

Nothing here places orders.
"""

from __future__ import annotations

import json
import os
import time
import urllib.request
from dataclasses import asdict, dataclass
from datetime import date, datetime
from pathlib import Path
from typing import Any, Mapping
from zoneinfo import ZoneInfo

from database.repository import DatabaseRepository
from database.schema import initialize_database
from instruments.symbol_master import normalize_master
from paper_trading.engine import PaperStrategyId
from strategies.strike_ladder import atm_strike, strike_ladder

IST = ZoneInfo("Asia/Kolkata")
STATUS_FILE = "live_status.json"
SLOT_NAMES = {
    PaperStrategyId.STRATEGY_A: "Slot 1",
    PaperStrategyId.STRATEGY_A_2: "Slot 2 (ATM+1)",
}


@dataclass(frozen=True)
class ContractSync:
    contracts: int
    nearest_expiry: date
    lot_size: int
    expiries: tuple[str, ...]


MASTER_URL = "https://public.fyers.in/sym_details/{name}_sym_master.json"


def load_fyers_master(name: str, folder: str | Path, *, today: date, fetch=None) -> dict:
    """FYERS public symbol master (e.g. NSE_FO, BSE_FO), downloaded at most once a day."""
    path = Path(folder) / f"{name}_{today.isoformat()}.json"
    if path.exists():
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except ValueError:
            path.unlink()                       # half-written file: download again
    if fetch is None:
        def fetch(url):
            request = urllib.request.Request(url, headers={"User-Agent": "KunalQuant/1.0"})
            with urllib.request.urlopen(request, timeout=180) as response:
                return json.loads(response.read().decode("utf-8"))
    data = fetch(MASTER_URL.format(name=name))
    if not isinstance(data, dict) or not data:
        raise RuntimeError(f"Unexpected FYERS {name} symbol master format.")
    path.parent.mkdir(parents=True, exist_ok=True)
    for old in path.parent.glob(f"{name}_*.json"):   # keep only today's copy
        old.unlink()
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(data), encoding="utf-8")
    os.replace(tmp, path)
    return data


def sync_option_contracts(database_path: str | Path, raw_master: Mapping[str, Any], *, underlying: str,
                          today: date) -> ContractSync:
    """Upsert current CE/PE contracts of one index (expiry today or later)."""
    rows = [
        r for r in normalize_master(dict(raw_master))
        if str(r.get("underlying") or "").upper() == underlying.upper()
        and r.get("option_type") in ("CE", "PE")
        and r.get("expiry_date") and r["expiry_date"] >= today.isoformat()
        and r.get("strike")
    ]
    if not rows:
        raise RuntimeError(f"FYERS symbol master has no current {underlying} options.")
    nearest = min(r["expiry_date"] for r in rows)
    lots = {r["lot_size"] for r in rows if r["expiry_date"] == nearest and r.get("lot_size")}
    if len(lots) != 1:
        raise RuntimeError(f"Nearest-expiry {underlying} lot size is not unique in FYERS data: {sorted(lots)}")
    initialize_database(database_path)
    DatabaseRepository(database_path).upsert_instruments(rows)
    return ContractSync(
        contracts=len(rows),
        nearest_expiry=date.fromisoformat(nearest),
        lot_size=int(next(iter(lots))),
        expiries=tuple(sorted({r["expiry_date"] for r in rows}))[:4],
    )


def sync_nifty_option_contracts(database_path, raw_master, *, today: date) -> ContractSync:
    return sync_option_contracts(database_path, raw_master, underlying="NIFTY", today=today)


def _ist(ts: int | None) -> str | None:
    return None if ts is None else datetime.fromtimestamp(int(ts), IST).strftime("%Y-%m-%d %H:%M:%S")


def build_status(session: Any, *, underlying_symbol: str, contracts: ContractSync | None,
                 strike_step: int = 50, now: float | None = None) -> dict:
    now = time.time() if now is None else now
    feed = session.feed.status()
    spot_snap = session.quote_cache.snapshot(underlying_symbol)
    spot = None if spot_snap is None else float(spot_snap.last_price)
    marks = session.coordinator.marks_provider() if session.coordinator.marks_provider else {}
    positions = []
    for slot, name in SLOT_NAMES.items():
        record = session.engine.open_trade(slot)
        if record is None:
            continue
        p = record.position
        mark = marks.get(slot)
        positions.append({
            "slot": name,
            "symbol": p.symbol,
            "side": "BUY CALL" if str(getattr(p.direction, "value", p.direction)) == "LONG" else "BUY PUT",
            "entry": p.entry_price,
            "quantity": p.remaining_quantity,
            "stop": p.stop_loss,
            "target": p.target,
            "mark": mark,
            "unrealised": None if mark is None else round((mark - p.entry_price) * p.remaining_quantity, 2),
            "opened_at": _ist(record.entry_timestamp),
        })
    account = session.account.snapshot(int(now), marks) if session.account is not None else None
    ladders = {}
    if spot is not None:
        ladders = {
            "atm": atm_strike(spot, strike_step),
            "call": [{"choice": c, "strike": k} for c, k in strike_ladder(spot, "CE", strike_step)],
            "put": [{"choice": c, "strike": k} for c, k in strike_ladder(spot, "PE", strike_step)],
        }
    return {
        "mode": "PAPER",
        "updated_at": _ist(int(now)),
        "updated_epoch": int(now),
        "feed": {
            "connected": feed.connected,
            "messages": feed.messages_received,
            "subscribed": list(feed.subscribed_symbols),
            "last_error": feed.last_error,
        },
        "spot": spot,
        "spot_time": None if spot_snap is None else _ist(spot_snap.exchange_timestamp),
        "ladders": ladders,
        "contracts": None if contracts is None else {
            "nearest_expiry": contracts.nearest_expiry.isoformat(), "lot_size": contracts.lot_size,
        },
        "settings": asdict(session.settings_store.settings) if session.settings_store else None,
        "positions": positions,
        "account": None if account is None else {
            "equity": round(account.equity, 2), "day_pnl": round(account.day_pnl, 2),
            "realised": round(account.realized_pnl, 2), "unrealised": round(account.unrealized_pnl, 2),
            "costs": round(account.costs, 2), "available_cash": round(account.available_cash, 2),
        },
    }


def write_status(folder: str | Path, status: dict) -> Path:
    """Write atomically so the dashboard never reads a half-written file."""
    path = Path(folder) / STATUS_FILE
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(status, indent=2, default=str), encoding="utf-8")
    os.replace(tmp, path)
    return path


__all__ = ["STATUS_FILE", "ContractSync", "build_status", "load_fyers_master", "sync_nifty_option_contracts",
           "sync_option_contracts", "write_status"]
