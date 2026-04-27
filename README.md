# Stock Tracker

The goal of this project is to make an app that allows the user to easily analyze the stock price of a company by summarizing the current price, various moving day averages, supporting financial metrics, and analysis of the earnings call transcripts.

It tracks a personal portfolio of stocks, persists data to both a local PostgreSQL database and a Neon cloud database, and surfaces everything through a CLI, a Streamlit web dashboard, and an emailed HTML report.

## What it tracks

- **Daily price** with 1-day change, plus 30/60/90-day moving averages
- **Key metrics**: PE ratio, EPS, 52-week high/low, debt-to-equity
- **Quarterly financials** with multi-year history from SEC EDGAR (revenue, net income, EPS, free cash flow)
- **Growth rates**: YOY revenue, YOY earnings, FCF YOY, FCF QOQ — for each of the last 5 quarters
- **Earnings call sentiment** via Claude AI (tone, management confidence, guidance direction, key themes, summary)
- **Significant news** filtered by Claude AI to surface only market-moving headlines

## Tech stack

| Concern | Tool |
|---|---|
| Language | Python 3.11+ |
| Prices, financials | yfinance |
| Historical financials | SEC EDGAR XBRL API |
| News | yfinance + Claude AI filtering |
| Earnings sentiment | Claude AI (`claude-sonnet-4-6`) |
| Database | PostgreSQL (local + Neon cloud, dual-write) + SQLAlchemy |
| Scheduling | APScheduler |
| CLI | Click |
| Dashboard | Streamlit + Plotly |
| Email | Gmail SMTP |

## Setup

```bash
# Install dependencies
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

# Configure
cp .env.example .env
# Edit .env with your local Postgres credentials, Neon URL, Anthropic key,
# Gmail App Password, and (optionally) FMP key

# Initialize databases (creates the stock_data schema and tables on both DBs)
python main.py init-db
```

## CLI Commands

### Portfolio management
```bash
python main.py add AAPL                       # Add a stock — backfills 90 days of prices,
                                              #   pulls financials from yfinance + SEC EDGAR,
                                              #   computes moving averages and growth metrics
python main.py remove AAPL                    # Remove a stock and all its data
python main.py list                           # One-line summary of every stock in the portfolio
```

### Checking a stock
```bash
python main.py portfolio-summary              # Full snapshot of every stock in the terminal
python main.py portfolio-summary --ticker AAPL  # Drill into one stock — price, MAs, financials,
                                                #   YOY/QOQ growth, latest sentiment, news
```

### Refreshing data
```bash
python main.py fetch-prices                       # Today's price + metrics for every stock
python main.py fetch-prices --ticker AAPL         # One stock (also fetches news for it)
python main.py fetch-financials [--ticker AAPL]   # Latest 4-5 quarters from yfinance
python main.py backfill-financials [--ticker AAPL]  # Multi-year history from SEC EDGAR (free)
python main.py compute-averages [--ticker AAPL]   # Recompute 30/60/90-day MAs
python main.py compute-metrics [--ticker AAPL]    # Recompute YOY/QOQ growth
python main.py fetch-news [--ticker AAPL]         # Pull headlines, Claude flags significant ones
```

### Earnings transcripts
```bash
# Manually save a transcript file at:
#   ~/Documents/earnings_transcripts/AAPL/2026_Q1.md
# Then:
python main.py load-transcript AAPL 2026 1    # Loads the file into the DB and runs Claude
                                              #   sentiment analysis automatically
```

### Reports & dashboard
```bash
python main.py send-report                    # Build an HTML report and email it to yourself
streamlit run dashboard.py                    # Launch the web UI on http://localhost:8501
python main.py start-scheduler                # Background daemon: daily prices @ 5 PM ET,
                                              #   quarterly report on the 1st of Jan/Apr/Jul/Oct
```

## Dashboard

Running `streamlit run dashboard.py` serves a 5-page web UI:

1. **Portfolio Overview** — one-row summary per stock plus an expandable per-stock table of the last 5 quarters with all growth metrics
2. **Stock Detail** — interactive price + moving averages chart, plus revenue/income/FCF bar charts
3. **News Feed** — Claude-flagged significant news, filterable by ticker
4. **Earnings Sentiment** — sentiment timeline, latest summary, key themes
5. **Reports** — every emailed report rendered inline

## Project structure

```
stock_tracker/
├── main.py              # CLI entry point (Click)
├── dashboard.py         # Streamlit web UI
├── scheduler.py         # APScheduler daemon
├── config.py            # Loads .env, exposes constants
├── db/                  # Models + dual-write connection layer
├── data/                # External data fetchers (yfinance, SEC EDGAR, FMP, news, transcripts)
├── analysis/            # Moving averages, growth metrics, Claude sentiment, report assembly
└── notifications/       # HTML rendering + Gmail SMTP send
```

See `CLAUDE.md` for the deeper architecture notes.
