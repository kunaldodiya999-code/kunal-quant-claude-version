from datetime import date

from backtest.historical_nifty_expiry import historical_nifty_expiry


def test_2024_uses_thursday_expiry():
    sessions = {date(2024, 1, d) for d in range(1, 32) if date(2024, 1, d).weekday() < 5}
    assert historical_nifty_expiry(date(2024, 1, 24), sessions) == date(2024, 1, 25)


def test_2025_transition_uses_thursday_then_tuesday():
    sessions = {
        date(2025, 8, 27),
        date(2025, 8, 28),
        date(2025, 8, 29),
        date(2025, 9, 1),
        date(2025, 9, 2),
        date(2025, 9, 3),
    }
    assert historical_nifty_expiry(date(2025, 8, 27), sessions) == date(2025, 8, 28)
    assert historical_nifty_expiry(date(2025, 9, 1), sessions) == date(2025, 9, 2)


def test_holiday_expiry_moves_to_previous_session():
    sessions = {date(2025, 9, 1), date(2025, 9, 3)}
    assert historical_nifty_expiry(date(2025, 9, 1), sessions) == date(2025, 9, 1)

def test_2025_diwali_muhurat_session_does_not_become_nifty_expiry():
    sessions = {
        date(2025, 10, 20),
        date(2025, 10, 21),  # Muhurat session
        date(2025, 10, 22),
        date(2025, 10, 28),
    }
    assert historical_nifty_expiry(date(2025, 10, 20), sessions) == date(2025, 10, 20)
    assert historical_nifty_expiry(date(2025, 10, 21), sessions) == date(2025, 10, 28)
