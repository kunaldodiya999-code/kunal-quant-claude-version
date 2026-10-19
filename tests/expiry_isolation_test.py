"""Database-backed expiry isolation audit.

This audit requires an existing analytics database with the GEX schema. It
must not fail pytest collection in a clean checkout with no analytics tables.
"""
import json
import sqlite3
import unittest

from config.settings import DATABASE_PATH


class ExpiryIsolationAudit(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.connection = sqlite3.connect(DATABASE_PATH)
        tables = {
            row[0] for row in cls.connection.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            )
        }
        required = {"gex_snapshots", "option_analytics"}
        missing = required - tables
        if missing:
            cls.connection.close()
            raise unittest.SkipTest(
                "Analytics schema unavailable; missing tables: "
                + ", ".join(sorted(missing))
            )

    @classmethod
    def tearDownClass(cls):
        connection = getattr(cls, "connection", None)
        if connection is not None:
            connection.close()

    def test_expiry_dates_and_gex_row_integrity(self):
        connection = self.connection
        checks = {}

        checks["2024-11-21"] = connection.execute(
            """
            SELECT COUNT(*)
            FROM gex_snapshots
            WHERE expiry_date = '2024-11-21'
              AND date(
                    datetime(timestamp, 'unixepoch'),
                    '+5 hours',
                    '+30 minutes'
                  ) != '2024-11-21'
            """
        ).fetchone()[0]

        checks["2024-11-28"] = connection.execute(
            """
            SELECT COUNT(*)
            FROM gex_snapshots
            WHERE expiry_date = '2024-11-28'
              AND date(
                    datetime(timestamp, 'unixepoch'),
                    '+5 hours',
                    '+30 minutes'
                  ) NOT IN ('2024-11-27', '2024-11-28')
            """
        ).fetchone()[0]

        checks["orphan_gex_rows"] = connection.execute(
            """
            SELECT COUNT(*)
            FROM gex_snapshots g
            LEFT JOIN (
                SELECT DISTINCT timestamp, expiry_date, strike
                FROM option_analytics
                WHERE resolution = '1'
                  AND calculation_version = 'black76_iv_greeks_v1'
            ) a
              ON a.timestamp = g.timestamp
             AND a.expiry_date = g.expiry_date
             AND a.strike = g.strike
            WHERE a.timestamp IS NULL
            """
        ).fetchone()[0]

        checks["same_timestamp_both_expiries"] = connection.execute(
            """
            SELECT COUNT(*)
            FROM (
                SELECT timestamp
                FROM gex_snapshots
                WHERE expiry_date = '2024-11-21'
                INTERSECT
                SELECT timestamp
                FROM gex_snapshots
                WHERE expiry_date = '2024-11-28'
            )
            """
        ).fetchone()[0]

        print(json.dumps(checks, indent=2))
        self.assertEqual(checks["2024-11-21"], 0)
        self.assertEqual(checks["2024-11-28"], 0)
        self.assertEqual(checks["orphan_gex_rows"], 0)
        self.assertEqual(checks["same_timestamp_both_expiries"], 0)


if __name__ == "__main__":
    unittest.main()
