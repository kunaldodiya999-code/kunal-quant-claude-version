import sqlite3
import json

from config.settings import DATABASE_PATH

connection = sqlite3.connect(
    DATABASE_PATH
)

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
          ) NOT IN (
            '2024-11-27',
            '2024-11-28'
          )
    """
).fetchone()[0]

checks["orphan_gex_rows"] = connection.execute(
    """
    SELECT COUNT(*)
    FROM gex_snapshots g

    LEFT JOIN (
        SELECT DISTINCT
            timestamp,
            expiry_date,
            strike
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

print(
    json.dumps(
        checks,
        indent=2
    )
)

connection.close()
