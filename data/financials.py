import yfinance as yf
import pandas as pd
from sqlalchemy.dialects.postgresql import insert
from db.connection import get_sessions
from db.models import Financials, Stock


def _get_stock_id(session, ticker: str) -> int:
    stock = session.query(Stock).filter_by(ticker=ticker.upper()).first()
    if not stock:
        raise ValueError(f"Ticker {ticker} not found in portfolio.")
    return stock.id


def fetch_and_store_financials(ticker: str):
    t = yf.Ticker(ticker.upper())

    income = t.quarterly_income_stmt
    cashflow = t.quarterly_cashflow

    rows = []
    if income is not None and not income.empty:
        for col in income.columns:
            try:
                dt = pd.Timestamp(col)
                fiscal_year = dt.year
                fiscal_quarter = (dt.month - 1) // 3 + 1

                revenue = _safe_get(income, col, ["Total Revenue"])
                net_income = _safe_get(income, col, ["Net Income"])
                eps = _safe_get(income, col, ["Diluted EPS", "Basic EPS"])

                fcf = None
                if cashflow is not None and not cashflow.empty and col in cashflow.columns:
                    ops = _safe_get(cashflow, col, ["Operating Cash Flow", "Total Cash From Operating Activities"])
                    capex = _safe_get(cashflow, col, ["Capital Expenditure", "Capital Expenditures"])
                    if ops is not None and capex is not None:
                        fcf = float(ops - abs(capex))

                rows.append({
                    "fiscal_year": fiscal_year,
                    "fiscal_quarter": fiscal_quarter,
                    "revenue": revenue,
                    "net_income": net_income,
                    "eps": eps,
                    "free_cash_flow": fcf,
                    "reported_date": dt.date(),
                })
            except Exception:
                continue

    def _store(session, stock_id, rows):
        for r in rows:
            stmt = insert(Financials).values(stock_id=stock_id, **r)
            stmt = stmt.on_conflict_do_update(
                index_elements=["stock_id", "fiscal_year", "fiscal_quarter"],
                set_={k: v for k, v in r.items()},
            )
            session.execute(stmt)

    with get_sessions() as (local, neon):
        local_id = _get_stock_id(local, ticker)
        neon_id = _get_stock_id(neon, ticker)
        _store(local, local_id, rows)
        _store(neon, neon_id, rows)

    return len(rows)


def _safe_get(df, col, keys):
    for key in keys:
        if key in df.index:
            val = df.loc[key, col]
            if pd.notna(val):
                return float(val)
    return None
