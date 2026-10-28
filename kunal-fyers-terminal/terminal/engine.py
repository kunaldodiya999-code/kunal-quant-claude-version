"""The terminal's engine: one background loop, every few seconds (owner's BBP_NM rules, terminal/strategy.py).

Each pass (``tick``):
  1. settings (data/settings.json) and today's nearest-expiry contracts of the index on the chart;
  2. live prices (FYERS quotes): index, the option chain (NIFTY / BANK NIFTY ATM +- 5, SENSEX ATM +- 8), open trade;
  3. open trade: option price at or below its stop (the signal candle's low) -> SELL limit; 15:10 -> SELL limit;
  4. just after every minute: 1-minute history of the index (+ nearest future for VWAP volume) -> 1 / 3 / 5-minute
     candles -> BBP_NM Direction on FINISHED candles; a cross at the newest finished candle -> exit / enter;
  5. data for the chart (static/live/chart.json) and the screen (``snapshot``).

Files (data/, never in git): state.json (open trade), trades.csv (closed trades), events.log, orders_journal.jsonl.
"""

from __future__ import annotations

import csv
import json
import threading
import time as _time
from collections import deque
from dataclasses import asdict, dataclass
from datetime import date, datetime, time, timedelta
from pathlib import Path
from typing import Callable, Optional

from terminal.broker import PaperBroker, RealBroker, real_orders_allowed
from terminal.candles import IST, Candle, bucket_start, close_time, finished, in_session, resample
from terminal.fyers import INDEXES, data_dir, Contracts, chain_strikes, load_master, nearest_contracts
from terminal.indicators import bbp_nm, ktmi, vwap
from terminal.settings import Settings, SettingsStore
from terminal.strategy import ChainRow, direction_events, last_sign, lots_for, pick_strike, plan

ROOT = Path(__file__).resolve().parents[1]
CHART_FILE = ROOT / "static" / "live" / "chart.json"
HISTORY_DAYS = 5                 # calendar days of 1-minute history (warm-up for BBP and KTMI)
QUOTE_EVERY = 2.0                # seconds between passes
FUNDS_EVERY = 30.0
LATE_MINUTE_WAIT = 30            # seconds to wait for FYERS to publish a candle's last minute
IST_SHIFT = 19800                # the chart library shows UTC: shift so the axis reads Indian time

TRADE_FIELDS = ["date", "index", "side", "symbol", "strike", "lots", "qty", "entry_time", "entry_price", "stop",
                "exit_time", "exit_price", "pnl", "exit_reason", "mode"]


@dataclass
class Position:
    day: str
    index: str
    side: str                    # CALL / PUT
    symbol: str
    strike: float
    lot_size: int
    lots: int
    qty: int
    entry_time: str
    entry_price: float
    stop: float
    mode: str                    # PAPER / REAL
    signal_bar: int              # epoch of the signal candle

    @staticmethod
    def from_dict(d: dict) -> "Position":
        return Position(**{k: d[k] for k in Position.__dataclass_fields__})


def _t(text: str) -> time:
    return time.fromisoformat(text)


class Terminal:
    def __init__(self, client, *, folder: Optional[Path] = None, store: Optional[SettingsStore] = None,
                 clock: Callable[[], datetime] = lambda: datetime.now(IST), chart_file: Optional[Path] = None,
                 master_loader: Optional[Callable[[str, date], dict]] = None) -> None:
        self.client = client
        self.folder = Path(folder or data_dir())
        self.folder.mkdir(parents=True, exist_ok=True)
        self.store = store or SettingsStore(self.folder)
        self.clock = clock
        self.chart_file = Path(chart_file or CHART_FILE)
        self.master_loader = master_loader or (lambda name, today: load_master(name, today, self.folder / "master"))
        self.lock = threading.RLock()
        self.events: deque = deque(maxlen=300)
        self._thread: Optional[threading.Thread] = None
        self._stop = threading.Event()
        # market picture
        self.contracts: dict[tuple[str, str], Contracts] = {}
        self.quotes: dict[str, dict] = {}
        self.chain: list[dict] = []
        self.funds: Optional[float] = None
        self.funds_at = 0.0
        self.status = "starting"
        self.error = ""
        # signal memory (reset when the index, timeframe or day changes)
        self._key: Optional[tuple] = None
        self._sign = 0
        self._done_ts: Optional[int] = None
        self._next_history = 0.0
        self._minutes: list[Candle] = []
        self._future_minutes: list[Candle] = []
        self._bars: list[Candle] = []
        self._last_dir: Optional[float] = None
        self._warned_real = ""
        self.position: Optional[Position] = self._load_position()

    # ------------------------------------------------------------------ files
    @property
    def state_file(self) -> Path:
        return self.folder / "state.json"

    @property
    def trades_file(self) -> Path:
        return self.folder / "trades.csv"

    def _load_position(self) -> Optional[Position]:
        try:
            p = Position.from_dict(json.loads(self.state_file.read_text(encoding="utf-8"))["position"])
        except (OSError, ValueError, KeyError, TypeError):
            return None
        if p.day != self.clock().date().isoformat():
            if p.mode == "PAPER":
                self.log(f"Paper trade {p.symbol} from {p.day} dropped (paper trades end every day).")
                self.state_file.unlink(missing_ok=True)
                return None
            self.log(f"ALERT: REAL trade {p.symbol} from {p.day} is still in the records. Check FYERS positions.")
        return p

    def _save_position(self) -> None:
        if self.position is None:
            self.state_file.unlink(missing_ok=True)
            return
        tmp = self.state_file.with_suffix(".tmp")
        tmp.write_text(json.dumps({"position": asdict(self.position)}, indent=2), encoding="utf-8")
        tmp.replace(self.state_file)

    def log(self, message: str) -> None:
        stamp = self.clock().strftime("%Y-%m-%d %H:%M:%S")
        with self.lock:
            self.events.appendleft(f"{stamp}  {message}")
        try:
            with (self.folder / "events.log").open("a", encoding="utf-8") as f:
                f.write(f"{stamp}  {message}\n")
        except OSError:
            pass

    def trades_today(self) -> list[dict]:
        if not self.trades_file.exists():
            return []
        today = self.clock().date().isoformat()
        with self.trades_file.open(encoding="utf-8", newline="") as f:
            return [r for r in csv.DictReader(f) if r.get("date") == today]

    def _write_trade(self, row: dict) -> None:
        new = not self.trades_file.exists()
        with self.trades_file.open("a", encoding="utf-8", newline="") as f:
            w = csv.DictWriter(f, fieldnames=TRADE_FIELDS)
            if new:
                w.writeheader()
            w.writerow(row)

    # ------------------------------------------------------------------ background thread
    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._run, name="kunal-terminal", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()

    @property
    def running(self) -> bool:
        return bool(self._thread and self._thread.is_alive())

    def _run(self) -> None:
        while not self._stop.is_set():
            self.tick()
            self._stop.wait(QUOTE_EVERY)

    # ------------------------------------------------------------------ one pass
    def tick(self) -> None:
        try:
            self._tick()
            self.error = ""
        except Exception as exc:   # keep the loop alive; show the problem on the screen
            message = str(exc)
            if "token" in message.lower() or "-16" in message or "-15" in message or "authenticat" in message.lower():
                message = "FYERS refused the token (it lasts one day). Log in again: button 'Log out' then log in."
            if message != self.error:
                self.log(f"Problem: {message}")
            self.error = message
            self.status = "problem"

    def _tick(self) -> None:
        now = self.clock()
        s = self.store.load()
        info = INDEXES[s.index]
        key = (now.date(), s.index, s.timeframe, s.bbp_window)
        if key != self._key:
            self._key, self._sign, self._done_ts, self._next_history = key, 0, None, 0.0
            self._minutes, self._future_minutes, self._bars, self._last_dir = [], [], [], None
            self.log(f"Watching {info.label} {s.timeframe}-minute chart (BBP_NM Direction on finished candles).")
        c = self._contracts(info, now.date())

        # live prices
        spot_q = self.client.quotes([info.spot]).get(info.spot)
        if not spot_q:
            raise ValueError(f"no live price for {info.spot}")
        strikes = chain_strikes(c, spot_q["ltp"], info.chain_width)
        symbols = [info.spot] + [c.calls[k] for k in strikes] + [c.puts[k] for k in strikes]
        if self.position:
            symbols.append(self.position.symbol)
        quotes = self.client.quotes(symbols)
        quotes.setdefault(info.spot, spot_q)
        atm = min(strikes, key=lambda k: (abs(k - spot_q["ltp"]), k)) if strikes else None
        with self.lock:
            self.quotes = quotes
            self.chain = [{"strike": k, "atm": k == atm, "call": c.calls[k], "put": c.puts[k],
                           "call_ltp": (quotes.get(c.calls[k]) or {}).get("ltp"),
                           "put_ltp": (quotes.get(c.puts[k]) or {}).get("ltp")} for k in strikes]
        if self.funds is None or _time.monotonic() - self.funds_at > FUNDS_EVERY:
            self.funds, self.funds_at = self.client.available_funds(), _time.monotonic()

        # open trade: stop loss and 15:10
        p = self.position
        if p:
            q = quotes.get(p.symbol)
            if now.time() >= _t(s.force_exit):
                self._exit(s, f"time exit {s.force_exit}", q)
            elif q and q["ltp"] <= p.stop:
                self._exit(s, f"stop loss: price {q['ltp']:g} at or below {p.stop:g} (signal candle low)", q)

        # finished candles and the strategy
        if _time.monotonic() >= self._next_history:
            self._signals(s, info, c, now)
        self._write_chart(s, info, c, spot_q["ltp"], now)
        self.status = "running"

    def _contracts(self, info, today: date) -> Contracts:
        k = (info.key, today.isoformat())
        if k not in self.contracts:
            c = nearest_contracts(self.master_loader(info.master, today), info.underlying, today)
            self.contracts[k] = c
            self.log(f"{info.label}: nearest expiry {c.expiry:%d %b %Y}, lot size {c.lot_size}, "
                     f"strike step {c.step:g}, future {c.future or '-'}")
        return self.contracts[k]

    def _signals(self, s: Settings, info, c: Contracts, now: datetime) -> None:
        now_ts = int(now.timestamp())
        start = now.date() - timedelta(days=HISTORY_DAYS)
        self._minutes = self.client.minutes(info.spot, start, now.date())
        if c.future:
            try:
                self._future_minutes = self.client.minutes(c.future, start, now.date())
            except ValueError as exc:
                self.log(f"Future volume not available for VWAP: {exc}")
        bars = resample(self._minutes, s.timeframe)
        done = finished(bars, s.timeframe, now_ts)
        self._bars = bars
        # next look: just after the next minute (FYERS publishes a minute a moment after it ends)
        self._next_history = _time.monotonic() + (60 - now.second) + 3
        if not done:
            return
        newest = done[-1]
        closes_at = close_time(newest.ts, s.timeframe)
        last_minute = closes_at - 60
        if newest.ts != self._done_ts and not any(m.ts >= last_minute for m in self._minutes) \
                and now_ts - closes_at < LATE_MINUTE_WAIT:
            self._next_history = _time.monotonic() + 5          # its last minute is not published yet
            done = done[:-1]
            if not done:
                return
            newest = done[-1]
        dirs = [d for _, _, d in bbp_nm([b.close for b in done], s.bbp_window)]
        self._last_dir = next((d for d in reversed(dirs) if d is not None), None)
        if self._done_ts is None:                               # first look: remember the sign, never trade it
            self._sign, self._done_ts = last_sign(dirs), newest.ts
            return
        if newest.ts == self._done_ts:
            return
        new_from = next(i for i, b in enumerate(done) if b.ts > self._done_ts)
        events = direction_events(dirs[new_from:], start_sign=self._sign)
        self._sign = last_sign(dirs) or self._sign
        self._done_ts = newest.ts
        if not events or new_from + events[-1][0] != len(done) - 1:
            return                                              # no cross at the newest finished candle
        if now_ts - close_time(newest.ts, s.timeframe) > 90:
            self.log("Cross seen late (the terminal was paused): not traded.")
            return
        event = events[-1][1]
        entries_allowed = _t(s.entry_start) <= now.time() < _t(s.entry_end)
        self.log(f"BBP_NM Direction crossed {'ABOVE' if event == 'UP' else 'BELOW'} 0 at the "
                 f"{datetime.fromtimestamp(newest.ts, IST):%H:%M} candle ({dirs[-1]:+.2f}).")
        position_side = self.position.side if self.position else None
        actions = plan(event, position=position_side, call_on=s.call_on, put_on=s.put_on,
                       entries_allowed=entries_allowed)
        if not actions and not entries_allowed and position_side is None:
            self.log(f"No entry: outside entry time {s.entry_start}-{s.entry_end}.")
        for a in actions:
            if a.kind == "EXIT":
                self._exit(s, a.reason, self.quotes.get(self.position.symbol) if self.position else None)
                if self.position:                                 # exit not done: never stack a second trade
                    return
            else:
                self._enter(s, info, c, a.side, newest, now)

    # ------------------------------------------------------------------ orders
    def _broker(self, s: Settings, now: datetime):
        if s.real_orders:
            if real_orders_allowed(True, self.folder, now.date()):
                return RealBroker(self.client.model, self.folder / "orders_journal.jsonl",
                                  lambda sym: self.client.quotes([sym])[sym]["ltp"],
                                  buffer_buy=s.buffer, buffer_sell=s.buffer)
            if self._warned_real != now.date().isoformat():
                self._warned_real = now.date().isoformat()
                self.log("Real orders is ON but today is not armed (python arm_real_orders.py): PAPER trades only.")
        return PaperBroker(s.buffer, s.buffer)

    def _enter(self, s: Settings, info, c: Contracts, side: str, signal_bar: Candle, now: datetime) -> None:
        rows = [ChainRow(r["strike"], r["call"] if side == "CALL" else r["put"],
                         r["call_ltp"] if side == "CALL" else r["put_ltp"]) for r in self.chain]
        pick = pick_strike(rows, mode=s.strike_mode, low=s.premium_low, high=s.premium_high,
                           per_lot=s.per_lot_amount, lot_size=c.lot_size)
        if pick.row is None:
            self.log(f"No {side} entry: {pick.reason}.")
            return
        funds = self.funds or 0.0
        lots = lots_for(s.funds_per_entry, funds, pick.row.price, c.lot_size)
        if lots < 1:
            self.log(f"No {side} entry: Rs {min(s.funds_per_entry, funds):,.0f} does not buy one lot of "
                     f"{pick.row.symbol} ({pick.row.price:g} x {c.lot_size} = Rs {pick.row.price * c.lot_size:,.0f}).")
            return
        stop = self._signal_candle_low(pick.row.symbol, signal_bar, s.timeframe, now)
        if stop is None:
            self.log(f"No {side} entry: no {s.timeframe}-minute candle of {pick.row.symbol} for the stop loss.")
            return
        quote = self.client.quotes([pick.row.symbol]).get(pick.row.symbol) or \
            {"ltp": pick.row.price, "bid": 0.0, "ask": 0.0}
        if quote["ltp"] <= stop:
            self.log(f"No {side} entry: {pick.row.symbol} {quote['ltp']:g} is already at or below the signal "
                     f"candle low {stop:g}.")
            return
        broker = self._broker(s, now)
        fill = broker.buy(pick.row.symbol, lots * c.lot_size, quote, c.lot_size)
        if not fill.ok or fill.qty <= 0:
            self.log(f"{side} entry NOT done ({broker.mode}): {fill.message}")
            return
        self.position = Position(now.date().isoformat(), s.index, side, pick.row.symbol, pick.row.strike,
                                 c.lot_size, fill.qty // c.lot_size, fill.qty, now.strftime("%H:%M:%S"),
                                 fill.price, stop, broker.mode, signal_bar.ts)
        self._save_position()
        self.log(f"BUY {side} {pick.row.symbol}: {self.position.lots} lot(s) = {fill.qty} qty at {fill.price:g} "
                 f"({broker.mode}, {fill.message}); stop {stop:g}. Picked: {pick.reason}.")

    def _signal_candle_low(self, symbol: str, signal_bar: Candle, minutes: int, now: datetime) -> Optional[float]:
        """Low of the option's own candle (same timeframe) that closed with the signal candle."""
        mins = self.client.minutes(symbol, now.date(), now.date())
        bars = finished(resample(mins, minutes), minutes, int(now.timestamp()))
        same = [b for b in bars if b.ts == signal_bar.ts]
        if same:
            return same[0].low
        earlier = [b for b in bars if b.ts < signal_bar.ts]       # the option did not trade in that candle
        return earlier[-1].low if earlier else None

    def _exit(self, s: Settings, reason: str, quote: Optional[dict]) -> None:
        p = self.position
        if p is None:
            return
        if quote is None:
            quote = self.client.quotes([p.symbol]).get(p.symbol)
        if not quote:
            self.log(f"ALERT: no price for {p.symbol}, exit ({reason}) not sent. Will try again.")
            return
        now = self.clock()
        broker = PaperBroker(s.buffer, s.buffer) if p.mode == "PAPER" else self._real_exit_broker(s)
        fill = broker.sell(p.symbol, p.qty, quote, p.lot_size)
        if not fill.ok:
            self.log(f"ALERT: exit of {p.symbol} NOT complete ({fill.message}). Check FYERS now.")
            return
        pnl = round((fill.price - p.entry_price) * p.qty, 2)
        self._write_trade({"date": p.day, "index": p.index, "side": p.side, "symbol": p.symbol, "strike": p.strike,
                           "lots": p.lots, "qty": p.qty, "entry_time": p.entry_time, "entry_price": p.entry_price,
                           "stop": p.stop, "exit_time": now.strftime("%H:%M:%S"), "exit_price": fill.price,
                           "pnl": pnl, "exit_reason": reason, "mode": p.mode})
        self.position = None
        self._save_position()
        self.log(f"SELL {p.side} {p.symbol}: {p.qty} qty at {fill.price:g} ({p.mode}, {fill.message}); "
                 f"P&L Rs {pnl:,.2f}. Reason: {reason}.")

    def _real_exit_broker(self, s: Settings):
        # a REAL trade is always closed with a real order, even if the day was disarmed meanwhile
        return RealBroker(self.client.model, self.folder / "orders_journal.jsonl",
                          lambda sym: self.client.quotes([sym])[sym]["ltp"], buffer_buy=s.buffer,
                          buffer_sell=s.buffer)

    def exit_now(self) -> None:
        """'Exit now' button on the screen (limit order with the buffer, like every exit)."""
        with self.lock:
            if self.position:
                self._exit(self.store.load(), "exit button", None)

    # ------------------------------------------------------------------ chart and screen
    def _write_chart(self, s: Settings, info, c: Contracts, ltp: float, now: datetime) -> None:
        bars = list(self._bars)
        if not bars:
            return
        now_ts = int(now.timestamp())
        last = bars[-1]
        if close_time(last.ts, s.timeframe) > now_ts:            # forming candle: follow the live price
            bars[-1] = Candle(last.ts, last.open, max(last.high, ltp), min(last.low, ltp), ltp, last.volume)
        fut = {m.ts: m.volume for m in self._future_minutes}
        vol: dict[int, float] = {}
        for m in self._minutes:
            if m.ts in fut and in_session(m.ts):
                k = bucket_start(m.ts, s.timeframe) if s.timeframe > 1 else m.ts
                vol[k] = vol.get(k, 0.0) + fut[m.ts]
        vw = vwap(bars, [vol.get(b.ts, 0.0) for b in bars])
        bbp = bbp_nm([b.close for b in bars], s.bbp_window)
        km = ktmi(bars)
        t = [b.ts + IST_SHIFT for b in bars]
        markers = []
        for i, k in enumerate(km):
            if k.long_buy:
                markers.append({"time": t[i], "position": "belowBar", "color": "#26a69a", "shape": "arrowUp"})
            if k.short_buy:
                markers.append({"time": t[i], "position": "aboveBar", "color": "#ef5350", "shape": "arrowDown"})
        trade_marks = []
        for r in self.trades_today() + ([asdict(self.position)] if self.position else []):
            if r.get("index") != s.index:
                continue
            for when, label, color in ((r.get("entry_time"), f"BUY {r.get('side')}", "#2962ff"),
                                       (r.get("exit_time"), "EXIT", "#ff9800")):
                if when:
                    ts = int(datetime.combine(now.date(), _t(when), IST).timestamp())
                    bar = max((b.ts for b in bars if b.ts <= ts), default=None)
                    if bar is not None:
                        trade_marks.append({"time": bar + IST_SHIFT, "position": "inBar", "color": color,
                                            "shape": "circle", "text": label})
        data = {
            "index": info.label, "timeframe": s.timeframe, "updated": now.strftime("%H:%M:%S"), "ltp": ltp,
            "candles": [{"time": t[i], "open": b.open, "high": b.high, "low": b.low, "close": b.close}
                        for i, b in enumerate(bars)],
            "vwap": [{"time": t[i], "value": round(v, 2)} for i, v in enumerate(vw) if v is not None],
            "bull": [{"time": t[i], "value": round(x[1], 2)} for i, x in enumerate(bbp) if x[1] is not None],
            "bear": [{"time": t[i], "value": round(x[0], 2)} for i, x in enumerate(bbp) if x[0] is not None],
            "direction": [{"time": t[i], "value": round(x[2], 2)} for i, x in enumerate(bbp) if x[2] is not None],
            "ktmi_long": [{"time": t[i], "value": round(k.long_speed, 3)} for i, k in enumerate(km)
                          if k.long_speed is not None],
            "ktmi_short": [{"time": t[i], "value": round(k.short_speed, 3)} for i, k in enumerate(km)
                           if k.short_speed is not None],
            "markers": sorted(markers + trade_marks, key=lambda m: m["time"]),
        }
        self.chart_file.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.chart_file.with_suffix(".tmp")
        tmp.write_text(json.dumps(data), encoding="utf-8")
        tmp.replace(self.chart_file)

    def snapshot(self) -> dict:
        with self.lock:
            p = self.position
            q = self.quotes.get(p.symbol) if p else None
            ltp = q["ltp"] if q else None
            deployed = p.entry_price * p.qty if p else 0.0
            funds = self.funds
            return {
                "status": self.status, "error": self.error, "funds": funds,
                "deployed": deployed,
                "utilized_pct": (deployed / funds * 100) if funds else 0.0,
                "chain": list(self.chain), "spot": (self.quotes.get(INDEXES[self.store.load().index].spot) or {})
                .get("ltp"),
                "direction": self._last_dir,
                "position": asdict(p) if p else None, "position_ltp": ltp,
                "position_pnl": round((ltp - p.entry_price) * p.qty, 2) if p and ltp is not None else None,
                "events": list(self.events)[:60],
            }


__all__ = ["CHART_FILE", "Position", "Terminal", "TRADE_FIELDS"]
