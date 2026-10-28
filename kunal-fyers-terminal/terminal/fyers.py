"""Everything that talks to FYERS (API v3): login, token, quotes, 1-minute history, funds, contract list.

Secrets stay on the PC: ``.env`` (FYERS_CLIENT_ID, FYERS_SECRET_KEY, FYERS_REDIRECT_URI) and ``data/token.json``
(today's access token), both ignored by git. Read-only towards the market: orders live in terminal/broker.py.
"""

from __future__ import annotations

import json
import os
import urllib.request
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any, Optional, Sequence
from urllib.parse import parse_qs, urlparse
from zoneinfo import ZoneInfo

from terminal.candles import Candle, parse_history

IST = ZoneInfo("Asia/Kolkata")
ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data"


def data_dir() -> Path:
    """data/ of this folder (tests point KFT_DATA at a temporary folder)."""
    return Path(os.environ.get("KFT_DATA") or DATA)
MASTER_URL = "https://public.fyers.in/sym_details/{name}_sym_master.json"
STATE = "kunal_fyers_terminal"


@dataclass(frozen=True)
class IndexInfo:
    key: str
    label: str
    spot: str               # FYERS symbol of the index
    underlying: str         # underSym in the FYERS contract list
    master: str             # NSE_FO / BSE_FO
    chain_width: int        # strikes each side of ATM (owner: NIFTY / BANK NIFTY 5, SENSEX 8)


INDEXES = {
    "NIFTY": IndexInfo("NIFTY", "NIFTY 50", "NSE:NIFTY50-INDEX", "NIFTY", "NSE_FO", 5),
    "BANKNIFTY": IndexInfo("BANKNIFTY", "BANK NIFTY", "NSE:NIFTYBANK-INDEX", "BANKNIFTY", "NSE_FO", 5),
    "SENSEX": IndexInfo("SENSEX", "SENSEX", "BSE:SENSEX-INDEX", "SENSEX", "BSE_FO", 8),
}


# ------------------------------------------------------------------ credentials and login
def read_env(path: Path = ROOT / ".env") -> dict:
    out = {}
    if path.exists():
        for line in path.read_text(encoding="utf-8").splitlines():
            if "=" in line and not line.strip().startswith("#"):
                k, v = line.split("=", 1)
                out[k.strip()] = v.strip().strip('"').strip("'")
    return out


def write_env(values: dict, path: Path = ROOT / ".env") -> None:
    current = read_env(path)
    current.update({k: v for k, v in values.items() if v})
    path.write_text("".join(f"{k}={v}\n" for k, v in current.items()), encoding="utf-8")


def credentials() -> dict:
    env = {**read_env(), **{k: os.environ[k] for k in ("FYERS_CLIENT_ID", "FYERS_SECRET_KEY", "FYERS_REDIRECT_URI")
                            if os.environ.get(k)}}
    return {"client_id": env.get("FYERS_CLIENT_ID", ""), "secret_key": env.get("FYERS_SECRET_KEY", ""),
            "redirect_uri": env.get("FYERS_REDIRECT_URI", "http://127.0.0.1:8000")}


def _session(creds: dict):
    from fyers_apiv3 import fyersModel
    return fyersModel.SessionModel(client_id=creds["client_id"], secret_key=creds["secret_key"],
                                   redirect_uri=creds["redirect_uri"], response_type="code",
                                   grant_type="authorization_code", state=STATE)


def login_url(creds: dict) -> str:
    return _session(creds).generate_authcode()


def auth_code_from(text: str) -> str:
    """The auth_code from the address FYERS opened after login (or the bare code itself)."""
    text = (text or "").strip()
    if "auth_code=" in text:
        code = parse_qs(urlparse(text).query).get("auth_code", [""])[0]
        if code:
            return code
    if text and "=" not in text and " " not in text and len(text) > 20:
        return text
    raise ValueError("No auth_code found. Paste the WHOLE address from the browser after the FYERS login.")


def exchange_code(creds: dict, code: str) -> str:
    session = _session(creds)
    session.set_token(code)
    response = session.generate_token()
    token = response.get("access_token") if isinstance(response, dict) else None
    if not token:
        raise ValueError(f"FYERS did not give a token: {response!r}"[:300])
    return token


def save_token(token: str, folder: Optional[Path] = None) -> None:
    folder = Path(folder or data_dir())
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "token.json").write_text(json.dumps({"date": datetime.now(IST).date().isoformat(), "token": token}),
                                       encoding="utf-8")


def saved_token(folder: Optional[Path] = None) -> Optional[str]:
    """Today's token (FYERS tokens last one trading day)."""
    folder = Path(folder or data_dir())
    try:
        data = json.loads((folder / "token.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return data.get("token") if data.get("date") == datetime.now(IST).date().isoformat() else None


# ------------------------------------------------------------------ the client
class Fyers:
    def __init__(self, client_id: str, token: str, model: Any = None) -> None:
        if model is None:
            from fyers_apiv3 import fyersModel
            logs = data_dir() / "logs"
            logs.mkdir(parents=True, exist_ok=True)
            model = fyersModel.FyersModel(client_id=client_id, token=token, is_async=False, log_path=str(logs))
        self.model = model

    @staticmethod
    def _ok(response: Any, what: str) -> dict:
        if not isinstance(response, dict) or response.get("s") != "ok":
            raise ValueError(f"FYERS {what} failed: {response!r}"[:300])
        return response

    def profile(self) -> dict:
        return self._ok(self.model.get_profile(), "profile").get("data", {})

    def available_funds(self) -> float:
        for row in self._ok(self.model.funds(), "funds").get("fund_limit") or []:
            if row.get("id") == 10 or str(row.get("title", "")).strip().lower() == "available balance":
                return float(row.get("equityAmount") or 0.0)
        raise ValueError("FYERS funds: no 'Available Balance' row")

    def quotes(self, symbols: Sequence[str]) -> dict[str, dict]:
        """symbol -> {"ltp", "bid", "ask"}; up to 50 symbols per FYERS call."""
        out: dict[str, dict] = {}
        symbols = [s for s in dict.fromkeys(symbols) if s]
        for i in range(0, len(symbols), 50):
            response = self._ok(self.model.quotes(data={"symbols": ",".join(symbols[i:i + 50])}), "quotes")
            for row in response.get("d") or []:
                v = row.get("v") or {}
                if isinstance(v, dict) and v.get("lp") is not None:
                    out[row.get("n")] = {"ltp": float(v["lp"]), "bid": float(v.get("bid") or 0),
                                         "ask": float(v.get("ask") or 0)}
        return out

    def minutes(self, symbol: str, start: date, end: date) -> list[Candle]:
        """1-minute candles from ``start`` to ``end`` (FYERS: up to 100 days a request)."""
        response = self.model.history(data={"symbol": symbol, "resolution": "1", "date_format": "1",
                                            "range_from": start.isoformat(), "range_to": end.isoformat(),
                                            "cont_flag": "1"})
        return parse_history(response)


# ------------------------------------------------------------------ contract list (public, once a day)
def load_master(name: str, today: date, folder: Optional[Path] = None, fetch=None) -> dict:
    folder = Path(folder or data_dir() / "master")
    path = folder / f"{name}_{today.isoformat()}.json"
    if path.exists():
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except ValueError:
            path.unlink()
    if fetch is None:
        def fetch(url):
            with urllib.request.urlopen(urllib.request.Request(url, headers={"User-Agent": "KunalTerminal"}),
                                        timeout=180) as r:
                return json.loads(r.read().decode("utf-8"))
    data = fetch(MASTER_URL.format(name=name))
    if not isinstance(data, dict) or not data:
        raise RuntimeError(f"FYERS {name} contract list looks wrong")
    folder.mkdir(parents=True, exist_ok=True)
    for old in folder.glob(f"{name}_*.json"):
        old.unlink()
    path.write_text(json.dumps(data), encoding="utf-8")
    return data


@dataclass(frozen=True)
class Contracts:
    expiry: date
    lot_size: int
    step: float
    calls: dict             # strike -> symbol
    puts: dict
    future: Optional[str]   # nearest futures contract (its volume feeds VWAP: the index has none)


def nearest_contracts(master: dict, underlying: str, today: date) -> Contracts:
    options: dict[date, list] = {}
    futures = []
    for symbol, row in master.items():
        if row.get("underSym") != underlying:
            continue
        try:
            expiry = datetime.fromtimestamp(int(row["expiryDate"]), IST).date()
        except (KeyError, TypeError, ValueError):
            continue
        if expiry < today:
            continue
        ticker = str(row.get("symTicker") or symbol)
        if row.get("optType") in ("CE", "PE"):
            options.setdefault(expiry, []).append((float(row["strikePrice"]), row["optType"], ticker,
                                                   int(row.get("minLotSize") or 0)))
        elif ticker.endswith("FUT"):
            futures.append((expiry, ticker))
    if not options:
        raise RuntimeError(f"No current {underlying} options in the FYERS contract list")
    expiry = min(options)
    rows = options[expiry]
    strikes = sorted({r[0] for r in rows})
    step = min(b - a for a, b in zip(strikes, strikes[1:])) if len(strikes) > 1 else 50.0
    lots = sorted({r[3] for r in rows if r[3]})
    return Contracts(expiry, lots[0] if lots else 1, step,
                     {r[0]: r[2] for r in rows if r[1] == "CE"}, {r[0]: r[2] for r in rows if r[1] == "PE"},
                     min(futures)[1] if futures else None)


def chain_strikes(c: Contracts, spot: float, width: int) -> list[float]:
    """ATM (strike nearest to the index) and ``width`` strikes either side that exist for both CE and PE."""
    both = sorted(set(c.calls) & set(c.puts))
    if not both:
        return []
    atm = min(both, key=lambda k: (abs(k - spot), k))
    i = both.index(atm)
    return both[max(0, i - width): i + width + 1]


__all__ = ["Contracts", "DATA", "data_dir", "Fyers", "INDEXES", "IndexInfo", "auth_code_from", "chain_strikes", "credentials",
           "exchange_code", "load_master", "login_url", "nearest_contracts", "read_env", "save_token",
           "saved_token", "write_env"]
