# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Environment Setup

All commands must be run using the project's virtual environment:
```bash
source .venv/bin/activate
# or prefix commands with:
.venv/bin/python main.py <command>
```

The `.env` file must exist at the project root (copy from `.env.example`). `config.py` loads it relative to its own file path, so the CLI works from any directory.

## Common Commands

```bash
# Database
python main.py init-db                        # Create stock_data schema + all tables on both DBs

# Portfolio management
python main.py add <TICKER>                   # Add stock + backfill 90 days prices/financials
python main.py remove <TICKER>                # Remove stock and all associated data
python main.py list                           # List portfolio with latest prices

# Daily data
python main.py fetch-prices                   # All stocks
python main.py fetch-prices --ticker AAPL     # Single stock (also fetches news)
python main.py fetch-financials [--ticker X]
python main.py compute-averages [--ticker X]  # 30/60/90-day MAs
python main.py compute-metrics [--ticker X]   # YOY/QOQ growth rates
python main.py fetch-news [--ticker X]

# Earnings (requires FMP paid plan)
python main.py fetch-transcript AAPL 2025 1   # Fetches + runs sentiment automatically

# Reports
python main.py portfolio-summary              # Terminal output
python main.py send-report                    # Generate + email HTML report

# Dashboard
streamlit run dashboard.py

# Scheduler (runs daily + quarterly jobs automatically)
python main.py start-scheduler
```

## Architecture

### Dual-database write pattern
Every write goes to both local PostgreSQL and Neon cloud simultaneously via `db/connection.py:get_sessions()`. This context manager yields `(local_session, neon_session)` and commits or rolls back both atomically. **Never write to only one DB** — always use `get_sessions()`.

ORM objects must **not** be accessed after the `with get_sessions()` block closes — they become detached. Extract plain Python values (strings, ints) inside the `with` block before the loop that uses them. See `_get_tickers()` in `main.py` for the established pattern.

### Schema
All tables live in the `stock_data` PostgreSQL schema (not `public`). The constant `SCHEMA = "stock_data"` is defined in `db/models.py` and referenced in all `ForeignKey()` definitions as `f"{SCHEMA}.table_name"`.

### Data flow
```
yfinance → data/prices.py, data/financials.py
FMP API  → data/transcripts.py (paid plan required), data/news.py (paid plan required)
yfinance → data/news.py (free fallback for news)
                ↓
         db/models.py (upsert via ON CONFLICT DO UPDATE)
                ↓
    analysis/moving_averages.py  (reads daily_prices, writes moving_averages)
    analysis/metrics.py          (reads financials, writes computed_metrics)
    analysis/sentiment.py        (reads transcripts, calls Claude API, writes sentiment)
    analysis/quarterly.py        (reads all tables, assembles report dict)
                ↓
    notifications/email.py       (renders HTML, sends via Gmail SMTP)
    dashboard.py                 (Streamlit, reads from local DB only)
```

### numpy type handling
yfinance 1.x returns `numpy.float64` values. psycopg2 cannot serialize these — always cast to `float()` before inserting into the DB. The helper `_f(v)` in `data/prices.py` is the established pattern. Apply the same to any new numeric values coming from yfinance or pandas.

### FMP API tier limitations
- **Free tier**: financial statements, company profiles only
- **Starter plan (~$14.99/mo)**: unlocks `stock_news` and `earning_call_transcript` endpoints
- News falls back to yfinance (free) when FMP returns 403
- Transcripts return `None` gracefully on 403 with a clear message

### Claude API usage
`analysis/sentiment.py` and `data/news.py` both instantiate `anthropic.Anthropic` at module load time. Sentiment analysis truncates transcripts to 40,000 characters before sending. The model used is `claude-sonnet-4-6`.

### Scheduler
`scheduler.py` runs two APScheduler jobs: daily prices/news/MAs at 5 PM ET on weekdays, and quarterly reports on the 1st of Jan/Apr/Jul/Oct. Run as a long-lived process with `python main.py start-scheduler`.
