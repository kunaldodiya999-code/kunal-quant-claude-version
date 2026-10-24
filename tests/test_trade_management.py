"""Trade management: settings, TSL on option or spot chart, 2R partial, manual stop, snapshots, restart."""

import csv
import json
from datetime import datetime
from zoneinfo import ZoneInfo

import pytest

from backtest.option_trade_lifecycle import OptionExitReason
from market_data.resampling import Candle
from paper_trading.buyer_lifecycle import BuyerLifecycleConfig, BuyerOptionTradeLifecycle
from paper_trading.engine import PaperStrategyId, PaperTradingEngine
from paper_trading.exit_manager import ExitManager, trade_id_of
from paper_trading.recorder import PaperTradeRecorder
from paper_trading.trade_management import (
    TradeManagementSettings, TradeManagementStore, TslTracker, session_bars,
)
from paper_trading.tsl_shadow_lab import TslShadowLab

IST = ZoneInfo("Asia/Kolkata")
A = PaperStrategyId.STRATEGY_A
CE, PE = "NSE:NIFTY2610024500CE", "NSE:NIFTY2610024500PE"


def at(h, m):
    return int(datetime(2026, 10, 26, h, m, tzinfo=IST).timestamp())


def minute(h, m, o, hi, lo, c):
    return Candle(at(h, m), o, hi, lo, c, None)


# --------------------------------------------------------------------------- settings

def test_defaults_are_the_owner_brief():
    s = TradeManagementSettings()
    assert (s.initial_sl_pct, s.tsl_enabled, s.tsl_mode, s.tsl_method) == (30.0, True, "INDICATOR", "CHANDELIER_9_1.5")
    assert (s.tsl_source, s.tsl_timeframe, s.tsl_trigger) == ("OPTION", "STRATEGY", "CLOSE")
    assert (s.partial_enabled, s.partial_r, s.partial_pct, s.one_lot_at_target, s.after_partial) == (
        True, 2.0, 50.0, "CLOSE_ALL", "BREAKEVEN")
    assert (s.forced_exit_enabled, s.allocation_basis, s.daily_loss_cutoff_enabled) == (True, "AVAILABLE_CASH", False)
    assert s.method() == ("CHANDELIER", {"length": 9, "mult": 1.5, "use_close": True})
    assert s.timeframe_minutes(5) == 5 and TradeManagementSettings(tsl_timeframe="1").timeframe_minutes(5) == 1


@pytest.mark.parametrize("bad", [{"tsl_source": "FUTURES"}, {"tsl_method": "DONCHIAN"}, {"initial_sl_pct": 0},
                                 {"partial_pct": 100}, {"tsl_trigger": "SOMETIMES"}, {"tsl_enabled": "yes"}])
def test_bad_settings_are_refused(bad):
    with pytest.raises(ValueError):
        TradeManagementSettings(**bad)


def test_store_saves_every_number_and_picks_up_dashboard_changes(tmp_path):
    store = TradeManagementStore(tmp_path)
    store.update(tsl_method="SUPERTREND_7_1.5", tsl_source="SPOT",
                 method_params={"SUPERTREND_7_1.5": {"factor": 2.0}})
    again = TradeManagementStore(tmp_path).settings
    assert again.method() == ("SUPERTREND", {"atr_length": 7, "factor": 2.0}) and again.tsl_source == "SPOT"
    other = TradeManagementStore(tmp_path)
    store.update(partial_r=3.0)
    import os, time
    os.utime(store.path, (time.time() + 5, time.time() + 5))
    assert other.refresh().partial_r == 3.0


# --------------------------------------------------------------------------- candles

def test_one_minute_candles_become_tsl_candles_even_with_a_missing_minute():
    minutes = [minute(9, 15, 10, 11, 9, 10.5), minute(9, 16, 10.5, 12, 10, 11), minute(9, 18, 11, 13, 10.5, 12.5),
               minute(9, 19, 12.5, 12.6, 11, 11.2)]
    bars = session_bars(minutes, 3)
    assert [(b.timestamp, b.open, b.high, b.low, b.close) for b in bars] == [(at(9, 15), 10, 12, 9, 11)]
    assert len(session_bars(minutes, 3, now=at(9, 21))) == 2                  # second candle finished by the clock


# --------------------------------------------------------------------------- the trail

POINTS = TradeManagementSettings(tsl_method="POINTS_10_15", tsl_timeframe="1")


def bars(rows, start=(9, 30)):
    h, m = start
    return [minute(h, m + i, *row) for i, row in enumerate(rows)]


def test_close_trigger_waits_for_the_close_and_never_looks_ahead():
    t = TslTracker(trade_id="x", settings=POINTS, side="LONG", entry_timestamp=at(9, 30), entry_price=100, timeframe=1)
    path = bars([(100, 101, 99, 100), (100, 126, 99, 125), (125, 126, 112, 116), (116, 117, 100, 110)])
    assert t.on_bars(path[:2]) is None and t.stop == 115           # 125 close: +25, stop = 115
    assert t.on_bars(path[:3]) is None                              # low 112 touched, but closed 116 above 115
    hit = t.on_bars(path)
    assert (hit.reason, hit.option_price, hit.timestamp) == ("TSL_CLOSE", 110, at(9, 34))


def test_touch_trigger_fills_at_the_stop_or_at_a_gap_open():
    touch = TradeManagementSettings(tsl_method="POINTS_10_15", tsl_timeframe="1", tsl_trigger="TOUCH")
    t = TslTracker(trade_id="x", settings=touch, side="LONG", entry_timestamp=at(9, 30), entry_price=100, timeframe=1)
    hit = t.on_bars(bars([(100, 101, 99, 100), (100, 126, 99, 125), (125, 126, 112, 116)]))
    assert (hit.reason, hit.option_price) == ("TSL_TOUCH", 115)
    g = TslTracker(trade_id="y", settings=touch, side="LONG", entry_timestamp=at(9, 30), entry_price=100, timeframe=1)
    assert g.on_bars(bars([(100, 101, 99, 100), (100, 126, 99, 125), (105, 106, 100, 101)])).option_price == 105


def test_stop_only_tightens_and_spot_put_trades_trail_from_above():
    t = TslTracker(trade_id="x", settings=POINTS, side="SHORT", entry_timestamp=at(9, 30), entry_price=24000,
                   timeframe=1)
    t.on_bars(bars([(24000, 24001, 23970, 23975)]))
    assert t.stop == 23985                                          # min(23975 + 10, 24000 - 15)
    t.on_bars(bars([(24000, 24001, 23970, 23975), (23975, 23982, 23974, 23980)]))
    assert t.stop == 23985                                          # looser 23990 ignored
    hit = t.on_bars(bars([(24000, 24001, 23970, 23975), (23975, 23982, 23974, 23980), (23980, 23995, 23979, 23990)]))
    assert hit.reason == "TSL_CLOSE" and hit.source_price == 23990  # index closed above the stop


def test_manual_mode_uses_the_owners_stop():
    manual = TradeManagementSettings(tsl_mode="MANUAL", tsl_timeframe="1")
    t = TslTracker(trade_id="x", settings=manual, side="LONG", entry_timestamp=at(9, 30), entry_price=100, timeframe=1)
    assert t.on_bars(bars([(100, 101, 90, 95)])) is None            # no manual stop yet
    t.manual_stop = 97
    hit = t.on_bars(bars([(100, 101, 90, 95), (95, 99, 94, 96)]))
    assert hit.reason == "MANUAL_STOP" and hit.option_price == 96


# --------------------------------------------------------------------------- lifecycle (2R partial)

def lifecycle(**kw):
    return BuyerOptionTradeLifecycle(BuyerLifecycleConfig(allocation=40_000, lot_size=50, target_rr=2.0, **kw))


@pytest.mark.parametrize("lots, booked", [(4, 2), (3, 2), (2, 1)])
def test_partial_books_half_the_lots_at_2r(lots, booked):
    assert BuyerOptionTradeLifecycle.calculate_partial_exit_lots(lots, 0.5) == (booked, lots - booked)


def test_two_r_example_and_stop_to_breakeven_after_the_partial():
    lc = lifecycle()
    pos = lc.create_position(strategy_id="A", direction="LONG", symbol=CE, entry_price=100.0)
    assert (pos.stop_loss, pos.target, pos.lots) == (70.0, 160.0, 8)          # 100 - 30% ; 100 + 2 x 30
    exits = lc.process_candle(position=pos, timestamp=1, option_high=161, option_low=99, option_close=150,
                              underlying_close=0, kama_value=None)
    assert exits[0].lots == 4 and pos.remaining_lots == 4 and pos.stop_loss == 100.0


@pytest.mark.parametrize("policy, stop", [("LOCK_1R", 130.0), ("KEEP", 70.0)])
def test_after_partial_policies(policy, stop):
    lc = lifecycle(after_partial=policy)
    pos = lc.create_position(strategy_id="A", direction="LONG", symbol=CE, entry_price=100.0)
    lc.process_candle(position=pos, timestamp=1, option_high=161, option_low=99, option_close=150,
                      underlying_close=0, kama_value=None)
    assert pos.stop_loss == stop


def test_one_lot_closes_in_full_at_2r_and_settings_are_snapshotted():
    lc = BuyerOptionTradeLifecycle(BuyerLifecycleConfig(allocation=6_000, lot_size=50, target_rr=2.0))
    pos = lc.create_position(strategy_id="A", direction="LONG", symbol=CE, entry_price=100.0)
    from dataclasses import replace
    lc.config = replace(lc.config, target_enabled=False)                       # a later change ...
    exits = lc.process_candle(position=pos, timestamp=1, option_high=161, option_low=99, option_close=150,
                              underlying_close=0, kama_value=None)
    assert pos.lots == 1 and exits[0].quantity == 50 and pos.closed          # ... does not touch this trade


# --------------------------------------------------------------------------- the live exit manager

def make(tmp_path, **settings):
    engine = PaperTradingEngine(recorder=PaperTradeRecorder(tmp_path),
                                lifecycle=BuyerOptionTradeLifecycle(BuyerLifecycleConfig(allocation=40_000, lot_size=50)))
    store = TradeManagementStore(tmp_path)
    if settings:
        store.update(**settings)
    manager = ExitManager(engine, TslShadowLab(tmp_path / "tsl_shadow"), store=store, journal_dir=tmp_path,
                          strategy_timeframe=lambda: 1)
    return engine, manager


def events(tmp_path):
    with (tmp_path / "exit_events.csv").open(newline="", encoding="utf-8") as h:
        return list(csv.DictReader(h))


def test_option_chart_tsl_closes_the_trade_and_logs_why(tmp_path):
    engine, manager = make(tmp_path, tsl_method="POINTS_10_15", tsl_timeframe="1", partial_enabled=False)
    engine.open_position(strategy_id=A, direction="LONG", symbol=CE, entry_price=100.0, timestamp=at(9, 30))
    for c in bars([(100, 101, 99, 100), (100, 126, 99, 125), (125, 126, 112, 116), (116, 117, 100, 110)], start=(9, 30)):
        manager.on_option_candle(symbol=CE, candle=c)
    trade = engine.trades(A)[0]
    assert trade.closed and trade.exits[-1].price == 110 and trade.exits[-1].reason == OptionExitReason.STOP_LOSS
    tsl = [e for e in events(tmp_path) if e["event_type"] == "TSL_EXIT"][0]
    assert "Point trail" in tsl["detail"] and "OPTION chart" in tsl["detail"]
    assert any(e["event_type"] == "TRADE_SETTINGS" for e in events(tmp_path))


def test_spot_chart_tsl_sells_the_put_at_its_latest_price(tmp_path):
    engine, manager = make(tmp_path, tsl_method="POINTS_10_15", tsl_timeframe="1", tsl_source="SPOT")
    manager.on_spot_minutes("NSE:NIFTY50-INDEX", [minute(9, 29, 24010, 24012, 23999, 24000)])
    engine.open_position(strategy_id=A, direction="SHORT", symbol=PE, entry_price=100.0, timestamp=at(9, 30))
    manager.on_option_candle(symbol=PE, candle=minute(9, 30, 100, 112, 99, 110))
    manager.on_spot_minutes("NSE:NIFTY50-INDEX", [minute(9, 30, 24000, 24001, 23970, 23975)])
    manager.on_option_candle(symbol=PE, candle=minute(9, 31, 110, 111, 103, 104))
    decisions = manager.on_spot_minutes("NSE:NIFTY50-INDEX", [minute(9, 31, 23975, 23995, 23974, 23990)])
    assert decisions and decisions[0].price == 104                          # the put's latest close
    view_side = json.loads((tmp_path / "trade_management_state.json").read_text())
    assert list(view_side.values())[0]["side"] == "SHORT"                     # PUT on the spot chart


def test_tsl_off_leaves_only_initial_stop_and_partial(tmp_path):
    engine, manager = make(tmp_path, tsl_enabled=False, tsl_method="POINTS_10_15", tsl_timeframe="1")
    engine.open_position(strategy_id=A, direction="LONG", symbol=CE, entry_price=100.0, timestamp=at(9, 30))
    for c in bars([(100, 101, 99, 100), (100, 126, 99, 125), (125, 126, 112, 116), (116, 117, 100, 110)]):
        manager.on_option_candle(symbol=CE, candle=c)
    assert not engine.trades(A)[0].closed


def test_manual_stop_from_the_dashboard(tmp_path):
    engine, manager = make(tmp_path, tsl_mode="MANUAL", tsl_timeframe="1")
    engine.open_position(strategy_id=A, direction="LONG", symbol=CE, entry_price=100.0, timestamp=at(9, 30))
    manager.on_option_candle(symbol=CE, candle=minute(9, 30, 100, 104, 99, 103))
    manager.set_manual_stop(trade_id_of(engine.open_trade(A)), 101.5)
    manager.on_option_candle(symbol=CE, candle=minute(9, 31, 103, 104, 100, 101))
    assert engine.trades(A)[0].exits[-1].price == 101


def test_open_trade_keeps_its_settings_through_a_change_and_a_restart(tmp_path):
    engine, manager = make(tmp_path, tsl_method="POINTS_10_15", tsl_timeframe="1", partial_enabled=False)
    engine.open_position(strategy_id=A, direction="LONG", symbol=CE, entry_price=100.0, timestamp=at(9, 30))
    manager.on_option_candle(symbol=CE, candle=minute(9, 30, 100, 126, 99, 125))
    manager.store.update(tsl_method="PSAR_0.04_0.04_0.10")                    # applies to NEW trades only
    restored = ExitManager(engine, None, store=TradeManagementStore(tmp_path), journal_dir=tmp_path,
                           strategy_timeframe=lambda: 1)
    restored.enroll_open_trades()
    tracker = restored.trackers[trade_id_of(engine.open_trade(A))]
    assert tracker.kind == "POINTS" and tracker.stop == 115                  # same rule, same ratcheted stop


def test_every_method_is_compared_on_every_trade(tmp_path):
    engine, manager = make(tmp_path, tsl_timeframe="1", partial_enabled=False)
    engine.open_position(strategy_id=A, direction="LONG", symbol=CE, entry_price=100.0, timestamp=at(9, 30))
    for i in range(20):
        manager.on_option_candle(symbol=CE, candle=minute(9, 30 + i, 100 + i, 102 + i, 99 + i, 101 + i))
    manager.finish_comparison(at(15, 10))
    with (tmp_path / "tsl_shadow" / "tsl_shadow_summary.csv").open(newline="", encoding="utf-8") as h:
        rows = list(csv.DictReader(h))
    assert len(rows) == 6 and {r["source"] for r in rows} == {"OPTION"}
    assert any("Chandelier" in r["method"] for r in rows) and all(r["gross_pnl"] for r in rows)
