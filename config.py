import os
from pathlib import Path
from dotenv import load_dotenv

load_dotenv(Path(__file__).parent / ".env")

# Build local DB URL from individual params
_host = os.environ["LOCAL_DB_HOST"]
_port = os.environ.get("LOCAL_DB_PORT", "5432")
_name = os.environ["LOCAL_DB_NAME"]
_user = os.environ["LOCAL_DB_USER"]
_pass = os.environ["LOCAL_DB_PASSWORD"]
LOCAL_DB_URL = f"postgresql://{_user}:{_pass}@{_host}:{_port}/{_name}"

NEON_DB_URL = os.environ["NEON_DB_URL"]
FMP_API_KEY = os.environ["FMP_API_KEY"]
ANTHROPIC_API_KEY = os.environ["ANTHROPIC_API_KEY"]
GMAIL_USER = os.environ["GMAIL_USER"]
GMAIL_APP_PASSWORD = os.environ["GMAIL_APP_PASSWORD"]
REPORT_RECIPIENT_EMAIL = os.environ.get("REPORT_RECIPIENT_EMAIL", GMAIL_USER)

TRANSCRIPTS_DIR = os.environ.get(
    "TRANSCRIPTS_DIR",
    str(Path.home() / "Documents" / "earnings_transcripts"),
)

FMP_BASE_URL = "https://financialmodelingprep.com/api/v3"
PRICE_BACKFILL_DAYS = 90
