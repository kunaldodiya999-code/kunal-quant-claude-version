"""Exit plan shared by every strategy: Reward 1:[box] (empty = TSL exit) and the TSL methods."""

import json
from datetime import datetime
from zoneinfo import ZoneInfo

import pytest

from backtest.option_trade_lifecycle import OptionExitReason, OptionTradeDirection
from paper_trading.buyer_lifecycle import BuyerLifecycleConfig, BuyerOptionTradeLifecycle
from paper_trading.exit_manager import lifecycle_config
from paper_trading.trade_management import TradeManagementSettings
from strategies.exit_plan import ExitPlan, parse_rr
from strategies.gap_reversal import (
    Bar, GapReversalSettings, GapReversalStore, SideSettings, flip, scan_bars, simulate,
)
from tests.test_gap_reversal import hcl_like_day

IST = ZoneInfo("Asia/Kolkata")


def clock(epoch):
    return datetime.fromtimestamp(epoch, IST).strftime("%H:%M")


def day_with_bounce():
    """The HCL-like gap-up reversal, then a fall to 100 and a bounce back to 104 (a TSL must close it)."""
    bars, minutes = hcl_like_day()
    more = [(101.2, 101.5, 100.4, 100.6, 700), (100.6, 101.0, 100.0, 100.3, 600), (100.3, 102.0, 100.2, 101.9, 900),
            (101.9, 103.2, 101.8, 103.0, 900), (103.0, 104.0, 102.8, 103.8, 800), (103.8, 104.1, 103.5, 104.0, 500)]
    for row in more:
        b = Bar(bars[-1].timestamp + 300, *row)
        bars.append(b)
        path = [b.open, b.high, b.low, b.close] if b.close < b.open else [b.open, b.low, b.high, b.close]
        pts = [path[0], path[1], path[2], path[3], b.close]
        for j in range(5):
            a, c = pts[j], pts[min(j + 1, 4)]
            minutes.append(Bar(b.timestamp + 60 * j, a, max(a, c), min(a, c), c, b.volume / 5))
    return bars, minutes


def first_candidate(bars, prev_close=100.0, s=GapReversalSettings()):
    return next(c for c in scan_bars("X", prev_close, bars, s) if c.qualifies)


@pytest.mark.parametrize("text, value", [(None, None), ("", None), ("  ", None), ("2", 2.0), ("1:2.5", 2.5),
                                         ("1,5", 1.5), (3, 3.0), (1.75, 1.75)])
def test_reward_box_accepts_any_number_or_empty(text, value):
    assert parse_rr(text) == value


def test_empty_box_needs_a_tsl_and_zero_is_refused():
    with pytest.raises(ValueError):
        ExitPlan(target_rr=None, tsl_method="NONE")
    with pytest.raises(ValueError):
        ExitPlan(target_rr=0)
    with pytest.raises(ValueError):
        ExitPlan(tsl_method="DONCHIAN")
    assert ExitPlan(target_rr=None).describe().startswith("no fixed target, TSL Chandelier")


@pytest.mark.parametrize("method", ["CHANDELIER_9_1.5", "SUPERTREND_5_1.0", "SUPERTREND_7_1.5"])
def test_empty_box_exits_when_a_candle_closes_beyond_the_tsl(method):
    bars, minutes = day_with_bounce()
    s = GapReversalSettings()
    trade = simulate(first_candidate(bars), bars, minutes, s, plan=ExitPlan(target_rr=None, tsl_method=method))
    # entry 108.6 at 09:45 (stop 110); the up-trend TSL values before the reversal do not stop it out at once;
    # the 10:20 candle closes at 103.0 above the falling TSL -> out at that close, known at 10:25
    assert (trade.result, trade.exit, clock(trade.exit_time)) == ("TSL", 103.0, "10:25")
    assert trade.rr is None and trade.target is None and trade.r_multiple == pytest.approx(4.0)
    assert trade.max_favourable_r == pytest.approx((108.6 - 100.0) / 1.4, abs=0.01)


def test_slow_psar_keeps_the_trade_and_touch_trigger_exits_inside_the_candle():
    bars, minutes = day_with_bounce()
    s = GapReversalSettings()
    slow = simulate(first_candidate(bars), bars, minutes, s, plan=ExitPlan(None, "PSAR_0.02_0.02_0.20"))
    assert slow.result == "TIME"                     # the SAR (105.5) was never reached by the bounce
    touch = simulate(first_candidate(bars), bars, minutes, s, plan=ExitPlan(None, "SUPERTREND_5_1.0", "TOUCH"))
    close = simulate(first_candidate(bars), bars, minutes, s, plan=ExitPlan(None, "SUPERTREND_5_1.0", "CLOSE"))
    assert touch.result == "TSL" and touch.exit_time < close.exit_time


def test_target_and_tsl_together_whichever_comes_first():
    bars, minutes = day_with_bounce()
    s = GapReversalSettings()
    both = simulate(first_candidate(bars), bars, minutes, s, plan=ExitPlan(2.0, "SUPERTREND_5_1.0"))
    assert both.result == "TARGET" and both.r_multiple == pytest.approx(2.0)
    far = simulate(first_candidate(bars), bars, minutes, s, plan=ExitPlan(10.0, "SUPERTREND_5_1.0"))
    assert far.result == "TSL"


def test_long_side_tsl_is_the_mirror():
    bars, minutes = day_with_bounce()
    up = [Bar(b.timestamp, b.open + 200, b.high + 200, b.low + 200, b.close + 200, b.volume) for b in flip(bars)]
    mins = [Bar(b.timestamp, b.open + 200, b.high + 200, b.low + 200, b.close + 200, b.volume) for b in flip(minutes)]
    s = GapReversalSettings()
    long_c = first_candidate(up, prev_close=103.6)
    short_t = simulate(first_candidate(bars), bars, minutes, s, plan=ExitPlan(None, "SUPERTREND_5_1.0"))
    long_t = simulate(long_c, up, mins, s, plan=ExitPlan(None, "SUPERTREND_5_1.0"))
    assert long_c.side == "LONG" and long_t.result == "TSL"
    assert long_t.r_multiple == pytest.approx(short_t.r_multiple) and long_t.exit_time == short_t.exit_time


def test_side_settings_keep_the_box_and_old_files_still_load(tmp_path):
    store = GapReversalStore(tmp_path)
    store.update(short={"target_rr": None, "tsl_method": "PSAR_0.04_0.04_0.10"}, long={"target_rr": "1:2.5"})
    again = GapReversalStore(tmp_path).settings
    assert again.short.target_rr is None and again.short.exit_plan().uses_tsl
    assert again.long.target_rr == 2.5 and again.long.tsl_method == "NONE"
    (tmp_path / "settings.json").write_text(json.dumps({"short": {"target_rr": 3.0}}), encoding="utf-8")
    assert GapReversalStore(tmp_path).settings.short.exit_plan().target_rr == 3.0
    with pytest.raises(ValueError):
        SideSettings(target_rr=None)                  # empty box without a TSL


def test_ktmi_reward_box_closes_the_whole_trade_at_the_target():
    filled = TradeManagementSettings(exit_target_rr="2.5")
    cfg = lifecycle_config(BuyerLifecycleConfig(lot_size=65, allocation=100_000), filled)
    assert cfg.close_all_at_target and cfg.target_rr == 2.5 and cfg.target_enabled
    life = BuyerOptionTradeLifecycle(cfg)
    pos = life.create_position(strategy_id="X", direction=OptionTradeDirection.LONG, symbol="NSE:X", entry_price=100.0)
    assert pos.lots >= 3 and pos.target == pytest.approx(175.0)          # 30% stop -> risk 30 x 2.5
    (out,) = life.process_candle(position=pos, timestamp=1, option_high=176, option_low=101, option_close=170,
                                 underlying_close=1.0, kama_value=None)
    assert out.reason == OptionExitReason.TARGET_3R and pos.closed and out.lots == pos.lots
    empty = lifecycle_config(BuyerLifecycleConfig(), TradeManagementSettings())
    assert not empty.close_all_at_target and empty.target_rr == 2.0           # partial at 2R, then TSL (unchanged)
    with pytest.raises(ValueError):
        TradeManagementSettings(exit_target_rr=None, tsl_enabled=False, partial_enabled=False)


def test_backtest_runs_every_exit_plan_with_50000_per_entry():
    from research.gap_reversal_backtest import run_symbol, summarize
    bars, minutes = day_with_bounce()
    prev = [Bar(m.timestamp - 86400, 100.0, 100.1, 99.9, 100.0, 100) for m in minutes]   # yesterday closed at 100
    s = GapReversalSettings()
    _cands, trades = run_symbol("X", prev + minutes, s)
    labels = {t["exit"] for t in trades}
    assert labels == {"1:1.5", "1:2", "1:2.5", "1:3", "TSL CHANDELIER_9_1.5", "TSL SUPERTREND_5_1.0",
                      "TSL SUPERTREND_7_1.5", "TSL PSAR_0.02_0.02_0.20", "TSL PSAR_0.04_0.04_0.10", "TSL POINTS_10_15"}
    st = next(t for t in trades if t["exit"] == "TSL SUPERTREND_5_1.0" and t["entry_mode"] == "BREAK")
    assert st["result"] == "TSL" and st["quantity"] == int(50_000 // 108.6)
    assert st["gross_pnl"] == pytest.approx((108.6 - 103.0) * st["quantity"], abs=0.01)
    assert 0 < st["charges"] < 100 and st["net_pnl"] == pytest.approx(st["gross_pnl"] - st["charges"], abs=0.01)
    rows = summarize(trades)
    both = [r for r in rows if r["group"] == "ALL" and r["side"] == "BOTH"]
    assert len(both) == 20 and all(r["trades"] == 1 for r in both)
    assert {r["exit_plan"] for r in both} >= {"Fixed target 1:2", "TSL only: Supertrend A - ATR 5 x 1.0"}
