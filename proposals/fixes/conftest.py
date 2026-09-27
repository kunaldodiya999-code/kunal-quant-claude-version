"""
Verification-only conftest. Mocks load_fyers_bars() with synthetic OHLC
data so the patched test file can be run without the real database, to
prove the fixture-wiring fix resolves pytest's "fixture 'bars' not found"
error. Does not validate KTMI output against any reference values -- only
that the fixture now resolves and the test functions execute end to end.
"""

import pytest


@pytest.fixture(autouse=True)
def _mock_fyers_data(monkeypatch):
    import ktmi_fyers_validation_test as m

    synthetic = [
        m.OHLCData(
            open=24800.0 + (i % 50) * 0.5,
            high=24805.0 + (i % 50) * 0.5,
            low=24795.0 + (i % 50) * 0.5,
            close=24800.0 + ((i + 3) % 50) * 0.5,
        )
        for i in range(200)
    ]
    monkeypatch.setattr(m, "load_fyers_bars", lambda: synthetic)
