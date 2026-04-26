from datetime import date, timedelta
from db.connection import get_sessions
from db.models import Stock, DailyPrice, MovingAverage, Financials, ComputedMetrics, Sentiment, Transcript, News


def _pct_change(new, old):
    if old and old != 0 and new is not None:
        return round(float((new - old) / abs(old) * 100), 2)
    return None


def quarterly_metrics(financials_rows) -> list[dict]:
    """Given Financials rows (any order), return per-quarter dicts with YOY/QOQ growth.

    Each dict has: quarter, revenue, net_income, eps, fcf, yoy_revenue,
    yoy_earnings, fcf_yoy, fcf_qoq. Latest quarter first.
    """
    rows = sorted(financials_rows, key=lambda r: (r.fiscal_year, r.fiscal_quarter), reverse=True)
    out = []
    for i, r in enumerate(rows):
        prior_year = next(
            (x for x in rows[i + 1:] if x.fiscal_year == r.fiscal_year - 1 and x.fiscal_quarter == r.fiscal_quarter),
            None,
        )
        prior_q = rows[i + 1] if i + 1 < len(rows) else None
        out.append({
            "quarter": f"Q{r.fiscal_quarter} {r.fiscal_year}",
            "revenue": r.revenue,
            "net_income": r.net_income,
            "eps": r.eps,
            "fcf": r.free_cash_flow,
            "yoy_revenue": _pct_change(r.revenue, prior_year.revenue if prior_year else None),
            "yoy_earnings": _pct_change(r.net_income, prior_year.net_income if prior_year else None),
            "fcf_yoy": _pct_change(r.free_cash_flow, prior_year.free_cash_flow if prior_year else None),
            "fcf_qoq": _pct_change(r.free_cash_flow, prior_q.free_cash_flow if prior_q else None),
        })
    return out


def generate_report_data(tickers: list[str] | None = None) -> list[dict]:
    with get_sessions() as (local, _neon):
        if tickers:
            stocks = local.query(Stock).filter(Stock.ticker.in_([t.upper() for t in tickers])).all()
        else:
            stocks = local.query(Stock).all()

        report = []
        for stock in stocks:
            report.append(_stock_snapshot(local, stock))

    return report


def _stock_snapshot(session, stock) -> dict:
    # Latest price
    price_row = (
        session.query(DailyPrice)
        .filter_by(stock_id=stock.id)
        .order_by(DailyPrice.date.desc())
        .first()
    )

    # Previous day price for % change
    prev_price_row = (
        session.query(DailyPrice)
        .filter_by(stock_id=stock.id)
        .order_by(DailyPrice.date.desc())
        .offset(1)
        .first()
    )

    price_change_pct = None
    if price_row and prev_price_row and prev_price_row.close:
        price_change_pct = round((price_row.close - prev_price_row.close) / prev_price_row.close * 100, 2)

    # Moving averages
    ma_row = (
        session.query(MovingAverage)
        .filter_by(stock_id=stock.id)
        .order_by(MovingAverage.date.desc())
        .first()
    )

    # Latest financials (last 4 quarters)
    fin_rows = (
        session.query(Financials)
        .filter_by(stock_id=stock.id)
        .order_by(Financials.fiscal_year.desc(), Financials.fiscal_quarter.desc())
        .limit(4)
        .all()
    )

    # Latest computed metrics
    metrics_row = (
        session.query(ComputedMetrics)
        .filter_by(stock_id=stock.id)
        .order_by(ComputedMetrics.computed_date.desc())
        .first()
    )

    # Latest sentiment
    latest_transcript = (
        session.query(Transcript)
        .filter_by(stock_id=stock.id)
        .order_by(Transcript.fiscal_year.desc(), Transcript.fiscal_quarter.desc())
        .first()
    )
    sentiment = latest_transcript.sentiment if latest_transcript else None

    # Significant news (last 90 days)
    cutoff = date.today() - timedelta(days=90)
    news_rows = (
        session.query(News)
        .filter(
            News.stock_id == stock.id,
            News.is_significant == True,
            News.published_at >= cutoff,
        )
        .order_by(News.published_at.desc())
        .limit(5)
        .all()
    )

    return {
        "ticker": stock.ticker,
        "company_name": stock.company_name,
        "price": {
            "close": price_row.close if price_row else None,
            "date": str(price_row.date) if price_row else None,
            "change_pct": price_change_pct,
            "pe_ratio": price_row.pe_ratio if price_row else None,
            "eps": price_row.eps if price_row else None,
            "high_52w": price_row.fifty_two_week_high if price_row else None,
            "low_52w": price_row.fifty_two_week_low if price_row else None,
            "debt_to_equity": price_row.debt_to_equity if price_row else None,
        },
        "moving_averages": {
            "ma_30": ma_row.ma_30 if ma_row else None,
            "ma_60": ma_row.ma_60 if ma_row else None,
            "ma_90": ma_row.ma_90 if ma_row else None,
            "date": str(ma_row.date) if ma_row else None,
        },
        "financials": [
            {
                "fiscal_year": r.fiscal_year,
                "fiscal_quarter": r.fiscal_quarter,
                "revenue": r.revenue,
                "net_income": r.net_income,
                "eps": r.eps,
                "free_cash_flow": r.free_cash_flow,
            }
            for r in fin_rows
        ],
        "quarterly_breakdown": quarterly_metrics(
            session.query(Financials)
            .filter_by(stock_id=stock.id)
            .order_by(Financials.fiscal_year.desc(), Financials.fiscal_quarter.desc())
            .limit(9)
            .all()
        )[:5],
        "data_as_of": {
            "price_date": str(price_row.date) if price_row else None,
            "ma_date": str(ma_row.date) if ma_row else None,
            "financials_reported": str(fin_rows[0].reported_date) if fin_rows and fin_rows[0].reported_date else None,
            "sentiment_analyzed": str(sentiment.analyzed_at)[:16] if sentiment else None,
        },
        "metrics": {
            "yoy_revenue_growth": metrics_row.yoy_revenue_growth if metrics_row else None,
            "yoy_earnings_growth": metrics_row.yoy_earnings_growth if metrics_row else None,
            "fcf_yoy": metrics_row.fcf_yoy if metrics_row else None,
            "fcf_qoq": metrics_row.fcf_qoq if metrics_row else None,
        } if metrics_row else {},
        "sentiment": {
            "overall_score": sentiment.overall_score,
            "tone_label": sentiment.tone_label,
            "key_themes": sentiment.key_themes,
            "management_confidence": sentiment.management_confidence,
            "guidance_sentiment": sentiment.guidance_sentiment,
            "summary": sentiment.summary,
            "quarter": f"Q{latest_transcript.fiscal_quarter} {latest_transcript.fiscal_year}",
        } if sentiment else None,
        "significant_news": [
            {
                "headline": n.headline,
                "url": n.url,
                "source": n.source,
                "published_at": str(n.published_at),
                "reason": n.significance_reason,
            }
            for n in news_rows
        ],
    }
