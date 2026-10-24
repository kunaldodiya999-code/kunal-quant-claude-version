"""End-to-end test of scripts/run_opening_breakout_v2_backtest.py on a
synthetic database created with the real canonical schema."""

import csv
import json
import sqlite3
from datetime import datetime
from zoneinfo import ZoneInfo

import pytest

from database.schema import initialize_database
from scripts.run_opening_breakout_v2_backtest import main, run, build_parser

IST = ZoneInfo("Asia/Kolkata")
STEP = 0.5  # underlying points per minute


def _session(day: int, direction: int):
    """375 one-minute bars; direction +1 trends up from an OPEN=LOW candle,
    -1 trends down from an OPEN=HIGH candle."""
    start = int(datetime(2026, 9, day, 9, 15, tzinfo=IST).timestamp())
    bars = []
    price = 25000.0
    for minute in range(375):
        open_price = price
        close = open_price + STEP * direction
        high = max(open_price, close) + 0.2
        low = min(open_price, close) - 0.2
        if minute == 0:
            if direction > 0:
                low = open_price
            else:
                high = open_price
        bars.append((start + 60 * minute, open_price, high, low, close))
        price = close
    return bars


def _premium(underlying: float, option_type: str) -> float:
    move = underlying - 25000.0
    return max(5.0, 100.0 + (move if option_type == "CE" else -move) * 0.5)


@pytest.fixture()
def database(tmp_path):
    path = tmp_path / "kq.db"
    initialize_database(path)
    with sqlite3.connect(path) as db:
        db.execute(
            "INSERT INTO instruments (broker, exchange, segment, symbol, underlying, instrument_type) "
            "VALUES ('FYERS','NSE','INDEX','NSE:NIFTY50-INDEX','NIFTY','INDEX')"
        )
        index_id = db.execute("SELECT id FROM instruments").fetchone()[0]
        option_ids = {}
        for option_type in ("CE", "PE"):
            cursor = db.execute(
                "INSERT INTO instruments (broker, exchange, segment, symbol, underlying, instrument_type, "
                "expiry_date, strike, option_type, lot_size) VALUES "
                "('FYERS','NSE','FNO',?, 'NIFTY','OPTION','2026-09-08',25000,?,65)",
                (f"NSE:NIFTY2690825000{option_type}", option_type),
            )
            option_ids[option_type] = cursor.lastrowid

        # 1 Sep = warm-up only, 2 Sep = up day, 3 Sep = down day.
        for day, direction in ((1, 1), (2, 1), (3, -1)):
            for ts, o, h, l, c in _session(day, direction):
                db.execute(
                    "INSERT INTO candles (instrument_id, timestamp, open, high, low, close, volume, "
                    "resolution, source) VALUES (?,?,?,?,?,?,0,'1','FYERS')",
                    (index_id, ts, o, h, l, c),
                )
                for option_type, option_id in option_ids.items():
                    po, pc = _premium(o, option_type), _premium(c, option_type)
                    db.execute(
                        "INSERT INTO candles (instrument_id, timestamp, open, high, low, close, volume, "
                        "resolution, source) VALUES (?,?,?,?,?,?,100,'1','FYERS_FNO_HISTORY')",
                        (option_id, ts, po, max(po, pc) + 0.1, min(po, pc) - 0.1, pc),
                    )
    return path


def _args(database, out_dir, *extra):
    return [
        "--from", "2026-09-02", "--to", "2026-09-03",
        "--warmup-days", "2",
        "--database", str(database),
        "--out-dir", str(out_dir),
        "--sl-points", "10", "--rr", "2", "--risk", "2000",
        *extra,
    ]


def test_call_run_trades_only_the_window_and_writes_reports(database, tmp_path, capsys):
    out_dir = tmp_path / "call"
    main(_args(database, out_dir, "--instrument", "CALL", "--open-low"))

    summary = json.loads((out_dir / "summary.json").read_text())
    assert summary["sessions"] == 2  # warm-up day 1 Sep is never traded
    assert summary["warmup_bars"] == 375
    assert summary["signals"] == 1  # only 2 Sep has OPEN=LOW
    assert summary["closed_trades"] == 1
    assert summary["net_pnl"] == pytest.approx(summary["gross_pnl"] - summary["total_costs"])

    trades = list(csv.DictReader((out_dir / "trades.csv").open()))
    assert len(trades) == 1
    assert trades[0]["contract"].endswith("CE")
    assert trades[0]["exit_reason"] == "TARGET"
    assert float(trades[0]["gross_pnl"]) > 0
    assert (out_dir / "equity_curve.csv").exists()
    assert "reports saved to" in capsys.readouterr().out


def test_put_run_books_rising_put_premium_as_profit(database, tmp_path):
    out_dir = tmp_path / "put"
    summary = run(build_parser().parse_args(
        _args(database, out_dir, "--instrument", "PUT", "--open-high", "--triggers", "CANDLE_LOW")
    ))

    trades = list(csv.DictReader((out_dir / "trades.csv").open()))
    assert summary["closed_trades"] == 1
    assert trades[0]["contract"].endswith("PE")
    assert trades[0]["direction"] == "SHORT"
    assert float(trades[0]["stop"]) < float(trades[0]["entry_price"]) < float(trades[0]["target"])
    assert trades[0]["exit_reason"] == "TARGET"
    assert float(trades[0]["gross_pnl"]) > 0


def test_vwap_trigger_on_volumeless_index_warns_and_never_trades(database, tmp_path):
    summary = run(build_parser().parse_args(
        _args(database, tmp_path / "vwap", "--instrument", "CALL", "--triggers", "CANDLE_HIGH,ABOVE_VWAP")
    ))
    assert summary["signals"] == 0
    assert summary["indicator_coverage"]["vwap_available"] == 0
    assert any("VWAP" in warning for warning in summary["warnings"])


def test_dmi_trigger_uses_warmed_up_values(database, tmp_path):
    summary = run(build_parser().parse_args(
        _args(database, tmp_path / "dmi", "--instrument", "CALL", "--open-low", "--triggers", "CANDLE_HIGH,DMI")
    ))
    coverage = summary["indicator_coverage"]
    assert coverage["dmi_available"] == coverage["candles"]  # warm-up covered the window
    assert summary["signals"] == 1  # steady up-trend: +DI and ADX are high


def test_unknown_trigger_is_rejected(database, tmp_path):
    with pytest.raises(SystemExit):
        run(build_parser().parse_args(_args(database, tmp_path / "x", "--triggers", "MAGIC")))
