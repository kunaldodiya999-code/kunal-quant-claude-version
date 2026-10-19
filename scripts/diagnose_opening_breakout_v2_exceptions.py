"""Diagnose known V2 historical backtest exceptions without changing trade logic."""

from __future__ import annotations

import sqlite3
import sys
from datetime import datetime, timezone, timedelta
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from backtest.fyers_option_candles import FyersOptionCandleLoader
from backtest.opening_breakout_v2_option_integration import _find_option_signal_price, _setup_option_candle
from config.settings import DATABASE_PATH
from strategies.option_contract_resolver import OptionContractResolver

IST = timezone(timedelta(hours=5, minutes=30))
CASES = (
    (1741248360, 1741232700, "LONG"),
    (1744863300, 1744861500, "LONG"),
)


def ist(ts: int) -> str:
    return datetime.fromtimestamp(ts, tz=IST).isoformat()


def main() -> None:
    resolver = OptionContractResolver(DATABASE_PATH)
    loader = FyersOptionCandleLoader(DATABASE_PATH)

    with sqlite3.connect(DATABASE_PATH) as db:
        for signal_ts, setup_ts, direction in CASES:
            print("=" * 100)
            print(f"CASE signal={signal_ts} ({ist(signal_ts)}) setup={setup_ts} ({ist(setup_ts)}) direction={direction}")

            underlying = db.execute(
                """
                SELECT timestamp, open, high, low, close
                FROM candles c
                JOIN instruments i ON i.id = c.instrument_id
                WHERE i.symbol='NSE:NIFTY50-INDEX'
                  AND c.resolution='1'
                  AND c.timestamp BETWEEN ? AND ?
                ORDER BY c.timestamp
                """,
                (signal_ts - 300, signal_ts + 300),
            ).fetchall()
            print("NIFTY candles:")
            for row in underlying:
                print(row)

            exact = db.execute(
                """
                SELECT timestamp, open, high, low, close
                FROM candles c
                JOIN instruments i ON i.id = c.instrument_id
                WHERE i.symbol='NSE:NIFTY50-INDEX'
                  AND c.resolution='1'
                  AND c.timestamp <= ?
                ORDER BY c.timestamp DESC LIMIT 1
                """,
                (signal_ts,),
            ).fetchone()
            if not exact:
                print("NO UNDERLYING CANDLE")
                continue

            underlying_price = float(exact[4])
            contract = resolver.resolve(
                underlying_price=underlying_price,
                entry_date=datetime.fromtimestamp(signal_ts, tz=IST).date(),
                direction=direction,
            )
            print(f"Resolved contract: id={contract.instrument_id} symbol={contract.symbol} expiry={contract.expiry_date} strike={contract.strike}")

            bars = loader.load(contract.instrument_id, setup_ts - 600, signal_ts + 1800)
            print(f"Option bars loaded: {len(bars)}")
            for bar in bars:
                if bar.high < max(bar.open, bar.close) or bar.low > min(bar.open, bar.close):
                    print(f"INVALID OHLC: {bar}")

            if not bars:
                continue

            from backtest.opening_breakout_v2_fill_engine import HistoricalBar, simulate_limit_fill
            hbars = [HistoricalBar(b.timestamp,b.open,b.high,b.low,b.close) for b in bars]
            signal_price = _find_option_signal_price(hbars, signal_ts)
            setup = _setup_option_candle(hbars, setup_ts)
            entry = simulate_limit_fill(
                hbars,
                start_after_timestamp=signal_ts,
                side="BUY",
                limit_price=signal_price + 1.0,
                timeout_seconds=60,
            )
            stop = entry.price - 20.0 if entry.filled else None

            print(f"Option signal price: {signal_price}")
            print(f"Setup candle: {setup}")
            print(f"Entry: {entry}")
            print(f"Derived custom LONG stop: {stop}")
            print("Nearby option candles:")
            for bar in hbars:
                if setup_ts - 120 <= bar.timestamp <= signal_ts + 300:
                    print(bar)


if __name__ == "__main__":
    main()
