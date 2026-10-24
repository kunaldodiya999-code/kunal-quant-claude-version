"""Candles, futures volume, KTMI Uni Lite and option-chain OI for the dashboard chart (read-only).

Sources:
  live      the trading program's files in data/paper_trading/<INDEX>/:
            minute_candles.csv (index), futures_minute_candles.csv (volume),
            daily_candles.csv, oi_chain.json.
  research  data/research/market_data.db (scripts/sweep_market_data.py): FYERS 1-minute when
            swept with FYERS (with futures volume), else Yahoo 1-minute (no volume).
  kq-db     the KunalQuant database (5 years of NIFTY 1-minute), if it is on this PC.

The spot index has no volume. Volume shown on the index chart is the nearest
FUTURES contract's volume of the same minute (the owner's choice); VWAP and the
volume profile use it. Without futures data the volume is 0 and the chart says so.

Every timeframe (1, 3, 5, 10, 15, 30, 60 minutes and 1 day) is sent at once, so the
chart switches timeframe instantly. KTMI Uni Lite is the locked calculation
(profile UNI_LITE_CORE) on each timeframe, with earlier days as warm-up.
"""

from __future__ import annotations

import json
import sqlite3
from collections import OrderedDict
from datetime import date, datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

from .live import paper_dir                # also puts the project folder on sys.path
from .research import research_dir
from indicators.ktmi.universal import OHLCData
from indicators.ktmi_uni_lite import UNI_LITE_CORE, calculate_uni_lite
from market_data.day_quality import group_by_day
from market_data.resampling import Candle, aggregate_day
from paper_trading.chart_feeds import DAILY_FILE, FUTURES_FILE, OI_FILE, read_candles
from paper_trading.minute_journal import MINUTE_FILE
from strategies.index_profiles import INDEX_PROFILES

IST = ZoneInfo("Asia/Kolkata")
IST_OFFSET = 19800            # the chart library shows UTC; shifting by +5:30 shows IST on the axis
WARMUP_DAYS = 15
TIMEFRAMES = ("1", "3", "5", "10", "15", "30", "60", "D")
KTMI_LINES = ("long_speed", "long_signal", "short_speed", "short_signal", "momentum_speed", "momentum_signal")
SOURCES = {
    "live": "Trading program (today + warm-up days)",
    "research": "Research data (data sweep)",
    "kq-db": "KunalQuant database (NIFTY, 5 years)",
}
DEFAULT_KQ_DB = Path(r"C:\Users\USER\Desktop\Kunal\KunalQuant\data\database\kunal_quant.db")


def _day(ts: int) -> date:
    return datetime.fromtimestamp(ts, IST).date()


class ChartData:
    """What one source offers for one index."""

    def __init__(self, minutes=(), futures=(), daily=(), oi=None, volume_source=None):
        self.minutes = list(minutes)            # index 1-minute candles (no volume of their own)
        self.futures = list(futures)            # futures 1-minute candles with volume
        self.daily = list(daily)                # index daily candles (volume = futures daily volume)
        self.oi = oi                            # option-chain OI dict or None
        self.volume_source = volume_source      # text for the chart, None = no volume


# ------------------------------------------------------------------ sources

def _live(index: str) -> ChartData:
    folder = paper_dir(index)
    futures = read_candles(folder / FUTURES_FILE)
    oi = None
    if (folder / OI_FILE).exists():
        try:
            oi = json.loads((folder / OI_FILE).read_text(encoding="utf-8"))
        except (OSError, ValueError):
            oi = None
    symbol = None
    if futures:
        import csv
        with (folder / FUTURES_FILE).open(newline="", encoding="utf-8") as handle:
            last = None
            for last in csv.DictReader(handle):
                pass
            symbol = (last or {}).get("symbol")
    return ChartData(read_candles(folder / MINUTE_FILE), futures, read_candles(folder / DAILY_FILE), oi,
                     f"{symbol} futures" if futures else None)


def _research(index: str) -> ChartData:
    path = research_dir() / "market_data.db"
    if not path.exists():
        return ChartData()
    from market_data.research_store import ResearchStore
    store = ResearchStore(path)
    minutes = store.load(index, "fyers", "1m", clean_only=False) or store.load(index, "yahoo", "1m", clean_only=False)
    futures = store.load(f"{index}_FUT", "fyers", "1m", clean_only=False)
    hourly = store.load(index, "yahoo", "60m", clean_only=False)
    daily = [Candle(day[0].timestamp, day[0].open, max(c.high for c in day), min(c.low for c in day),
                    day[-1].close, None) for _, day in sorted(group_by_day(hourly).items())]
    return ChartData(minutes, futures, daily, None, f"{index} futures (FYERS sweep)" if futures else None)


def _kq_rows(path: Path, sql: str, args) -> list:
    with sqlite3.connect(f"file:{path}?mode=ro", uri=True) as db:
        return db.execute(sql, args).fetchall()


def kq_last_day(index: str, path: Path = DEFAULT_KQ_DB) -> date | None:
    if not Path(path).exists():
        return None
    row = _kq_rows(path, "SELECT MAX(c.timestamp) FROM candles c JOIN instruments i ON i.id = c.instrument_id "
                         "WHERE i.symbol = ? AND c.resolution = '1'", (INDEX_PROFILES[index].spot_symbol,))
    return _day(row[0][0]) if row and row[0][0] else None


def _kq(index: str, last_day: date | None, path: Path) -> ChartData:
    if not Path(path).exists():
        return ChartData()
    last_day = last_day or kq_last_day(index, path)
    if last_day is None:
        return ChartData()
    symbol = INDEX_PROFILES[index].spot_symbol
    end = int(datetime.combine(last_day + timedelta(days=1), datetime.min.time(), IST).timestamp())
    since = int(datetime.combine(last_day - timedelta(days=WARMUP_DAYS * 2), datetime.min.time(), IST).timestamp())
    year = int(datetime.combine(last_day - timedelta(days=400), datetime.min.time(), IST).timestamp())
    query = ("SELECT c.timestamp, c.open, c.high, c.low, c.close FROM candles c JOIN instruments i "
             "ON i.id = c.instrument_id WHERE i.symbol = ? AND c.resolution = '1' AND c.timestamp >= ? "
             "AND c.timestamp < ? GROUP BY c.timestamp ORDER BY c.timestamp")
    minutes = [Candle(int(t), float(o), float(h), float(l), float(c), None)
               for t, o, h, l, c in _kq_rows(path, query, (symbol, since, end))]
    daily = []
    for _, day in sorted(group_by_day(Candle(int(t), float(o), float(h), float(l), float(c), None)
                                      for t, o, h, l, c in _kq_rows(path, query, (symbol, year, end))).items()):
        daily.append(Candle(day[0].timestamp, day[0].open, max(c.high for c in day), min(c.low for c in day),
                            day[-1].close, None))
    return ChartData(minutes, (), daily, None, None)


def load_chart_data(source: str, index: str, *, last_day: date | None = None,
                    kq_db: Path = DEFAULT_KQ_DB) -> ChartData:
    if source == "kq-db":
        return _kq(index, last_day, kq_db)
    data = _live(index) if source == "live" else _research(index)
    if last_day is not None:
        cut = int(datetime.combine(last_day + timedelta(days=1), datetime.min.time(), IST).timestamp())
        data.minutes = [c for c in data.minutes if c.timestamp < cut]
        data.futures = [c for c in data.futures if c.timestamp < cut]
        data.daily = [c for c in data.daily if c.timestamp < cut]
        data.oi = None                               # OI is only known for now
    return data


def load_minutes(source: str, index: str, *, last_day: date | None = None, kq_db: Path = DEFAULT_KQ_DB):
    return load_chart_data(source, index, last_day=last_day, kq_db=kq_db).minutes


def trading_days(minutes) -> list[date]:
    return sorted({_day(c.timestamp) for c in minutes})


# ------------------------------------------------------------------ payload

def with_futures_volume(minutes, futures) -> list[Candle]:
    """Index minutes carrying the same minute's futures volume (0 when that minute has none)."""
    if not futures:
        return [Candle(c.timestamp, c.open, c.high, c.low, c.close, None) for c in minutes]
    volume = {int(c.timestamp): int(c.volume or 0) for c in futures}
    return [Candle(c.timestamp, c.open, c.high, c.low, c.close, volume.get(int(c.timestamp), 0)) for c in minutes]


def _daily_bars(data: ChartData, minutes: list[Candle]) -> list[Candle]:
    """Daily candles; today's forming day is added from today's minutes when the file lacks it."""
    days = OrderedDict((_day(c.timestamp), c) for c in data.daily)
    for day, bars in sorted(group_by_day(minutes).items()):
        if day not in days:
            vols = [c.volume for c in bars]
            days[day] = Candle(bars[0].timestamp, bars[0].open, max(c.high for c in bars), min(c.low for c in bars),
                               bars[-1].close, None if any(v is None for v in vols) else sum(vols))
    return [days[d] for d in sorted(days)]


def _frame(bars, *, first_shown: int | None, daily: bool = False) -> dict:
    """Columns for one timeframe. Every bar is drawn (also the one still forming), but KTMI
    runs on complete bars only, exactly like the trading engine; others get no KTMI value."""
    complete = [b for b in bars if getattr(b, "complete", True)]
    ktmi = calculate_uni_lite([OHLCData(b.open, b.high, b.low, b.close) for b in complete], UNI_LITE_CORE) if complete else []
    by_ts = {int(b.timestamp): v for b, v in zip(complete, ktmi)}
    out = {"t": [], "o": [], "h": [], "l": [], "c": [], "v": [], "long": [], "short": [],
           "ktmi": {name: [] for name in KTMI_LINES}}
    for bar in bars:
        v = by_ts.get(int(bar.timestamp))
        if first_shown is not None and bar.timestamp < first_shown:
            continue
        if daily:      # a day is shown at its date (00:00 on the chart's IST clock)
            d = _day(int(bar.timestamp))
            t = int(datetime(d.year, d.month, d.day, tzinfo=ZoneInfo("UTC")).timestamp())
        else:
            t = int(bar.timestamp) + IST_OFFSET
        out["t"].append(t)
        for key, value in (("o", bar.open), ("h", bar.high), ("l", bar.low), ("c", bar.close)):
            out[key].append(round(float(value), 2))
        out["v"].append(int(bar.volume or 0))
        for name in KTMI_LINES:
            value = None if v is None else getattr(v, name)
            out["ktmi"][name].append(None if value is None else round(float(value), 4))
        if v is not None and v.long_buy:
            out["long"].append(t)
        if v is not None and v.short_buy:
            out["short"].append(t)
    return out


def chart_payload(data: ChartData, *, index: str, show_days: int = 2, timeframe: int | str = 3,
                  marks: list | None = None) -> dict:
    """Everything the chart needs, for every timeframe, as compact columns.

    ``index`` may also be a stock name (title only). ``marks``: extra markers, e.g. Gap Reversal setups:
    [{"time": epoch seconds of the candle, "side": "SHORT"/"LONG", "text": "78%"}]."""
    minutes = with_futures_volume(data.minutes, data.futures)
    days = trading_days(minutes)
    shown = days[-show_days:] if days else []
    first = int(datetime.combine(shown[0], datetime.min.time(), IST).timestamp()) if shown else None
    by_day = sorted(group_by_day(minutes).items())
    frames = {"1": _frame(minutes, first_shown=first)}
    for tf in TIMEFRAMES[1:-1]:
        bars = [b for _, day in by_day for b in aggregate_day(day, int(tf))]
        frames[tf] = _frame(bars, first_shown=first)
    frames["D"] = _frame(_daily_bars(data, minutes), first_shown=None, daily=True)
    oi = data.oi if data.oi and data.oi.get("rows") else None
    last = frames["1"]["t"][-1] if frames["1"]["t"] else 0
    return {
        "version": f"{last}-{len(frames['1']['t'])}-{(oi or {}).get('updated_at', '')}-{len(data.futures)}",
        "updated_at": datetime.now(IST).strftime("%H:%M:%S"),
        "index": index, "title": INDEX_PROFILES[index].label if index in INDEX_PROFILES else index, "frames": frames,
        "marks": [{**m, "time": int(m["time"]) + IST_OFFSET} for m in (marks or [])],
        "default_tf": str(timeframe), "days": [d.isoformat() for d in shown],
        "volume_source": data.volume_source, "oi": oi,
        "levels": {"center": 0.0, "upper": 0.5, "lower": -0.5, "overbought": 3.0, "oversold": -3.0},
    }


__all__ = [
    "ChartData", "IST_OFFSET", "SOURCES", "TIMEFRAMES", "chart_payload", "kq_last_day", "load_chart_data",
    "load_minutes", "trading_days", "with_futures_volume",
]
