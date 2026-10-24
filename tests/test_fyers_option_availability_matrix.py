from scripts.audit_fyers_option_availability_matrix import select_matrix


class FakeDB:
    def __init__(self, rows):
        self.rows = rows

    def execute(self, *_args):
        return self

    def fetchone(self):
        return self.rows.pop(0) if self.rows else None


def test_select_matrix_uses_four_samples_per_expiry_when_available():
    rows = [
        {"id": 1, "symbol": "A", "expiry_date": "2021-01-07", "strike": 100,
         "option_type": "CE", "existing_candles": 10},
        {"id": 2, "symbol": "B", "expiry_date": "2021-01-07", "strike": 100,
         "option_type": "CE", "existing_candles": 0},
        {"id": 3, "symbol": "C", "expiry_date": "2021-01-07", "strike": 100,
         "option_type": "PE", "existing_candles": 10},
        {"id": 4, "symbol": "D", "expiry_date": "2021-01-07", "strike": 100,
         "option_type": "PE", "existing_candles": 0},
    ]
    result = select_matrix(FakeDB(rows), ["2021-01-07"])
    assert len(result) == 4
