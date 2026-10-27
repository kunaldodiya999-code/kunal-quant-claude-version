"""Owner 27 Oct 2026: buy ATM or ATM+1 by the money; one NIFTY lot at most Rs 8,000; live = real FYERS funds."""

from datetime import date, datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

from live_trading.funds import available_balance, funds_provider
from market_data.fyers_quote_cache import FyersQuoteCache
from paper_trading.coordinator import PaperEntryAttempt
from paper_trading.engine import PaperStrategyId
from paper_trading.pending_entry_orchestrator import PendingEntryConfig, PendingEntryOrchestrator
from paper_trading.signals import PaperSignal
from paper_trading.strategy_settings import StrategySettings, entry_strike_offsets
from strategies.funds_strike import choose_strike
from strategies.option_contract_resolver import ResolvedOptionContract

IST = ZoneInfo("Asia/Kolkata")
NOW = datetime(2026, 10, 27, 10, 0, tzinfo=IST)
TS = int(NOW.timestamp())


def test_the_owners_example_two_lots_of_115():
    # Rs 15,000: ATM at 135 = Rs 8,775 a lot (above the Rs 8,000 cap), ATM+1 at 115 = Rs 7,475 -> 2 lots
    c = choose_strike([("ATM", 0, 135.0), ("ATM+1", 1, 115.0)], budget=15000, lot_size=65, max_lot_cost=8000)
    assert (c.label, c.offset, c.lots) == ("ATM+1", 1, 2)
    assert "cap Rs 8,000" in c.reason


def test_more_lots_wins_equal_lots_keeps_atm():
    assert choose_strike([("ATM", 0, 110.0), ("ATM+1", 1, 95.0)], budget=15000, lot_size=65,
                         max_lot_cost=8000).label == "ATM"                      # 2 lots each: ATM
    c = choose_strike([("ATM", 0, 110.0), ("ATM+1", 1, 95.0)], budget=20000, lot_size=65, max_lot_cost=8000)
    assert (c.label, c.lots) == ("ATM+1", 3)                                   # 2 vs 3 lots: ATM+1


def test_no_trade_when_no_strike_fits():
    c = choose_strike([("ATM", 0, 140.0), ("ATM+1", 1, 125.0)], budget=50000, lot_size=65, max_lot_cost=8000)
    assert c.label is None and c.reason.startswith("no trade")                  # both above Rs 8,000 a lot
    c = choose_strike([("ATM", 0, 110.0), ("ATM+1", 1, 95.0)], budget=5000, lot_size=65, max_lot_cost=8000)
    assert c.label is None                                                      # not one whole lot of money


def test_settings_auto_mode_and_cap_are_checked():
    s = StrategySettings(strike_mode="AUTO_ATM_ATM1", max_lot_cost=8000)
    assert entry_strike_offsets(s, "LONG") == [("AUTO", 0)]
    with pytest.raises(ValueError):
        StrategySettings(strike_mode="ATM+2")
    with pytest.raises(ValueError):
        StrategySettings(max_lot_cost=-1)


def test_real_fyers_available_balance_is_read_and_cached():
    response = {"s": "ok", "fund_limit": [{"id": 1, "title": "Total Balance", "equityAmount": 20000},
                                          {"id": 10, "title": "Available Balance", "equityAmount": 15000.5}]}
    assert available_balance(response) == 15000.5
    with pytest.raises(ValueError):
        available_balance({"s": "error", "message": "token expired"})

    class Model:
        calls = 0

        def funds(self):
            Model.calls += 1
            return response
    t = {"now": 0.0}
    get = funds_provider(Model(), max_age=15, clock=lambda: t["now"], log=lambda _m: None)
    assert get() == 15000.5 and get() == 15000.5 and Model.calls == 1
    t["now"] = 16
    get()
    assert Model.calls == 2


class Resolver:
    def resolve(self, *, underlying_price, entry_date, direction, strike_offset=0):
        strike = 25000 + 50 * strike_offset
        return ResolvedOptionContract(instrument_id=1 + strike_offset, symbol=f"NSE:NIFTY26O27{strike}CE",
                                      underlying="NIFTY", expiry_date=date(2026, 10, 27), strike=strike,
                                      option_type="CE")


class Coordinator:
    def __init__(self):
        self.calls = []

    def process_signal(self, **kwargs):
        self.calls.append(kwargs)
        return PaperEntryAttempt(signal=kwargs["signal"], candidate=None, trade=object(), rejection_reason=None)


def orchestrator(tmp_path, budget):
    cache = FyersQuoteCache(receive_clock=lambda: 1000.0)
    cache.update({"symbol": "NSE:NIFTY50-INDEX", "ltp": 25010, "exch_feed_time": TS})
    coord = Coordinator()
    subs = []
    orch = PendingEntryOrchestrator(
        resolver=Resolver(), quote_cache=cache, coordinator=coord, subscribe_symbols=subs.extend,
        config=PendingEntryConfig(timeout_seconds=8, journal_path=Path(tmp_path) / "pending.csv"),
        clock=lambda: NOW,
        strike_chooser=lambda *, candidates, timestamp: choose_strike(candidates, budget=budget, lot_size=65,
                                                                      max_lot_cost=8000))
    return orch, cache, coord, subs


def auto_signal():
    return PaperSignal(PaperStrategyId.STRATEGY_A, "LONG", TS - 180, 10, "CROSS|AUTO", strike_auto=True)


def test_auto_signal_watches_atm_and_atm1_and_buys_the_one_with_more_lots(tmp_path):
    orch, cache, coord, subs = orchestrator(tmp_path, budget=15000)
    assert orch.on_signals([auto_signal()])[0].status == "PENDING"
    assert subs == ["NSE:NIFTY26O2725000CE", "NSE:NIFTY26O2725050CE"]
    cache.update({"symbol": "NSE:NIFTY26O2725000CE", "ltp": 135.0, "exch_feed_time": TS})
    assert orch.on_tick() == ()                                           # waits for the ATM+1 price too
    cache.update({"symbol": "NSE:NIFTY26O2725050CE", "ltp": 115.0, "exch_feed_time": TS})
    (event,) = orch.on_tick()
    assert event.status == "ENTERED" and event.symbol == "NSE:NIFTY26O2725050CE"
    assert coord.calls[0]["signal"].strike_offset == 1
    assert coord.calls[0]["option_quote"]["symbol"] == "NSE:NIFTY26O2725050CE"
    journal = (Path(tmp_path) / "pending.csv").read_text()
    assert "STRIKE_CHOSEN" in journal and "ATM+1 chosen" in journal


def test_auto_signal_with_no_affordable_strike_is_not_traded(tmp_path):
    orch, cache, coord, _subs = orchestrator(tmp_path, budget=15000)
    orch.on_signals([auto_signal()])
    cache.update({"symbol": "NSE:NIFTY26O2725000CE", "ltp": 150.0, "exch_feed_time": TS})
    cache.update({"symbol": "NSE:NIFTY26O2725050CE", "ltp": 128.0, "exch_feed_time": TS})
    (event,) = orch.on_tick()
    assert event.status == "REJECTED" and "no trade" in event.reason and coord.calls == []


def test_manual_strike_above_the_cap_is_not_traded(tmp_path):
    orch, cache, coord, _subs = orchestrator(tmp_path, budget=50000)
    orch.on_signals([PaperSignal(PaperStrategyId.STRATEGY_A, "LONG", TS - 180, 10, "CROSS|ATM")])
    cache.update({"symbol": "NSE:NIFTY26O2725000CE", "ltp": 140.0, "exch_feed_time": TS})
    (event,) = orch.on_tick()
    assert event.status == "REJECTED" and "cap Rs 8,000" in event.reason and coord.calls == []
