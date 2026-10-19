from pathlib import Path
import os

from dotenv import load_dotenv


# ============================================================
# KUNAL QUANT
# GLOBAL CONFIGURATION
# ============================================================

PROJECT_ROOT = Path(__file__).resolve().parents[1]

# Load local secrets/configuration
load_dotenv(PROJECT_ROOT / ".env")


# ------------------------------------------------------------
# PROJECT
# ------------------------------------------------------------

PROJECT_NAME = "Kunal Quant"
PROJECT_VERSION = "1.0.0"
ENVIRONMENT = os.getenv(
    "KUNAL_QUANT_ENV",
    "development"
).strip().lower()


# ------------------------------------------------------------
# DIRECTORIES
# ------------------------------------------------------------

DATA_DIR = PROJECT_ROOT / "data"

RAW_DATA_DIR = DATA_DIR / "raw"
PROCESSED_DATA_DIR = DATA_DIR / "processed"
REPORTS_DIR = DATA_DIR / "reports"
DATABASE_DIR = DATA_DIR / "database"

for directory in (
    DATA_DIR,
    RAW_DATA_DIR,
    PROCESSED_DATA_DIR,
    REPORTS_DIR,
    DATABASE_DIR,
):
    directory.mkdir(parents=True, exist_ok=True)


# ------------------------------------------------------------
# DATABASE
# ------------------------------------------------------------

DATABASE_PATH = DATABASE_DIR / "kunal_quant.db"


# ------------------------------------------------------------
# TIMEZONE
# ------------------------------------------------------------

TIMEZONE = "Asia/Kolkata"


# ------------------------------------------------------------
# NSE TRADING SESSION
# ------------------------------------------------------------

MARKET_OPEN = "09:15"
MARKET_CLOSE = "15:30"

EXPECTED_FIRST_CANDLE = "09:15:00"
EXPECTED_LAST_1M_CANDLE = "15:29:00"

EXPECTED_1M_CANDLES = 375


# ------------------------------------------------------------
# FYERS
# ------------------------------------------------------------

FYERS_CLIENT_ID = os.getenv(
    "FYERS_CLIENT_ID",
    ""
).strip()

FYERS_TOKEN_FILE = PROJECT_ROOT / "fyers_access_token.txt"


def get_fyers_access_token() -> str:
    """Read the locally stored FYERS access token."""

    if not FYERS_TOKEN_FILE.exists():
        raise FileNotFoundError(
            f"FYERS token file not found: {FYERS_TOKEN_FILE}"
        )

    token = FYERS_TOKEN_FILE.read_text(
        encoding="utf-8"
    ).strip()

    if not token:
        raise ValueError(
            "FYERS access token file is empty."
        )

    return token


def get_fyers_auth_token() -> str:
    """
    Build the FYERS authentication token used by
    the WebSocket:

        CLIENT_ID:ACCESS_TOKEN
    """

    if not FYERS_CLIENT_ID:
        raise ValueError(
            "FYERS_CLIENT_ID is missing from .env"
        )

    return f"{FYERS_CLIENT_ID}:{get_fyers_access_token()}"


# ------------------------------------------------------------
# HISTORICAL DATA
# ------------------------------------------------------------

PRIMARY_RESOLUTION = "1"

SUPPORTED_RESOLUTIONS = (
    "1",
    "3",
    "5",
    "15",
    "30",
    "60",
)


# ------------------------------------------------------------
# OPTIONS
# ------------------------------------------------------------

# Initial research range around ATM.
OPTION_STRIKE_RANGE = 10


# ------------------------------------------------------------
# DOWNLOADER
# ------------------------------------------------------------

MAX_RETRIES = 3
REQUEST_TIMEOUT_SECONDS = 30
RETRY_DELAY_SECONDS = 2


# ------------------------------------------------------------
# VALIDATION
# ------------------------------------------------------------

REQUIRE_OPEN_INTEREST_FOR_OPTIONS = True

ALLOW_ZERO_VOLUME_CANDLES = True


# ------------------------------------------------------------
# CONFIG VALIDATION
# ------------------------------------------------------------

def validate_configuration() -> None:
    """Validate required local configuration."""

    if not FYERS_CLIENT_ID:
        raise ValueError(
            "FYERS_CLIENT_ID is missing from .env"
        )

    if not FYERS_TOKEN_FILE.exists():
        raise FileNotFoundError(
            "fyers_access_token.txt is missing."
        )