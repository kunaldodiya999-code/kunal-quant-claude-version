from yt_trailing_structure import AtrStructureTrailing


def test_long_stop_only_ratchets_up():
    t = AtrStructureTrailing(atr_period=2, swing_atr_mult=1.0, stop_atr_buffer=0.0)
    rows = [
        (0, 100, 101, 99, 100),
        (1, 100, 101, 99, 100),
        (2, 100, 105, 100, 104),
        (3, 104, 106, 103, 105),
    ]
    stops = []
    for row in rows:
        u = t.on_bar(row[0], *row[1:], "LONG")
        if u:
            stops.append(u.stop)
    assert stops == sorted(stops)


def test_short_stop_only_ratchets_down():
    t = AtrStructureTrailing(atr_period=2, swing_atr_mult=1.0, stop_atr_buffer=0.0)
    rows = [
        (0, 100, 101, 99, 100),
        (1, 100, 101, 99, 100),
        (2, 100, 100, 95, 96),
        (3, 96, 97, 94, 95),
    ]
    stops = []
    for row in rows:
        u = t.on_bar(row[0], *row[1:], "SHORT")
        if u:
            stops.append(u.stop)
    assert stops == sorted(stops, reverse=True)
