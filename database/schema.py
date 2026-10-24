from __future__ import annotations

import sqlite3
from pathlib import Path


# ============================================================
# KUNAL QUANT
# DATABASE SCHEMA
# ============================================================

SCHEMA_VERSION = 4


SCHEMA_SQL = """
PRAGMA foreign_keys = ON;


-- ==========================================================
-- SCHEMA METADATA
-- ==========================================================

CREATE TABLE IF NOT EXISTS schema_metadata (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);


-- ==========================================================
-- INSTRUMENT MASTER
-- ==========================================================

CREATE TABLE IF NOT EXISTS instruments (
    id INTEGER PRIMARY KEY AUTOINCREMENT,

    broker TEXT NOT NULL,
    exchange TEXT NOT NULL,
    segment TEXT NOT NULL,

    symbol TEXT NOT NULL,

    broker_token TEXT,
    security_id TEXT,

    underlying TEXT,

    instrument_type TEXT NOT NULL,

    expiry_date TEXT,
    strike REAL,
    option_type TEXT,

    lot_size INTEGER,
    tick_size REAL,

    currency TEXT DEFAULT 'INR',

    is_active INTEGER DEFAULT 1,

    created_at TEXT DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT DEFAULT CURRENT_TIMESTAMP,

    UNIQUE (broker, symbol)
);


CREATE INDEX IF NOT EXISTS idx_instruments_symbol
ON instruments(symbol);


CREATE INDEX IF NOT EXISTS idx_instruments_underlying
ON instruments(underlying);


CREATE INDEX IF NOT EXISTS idx_instruments_expiry
ON instruments(expiry_date);


CREATE INDEX IF NOT EXISTS idx_instruments_option_type
ON instruments(option_type);


CREATE INDEX IF NOT EXISTS idx_instruments_type_expiry
ON instruments(
    underlying,
    instrument_type,
    expiry_date
);


-- ==========================================================
-- HISTORICAL CANDLES
--
-- RAW BROKER DATA
--
-- Do not mix calculated indicators into this table.
-- ==========================================================

CREATE TABLE IF NOT EXISTS candles (
    id INTEGER PRIMARY KEY AUTOINCREMENT,

    instrument_id INTEGER NOT NULL,

    timestamp INTEGER NOT NULL,

    open REAL NOT NULL,
    high REAL NOT NULL,
    low REAL NOT NULL,
    close REAL NOT NULL,

    volume INTEGER,
    open_interest INTEGER,

    resolution TEXT NOT NULL,
    source TEXT NOT NULL,

    created_at TEXT DEFAULT CURRENT_TIMESTAMP,

    FOREIGN KEY (instrument_id)
        REFERENCES instruments(id)
        ON DELETE CASCADE,

    UNIQUE (
        instrument_id,
        timestamp,
        resolution,
        source
    )
);


CREATE INDEX IF NOT EXISTS idx_candles_instrument_timestamp
ON candles(
    instrument_id,
    timestamp
);


CREATE INDEX IF NOT EXISTS idx_candles_timestamp
ON candles(timestamp);


CREATE INDEX IF NOT EXISTS idx_candles_instrument_resolution
ON candles(
    instrument_id,
    resolution,
    timestamp
);


-- ==========================================================
-- DOWNLOAD JOBS
-- ==========================================================

CREATE TABLE IF NOT EXISTS download_jobs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,

    broker TEXT NOT NULL,
    symbol TEXT NOT NULL,

    instrument_id INTEGER,

    resolution TEXT NOT NULL,

    range_from TEXT NOT NULL,
    range_to TEXT NOT NULL,

    status TEXT NOT NULL,

    requested_candles INTEGER DEFAULT 0,
    received_candles INTEGER DEFAULT 0,
    inserted_candles INTEGER DEFAULT 0,
    duplicate_candles INTEGER DEFAULT 0,
    missing_candles INTEGER DEFAULT 0,

    retry_count INTEGER DEFAULT 0,

    error_message TEXT,

    started_at TEXT,
    completed_at TEXT,

    created_at TEXT DEFAULT CURRENT_TIMESTAMP,

    FOREIGN KEY (instrument_id)
        REFERENCES instruments(id)
        ON DELETE SET NULL
);


CREATE INDEX IF NOT EXISTS idx_download_jobs_symbol
ON download_jobs(symbol);


CREATE INDEX IF NOT EXISTS idx_download_jobs_status
ON download_jobs(status);



-- ==========================================================
-- DATA QUALITY EVENTS
-- ==========================================================

CREATE TABLE IF NOT EXISTS data_quality_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,

    instrument_id INTEGER,
    timestamp INTEGER,

    event_type TEXT NOT NULL,
    severity TEXT NOT NULL,

    description TEXT,

    detected_at TEXT DEFAULT CURRENT_TIMESTAMP,

    FOREIGN KEY (instrument_id)
        REFERENCES instruments(id)
        ON DELETE CASCADE
);


CREATE INDEX IF NOT EXISTS idx_quality_instrument
ON data_quality_events(instrument_id);


CREATE INDEX IF NOT EXISTS idx_quality_type
ON data_quality_events(event_type);


CREATE INDEX IF NOT EXISTS idx_quality_timestamp
ON data_quality_events(timestamp);


-- ==========================================================
-- TRADING SESSIONS
-- ==========================================================

CREATE TABLE IF NOT EXISTS trading_sessions (
    trade_date TEXT PRIMARY KEY,

    exchange TEXT NOT NULL,

    market_open TEXT NOT NULL,
    market_close TEXT NOT NULL,

    expected_minutes INTEGER NOT NULL,
    actual_minutes INTEGER DEFAULT 0,

    status TEXT DEFAULT 'unknown',

    created_at TEXT DEFAULT CURRENT_TIMESTAMP
);


-- ==========================================================
-- DATASETS
-- ==========================================================

CREATE TABLE IF NOT EXISTS datasets (
    id INTEGER PRIMARY KEY AUTOINCREMENT,

    dataset_name TEXT UNIQUE NOT NULL,

    description TEXT,

    broker TEXT,
    asset_class TEXT,
    timeframe TEXT,

    date_from TEXT,
    date_to TEXT,

    instrument_count INTEGER DEFAULT 0,
    candle_count INTEGER DEFAULT 0,

    status TEXT DEFAULT 'created',

    created_at TEXT DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT DEFAULT CURRENT_TIMESTAMP
);


-- ==========================================================
-- OPTION ANALYTICS
--
-- CALCULATED / DERIVED DATA
--
-- The broker may return IV/Greeks as null historically.
-- Therefore this table stores our own calculations separately.
-- ==========================================================

CREATE TABLE IF NOT EXISTS option_analytics (
    id INTEGER PRIMARY KEY AUTOINCREMENT,

    instrument_id INTEGER NOT NULL,

    timestamp INTEGER NOT NULL,

    resolution TEXT NOT NULL,

    underlying_price REAL,

    forward_price REAL,

    expiry_date TEXT,

    strike REAL,

    option_type TEXT,

    dte REAL,

    moneyness REAL,

    implied_volatility REAL,

    delta REAL,

    gamma REAL,

    theta REAL,

    vega REAL,

    rho REAL,

    iv_source TEXT,

    greek_source TEXT,

    calculation_version TEXT,

    created_at TEXT DEFAULT CURRENT_TIMESTAMP,

    FOREIGN KEY (instrument_id)
        REFERENCES instruments(id)
        ON DELETE CASCADE,

    UNIQUE (
        instrument_id,
        timestamp,
        resolution
    )
);


CREATE INDEX IF NOT EXISTS idx_option_analytics_timestamp
ON option_analytics(timestamp);


CREATE INDEX IF NOT EXISTS idx_option_analytics_instrument
ON option_analytics(
    instrument_id,
    timestamp
);


CREATE INDEX IF NOT EXISTS idx_option_analytics_expiry_strike
ON option_analytics(
    expiry_date,
    strike,
    option_type,
    timestamp
);


-- ==========================================================
-- PRICE / OI FLOW METRICS
--
-- Derived from raw candle + OI series.
-- ==========================================================

CREATE TABLE IF NOT EXISTS flow_metrics (
    id INTEGER PRIMARY KEY AUTOINCREMENT,

    instrument_id INTEGER NOT NULL,

    timestamp INTEGER NOT NULL,

    resolution TEXT NOT NULL,

    price_change REAL,

    price_change_pct REAL,

    oi_change INTEGER,

    oi_change_pct REAL,

    volume_change INTEGER,

    volume_change_pct REAL,

    price_direction INTEGER,

    oi_direction INTEGER,

    flow_state TEXT,

    flow_strength REAL,

    calculation_version TEXT,

    created_at TEXT DEFAULT CURRENT_TIMESTAMP,

    FOREIGN KEY (instrument_id)
        REFERENCES instruments(id)
        ON DELETE CASCADE,

    UNIQUE (
        instrument_id,
        timestamp,
        resolution
    )
);


CREATE INDEX IF NOT EXISTS idx_flow_metrics_timestamp
ON flow_metrics(timestamp);


CREATE INDEX IF NOT EXISTS idx_flow_metrics_instrument
ON flow_metrics(
    instrument_id,
    timestamp
);


CREATE INDEX IF NOT EXISTS idx_flow_metrics_state
ON flow_metrics(flow_state);


-- ==========================================================
-- MARKET CONTEXT
--
-- One synchronized timestamp can contain:
--
-- NIFTY spot
-- NIFTY futures
-- India VIX
-- aggregate option-chain statistics
--
-- This is a derived convenience layer for the backtester.
-- ==========================================================

CREATE TABLE IF NOT EXISTS market_context (
    id INTEGER PRIMARY KEY AUTOINCREMENT,

    timestamp INTEGER NOT NULL,

    resolution TEXT NOT NULL,

    underlying TEXT NOT NULL,

    expiry_date TEXT NOT NULL,

    spot_price REAL,

    futures_price REAL,

    futures_oi INTEGER,

    futures_oi_change INTEGER,

    india_vix REAL,

    india_vix_change REAL,

    india_vix_change_pct REAL,

    total_call_oi INTEGER,

    total_put_oi INTEGER,

    call_oi_change INTEGER,

    put_oi_change INTEGER,

    pcr_oi REAL,

    pcr_oi_change REAL,

    atm_strike REAL,

    atm_call_price REAL,

    atm_put_price REAL,

    atm_call_iv REAL,

    atm_put_iv REAL,

    net_gex REAL,

    calculation_version TEXT,

    created_at TEXT DEFAULT CURRENT_TIMESTAMP,

    UNIQUE (
        timestamp,
        resolution,
        underlying,
        expiry_date
    )
);



CREATE INDEX IF NOT EXISTS idx_market_context_timestamp
ON market_context(timestamp);


CREATE INDEX IF NOT EXISTS idx_market_context_underlying
ON market_context(
    underlying,
    timestamp
);


-- ==========================================================
-- GEX SNAPSHOTS
--
-- One record per timestamp / expiry / strike.
--
-- The signed GEX convention remains explicit because
-- dealer positioning cannot be inferred perfectly from OI alone.
-- ==========================================================

CREATE TABLE IF NOT EXISTS gex_snapshots (
    id INTEGER PRIMARY KEY AUTOINCREMENT,

    timestamp INTEGER NOT NULL,

    resolution TEXT NOT NULL,

    underlying TEXT NOT NULL,

    expiry_date TEXT NOT NULL,

    strike REAL NOT NULL,

    spot_price REAL,

    call_oi INTEGER,
    put_oi INTEGER,

    call_gamma REAL,
    put_gamma REAL,

    call_gex REAL,
    put_gex REAL,

    gross_gex REAL,
    net_gex REAL,

    gex_convention TEXT NOT NULL,

    calculation_version TEXT,

    gex_quality TEXT,

    expiry_state TEXT,

    dte_seconds INTEGER,

    dte_minutes REAL,

    max_gamma REAL,

    gamma_1pct REAL,

    extreme_gamma INTEGER DEFAULT 0,

    quality_flags TEXT,

    created_at TEXT DEFAULT CURRENT_TIMESTAMP,

    UNIQUE (
        timestamp,
        resolution,
        underlying,
        expiry_date,
        strike,
        gex_convention
    )
);


CREATE INDEX IF NOT EXISTS idx_gex_timestamp
ON gex_snapshots(timestamp);


CREATE INDEX IF NOT EXISTS idx_gex_expiry_strike
ON gex_snapshots(
    expiry_date,
    strike,
    timestamp
);


CREATE INDEX IF NOT EXISTS idx_gex_underlying
ON gex_snapshots(
    underlying,
    timestamp
);


-- ==========================================================
-- BACKTEST RUNS
-- ==========================================================

CREATE TABLE IF NOT EXISTS backtest_runs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,

    strategy_name TEXT NOT NULL,
    strategy_version TEXT,

    instrument TEXT,

    date_from TEXT,
    date_to TEXT,

    timeframe TEXT,

    initial_capital REAL,
    final_capital REAL,

    pnl REAL,

    total_trades INTEGER,
    winning_trades INTEGER,
    losing_trades INTEGER,

    max_drawdown REAL,
    profit_factor REAL,

    status TEXT DEFAULT 'created',

    created_at TEXT DEFAULT CURRENT_TIMESTAMP,
    completed_at TEXT
);


-- ==========================================================
-- BACKTEST TRADES
-- ==========================================================

CREATE TABLE IF NOT EXISTS backtest_trades (
    id INTEGER PRIMARY KEY AUTOINCREMENT,

    backtest_run_id INTEGER NOT NULL,

    trade_number INTEGER,

    trade_date TEXT,

    symbol TEXT,

    option_type TEXT,
    strike REAL,
    expiry_date TEXT,

    entry_time INTEGER,
    entry_price REAL,

    exit_time INTEGER,
    exit_price REAL,

    quantity INTEGER,

    gross_pnl REAL,
    charges REAL,
    net_pnl REAL,

    stop_loss REAL,
    target REAL,
    rr REAL,

    exit_reason TEXT,

    FOREIGN KEY (backtest_run_id)
        REFERENCES backtest_runs(id)
        ON DELETE CASCADE
);


CREATE INDEX IF NOT EXISTS idx_backtest_trades_run
ON backtest_trades(backtest_run_id);


CREATE INDEX IF NOT EXISTS idx_backtest_trades_entry_time
ON backtest_trades(entry_time);


-- ==========================================================
-- STRATEGY EXPERIMENTS
-- Future ML/self-learning system
-- ==========================================================

CREATE TABLE IF NOT EXISTS strategy_experiments (
    id INTEGER PRIMARY KEY AUTOINCREMENT,

    strategy_name TEXT NOT NULL,

    base_version TEXT,
    proposed_version TEXT,

    change_summary TEXT,

    evidence TEXT,

    approval_status TEXT DEFAULT 'pending',

    approved_by TEXT,
    approved_at TEXT,

    created_at TEXT DEFAULT CURRENT_TIMESTAMP
);


-- ==========================================================
-- TRADE LEARNING / REVIEW
-- Future self-learning system
-- ==========================================================

CREATE TABLE IF NOT EXISTS trade_reviews (
    id INTEGER PRIMARY KEY AUTOINCREMENT,

    backtest_trade_id INTEGER,

    review_type TEXT,

    finding TEXT,

    severity TEXT,

    proposed_change TEXT,

    status TEXT DEFAULT 'pending',

    created_at TEXT DEFAULT CURRENT_TIMESTAMP,

    FOREIGN KEY (backtest_trade_id)
        REFERENCES backtest_trades(id)
        ON DELETE CASCADE
);


-- ==========================================================
-- DAILY INSTRUMENT SYNC
-- ==========================================================

CREATE TABLE IF NOT EXISTS daily_sync_runs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,

    broker TEXT NOT NULL,

    underlying TEXT NOT NULL,

    run_date TEXT NOT NULL,

    status TEXT NOT NULL,

    current_instruments INTEGER NOT NULL DEFAULT 0,

    current_expiries INTEGER NOT NULL DEFAULT 0,

    expired_expiries_detected INTEGER NOT NULL DEFAULT 0,

    expired_jobs_completed INTEGER NOT NULL DEFAULT 0,

    expired_jobs_failed INTEGER NOT NULL DEFAULT 0,

    error_message TEXT,

    started_at TEXT NOT NULL
        DEFAULT CURRENT_TIMESTAMP,

    completed_at TEXT,

    UNIQUE (
        broker,
        underlying,
        run_date
    )
);


CREATE INDEX IF NOT EXISTS idx_daily_sync_runs_lookup
ON daily_sync_runs(
    broker,
    underlying,
    run_date,
    status
);


-- ==========================================================
-- EXPIRY REGISTRY
-- ==========================================================

CREATE TABLE IF NOT EXISTS expiry_registry (
    id INTEGER PRIMARY KEY AUTOINCREMENT,

    broker TEXT NOT NULL,

    underlying_symbol TEXT NOT NULL,

    expiry_date TEXT NOT NULL,

    contract_type TEXT NOT NULL,

    source TEXT NOT NULL DEFAULT 'FYERS',

    discovered_at TEXT NOT NULL
        DEFAULT CURRENT_TIMESTAMP,

    UNIQUE (
        broker,
        underlying_symbol,
        expiry_date,
        contract_type
    )
);


CREATE INDEX IF NOT EXISTS idx_expiry_registry_lookup
ON expiry_registry(
    broker,
    underlying_symbol,
    expiry_date,
    contract_type
);


-- ==========================================================
-- EXPIRED CONTRACT REGISTRY
-- ==========================================================

CREATE TABLE IF NOT EXISTS expired_contract_registry (
    id INTEGER PRIMARY KEY AUTOINCREMENT,

    broker TEXT NOT NULL,

    underlying_symbol TEXT NOT NULL,

    expiry_date TEXT NOT NULL,

    status TEXT NOT NULL DEFAULT 'PENDING',

    attempts INTEGER NOT NULL DEFAULT 0,

    futures_count INTEGER NOT NULL DEFAULT 0,

    options_count INTEGER NOT NULL DEFAULT 0,

    total_count INTEGER NOT NULL DEFAULT 0,

    error_message TEXT,

    created_at TEXT NOT NULL
        DEFAULT CURRENT_TIMESTAMP,

    updated_at TEXT NOT NULL
        DEFAULT CURRENT_TIMESTAMP,

    started_at TEXT,

    completed_at TEXT,

    UNIQUE (
        broker,
        underlying_symbol,
        expiry_date
    )
);


CREATE INDEX IF NOT EXISTS
idx_expired_contract_registry_status
ON expired_contract_registry(
    broker,
    underlying_symbol,
    status,
    expiry_date
);


-- ==========================================================
-- SCHEMA VERSION
-- ==========================================================

"""


# ============================================================
# MIGRATION HELPERS
# ============================================================

def _column_exists(
    connection: sqlite3.Connection,
    table_name: str,
    column_name: str,
) -> bool:

    rows = connection.execute(
        f"PRAGMA table_info({table_name})"
    ).fetchall()

    return any(
        row[1] == column_name
        for row in rows
    )


def _add_column_if_missing(
    connection: sqlite3.Connection,
    table_name: str,
    column_name: str,
    column_definition: str,
) -> None:

    if _column_exists(
        connection,
        table_name,
        column_name,
    ):

        return

    connection.execute(
        f"""
        ALTER TABLE {table_name}
        ADD COLUMN {column_name}
        {column_definition}
        """
    )


def migrate_schema(
    connection: sqlite3.Connection,
) -> None:

    # --------------------------------------------------------
    # Version 1 → Version 2
    #
    # Existing databases already contain:
    #
    # - instruments
    # - candles
    # - download_jobs
    # - data_quality_events
    # - trading_sessions
    # - datasets
    # - backtest tables
    # - strategy tables
    #
    # We preserve all existing rows.
    # --------------------------------------------------------

    _add_column_if_missing(
        connection,
        "download_jobs",
        "instrument_id",
        "INTEGER",
    )

    connection.execute(
        """
        CREATE INDEX IF NOT EXISTS
        idx_download_jobs_instrument
        ON download_jobs(instrument_id)
        """
    )

        # --------------------------------------------------------
    # Version 3 → Version 4
    #
    # Persist GEX quality metadata.
    #
    # Existing GEX data is preserved.
    # --------------------------------------------------------

    _add_column_if_missing(
        connection,
        "gex_snapshots",
        "gex_quality",
        "TEXT",
    )

    _add_column_if_missing(
        connection,
        "gex_snapshots",
        "expiry_state",
        "TEXT",
    )

    _add_column_if_missing(
        connection,
        "gex_snapshots",
        "dte_seconds",
        "INTEGER",
    )

    _add_column_if_missing(
        connection,
        "gex_snapshots",
        "dte_minutes",
        "REAL",
    )

    _add_column_if_missing(
        connection,
        "gex_snapshots",
        "max_gamma",
        "REAL",
    )

    _add_column_if_missing(
        connection,
        "gex_snapshots",
        "gamma_1pct",
        "REAL",
    )

    _add_column_if_missing(
        connection,
        "gex_snapshots",
        "extreme_gamma",
        "INTEGER DEFAULT 0",
    )

    _add_column_if_missing(
        connection,
        "gex_snapshots",
        "quality_flags",
        "TEXT",
    )

    connection.execute(
        """
        CREATE INDEX IF NOT EXISTS
        idx_gex_quality
        ON gex_snapshots(
            expiry_date,
            gex_quality,
            timestamp
        )
        """
    )


# ============================================================
# DATABASE INITIALIZATION
# ============================================================

def initialize_database(
    database_path: Path | str
) -> None:

    database_path = Path(
        database_path
    )

    database_path.parent.mkdir(
        parents=True,
        exist_ok=True
    )

    connection = sqlite3.connect(
        database_path
    )

    try:

        connection.execute(
            "PRAGMA foreign_keys = ON"
        )

        # ----------------------------------------------------
        # Create all new tables/indexes.
        #
        # Existing tables are protected by IF NOT EXISTS.
        # ----------------------------------------------------

        connection.executescript(
            SCHEMA_SQL
        )

        # ----------------------------------------------------
        # Apply safe migrations.
        # ----------------------------------------------------

        migrate_schema(
            connection
        )

        # ----------------------------------------------------
        # Store schema version.
        # ----------------------------------------------------

        connection.execute(
            """
            INSERT INTO schema_metadata (
                key,
                value
            )
            VALUES (?, ?)

            ON CONFLICT(key)
            DO UPDATE SET
                value = excluded.value
            """,
            (
                "schema_version",
                str(SCHEMA_VERSION)
            )
        )

        connection.commit()

    finally:

        connection.close()


# ============================================================
# CONNECTION
# ============================================================

def get_connection(
    database_path: Path | str
) -> sqlite3.Connection:

    database_path = Path(
        database_path
    )

    database_path.parent.mkdir(
        parents=True,
        exist_ok=True
    )

    connection = sqlite3.connect(
        database_path
    )

    connection.execute(
        "PRAGMA foreign_keys = ON"
    )

    return connection


# ============================================================
# LIST TABLES
# ============================================================

def get_table_names(
    database_path: Path | str
) -> list[str]:

    connection = get_connection(
        database_path
    )

    try:

        rows = connection.execute(
            """
            SELECT name
            FROM sqlite_master
            WHERE type = 'table'
            ORDER BY name
            """
        ).fetchall()

        return [
            row[0]
            for row in rows
        ]

    finally:

        connection.close()


# ============================================================
# DATABASE SUMMARY
# ============================================================

def get_schema_summary(
    database_path: Path | str
) -> dict:

    connection = get_connection(
        database_path
    )

    try:

        tables = get_table_names(
            database_path
        )

        schema_version = connection.execute(
            """
            SELECT value
            FROM schema_metadata
            WHERE key = 'schema_version'
            """
        ).fetchone()

        instrument_count = connection.execute(
            """
            SELECT COUNT(*)
            FROM instruments
            """
        ).fetchone()[0]

        candle_count = connection.execute(
            """
            SELECT COUNT(*)
            FROM candles
            """
        ).fetchone()[0]

        expiry_count = connection.execute(
            """
            SELECT COUNT(*)
            FROM expiry_registry
            """
        ).fetchone()[0]

        expired_job_count = connection.execute(
            """
            SELECT COUNT(*)
            FROM expired_contract_registry
            """
        ).fetchone()[0]

        return {
            "schema_version": (
                schema_version[0]
                if schema_version
                else None
            ),
            "table_count": len(
                tables
            ),
            "instrument_count": int(
                instrument_count
            ),
            "candle_count": int(
                candle_count
            ),
            "expiry_count": int(
                expiry_count
            ),
            "expired_contract_jobs": int(
                expired_job_count
            ),
            "tables": tables,
        }

    finally:

        connection.close()


# ============================================================
# TEST
# ============================================================

if __name__ == "__main__":

    from config.settings import DATABASE_PATH

    print("=" * 75)

    print(
        "KUNAL QUANT - DATABASE INITIALIZATION"
    )

    print("=" * 75)

    print(
        "\nDatabase:"
    )

    print(
        DATABASE_PATH
    )

    print(
        "\nInitializing / migrating database..."
    )

    initialize_database(
        DATABASE_PATH
    )

    summary = get_schema_summary(
        DATABASE_PATH
    )

    print(
        "\nDatabase summary:"
    )

    print(
        f"  Schema version       : "
        f"{summary['schema_version']}"
    )

    print(
        f"  Instruments          : "
        f"{summary['instrument_count']}"
    )

    print(
        f"  Candles              : "
        f"{summary['candle_count']}"
    )

    print(
        f"  Expiry records       : "
        f"{summary['expiry_count']}"
    )

    print(
        f"  Expired-contract jobs: "
        f"{summary['expired_contract_jobs']}"
    )

    print(
        "\nTables:"
    )

    for table in summary["tables"]:

        print(
            f"  [OK] {table}"
        )

    print(
        "\nDatabase ready."
    )

    print("=" * 75)