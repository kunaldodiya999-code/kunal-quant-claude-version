"""The engine end to end with a pretend FYERS: cross -> limit buy, stop loss, opposite cross, CALL-only, 15:10."""

import csv
import json
import math
from datetime import timedelta

import pytest

from terminal.engine import Terminal
from terminal.indicators import bbp_nm
from terminal.settings import Settings, SettingsStore
from terminal.strategy import direction_events
from tests.fakes import FakeFyers, at, master

SPOT = "NSE:NIFTY50-INDEX"
CE = "NSE:NIFTY26N04{}CE"
PE = "NSE:NIFTY26N04{}PE"


def wave(n=80):
    return [round(25000 + 40 * math.sin(i / 3.0), 2) for i in range(n)]


def crosses(closes):
    return direction_events([d for _, _, d in bbp_nm(closes, 10)])


class Clock:
    def __init__(self, now):
        self.now = now

    def __call__(self):
        return self.now


@pytest.fixture
def setup(tmp_path):
    closes = wave()
    fake = FakeFyers(funds=50000)
    fake.add_minutes(SPOT, at(9, 15), closes)
    fake.add_minutes("NSE:NIFTY26NOVFUT", at(9, 15), [c + 50 for c in closes])
    fake.set_price(SPOT, 25000)
    for k in range(24500, 25550, 50):
        ce, pe = max(5, 120 + (25000 - k) / 2), max(5, 120 + (k - 25000) / 2)   # 25000 CE = 120, 25050 CE = 95
        fake.set_price(CE.format(k), ce)
        fake.set_price(PE.format(k), pe)
        fake.add_minutes(CE.format(k), at(9, 15), [ce] * 80)              # option candles: low = price - 1
        fake.add_minutes(PE.format(k), at(9, 15), [pe] * 80)
    store = SettingsStore(tmp_path)
    store.save(Settings(timeframe=1, premium_low=90, premium_high=130, funds_per_entry=20000))
    clock = Clock(at(9, 15))
    term = Terminal(fake, folder=tmp_path, store=store, clock=clock, chart_file=tmp_path / "chart.json",
                    master_loader=lambda name, today: master())
    return term, fake, clock, closes, store


def run_to(term, clock, minute_index, second=5):
    clock.now = at(9, 15) + timedelta(minutes=minute_index, seconds=second)
    term._next_history = 0
    term.tick()
    assert term.error == "", term.error


def test_first_look_never_trades_then_a_cross_buys_with_a_limit(setup):
    term, fake, clock, closes, _ = setup
    events = [(i, e) for i, e in crosses(closes) if i >= 16]
    i, event = events[0]
    run_to(term, clock, i)                     # bar i still forming: only remembers the sign
    assert term.position is None
    run_to(term, clock, i + 1)                 # bar i finished -> cross
    p = term.position
    assert p is not None and p.side == ("CALL" if event == "UP" else "PUT")
    # premium range 90 - 130: the cheapest inside (95 at 25050 CE / 24950 PE)
    assert p.entry_price <= 95 + 2 and p.symbol in (CE.format(25050), PE.format(24950))
    assert p.lots == 3 and p.qty == 195        # Rs 20,000 / (95 x 65) = 3 lots
    assert p.stop == 94.0                      # low of the option's own candle at the signal (95 - 1)
    chart = json.loads((term.chart_file).read_text())
    assert chart["candles"] and chart["direction"] and chart["vwap"] and chart["ktmi_long"]
    snap = term.snapshot()
    assert len(snap["chain"]) == 11 and sum(r["atm"] for r in snap["chain"]) == 1
    assert snap["utilized_pct"] == pytest.approx(p.entry_price * 195 / 50000 * 100)


def test_stop_loss_on_the_option_price_exits_with_a_limit(setup):
    term, fake, clock, closes, _ = setup
    i, _ = [(i, e) for i, e in crosses(closes) if i >= 16][0]
    run_to(term, clock, i)
    run_to(term, clock, i + 1)
    sym = term.position.symbol
    fake.set_price(sym, 93.5, bid=93.0, ask=94.0)
    clock.now += timedelta(seconds=2)
    term.tick()
    assert term.position is None
    row = list(csv.DictReader(term.trades_file.open()))[-1]
    assert row["exit_reason"].startswith("stop loss") and float(row["exit_price"]) == 93.0    # bid >= 91.5 limit


def test_opposite_cross_exits_and_enters_the_other_side(setup):
    term, fake, clock, closes, _ = setup
    ev = [(i, e) for i, e in crosses(closes) if i >= 16]
    (i1, e1), (i2, e2) = ev[0], ev[1]
    run_to(term, clock, i1)
    run_to(term, clock, i1 + 1)
    first = term.position.side
    for m in range(i1 + 2, i2 + 2):
        run_to(term, clock, m)
    assert term.position is not None and term.position.side != first
    rows = list(csv.DictReader(term.trades_file.open()))
    assert rows[-1]["side"] == first and "Direction crossed" in rows[-1]["exit_reason"]


def test_only_call_ticked_exits_the_call_without_buying_a_put(setup):
    term, fake, clock, closes, store = setup
    store.update(put_on=False)
    ev = [(i, e) for i, e in crosses(closes) if i >= 16]
    up = next(k for k, (i, e) in enumerate(ev) if e == "UP")
    (i1, _), (i2, _) = ev[up], ev[up + 1]
    run_to(term, clock, i1)
    run_to(term, clock, i1 + 1)
    assert term.position.side == "CALL"
    for m in range(i1 + 2, i2 + 2):
        run_to(term, clock, m)
    assert term.position is None
    assert list(csv.DictReader(term.trades_file.open()))[-1]["side"] == "CALL"


def test_time_exit_at_1510_and_paper_trade_saved_across_restart(setup, tmp_path):
    term, fake, clock, closes, store = setup
    i, _ = [(i, e) for i, e in crosses(closes) if i >= 16][0]
    run_to(term, clock, i)
    run_to(term, clock, i + 1)
    again = Terminal(fake, folder=tmp_path, store=store, clock=clock, chart_file=tmp_path / "c.json",
                     master_loader=lambda n, d: master())
    assert again.position == term.position     # state.json keeps the open trade
    clock.now = at(15, 10, 1)
    again.tick()
    assert again.position is None
    assert list(csv.DictReader(again.trades_file.open()))[-1]["exit_reason"] == "time exit 15:10"


def test_no_trade_reasons_are_logged(setup):
    term, fake, clock, closes, store = setup
    store.update(funds_per_entry=1000)
    i, _ = [(i, e) for i, e in crosses(closes) if i >= 16][0]
    run_to(term, clock, i)
    run_to(term, clock, i + 1)
    assert term.position is None
    assert any("does not buy one lot" in e for e in term.events)


def test_real_orders_setting_without_the_daily_arm_stays_paper(setup):
    term, fake, clock, closes, store = setup
    store.update(real_orders=True)
    i, _ = [(i, e) for i, e in crosses(closes) if i >= 16][0]
    run_to(term, clock, i)
    run_to(term, clock, i + 1)
    assert term.position.mode == "PAPER"
    assert any("not armed" in e for e in term.events)
