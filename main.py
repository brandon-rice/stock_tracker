import click
import yfinance as yf
from datetime import date, timedelta
from db.init_db import init_db
from db.connection import get_sessions
from db.models import Stock, DailyPrice, MovingAverage, ComputedMetrics, Financials, News
from data.prices import fetch_and_store_prices, backfill_prices
from data.financials import fetch_and_store_financials
from data.transcripts import fetch_and_store_transcript, load_transcript_from_file
from data.sec_edgar import backfill_from_sec
from data.news import fetch_and_store_news
from analysis.moving_averages import compute_and_store_moving_averages
from analysis.metrics import compute_and_store_metrics
from analysis.sentiment import analyze_and_store_sentiment
from analysis.quarterly import generate_report_data
from notifications.email import render_html_report, send_report as _send_email


@click.group()
def cli():
    """Stock Portfolio Tracker"""


@cli.command()
def init_db_cmd():
    """Create tables on local and Neon databases."""
    init_db()


def _get_company_name(ticker: str) -> str:
    import time
    for attempt in range(3):
        try:
            info = yf.Ticker(ticker).info
            return info.get("longName") or info.get("shortName") or ticker
        except Exception:
            if attempt < 2:
                time.sleep(2 ** attempt)
    return ticker


@cli.command()
@click.argument("ticker")
def add(ticker: str):
    """Add a stock to the portfolio and backfill 90 days of data."""
    ticker = ticker.upper()

    company_name = _get_company_name(ticker)

    with get_sessions() as (local, neon):
        for session in (local, neon):
            existing = session.query(Stock).filter_by(ticker=ticker).first()
            if not existing:
                session.add(Stock(ticker=ticker, company_name=company_name))

    click.echo(f"Added {ticker} ({company_name})")

    click.echo("Backfilling 90 days of prices...")
    n = backfill_prices(ticker, days=90)
    click.echo(f"  Stored {n} price rows")

    click.echo("Fetching recent financials (yfinance)...")
    n = fetch_and_store_financials(ticker)
    click.echo(f"  Stored {n} quarterly financials")

    click.echo("Backfilling historical financials (SEC EDGAR)...")
    try:
        n = backfill_from_sec(ticker)
        click.echo(f"  Backfilled {n} quarters from SEC")
    except Exception as e:
        click.echo(f"  SEC backfill failed: {e}")

    click.echo("Computing moving averages...")
    compute_and_store_moving_averages(ticker)

    click.echo("Computing growth metrics...")
    compute_and_store_metrics(ticker)

    click.echo(f"{ticker} is ready.")


@cli.command()
@click.argument("ticker")
def remove(ticker: str):
    """Remove a stock from the portfolio."""
    ticker = ticker.upper()
    with get_sessions() as (local, neon):
        for session in (local, neon):
            stock = session.query(Stock).filter_by(ticker=ticker).first()
            if stock:
                session.delete(stock)
    click.echo(f"Removed {ticker}.")


@cli.command("list")
def list_stocks():
    """List all tracked stocks with latest price."""
    with get_sessions() as (local, _):
        stocks = local.query(Stock).order_by(Stock.ticker).all()
        if not stocks:
            click.echo("No stocks in portfolio.")
            return
        click.echo(f"\n{'TICKER':<8} {'COMPANY':<35} {'PRICE':>10} {'CHANGE':>8}")
        click.echo("-" * 65)
        for s in stocks:
            p = local.query(DailyPrice).filter_by(stock_id=s.id).order_by(DailyPrice.date.desc()).first()
            prev = local.query(DailyPrice).filter_by(stock_id=s.id).order_by(DailyPrice.date.desc()).offset(1).first()
            price_str = f"${p.close:,.2f}" if p and p.close else "N/A"
            chg = ""
            if p and prev and prev.close:
                pct = (p.close - prev.close) / prev.close * 100
                chg = f"{'+' if pct > 0 else ''}{pct:.2f}%"
            click.echo(f"{s.ticker:<8} {(s.company_name or ''):<35} {price_str:>10} {chg:>8}")


def _get_tickers(ticker_arg):
    """Return list of ticker strings from DB. Stays inside session so no DetachedInstanceError."""
    with get_sessions() as (local, _):
        if ticker_arg:
            s = local.query(Stock).filter_by(ticker=ticker_arg.upper()).first()
            return [ticker_arg.upper()] if s else []
        return [s.ticker for s in local.query(Stock).all()]


@cli.command()
@click.option("--ticker", default=None, help="Fetch for a single ticker (also fetches news)")
def fetch_prices(ticker):
    """Fetch today's prices and metrics for all stocks (or one)."""
    tickers = _get_tickers(ticker)
    if not tickers:
        click.echo(f"Ticker {ticker} not found." if ticker else "No stocks in portfolio.")
        return
    for t in tickers:
        click.echo(f"Fetching prices for {t}...")
        n = fetch_and_store_prices(t)
        click.echo(f"  {n} row(s) stored")
        if ticker:
            click.echo(f"Fetching significant news for {t}...")
            n = fetch_and_store_news(t)
            click.echo(f"  {n} significant article(s) found")


@cli.command()
@click.option("--ticker", default=None)
def fetch_financials(ticker):
    """Fetch latest quarterly financials for all stocks (or one)."""
    tickers = _get_tickers(ticker)
    if not tickers:
        click.echo(f"Ticker {ticker} not found." if ticker else "No stocks in portfolio.")
        return
    for t in tickers:
        click.echo(f"Fetching financials for {t}...")
        n = fetch_and_store_financials(t)
        click.echo(f"  {n} quarter(s) stored")


@cli.command("backfill-financials")
@click.option("--ticker", default=None)
def backfill_financials(ticker):
    """Backfill multi-year quarterly financials from SEC EDGAR (free)."""
    tickers = _get_tickers(ticker)
    if not tickers:
        click.echo(f"Ticker {ticker} not found." if ticker else "No stocks in portfolio.")
        return
    for t in tickers:
        click.echo(f"Backfilling {t} from SEC EDGAR...")
        try:
            n = backfill_from_sec(t)
            click.echo(f"  {n} quarter(s) backfilled")
        except Exception as e:
            click.echo(f"  failed: {e}")


@cli.command()
@click.option("--ticker", default=None)
def compute_averages(ticker):
    """Compute 30/60/90 day moving averages."""
    tickers = _get_tickers(ticker)
    for t in tickers:
        n = compute_and_store_moving_averages(t)
        click.echo(f"{t}: {n} MA rows computed")


@cli.command()
@click.option("--ticker", default=None)
def compute_metrics(ticker):
    """Compute YOY/QOQ growth metrics."""
    tickers = _get_tickers(ticker)
    for t in tickers:
        compute_and_store_metrics(t)
        click.echo(f"{t}: metrics computed")


@cli.command()
@click.option("--ticker", default=None)
def fetch_news(ticker):
    """Fetch and filter significant news."""
    tickers = _get_tickers(ticker)
    if not tickers:
        click.echo(f"Ticker {ticker} not found." if ticker else "No stocks in portfolio.")
        return
    for t in tickers:
        click.echo(f"Fetching news for {t}...")
        n = fetch_and_store_news(t)
        click.echo(f"  {n} significant article(s)")


@cli.command()
@click.argument("ticker")
@click.argument("year", type=int)
@click.argument("quarter", type=int)
def fetch_transcript(ticker, year, quarter):
    """Fetch transcript from FMP API (paid plan required). E.g.: fetch-transcript AAPL 2024 4"""
    click.echo(f"Fetching transcript for {ticker.upper()} Q{quarter} {year}...")
    text = fetch_and_store_transcript(ticker, year, quarter)
    if text:
        click.echo(f"  Transcript stored ({len(text)} chars)")
        click.echo("Running sentiment analysis...")
        result = analyze_and_store_sentiment(ticker, year, quarter)
        if result:
            click.echo(f"  Tone: {result['tone_label']} (score: {result['overall_score']:+.2f})")
            click.echo(f"  Guidance: {result['guidance_sentiment']}")
            click.echo(f"  Summary: {result['summary']}")


@cli.command("load-transcript")
@click.argument("ticker")
@click.argument("year", type=int)
@click.argument("quarter", type=int)
def load_transcript(ticker, year, quarter):
    """Load transcript from local file and run sentiment. E.g.: load-transcript AAPL 2025 4

    Reads from $TRANSCRIPTS_DIR/{TICKER}/{YEAR}_Q{N}.md
    """
    text = load_transcript_from_file(ticker, year, quarter)
    if not text:
        return
    click.echo("Running sentiment analysis...")
    result = analyze_and_store_sentiment(ticker, year, quarter)
    if result:
        click.echo(f"  Tone: {result['tone_label']} (score: {result['overall_score']:+.2f})")
        click.echo(f"  Guidance: {result['guidance_sentiment']}")
        click.echo(f"  Confidence: {result['management_confidence']}")
        click.echo(f"  Themes: {', '.join(result.get('key_themes', []))}")
        click.echo(f"  Summary: {result['summary']}")


@cli.command()
def portfolio_summary():
    """Print a full portfolio summary to the terminal."""
    report = generate_report_data()
    if not report:
        click.echo("No stocks in portfolio.")
        return

    for s in report:
        p = s["price"]
        ma = s["moving_averages"]
        m = s.get("metrics", {})

        click.echo(f"\n{'='*65}")
        click.echo(f"  {s['ticker']}  {s.get('company_name','')}")
        click.echo(f"{'='*65}")

        price_str = f"${p['close']:,.2f}" if p['close'] else "N/A"
        chg = f"({'+' if (p['change_pct'] or 0) > 0 else ''}{p['change_pct']:.2f}%)" if p['change_pct'] is not None else ""
        click.echo(f"  Price:          {price_str} {chg}  [{p.get('date','')}]")
        click.echo(f"  52W High/Low:   ${p['high_52w']:,.2f} / ${p['low_52w']:,.2f}" if p['high_52w'] and p['low_52w'] else "  52W High/Low:   N/A")
        click.echo(f"  PE Ratio:       {p['pe_ratio']:.2f}" if p['pe_ratio'] else "  PE Ratio:       N/A")
        click.echo(f"  EPS:            ${p['eps']:.2f}" if p['eps'] else "  EPS:            N/A")
        click.echo(f"  Debt/Equity:    {p['debt_to_equity']:.2f}" if p['debt_to_equity'] else "  Debt/Equity:    N/A")

        click.echo(f"\n  Moving Averages:")
        click.echo(f"    30-day: ${ma['ma_30']:,.2f}" if ma.get('ma_30') else "    30-day: N/A")
        click.echo(f"    60-day: ${ma['ma_60']:,.2f}" if ma.get('ma_60') else "    60-day: N/A")
        click.echo(f"    90-day: ${ma['ma_90']:,.2f}" if ma.get('ma_90') else "    90-day: N/A")

        click.echo(f"\n  Growth Metrics:")
        click.echo(f"    YOY Revenue Growth:   {m.get('yoy_revenue_growth'):+.2f}%" if m.get('yoy_revenue_growth') is not None else "    YOY Revenue Growth:   N/A")
        click.echo(f"    YOY Earnings Growth:  {m.get('yoy_earnings_growth'):+.2f}%" if m.get('yoy_earnings_growth') is not None else "    YOY Earnings Growth:  N/A")
        click.echo(f"    FCF YOY:              {m.get('fcf_yoy'):+.2f}%" if m.get('fcf_yoy') is not None else "    FCF YOY:              N/A")
        click.echo(f"    FCF QOQ:              {m.get('fcf_qoq'):+.2f}%" if m.get('fcf_qoq') is not None else "    FCF QOQ:              N/A")

        fin = s.get("financials", [])
        if fin:
            click.echo(f"\n  Recent Financials:")
            click.echo(f"    {'Quarter':<10} {'Revenue':>12} {'Net Income':>12} {'FCF':>12}")
            for f in fin:
                rev = f"${f['revenue']/1e9:.2f}B" if f['revenue'] else "N/A"
                ni = f"${f['net_income']/1e9:.2f}B" if f['net_income'] else "N/A"
                fcf = f"${f['free_cash_flow']/1e9:.2f}B" if f['free_cash_flow'] else "N/A"
                click.echo(f"    Q{f['fiscal_quarter']} {f['fiscal_year']:<6} {rev:>12} {ni:>12} {fcf:>12}")

        sent = s.get("sentiment")
        if sent:
            click.echo(f"\n  Earnings Sentiment ({sent.get('quarter','')}):")
            click.echo(f"    Tone:       {sent['tone_label']} ({sent['overall_score']:+.2f})")
            click.echo(f"    Guidance:   {sent['guidance_sentiment']}")
            click.echo(f"    Confidence: {sent['management_confidence']}")
            click.echo(f"    Summary:    {sent['summary']}")

        news = s.get("significant_news", [])
        if news:
            click.echo(f"\n  Significant News:")
            for n in news[:3]:
                click.echo(f"    - {n['headline']}")
                click.echo(f"      {n['source']} | {n['published_at'][:10] if n['published_at'] else ''}")


@cli.command()
def send_report():
    """Generate and email the portfolio report."""
    click.echo("Generating report...")
    report = generate_report_data()
    if not report:
        click.echo("No stocks in portfolio.")
        return

    html = render_html_report(report)

    from datetime import datetime
    from db.connection import get_sessions
    from db.models import QuarterlyReport

    with get_sessions() as (local, neon):
        for session in (local, neon):
            session.add(QuarterlyReport(report_html=html))

    click.echo("Sending email...")
    success = _send_email(html)
    if success:
        from db.connection import get_sessions
        from db.models import QuarterlyReport
        from datetime import datetime
        with get_sessions() as (local, neon):
            for session in (local, neon):
                report_row = session.query(QuarterlyReport).order_by(QuarterlyReport.generated_at.desc()).first()
                if report_row:
                    report_row.sent_at = datetime.utcnow()
        click.echo("Report sent.")
    else:
        click.echo("Failed to send email. Check Gmail credentials.")


@cli.command("start-scheduler")
def start_scheduler():
    """Start the APScheduler background daemon."""
    from scheduler import start
    start()


# Alias for init-db command name
cli.add_command(init_db_cmd, name="init-db")


if __name__ == "__main__":
    cli()
