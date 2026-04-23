from datetime import date
from sqlalchemy.dialects.postgresql import insert
from db.connection import get_sessions
from db.models import Stock, Financials, ComputedMetrics


def _pct_change(new, old):
    if old and old != 0 and new is not None:
        return round((new - old) / abs(old) * 100, 2)
    return None


def compute_and_store_metrics(ticker: str):
    with get_sessions() as (local, neon):
        stock = local.query(Stock).filter_by(ticker=ticker.upper()).first()
        if not stock:
            raise ValueError(f"Ticker {ticker} not found.")

        rows = (
            local.query(Financials)
            .filter_by(stock_id=stock.id)
            .order_by(Financials.fiscal_year.desc(), Financials.fiscal_quarter.desc())
            .limit(8)
            .all()
        )

        if len(rows) < 2:
            return 0

        # Latest quarter
        latest = rows[0]
        prev_quarter = rows[1] if len(rows) > 1 else None

        # Same quarter prior year
        prior_year = next(
            (r for r in rows[1:] if r.fiscal_quarter == latest.fiscal_quarter and r.fiscal_year == latest.fiscal_year - 1),
            None,
        )

        yoy_revenue = _pct_change(latest.revenue, prior_year.revenue if prior_year else None)
        yoy_earnings = _pct_change(latest.net_income, prior_year.net_income if prior_year else None)
        fcf_yoy = _pct_change(latest.free_cash_flow, prior_year.free_cash_flow if prior_year else None)
        fcf_qoq = _pct_change(latest.free_cash_flow, prev_quarter.free_cash_flow if prev_quarter else None)

        metrics = {
            "computed_date": date.today(),
            "yoy_revenue_growth": yoy_revenue,
            "yoy_earnings_growth": yoy_earnings,
            "fcf_yoy": fcf_yoy,
            "fcf_qoq": fcf_qoq,
        }

        def _store(session, stock_id):
            stmt = insert(ComputedMetrics).values(stock_id=stock_id, **metrics)
            stmt = stmt.on_conflict_do_update(
                index_elements=["stock_id", "computed_date"],
                set_={k: v for k, v in metrics.items()},
            )
            session.execute(stmt)

        local_id = stock.id
        neon_id = neon.query(Stock).filter_by(ticker=ticker.upper()).first().id
        _store(local, local_id)
        _store(neon, neon_id)

    return 1
