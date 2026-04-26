import requests
from datetime import datetime
from pathlib import Path
from sqlalchemy.dialects.postgresql import insert
from config import FMP_API_KEY, FMP_BASE_URL, TRANSCRIPTS_DIR
from db.connection import get_sessions
from db.models import Transcript, Stock


def _get_stock_id(session, ticker: str) -> int:
    stock = session.query(Stock).filter_by(ticker=ticker.upper()).first()
    if not stock:
        raise ValueError(f"Ticker {ticker} not found in portfolio.")
    return stock.id


def fetch_and_store_transcript(ticker: str, year: int, quarter: int) -> str | None:
    url = f"{FMP_BASE_URL}/earning_call_transcript/{ticker.upper()}"
    resp = requests.get(url, params={"quarter": quarter, "year": year, "apikey": FMP_API_KEY}, timeout=30)
    if resp.status_code == 403:
        print("FMP transcript fetch failed: 403 Forbidden. Earnings call transcripts require an FMP paid plan (Starter or above).")
        return None
    resp.raise_for_status()
    data = resp.json()

    if not data:
        print(f"No transcript found for {ticker} Q{quarter} {year}")
        return None

    text = data[0].get("content", "")
    if not text:
        return None

    def _store(session, stock_id):
        stmt = insert(Transcript).values(
            stock_id=stock_id,
            fiscal_year=year,
            fiscal_quarter=quarter,
            transcript_text=text,
            fetched_at=datetime.utcnow(),
        )
        stmt = stmt.on_conflict_do_update(
            index_elements=["stock_id", "fiscal_year", "fiscal_quarter"],
            set_={"transcript_text": text, "fetched_at": datetime.utcnow()},
        )
        session.execute(stmt)

    with get_sessions() as (local, neon):
        local_id = _get_stock_id(local, ticker)
        neon_id = _get_stock_id(neon, ticker)
        _store(local, local_id)
        _store(neon, neon_id)

    return text


def _find_transcript_file(ticker: str, year: int, quarter: int) -> Path | None:
    base = Path(TRANSCRIPTS_DIR)
    if not base.exists():
        return None
    # Case-insensitive ticker folder lookup
    ticker_dirs = [d for d in base.iterdir() if d.is_dir() and d.name.upper() == ticker.upper()]
    if not ticker_dirs:
        return None
    folder = ticker_dirs[0]
    # Try .md then .txt with year_QN naming
    for ext in (".md", ".txt"):
        for name in (f"{year}_Q{quarter}{ext}", f"Q{quarter}_{year}{ext}"):
            p = folder / name
            if p.exists():
                return p
    return None


def load_transcript_from_file(ticker: str, year: int, quarter: int) -> str | None:
    path = _find_transcript_file(ticker, year, quarter)
    if not path:
        print(f"No transcript file found for {ticker} Q{quarter} {year}")
        print(f"  Looked in: {Path(TRANSCRIPTS_DIR) / ticker.upper()}/{year}_Q{quarter}.md")
        return None

    text = path.read_text(encoding="utf-8").strip()
    if not text:
        print(f"Transcript file is empty: {path}")
        return None

    def _store(session, stock_id):
        stmt = insert(Transcript).values(
            stock_id=stock_id,
            fiscal_year=year,
            fiscal_quarter=quarter,
            transcript_text=text,
            fetched_at=datetime.utcnow(),
        )
        stmt = stmt.on_conflict_do_update(
            index_elements=["stock_id", "fiscal_year", "fiscal_quarter"],
            set_={"transcript_text": text, "fetched_at": datetime.utcnow()},
        )
        session.execute(stmt)

    with get_sessions() as (local, neon):
        local_id = _get_stock_id(local, ticker)
        neon_id = _get_stock_id(neon, ticker)
        _store(local, local_id)
        _store(neon, neon_id)

    print(f"Loaded transcript from {path} ({len(text):,} chars)")
    return text


def get_transcript_id(session, stock_id: int, year: int, quarter: int) -> int | None:
    row = session.query(Transcript).filter_by(
        stock_id=stock_id, fiscal_year=year, fiscal_quarter=quarter
    ).first()
    return row.id if row else None
