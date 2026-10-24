"""Gap Reversal daily trade cap: same rule in the live desk and the backtest."""

import pytest

from paper_trading.gap_reversal_paper import GapReversalDesk
from research.gap_reversal_backtest import apply_daily_cap, cap_study
from strategies.gap_reversal import GapReversalSettings, daily_cap
from tests.test_gap_reversal import hcl_like_day


def row(sym, side, time, strength, day="2026-10-22", mode="BREAK", ex="1:2", net=1.0):
    return {"symbol": sym, "side": side, "entry_time": time, "strength": strength, "day": day, "entry_mode": mode,
            "exit": ex, "r": net, "net_pnl": net, "gross_pnl": net, "charges": 0.0, "result": "TARGET", "best_r": 1.0}


def test_order_is_entry_time_then_strength_and_side_caps_count():
    s = GapReversalSettings(max_trades_per_day=3, max_short_per_day=1)
    rows = [row("A", "SHORT", "09:40", 70), row("B", "LONG", "09:30", 65), row("C", "SHORT", "09:30", 90),
            row("D", "LONG", "09:30", 80), row("E", "LONG", "09:50", 99)]
    taken, skipped = daily_cap(rows, s)
    assert [r["symbol"] for r in taken] == ["C", "D", "B"]          # 09:30 first, strongest first; cap 3 full
    assert {r["symbol"] for r in skipped} == {"A", "E"}             # A also hits the SHORT cap of 1
    assert daily_cap(rows, GapReversalSettings(max_trades_per_day=0))[1] == []   # 0 = no limit
    _, more = daily_cap([row("F", "LONG", "10:00", 70)], GapReversalSettings(max_trades_per_day=2),
                        taken=[row("X", "LONG", "09:20", 60), row("Y", "SHORT", "09:25", 60)])
    assert [r["symbol"] for r in more] == ["F"]                     # trades already taken today count


def test_settings_refuse_bad_caps():
    with pytest.raises(ValueError):
        GapReversalSettings(max_trades_per_day=-1)
    with pytest.raises(ValueError):
        GapReversalSettings(max_long_per_day=1.5)
    assert GapReversalSettings().max_trades_per_day == 5             # = 1,00,000 paper capital / 20% per trade


def test_backtest_applies_the_cap_per_day_across_symbols():
    rows = [row(f"S{i}", "LONG", f"09:{30 + i}", 70, net=i) for i in range(6)] + [row("Z", "LONG", "09:31", 70,
                                                                                    day="2026-10-23")]
    kept = apply_daily_cap(rows, GapReversalSettings(max_trades_per_day=2))
    assert [(r["day"], r["symbol"]) for r in kept] == [("2026-10-22", "S0"), ("2026-10-22", "S1"), ("2026-10-23", "Z")]
    study = {r["max_trades_per_day"]: r for r in cap_study(rows, GapReversalSettings(), caps=(0, 1, 3))}
    assert study["no limit"]["trades"] == 7 and study[1]["trades"] == 2 and study[3]["trades"] == 4
    assert study[1]["net_pnl"] == 0 + 1                               # S0 (net 0) and Z (net 1)


def test_live_desk_skips_trades_past_the_cap(tmp_path):
    bars, minutes = hcl_like_day()
    desk = GapReversalDesk(tmp_path, GapReversalSettings(enabled=True, max_trades_per_day=1))
    now = minutes[-1].timestamp + 60
    for sym in ("NSE:AAA-EQ", "NSE:BBB-EQ"):
        desk.set_gap(sym, 100.0, 103.5)
        desk.on_minutes(sym, minutes, now)
    status = desk.write_status(now)
    assert len(status["trades"]) == 1 and len(status["skipped"]) == 1
    assert status["skipped"][0]["status"] == "SKIPPED (daily cap)"
    assert status["daily_cap"] == {"max_trades": 1, "max_short": 0, "max_long": 0, "taken": 1}
    for sym in ("NSE:AAA-EQ", "NSE:BBB-EQ"):                          # next minute: still one trade, still skipped
        desk.on_minutes(sym, minutes, now + 60)
    again = desk.write_status(now + 60)
    assert len(again["trades"]) == 1 and len(again["skipped"]) == 1


def test_no_entry_before_entry_from_and_a_later_setup_can_still_trade():
    from datetime import datetime
    from zoneinfo import ZoneInfo
    from dataclasses import replace
    from strategies.gap_reversal import first_entry, scan_bars, simulate
    clock = lambda e: datetime.fromtimestamp(e, ZoneInfo("Asia/Kolkata")).strftime("%H:%M")   # noqa: E731
    bars, minutes = hcl_like_day()
    s = GapReversalSettings(entry_from="09:15")
    found = scan_bars("X", 100.0, bars, s)
    first = next(c for c in found if c.qualifies)
    assert clock(simulate(first, bars, minutes, s, rr=2.0).entry_time) == "09:46"
    late = replace(s, entry_from="09:50")
    t = simulate(first, bars, minutes, late, rr=2.0)
    assert clock(t.entry_time) == "09:50" and t.entry < first.trigger          # still beyond the trigger at 09:50
    assert simulate(first, bars, minutes, replace(s, entry_from="10:30"), rr=2.0) is None
    c, t2 = first_entry(found, bars, minutes, late, rr=2.0)
    assert c is not None and clock(t2.entry_time) == "09:50"
    assert first_entry(found, bars, minutes, replace(s, entry_from="10:30"), rr=2.0) == (None, None)
    assert GapReversalSettings().entry_from == "09:40"
    with pytest.raises(ValueError):
        GapReversalSettings(entry_from="15:20")                                # after the exit time
