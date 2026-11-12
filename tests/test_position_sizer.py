"""Position Sizer (TradingView): same dual-constraint maths as the trading terminal (owner's formula)."""

import math
from pathlib import Path

PINE = (Path(__file__).resolve().parents[1] / "indicators" / "position_sizer" / "Position_Sizer_RR.pine").read_text()


def lots(capital, alloc, max_risk, entry, stop, lot, strict=False, buffer=2.0):
    d = 1 if stop < entry else -1
    e = entry + d * buffer if strict else entry
    s = stop - d * buffer if strict else stop
    rpu = abs(e - s)
    return max(0, min(math.floor(capital * alloc / 100 / (e * lot)), math.floor(max_risk / (rpu * lot))))


def test_owner_sensex_example():
    assert lots(50000, 50, 5000, 100, 75, 20) == 10                 # plain = owner's formula
    assert lots(50000, 50, 5000, 100, 75, 20, strict=True) == 8      # strict = buffer on both sides


def test_pine_has_the_same_formulas_and_no_orders():
    for needed in ("math.floor(budget / (entryUsed * lotSize))", "math.floor(maxRisk / (riskPerUnit * lotSize))",
                   "math.min(lotsCapital, lotsRisk)", "input.price(100, \"Entry\", confirm=true",
                   "entryUsed = strict ? entry + dir * buffer : entry", "stopUsed = strict ? stop - dir * buffer : stop"):
        assert needed in PINE, needed
    assert "strategy(" not in PINE and "alert(" not in PINE
