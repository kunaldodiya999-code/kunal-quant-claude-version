from paper_trading.tsl_shadow_lab import OptionCandle, TslShadowLab


def test_shadow_trade_registers_all_six_candidates(tmp_path):
    lab = TslShadowLab(tmp_path)
    lab.register_trade(
        trade_id="t1", symbol="NSE:NIFTY26100CE", direction="LONG",
        entry_timestamp=100, entry_price=100.0, quantity=25,
    )
    assert set(lab.trades["t1"]["candidates"]) == set(lab.CANDIDATES)


def test_shadow_uses_previous_stop_for_intrabar_hit(tmp_path):
    lab = TslShadowLab(tmp_path)
    lab.register_trade(
        trade_id="t1", symbol="NSE:NIFTY26100CE", direction="SHORT",
        entry_timestamp=100, entry_price=100.0, quantity=25,
    )
    candidate = lab.trades["t1"]["candidates"]["chandelier_atr9_mult1.5"]
    candidate.stop = 95.0
    lab.on_candle(
        symbol="NSE:NIFTY26100CE",
        candle=OptionCandle(timestamp=160, open=96, high=98, low=94, close=95),
    )
    assert candidate.exited
    assert candidate.exit_price == 95.0
    assert candidate.exit_reason == "OPTION_LOW_HIT_TRAILING_STOP"


def test_candle_at_or_before_entry_is_ignored(tmp_path):
    lab = TslShadowLab(tmp_path)
    lab.register_trade(
        trade_id="t1", symbol="NSE:NIFTY26100CE", direction="LONG",
        entry_timestamp=150, entry_price=100.0, quantity=25,
    )
    lab.on_candle(
        symbol="NSE:NIFTY26100CE",
        candle=OptionCandle(timestamp=120, open=100, high=105, low=90, close=95),
    )
    assert lab.trades["t1"]["bars"] == []
    assert not (tmp_path / "tsl_shadow_bars.csv").exists()



def test_exited_candidate_is_frozen_while_other_candidates_continue(tmp_path):
    lab = TslShadowLab(tmp_path)
    lab.register_trade(
        trade_id="t1", symbol="NSE:NIFTY26100CE", direction="LONG",
        entry_timestamp=100, entry_price=100.0, quantity=25,
    )
    trade = lab.trades["t1"]
    candidate = trade["candidates"]["chandelier_atr9_mult1.5"]
    candidate.exited = True
    candidate.stop = 95.0
    candidate.state["sentinel"] = "unchanged"

    lab.on_candle(
        symbol="NSE:NIFTY26100CE",
        candle=OptionCandle(timestamp=160, open=100, high=102, low=99, close=101),
    )

    assert candidate.stop == 95.0
    assert candidate.state == {"sentinel": "unchanged"}
    assert not all(item.exited for item in trade["candidates"].values())



def test_wilder_atr_uses_rma_after_initial_sma(tmp_path):
    lab = TslShadowLab(tmp_path)
    bars = [
        OptionCandle(timestamp=60, open=10, high=12, low=10, close=11),
        OptionCandle(timestamp=120, open=11, high=14, low=11, close=13),
        OptionCandle(timestamp=180, open=13, high=17, low=13, close=16),
        OptionCandle(timestamp=240, open=16, high=21, low=16, close=20),
    ]
    # TRs are 2, 3, 4, 5; seed SMA(3)=3, then RMA=(2*3+5)/3.
    assert lab._atr_wilder(bars[:3], 3) == 3
    assert abs(lab._atr_wilder(bars, 3) - (11 / 3)) < 1e-9
