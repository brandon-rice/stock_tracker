from apscheduler.schedulers.blocking import BlockingScheduler
from apscheduler.triggers.cron import CronTrigger
from db.connection import get_sessions
from db.models import Stock


def run_daily_update():
    print("Running daily price + news + MA update...")
    with get_sessions() as (local, _):
        tickers = [s.ticker for s in local.query(Stock).all()]

    from data.prices import fetch_and_store_prices
    from data.news import fetch_and_store_news
    from analysis.moving_averages import compute_and_store_moving_averages

    for ticker in tickers:
        try:
            fetch_and_store_prices(ticker)
            fetch_and_store_news(ticker)
            compute_and_store_moving_averages(ticker)
            print(f"  {ticker} updated")
        except Exception as e:
            print(f"  {ticker} failed: {e}")


def run_quarterly_report():
    print("Running quarterly report...")
    with get_sessions() as (local, _):
        tickers = [s.ticker for s in local.query(Stock).all()]

    from data.financials import fetch_and_store_financials
    from analysis.metrics import compute_and_store_metrics
    from analysis.quarterly import generate_report_data
    from notifications.email import render_html_report, send_report
    from datetime import datetime

    for ticker in tickers:
        try:
            fetch_and_store_financials(ticker)
            compute_and_store_metrics(ticker)
        except Exception as e:
            print(f"  {ticker} financials failed: {e}")

    report = generate_report_data()
    html = render_html_report(report)

    from db.connection import get_sessions
    from db.models import QuarterlyReport
    with get_sessions() as (local, neon):
        for session in (local, neon):
            session.add(QuarterlyReport(report_html=html))

    success = send_report(html, subject=f"Quarterly Portfolio Report — {datetime.now().strftime('%B %Y')}")
    print(f"Quarterly report {'sent' if success else 'failed to send'}.")


def start():
    scheduler = BlockingScheduler(timezone="America/New_York")

    # Weekdays at 5 PM ET
    scheduler.add_job(run_daily_update, CronTrigger(day_of_week="mon-fri", hour=17, minute=0))

    # 1st of Jan, Apr, Jul, Oct at 6 AM ET
    scheduler.add_job(run_quarterly_report, CronTrigger(month="1,4,7,10", day=1, hour=6, minute=0))

    print("Scheduler started. Daily: weekdays 5 PM ET. Quarterly: Jan/Apr/Jul/Oct 1st.")
    try:
        scheduler.start()
    except (KeyboardInterrupt, SystemExit):
        print("Scheduler stopped.")


if __name__ == "__main__":
    start()
