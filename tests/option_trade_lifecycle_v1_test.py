from backtest.option_trade_lifecycle import (
    OptionTradeDirection,
    OptionExitReason,
    OptionTradeLifecycle,
)


TEST_STRATEGY_ID = "KTMI_LONG_SHORT_SPEED"
TEST_SYMBOL_CE = "NSE:NIFTY24N2123350CE"
TEST_SYMBOL_PE = "NSE:NIFTY24N2123350PE"


def assert_equal(actual, expected, label):
    assert actual == expected, f"{label}: expected {expected}, got {actual}"
    print(f"PASS | {label}")


def assert_close(actual, expected, label, tolerance=1e-9):
    assert abs(actual - expected) <= tolerance, (
        f"{label}: expected {expected}, got {actual}"
    )
    print(f"PASS | {label}")


def one_exit(exits, label):
    assert_equal(len(exits), 1, f"{label} event count")
    return exits[0]


def test_long_position_creation():
    lifecycle = OptionTradeLifecycle()

    position = lifecycle.create_position(
        strategy_id=TEST_STRATEGY_ID,
        symbol=TEST_SYMBOL_CE,
        direction=OptionTradeDirection.LONG,
        entry_price=100.0,
    )

    assert_equal(position.lots, 2, "LONG lots")
    assert_equal(position.quantity, 130, "LONG quantity")
    assert_close(
        position.entry_price * position.quantity,
        13000.0,
        "LONG capital used",
    )
    assert_close(position.stop_loss, 80.0, "LONG stop loss")
    assert_close(
        position.entry_price
        + (position.entry_price - position.stop_loss) * 3.0,
        160.0,
        "LONG 3R target",
    )
    assert_close(
        (position.entry_price - position.stop_loss) * position.quantity,
        2600.0,
        "LONG planned risk",
    )


def test_short_position_creation():
    lifecycle = OptionTradeLifecycle()

    position = lifecycle.create_position(
        strategy_id=TEST_STRATEGY_ID,
        symbol=TEST_SYMBOL_PE,
        direction=OptionTradeDirection.SHORT,
        entry_price=100.0,
    )

    assert_equal(position.lots, 2, "SHORT lots")
    assert_equal(position.quantity, 130, "SHORT quantity")
    assert_close(position.stop_loss, 120.0, "SHORT stop loss")
    assert_close(
        position.entry_price
        - (position.stop_loss - position.entry_price) * 3.0,
        40.0,
        "SHORT 3R target",
    )
    assert_close(
        (position.stop_loss - position.entry_price) * position.quantity,
        2600.0,
        "SHORT planned risk",
    )


def test_partial_lot_rounding():
    lifecycle = OptionTradeLifecycle()

    expected = {
        1: (0, 1),
        2: (1, 1),
        3: (2, 1),
        4: (2, 2),
        5: (3, 2),
        6: (3, 3),
        7: (4, 3),
    }

    for total_lots, expected_result in expected.items():
        result = lifecycle.calculate_partial_exit_lots(total_lots)
        assert_equal(
            result,
            expected_result,
            f"partial lots {total_lots}",
        )


def test_long_target_partial_exit():
    lifecycle = OptionTradeLifecycle()

    position = lifecycle.create_position(
        strategy_id=TEST_STRATEGY_ID,
        symbol=TEST_SYMBOL_CE,
        direction=OptionTradeDirection.LONG,
        entry_price=100.0,
    )

    exits = lifecycle.process_candle(
        position=position,
        timestamp=2,
        option_high=161.0,
        option_low=155.0,
        option_close=160.0,
        underlying_close=23500.0,
        kama_value=23490.0,
    )

    exit_event = one_exit(exits, "LONG target")

    assert_equal(
        exit_event.reason,
        OptionExitReason.TARGET_3R,
        "LONG target reason",
    )
    assert_equal(
        exit_event.quantity,
        65,
        "LONG target quantity",
    )
    assert_close(
        exit_event.price,
        160.0,
        "LONG target price",
    )
    assert_equal(
        exit_event.remaining_lots,
        1,
        "LONG target remaining lots",
    )
    assert_equal(
        exit_event.remaining_quantity,
        65,
        "LONG target remaining quantity",
    )
    assert_equal(
        position.remaining_lots,
        1,
        "LONG position remaining lots after target",
    )
    assert_equal(
        position.remaining_quantity,
        65,
        "LONG position remaining quantity after target",
    )
    assert_equal(
        position.partial_exit_done,
        True,
        "LONG partial target flag",
    )


def test_long_kama_exit():
    lifecycle = OptionTradeLifecycle()

    position = lifecycle.create_position(
        strategy_id=TEST_STRATEGY_ID,
        symbol=TEST_SYMBOL_CE,
        direction=OptionTradeDirection.LONG,
        entry_price=100.0,
    )

    # Simulate the 1:3 partial target having already occurred.
    position.remaining_lots = 1
    position.remaining_quantity = 65
    position.partial_exit_done = True

    exits = lifecycle.process_candle(
        position=position,
        timestamp=3,
        option_high=150.0,
        option_low=140.0,
        option_close=145.0,
        underlying_close=23480.0,
        kama_value=23490.0,
    )

    exit_event = one_exit(exits, "LONG KAMA")

    assert_equal(
        exit_event.reason,
        OptionExitReason.KAMA_EXIT,
        "LONG KAMA exit reason",
    )
    assert_equal(
        exit_event.quantity,
        65,
        "LONG KAMA quantity",
    )
    assert_close(
        exit_event.price,
        145.0,
        "LONG KAMA exit price",
    )
    assert_equal(
        exit_event.remaining_quantity,
        0,
        "LONG KAMA remaining quantity",
    )
    assert_equal(
        position.closed,
        True,
        "LONG position closed by KAMA",
    )


def test_short_stop_loss():
    lifecycle = OptionTradeLifecycle()

    position = lifecycle.create_position(
        strategy_id=TEST_STRATEGY_ID,
        symbol=TEST_SYMBOL_PE,
        direction=OptionTradeDirection.SHORT,
        entry_price=100.0,
    )

    exits = lifecycle.process_candle(
        position=position,
        timestamp=2,
        option_high=121.0,
        option_low=110.0,
        option_close=118.0,
        underlying_close=23500.0,
        kama_value=23490.0,
    )

    exit_event = one_exit(exits, "SHORT stop")

    assert_equal(
        exit_event.reason,
        OptionExitReason.STOP_LOSS,
        "SHORT stop reason",
    )
    assert_close(
        exit_event.price,
        120.0,
        "SHORT stop price",
    )
    assert_equal(
        exit_event.quantity,
        130,
        "SHORT stop quantity",
    )
    assert_equal(
        position.closed,
        True,
        "SHORT position closed by stop",
    )


def test_short_target_partial():
    lifecycle = OptionTradeLifecycle()

    position = lifecycle.create_position(
        strategy_id=TEST_STRATEGY_ID,
        symbol=TEST_SYMBOL_PE,
        direction=OptionTradeDirection.SHORT,
        entry_price=100.0,
    )

    exits = lifecycle.process_candle(
        position=position,
        timestamp=2,
        option_high=50.0,
        option_low=39.0,
        option_close=40.0,
        underlying_close=23480.0,
        kama_value=23490.0,
    )

    exit_event = one_exit(exits, "SHORT target")

    assert_equal(
        exit_event.reason,
        OptionExitReason.TARGET_3R,
        "SHORT target reason",
    )
    assert_close(
        exit_event.price,
        40.0,
        "SHORT target price",
    )
    assert_equal(
        exit_event.quantity,
        65,
        "SHORT target quantity",
    )
    assert_equal(
        exit_event.remaining_quantity,
        65,
        "SHORT target remaining quantity",
    )
    assert_equal(
        position.remaining_lots,
        1,
        "SHORT target remaining lots",
    )


def test_stop_first_when_stop_and_target_same_candle():
    lifecycle = OptionTradeLifecycle()

    position = lifecycle.create_position(
        strategy_id=TEST_STRATEGY_ID,
        symbol=TEST_SYMBOL_CE,
        direction=OptionTradeDirection.LONG,
        entry_price=100.0,
    )

    # Both SL=80 and target=160 are touched.
    # Conservative rule: SL executes first.
    exits = lifecycle.process_candle(
        position=position,
        timestamp=2,
        option_high=165.0,
        option_low=75.0,
        option_close=100.0,
        underlying_close=23500.0,
        kama_value=23490.0,
    )

    exit_event = one_exit(exits, "same-candle stop-first")

    assert_equal(
        exit_event.reason,
        OptionExitReason.STOP_LOSS,
        "same-candle stop-first reason",
    )
    assert_close(
        exit_event.price,
        80.0,
        "same-candle stop price",
    )
    assert_equal(
        exit_event.quantity,
        130,
        "same-candle stop quantity",
    )


def test_target_then_kama_not_same_candle():
    lifecycle = OptionTradeLifecycle()

    position = lifecycle.create_position(
        strategy_id=TEST_STRATEGY_ID,
        symbol=TEST_SYMBOL_CE,
        direction=OptionTradeDirection.LONG,
        entry_price=100.0,
    )

    # Target is hit and underlying is also below KAMA.
    # V1 target event must be processed first and KAMA must wait
    # for the next candle.
    exits = lifecycle.process_candle(
        position=position,
        timestamp=2,
        option_high=161.0,
        option_low=155.0,
        option_close=160.0,
        underlying_close=23480.0,
        kama_value=23490.0,
    )

    exit_event = one_exit(exits, "target before KAMA")

    assert_equal(
        exit_event.reason,
        OptionExitReason.TARGET_3R,
        "target before KAMA reason",
    )
    assert_equal(
        position.closed,
        False,
        "position remains open after partial target",
    )


def test_kama_unavailable_holds():
    lifecycle = OptionTradeLifecycle()

    position = lifecycle.create_position(
        strategy_id=TEST_STRATEGY_ID,
        symbol=TEST_SYMBOL_CE,
        direction=OptionTradeDirection.LONG,
        entry_price=100.0,
    )

    position.remaining_lots = 1
    position.remaining_quantity = 65
    position.partial_exit_done = True

    exits = lifecycle.process_candle(
        position=position,
        timestamp=2,
        option_high=150.0,
        option_low=140.0,
        option_close=145.0,
        underlying_close=23480.0,
        kama_value=None,
    )

    assert_equal(
        exits,
        [],
        "KAMA unavailable = HOLD",
    )


def test_long_kama_equal_holds():
    lifecycle = OptionTradeLifecycle()

    position = lifecycle.create_position(
        strategy_id=TEST_STRATEGY_ID,
        symbol=TEST_SYMBOL_CE,
        direction=OptionTradeDirection.LONG,
        entry_price=100.0,
    )

    position.remaining_lots = 1
    position.remaining_quantity = 65
    position.partial_exit_done = True

    exits = lifecycle.process_candle(
        position=position,
        timestamp=2,
        option_high=150.0,
        option_low=140.0,
        option_close=145.0,
        underlying_close=23500.0,
        kama_value=23500.0,
    )

    assert_equal(
        exits,
        [],
        "LONG close equal KAMA = HOLD",
    )


def test_short_kama_equal_holds():
    lifecycle = OptionTradeLifecycle()

    position = lifecycle.create_position(
        strategy_id=TEST_STRATEGY_ID,
        symbol=TEST_SYMBOL_PE,
        direction=OptionTradeDirection.SHORT,
        entry_price=100.0,
    )

    position.remaining_lots = 1
    position.remaining_quantity = 65
    position.partial_exit_done = True

    exits = lifecycle.process_candle(
        position=position,
        timestamp=2,
        option_high=70.0,
        option_low=60.0,
        option_close=65.0,
        underlying_close=23500.0,
        kama_value=23500.0,
    )

    assert_equal(
        exits,
        [],
        "SHORT close equal KAMA = HOLD",
    )


def test_long_kama_above_holds():
    lifecycle = OptionTradeLifecycle()

    position = lifecycle.create_position(
        strategy_id=TEST_STRATEGY_ID,
        symbol=TEST_SYMBOL_CE,
        direction=OptionTradeDirection.LONG,
        entry_price=100.0,
    )

    position.remaining_lots = 1
    position.remaining_quantity = 65
    position.partial_exit_done = True

    exits = lifecycle.process_candle(
        position=position,
        timestamp=2,
        option_high=150.0,
        option_low=140.0,
        option_close=145.0,
        underlying_close=23510.0,
        kama_value=23500.0,
    )

    assert_equal(
        exits,
        [],
        "LONG close above KAMA = HOLD",
    )


def test_short_kama_below_holds():
    lifecycle = OptionTradeLifecycle()

    position = lifecycle.create_position(
        strategy_id=TEST_STRATEGY_ID,
        symbol=TEST_SYMBOL_PE,
        direction=OptionTradeDirection.SHORT,
        entry_price=100.0,
    )

    position.remaining_lots = 1
    position.remaining_quantity = 65
    position.partial_exit_done = True

    exits = lifecycle.process_candle(
        position=position,
        timestamp=2,
        option_high=70.0,
        option_low=60.0,
        option_close=65.0,
        underlying_close=23490.0,
        kama_value=23500.0,
    )

    assert_equal(
        exits,
        [],
        "SHORT close below KAMA = HOLD",
    )


def test_short_kama_exit():
    lifecycle = OptionTradeLifecycle()

    position = lifecycle.create_position(
        strategy_id=TEST_STRATEGY_ID,
        symbol=TEST_SYMBOL_PE,
        direction=OptionTradeDirection.SHORT,
        entry_price=100.0,
    )

    position.remaining_lots = 1
    position.remaining_quantity = 65
    position.partial_exit_done = True

    exits = lifecycle.process_candle(
        position=position,
        timestamp=3,
        option_high=70.0,
        option_low=60.0,
        option_close=65.0,
        underlying_close=23510.0,
        kama_value=23500.0,
    )

    exit_event = one_exit(exits, "SHORT KAMA")

    assert_equal(
        exit_event.reason,
        OptionExitReason.KAMA_EXIT,
        "SHORT KAMA exit reason",
    )
    assert_equal(
        exit_event.quantity,
        65,
        "SHORT KAMA quantity",
    )
    assert_close(
        exit_event.price,
        65.0,
        "SHORT KAMA exit price",
    )
    assert_equal(
        exit_event.remaining_quantity,
        0,
        "SHORT KAMA remaining quantity",
    )
    assert_equal(
        position.closed,
        True,
        "SHORT position closed by KAMA",
    )


def main():
    print("=" * 78)
    print("KUNAL QUANT — OPTION TRADE LIFECYCLE V1 TEST")
    print("=" * 78)

    test_long_position_creation()
    test_short_position_creation()
    test_partial_lot_rounding()

    test_long_target_partial_exit()
    test_long_kama_exit()

    test_short_stop_loss()
    test_short_target_partial()

    test_stop_first_when_stop_and_target_same_candle()
    test_target_then_kama_not_same_candle()

    test_kama_unavailable_holds()
    test_long_kama_equal_holds()
    test_short_kama_equal_holds()
    test_long_kama_above_holds()
    test_short_kama_below_holds()
    test_short_kama_exit()

    print()
    print("ALL OPTION TRADE LIFECYCLE V1 TESTS PASSED")


if __name__ == "__main__":
    main()
