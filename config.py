import os
from dotenv import load_dotenv

load_dotenv()

LOCAL_DB_URL = os.environ["LOCAL_DB_URL"]
NEON_DB_URL = os.environ["NEON_DB_URL"]
FMP_API_KEY = os.environ["FMP_API_KEY"]
ANTHROPIC_API_KEY = os.environ["ANTHROPIC_API_KEY"]
GMAIL_USER = os.environ["GMAIL_USER"]
GMAIL_APP_PASSWORD = os.environ["GMAIL_APP_PASSWORD"]
REPORT_RECIPIENT_EMAIL = os.environ.get("REPORT_RECIPIENT_EMAIL", GMAIL_USER)

FMP_BASE_URL = "https://financialmodelingprep.com/api/v3"
PRICE_BACKFILL_DAYS = 90
