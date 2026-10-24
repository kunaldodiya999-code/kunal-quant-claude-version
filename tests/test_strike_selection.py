"""Order window: 5-strike ladder, call/put dropdowns, ATM and ATM+1 checkboxes."""

import json
import random
import sqlite3
from dataclasses import dataclass, replace
from datetime import datetime
from zoneinfo import ZoneInfo

import pytest

from database.schema import initialize_database
from indicators.ktmi.universal import OHLCData
from indicators.ktmi_uni_lite import UNI_LITE_CORE, calculate_uni_lite
from paper_trading.engine import PaperStrategyId
from paper_trading.session import PaperSessionConfig, build_paper_session
from paper_trading.strategy_settings import StrategySettings, entry_strike_offsets
from strategies.option_contract_resolver import OptionContractResolver
from strategies.strike_ladder import StrikeLadderResolver, atm_strike, strike_ladder

IST = ZoneInfo("Asia/Kolkata")


# --------------------------------------------------------------------- ladder

def test_owner_example_nifty_22000():
    assert strike_ladder(22000, "CE") == [
        ("ITM1", 21950), ("ATM", 22000), ("OTM1", 22050), ("OTM2", 22100), ("OTM3", 22150)]
    assert strike_ladder(22000, "PE") == [
        ("ITM1", 22050), ("ATM", 22000), ("OTM1", 21950), ("OTM2", 21900), ("OTM3", 21850)]


def test_atm_is_the_nearest_strike():
    assert atm_strike(22020) == 22000
    assert atm_strike(22030) == 22050


# --------------------------------------------------------- dropdown/checkbox plan

@pytest.mark.parametrize(
    "atm, plus1, expected",
    [
        (True, False, [("ATM", 0)]),
        (False, True, [("ATM+1", 1)]),
        (True, True, [("ATM", 0), ("ATM+1", 1)]),
    ],
)
def test_checkboxes_decide_when_ticked(atm, plus1, expected):
    settings = StrategySettings(call_strike="OTM3", put_strike="ITM1", use_atm=atm, use_atm_plus_1=plus1)
    assert entry_strike_offsets(settings, "LONG") == expected
    assert entry_strike_offsets(settings, "SHORT") == expected


def test_dropdowns_decide_when_no_box_is_ticked():
    settings = StrategySettings(call_strike="OTM2", put_strike="ITM1")
    assert entry_strike_offsets(settings, "LONG") == [("OTM2", 2)]
    assert entry_strike_offsets(settings, "SHORT") == [("ITM1", -1)]


def test_unknown_strike_choice_is_refused():
    with pytest.raises(ValueError):
        StrategySettings(call_strike="ATM+5")


# ------------------------------------------------------------- exact contracts

EXPIRY = "2026-10-27"


@pytest.fixture()
def database(tmp_path):
    path = tmp_path / "kq.db"
    initialize_database(path)
    with sqlite3.connect(path) as db:
        for strike in range(21800, 22251, 50):
            for typ in ("CE", "PE"):
                db.execute(
                    "INSERT INTO instruments (broker, exchange, segment, symbol, underlying, instrument_type,"
                    " expiry_date, strike, option_type, lot_size) VALUES ('FYERS','NSE','FNO',?,'NIFTY','OPTION',?,?,?,65)",
                    (f"NSE:NIFTY26O27{strike}{typ}", EXPIRY, strike, typ),
                )
    return path


@pytest.mark.parametrize(
    "direction, offset, strike, typ",
    [
        ("LONG", -1, 21950, "CE"), ("LONG", 0, 22000, "CE"), ("LONG", 1, 22050, "CE"), ("LONG", 3, 22150, "CE"),
        ("SHORT", -1, 22050, "PE"), ("SHORT", 0, 22000, "PE"), ("SHORT", 1, 21950, "PE"), ("SHORT", 3, 21850, "PE"),
    ],
)
def test_resolver_picks_the_exact_ladder_contract(database, direction, offset, strike, typ):
    resolver = StrikeLadderResolver(OptionContractResolver(database))
    contract = resolver.resolve(
        underlying_price=22010, entry_date=datetime(2026, 10, 26).date(), direction=direction, strike_offset=offset
    )
    assert (contract.strike, contract.option_type, str(contract.expiry_date)) == (strike, typ, EXPIRY)


def test_missing_contract_is_a_clear_error(database):
    resolver = StrikeLadderResolver(OptionContractResolver(database))
    with pytest.raises(LookupError, match="22450"):
        resolver.resolve(underlying_price=22300, entry_date=datetime(2026, 10, 26).date(),
                         direction="LONG", strike_offset=3)


# -------------------------------------------------- one signal, two positions

@dataclass(frozen=True)
class Bar:
    timestamp: int
    open: float
    high: float
    low: float
    close: float


def _bars_ending_on_long_buy():
    rng = random.Random(5)
    price, raw = 22000.0, []
    for _ in range(600):
        o = price
        c = o + rng.gauss(0, 9.0)
        raw.append(OHLCData(o, max(o, c) + abs(rng.gauss(0, 2)), min(o, c) - abs(rng.gauss(0, 2)), c))
        price = c
    rows = calculate_uni_lite(raw, UNI_LITE_CORE)
    end = next(i for i, r in enumerate(rows) if r.long_buy and i > 100)
    start = int(datetime(2026, 10, 26, 10, 15, tzinfo=IST).timestamp()) - 60 * end
    return [Bar(start + 60 * i, b.open, b.high, b.low, b.close) for i, b in enumerate(raw[: end + 1])]


def test_both_boxes_open_atm_and_atm_plus_1_from_one_signal(database, tmp_path):
    (tmp_path / "strategy_settings.json").write_text(json.dumps({"use_atm": True, "use_atm_plus_1": True}))
    session = build_paper_session(
        client=object(),
        config=PaperSessionConfig(lot_size=65, output_dir=tmp_path, pending_journal_path=tmp_path / "p.csv",
                                  database_path=database),
        socket_factory=lambda **kwargs: None,
    )
    signals = session.pipeline.signal_evaluator(_bars_ending_on_long_buy(), paper_config=session.pipeline.paper_config)
    assert [(s.strategy_id, s.strike_offset) for s in signals] == [
        (PaperStrategyId.STRATEGY_A, 0), (PaperStrategyId.STRATEGY_A_2, 1)]

    decision = signals[0].timestamp + 60
    opened = []
    for signal in signals:
        contract = session.resolver.resolve(
            underlying_price=22010, entry_date=datetime(2026, 10, 26).date(),
            direction=signal.direction, strike_offset=signal.strike_offset)
        attempt = session.coordinator.process_signal(
            signal=replace(signal, close_timestamp=decision), underlying_price=22010,
            option_quote={"symbol": contract.symbol, "lp": 100, "exch_feed_time": decision},
            decision_timestamp=decision,
        )
        assert attempt.rejection_reason is None, attempt.rejection_reason
        opened.append(attempt.trade.position.symbol)
    assert opened == ["NSE:NIFTY26O2722000CE", "NSE:NIFTY26O2722050CE"]
    assert session.engine.open_trade(PaperStrategyId.STRATEGY_A) is not None
    assert session.engine.open_trade(PaperStrategyId.STRATEGY_A_2) is not None


def test_dashboard_change_applies_to_the_next_signal_without_restart(database, tmp_path):
    session = build_paper_session(
        client=object(),
        config=PaperSessionConfig(lot_size=65, output_dir=tmp_path, pending_journal_path=tmp_path / "p.csv",
                                  database_path=database),
        socket_factory=lambda **kwargs: None,
    )
    bars = _bars_ending_on_long_buy()
    first = session.pipeline.signal_evaluator(bars, paper_config=session.pipeline.paper_config)
    assert [(s.strike_offset, s.reason.split("|")[1]) for s in first] == [(0, "ATM")]   # dropdown default ATM

    session.settings_store.update(call_strike="OTM2", trade_direction="SHORT")   # what the dashboard does
    second = session.pipeline.signal_evaluator(bars, paper_config=session.pipeline.paper_config)
    assert [(s.strike_offset, s.reason.split("|")[1]) for s in second] == [(2, "OTM2")]
    assert session.coordinator.trade_direction == "SHORT"
