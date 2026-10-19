from scripts.probe_fyers_nifty_option_coverage import _extract_candles


def test_extracts_top_level_candles():
    assert _extract_candles({"s": "ok", "candles": [[1, 2, 3]]}) == [[1, 2, 3]]


def test_extracts_nested_candles():
    assert _extract_candles({"s": "ok", "data": {"candles": [[1, 2, 3]]}}) == [[1, 2, 3]]


def test_empty_or_error_response_has_no_candles():
    assert _extract_candles({"s": "ok", "data": {}}) == []
    assert _extract_candles({"s": "error"}) == []
