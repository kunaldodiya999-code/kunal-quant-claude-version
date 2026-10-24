from pathlib import Path

import sqlite3

from scripts.run_real_option_sample import load_complete_3m_bars


def test_sample_loader_uses_complete_3m_only(tmp_path: Path, monkeypatch):
    db = tmp_path / "derived.db"
    with sqlite3.connect(db) as connection:
        connection.execute(
            """
            CREATE TABLE derived_candles (
                symbol TEXT,
                timestamp INTEGER,
                open REAL,
                high REAL,
                low REAL,
                close REAL,
                volume INTEGER,
                open_interest INTEGER,
                resolution TEXT,
                source TEXT,
                complete INTEGER
            )
            """
        )
        rows = [
            ("NIFTY", 100, 1, 2, 0.5, 1.5, 1, None, "3", "SRC", 1),
            ("NIFTY", 101, 1, 2, 0.5, 1.5, 1, None, "3", "SRC", 0),
        ]
        connection.executemany(
            "INSERT INTO derived_candles VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            rows,
        )

    monkeypatch.setattr(
        "scripts.run_real_option_sample.DERIVED_DB",
        db,
    )
    monkeypatch.setattr(
        "scripts.run_real_option_sample.SYMBOL",
        "NIFTY",
    )
    monkeypatch.setattr(
        "scripts.run_real_option_sample.SOURCE",
        "SRC",
    )

    bars = load_complete_3m_bars(20)
    assert len(bars) == 1
    assert bars[0].timestamp == 100
