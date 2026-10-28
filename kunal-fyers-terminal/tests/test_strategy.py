"""The owner's rules (28 Oct 2026) as tests: strike pick, lots, Direction crosses, what happens on each cross."""

import pytest

from terminal.strategy import ChainRow, direction_events, last_sign, lots_for, pick_strike, plan


def rows(*pairs):
    return [ChainRow(float(k), f"NSE:SENSEX{k}CE", p) for k, p in pairs]


def test_premium_range_takes_the_cheapest_strike_inside():
    # owner's example: 73000 CE at 195 and 72900 CE at 182 inside 180-200 -> 72900 CE
    p = pick_strike(rows((72800, 240), (72900, 182), (73000, 195), (73100, 160)), mode="RANGE", low=180, high=200)
    assert p.row.strike == 72900
    assert pick_strike(rows((73000, 210)), mode="RANGE", low=180, high=200).row is None
    assert pick_strike(rows((73000, 190)), mode="RANGE", low=0, high=0).row is None        # empty boxes


def test_per_lot_amount_takes_the_price_nearest_without_going_above():
    # Rs 6,500 and NIFTY lot 65 -> nearest to Rs 100, at most 100
    p = pick_strike(rows((24900, 131.5), (24950, 104.0), (25000, 98.5), (25050, 76.0)), mode="PER_LOT",
                    per_lot=6500, lot_size=65)
    assert p.row.strike == 25000 and p.row.price == 98.5
    assert pick_strike(rows((25000, 120)), mode="PER_LOT", per_lot=6500, lot_size=65).row is None


def test_no_price_is_never_picked():
    assert pick_strike([ChainRow(25000, "X", None)], mode="RANGE", low=1, high=500).row is None


def test_lots_from_funds_to_use_per_entry():
    assert lots_for(20000, 50000, 100.0, 65) == 3            # 20,000 / 6,500 = 3 lots (owner's example)
    assert lots_for(20000, 12000, 100.0, 65) == 1            # never more than the funds available
    assert lots_for(5000, 50000, 100.0, 65) == 0


def test_direction_crosses_on_finished_candles_skip_na_and_ignore_the_first_sign():
    d = [None, -3.0, -1.0, None, 2.0, 4.0, 0.0, -2.5, None, 1.0]
    assert direction_events(d) == [(4, "UP"), (7, "DOWN"), (9, "UP")]
    assert direction_events([5.0, 6.0]) == []                                   # first sign is only remembered
    assert direction_events([5.0], start_sign=-1) == [(0, "UP")]
    assert last_sign(d) == 1 and last_sign([None]) == 0


@pytest.mark.parametrize("event,position,call_on,put_on,expected", [
    ("UP", None, True, True, [("ENTER", "CALL")]),
    ("DOWN", "CALL", True, True, [("EXIT", "CALL"), ("ENTER", "PUT")]),          # exit call, enter put at once
    ("DOWN", "CALL", True, False, [("EXIT", "CALL")]),                          # PUT box off: exit only
    ("UP", "PUT", True, True, [("EXIT", "PUT"), ("ENTER", "CALL")]),
    ("UP", "PUT", False, True, [("EXIT", "PUT")]),
    ("UP", None, False, True, []),
])
def test_what_each_cross_does(event, position, call_on, put_on, expected):
    got = plan(event, position=position, call_on=call_on, put_on=put_on, entries_allowed=True)
    assert [(a.kind, a.side) for a in got] == expected


def test_after_entry_hours_only_exits():
    got = plan("DOWN", position="CALL", call_on=True, put_on=True, entries_allowed=False)
    assert [(a.kind, a.side) for a in got] == [("EXIT", "CALL")]
