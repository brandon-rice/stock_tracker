from datetime import date, timedelta
import yfinance as yf
from sqlalchemy.dialects.postgresql import insert
from db.connection import get_sessions
from db.models import DailyPrice, Stock


def _get_stock_id(session, ticker: str) -> int:
    stock = session.query(Stock).filter_by(ticker=ticker.upper()).first()
    if not stock:
        raise ValueError(f"Ticker {ticker} not found in portfolio. Run `add` first.")
    return stock.id


def _safe_info(t) -> dict:
    import time
    for attempt in range(3):
        try:
            return t.info or {}
        except Exception:
            if attempt < 2:
                time.sleep(2 ** attempt)
    return {}


def fetch_and_store_prices(ticker: str, start: date = None, end: date = None):
    t = yf.Ticker(ticker.upper())
    info = _safe_info(t)

    if start and end:
        hist = t.history(start=str(start), end=str(end))
    else:
        hist = t.history(period="1d")

    pe_ratio = info.get("trailingPE") or info.get("forwardPE")
    eps = info.get("trailingEps")
    high_52w = info.get("fiftyTwoWeekHigh")
    low_52w = info.get("fiftyTwoWeekLow")
    debt_to_equity = info.get("debtToEquity")

    def _f(v):
        try:
            return float(v) if v is not None else None
        except (TypeError, ValueError):
            return None

    rows = []
    for ts, row in hist.iterrows():
        rows.append({
            "date": ts.date(),
            "open": _f(row.get("Open")),
            "high": _f(row.get("High")),
            "low": _f(row.get("Low")),
            "close": _f(row.get("Close")),
            "volume": _f(row.get("Volume")),
            "adj_close": _f(row.get("Close")),
            "pe_ratio": _f(pe_ratio),
            "eps": _f(eps),
            "fifty_two_week_high": _f(high_52w),
            "fifty_two_week_low": _f(low_52w),
            "debt_to_equity": _f(debt_to_equity),
        })

    def _store(session, stock_id, rows):
        for r in rows:
            stmt = insert(DailyPrice).values(stock_id=stock_id, **r)
            stmt = stmt.on_conflict_do_update(
                index_elements=["stock_id", "date"],
                set_={k: v for k, v in r.items()},
            )
            session.execute(stmt)

    with get_sessions() as (local, neon):
        local_id = _get_stock_id(local, ticker)
        neon_id = _get_stock_id(neon, ticker)
        _store(local, local_id, rows)
        _store(neon, neon_id, rows)

    return len(rows)


def backfill_prices(ticker: str, days: int = 90):
    end = date.today()
    start = end - timedelta(days=days)
    return fetch_and_store_prices(ticker, start=start, end=end)
