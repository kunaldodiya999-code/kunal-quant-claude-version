"""Owner settings: timeframes, Long/Short/Both, entry window, enter on candle close."""

import json
from dataclasses import replace
from datetime import date, datetime
from zoneinfo import ZoneInfo

import pytest

from market_data.resampling import Candle, aggregate_day
from paper_trading.buyer_lifecycle import BuyerLifecycleConfig, BuyerOptionTradeLifecycle
from paper_trading.coordinator import PaperExecutionCoordinator
from paper_trading.engine import PaperStrategyId, PaperTradingEngine
from paper_trading.entry_adapter import PaperEntryAdapter
from paper_trading.market_data_pipeline import (
    SUPPORTED_RESOLUTIONS,
    PaperMarketDataPipeline,
    bar_close_timestamp,
)
from paper_trading.session import PaperSessionConfig, build_paper_session
from paper_trading.signals import PaperSignal
from paper_trading.strategy_settings import StrategySettings, StrategySettingsStore
from scripts.paper_settings import main as settings_command
from strategies.option_contract_resolver import ResolvedOptionContract

IST = ZoneInfo("Asia/Kolkata")


def ts(hour, minute, day=12):
    return int(datetime(2026, 10, day, hour, minute, tzinfo=IST).timestamp())


def full_day():
    return [Candle(ts(9, 15) + 60 * i, 100, 101, 99, 100) for i in range(375)]  # 09:15 .. 15:29


# ------------------------------------------------------------------ timeframes

def test_all_owner_timeframes_are_supported():
    assert SUPPORTED_RESOLUTIONS == (1, 3, 5, 10, 15, 30, 60)


@pytest.mark.parametrize(
    "minutes, bars_per_day, last_start, last_size",
    [
        (3, 125, (15, 27), 3),
        (5, 75, (15, 25), 5),
        (10, 38, (15, 25), 5),    # last bar 15:25-15:29, like TradingView
        (15, 25, (15, 15), 15),
        (30, 13, (15, 15), 15),
        (60, 7, (15, 15), 15),    # 09:15, 10:15, ... 14:15, 15:15
    ],
)
def test_bars_start_at_0915_and_keep_the_shorter_last_bar(minutes, bars_per_day, last_start, last_size):
    bars = aggregate_day(full_day(), minutes)
    assert len(bars) == bars_per_day
    assert bars[0].timestamp == ts(9, 15)
    assert all(bar.complete for bar in bars)
    assert bars[-1].timestamp == ts(*last_start)
    assert bars[-1].actual_1m_candles == last_size


def test_bar_with_a_missing_minute_is_not_complete():
    candles = [c for c in full_day() if c.timestamp != ts(9, 20)]
    assert not aggregate_day(candles, 15)[0].complete


def test_bar_close_times():
    assert bar_close_timestamp(ts(9, 27), 3) == ts(9, 30)
    assert bar_close_timestamp(ts(9, 15), 60) == ts(10, 15)
    assert bar_close_timestamp(ts(15, 15), 60) == ts(15, 30)   # shorter last bar
    assert bar_close_timestamp(ts(15, 25), 10) == ts(15, 30)


def tick(timestamp, ltp):
    return {"symbol": "NSE:NIFTY50-INDEX", "last_traded_time": timestamp + 5, "ltp": ltp, "type": "sf"}


def test_pipeline_signal_carries_the_candle_close_and_only_after_close():
    seen = []

    def evaluator(bars, *, paper_config):
        seen.append(bars[-1].timestamp)
        return [PaperSignal(PaperStrategyId.STRATEGY_A, "LONG", bars[-1].timestamp, len(bars) - 1, "TEST")]

    pipeline = PaperMarketDataPipeline(resolution_minutes=15, signal_evaluator=evaluator)
    for minute in range(15):
        assert pipeline.on_message(tick(ts(9, 15) + 60 * minute, 100)) == []
    assert seen == []                     # 15-minute bar still forming: nothing evaluated
    signals = pipeline.on_message(tick(ts(9, 30), 100))
    assert seen == [ts(9, 15)]
    assert signals[0].close_timestamp == ts(9, 30)


# ------------------------------------------------------- coordinator rules

class Resolver:
    def resolve(self, *, underlying_price, entry_date, direction):
        typ = "CE" if direction == "LONG" else "PE"
        return ResolvedOptionContract(1, f"NSE:NIFTY2610025000{typ}", "NIFTY", date(2026, 10, 27), 25000, typ)


def coordinator(direction="BOTH"):
    engine = PaperTradingEngine(
        lifecycle=BuyerOptionTradeLifecycle(BuyerLifecycleConfig(allocation=15000, lot_size=25, stop_loss_pct=0.30))
    )
    return PaperExecutionCoordinator(adapter=PaperEntryAdapter(Resolver()), engine=engine, trade_direction=direction)


def attempt(coord, direction, *, decision, bar=ts(10, 0), close=ts(10, 3)):
    typ = "CE" if direction == "LONG" else "PE"
    signal = PaperSignal(PaperStrategyId.STRATEGY_A, direction, bar, 20, "UNI_LITE", close_timestamp=close)
    return coord.process_signal(
        signal=signal, underlying_price=25000,
        option_quote={"symbol": f"NSE:NIFTY2610025000{typ}", "lp": 100, "exch_feed_time": decision},
        decision_timestamp=decision,
    )


def test_no_entry_before_the_signal_candle_closes():
    result = attempt(coordinator(), "LONG", decision=ts(10, 2))   # 3m bar 10:00 closes 10:03
    assert result.trade is None
    assert "not closed" in result.rejection_reason


def test_entry_allowed_once_the_candle_has_closed():
    result = attempt(coordinator(), "LONG", decision=ts(10, 3))
    assert result.rejection_reason is None
    assert result.trade.position.symbol.endswith("CE")


@pytest.mark.parametrize(
    "setting, direction, allowed",
    [
        ("BOTH", "LONG", True), ("BOTH", "SHORT", True),
        ("LONG", "LONG", True), ("LONG", "SHORT", False),
        ("SHORT", "SHORT", True), ("SHORT", "LONG", False),
    ],
)
def test_long_short_both_switch(setting, direction, allowed):
    result = attempt(coordinator(setting), direction, decision=ts(10, 3))
    assert (result.trade is not None) == allowed
    if not allowed:
        assert "switched off" in result.rejection_reason


def test_unknown_direction_is_refused():
    with pytest.raises(ValueError):
        coordinator("SIDEWAYS")


# ------------------------------------------------------------ settings file

def test_defaults_match_owner_choices():
    s = StrategySettings()
    assert (s.timeframe_minutes, s.trade_direction, s.entry_start, s.entry_end, s.force_exit) == (
        3, "BOTH", "09:30", "15:00", "15:10")


@pytest.mark.parametrize(
    "bad",
    [
        {"timeframe_minutes": 7},
        {"trade_direction": "UP"},
        {"entry_start": "15:30"},           # after the end time
        {"entry_start": "9.30"},             # not HH:MM
        {"force_exit": "14:00"},             # before the entry end
    ],
)
def test_invalid_settings_are_refused(bad):
    with pytest.raises(ValueError):
        replace(StrategySettings(), **bad)


def test_saved_settings_survive_a_restart(tmp_path):
    StrategySettingsStore(StrategySettings(), tmp_path).update(timeframe_minutes=5, trade_direction="LONG")
    again = StrategySettingsStore(StrategySettings(), tmp_path).settings
    assert (again.timeframe_minutes, again.trade_direction) == (5, "LONG")


def test_broken_settings_file_gives_a_clear_error(tmp_path):
    (tmp_path / "strategy_settings.json").write_text('{"timeframe_minutes": 7}')
    with pytest.raises(ValueError, match="fix or delete"):
        StrategySettingsStore(StrategySettings(), tmp_path)


def test_session_uses_the_saved_settings(tmp_path):
    (tmp_path / "strategy_settings.json").write_text(
        json.dumps({"timeframe_minutes": 15, "trade_direction": "SHORT", "entry_start": "09:45"})
    )
    session = build_paper_session(
        client=object(),
        config=PaperSessionConfig(lot_size=65, output_dir=tmp_path, pending_journal_path=tmp_path / "p.csv"),
        resolver=object(),
        socket_factory=lambda **kwargs: None,
    )
    assert session.pipeline.resolution_minutes == 15
    assert session.coordinator.trade_direction == "SHORT"
    assert session.controls.entry_block_reason(ts(9, 40)).startswith("Before entry window")
    assert session.controls.entry_block_reason(ts(9, 45)) is None


def test_settings_command_saves_and_rejects(tmp_path, capsys):
    assert settings_command(["--folder", str(tmp_path), "--index", "NIFTY", "--timeframe", "60",
                             "--direction", "short"]) == 0
    assert "60 minute candles" in capsys.readouterr().out
    assert settings_command(["--folder", str(tmp_path), "--index", "NIFTY", "--start", "15:20"]) == 1
    assert "NOT SAVED" in capsys.readouterr().out
    saved = json.loads((tmp_path / "NIFTY" / "strategy_settings.json").read_text())
    assert saved["timeframe_minutes"] == 60 and saved["entry_start"] == "09:30"
    assert not (tmp_path / "SENSEX" / "strategy_settings.json").exists()   # other indexes untouched


def test_settings_command_all_indexes_and_old_file(tmp_path, capsys):
    (tmp_path / "strategy_settings.json").write_text(json.dumps({"timeframe_minutes": 5}))
    assert settings_command(["--folder", str(tmp_path), "--direction", "LONG"]) == 0   # default ALL
    out = capsys.readouterr().out
    assert "NIFTY 50" in out and "BANK NIFTY" in out and "SENSEX" in out
    for key in ("NIFTY", "BANKNIFTY", "SENSEX"):
        saved = json.loads((tmp_path / key / "strategy_settings.json").read_text())
        assert (saved["timeframe_minutes"], saved["trade_direction"]) == (5, "LONG")


# ------------------------------------------------------------ trade in (index on/off)

def test_index_switched_off_takes_no_entry_but_says_why():
    coord = coordinator()
    coord.trading_enabled = False
    result = attempt(coord, "LONG", decision=ts(10, 3))
    assert result.trade is None and "switched off for this index" in result.rejection_reason
    assert StrategySettings().trading_enabled is True
    with pytest.raises(ValueError):
        replace(StrategySettings(), trading_enabled="yes")


def test_session_reads_trade_in_and_command_sets_it(tmp_path, capsys):
    assert settings_command(["--folder", str(tmp_path), "--index", "BANKNIFTY", "--trade", "off"]) == 0
    assert "OFF (watch only)" in capsys.readouterr().out
    session = build_paper_session(
        client=object(),
        config=PaperSessionConfig(lot_size=30, output_dir=tmp_path / "BANKNIFTY",
                                  pending_journal_path=tmp_path / "p.csv"),
        resolver=object(),
        socket_factory=lambda **kwargs: None,
    )
    assert session.coordinator.trading_enabled is False
    assert not (tmp_path / "NIFTY" / "strategy_settings.json").exists()
