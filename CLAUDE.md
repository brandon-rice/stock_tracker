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
python main.py init-db                        # Create database + stock_data schema + tables on both DBs

# Portfolio management
python main.py add <TICKER>                   # Add stock + backfill prices + yfinance + SEC EDGAR financials
python main.py remove <TICKER>                # Remove stock and all associated data
python main.py list                           # Quick list with latest prices

# Daily data
python main.py fetch-prices                   # All stocks
python main.py fetch-prices --ticker AAPL     # Single stock (also fetches news for that ticker)
python main.py fetch-financials [--ticker X]  # Latest 4-5 quarters from yfinance
python main.py backfill-financials [--ticker X]  # Multi-year history from SEC EDGAR (free)
python main.py compute-averages [--ticker X]  # 30/60/90-day MAs
python main.py compute-metrics [--ticker X]   # YOY/QOQ growth (latest quarter snapshot only)
python main.py fetch-news [--ticker X]

# Earnings transcripts
python main.py load-transcript AAPL 2025 4    # Load from local file (preferred — no FMP plan needed)
python main.py fetch-transcript AAPL 2025 4   # Fetch from FMP (paid plan required)

# Reports
python main.py portfolio-summary              # All stocks, terminal output
python main.py portfolio-summary --ticker AAPL  # Drill into one stock
python main.py send-report                    # Generate + email full HTML report

# Dashboard
streamlit run dashboard.py                    # Local web UI on localhost:8501

# Scheduler
python main.py start-scheduler                # Long-running daemon for daily + quarterly jobs
```

## Architecture

### Dual-database write pattern
Every write goes to both local PostgreSQL and Neon cloud simultaneously via `db/connection.py:get_sessions()`. This context manager yields `(local_session, neon_session)` and commits or rolls back both atomically. **Never write to only one DB** — always use `get_sessions()`.

ORM objects must **not** be accessed after the `with get_sessions()` block closes — they become detached and raise `DetachedInstanceError`. Extract plain Python values (strings, ints, dicts) inside the `with` block before any loop or rendering that uses them. Established patterns:
- `_get_tickers()` in `main.py` for list-of-strings extraction
- The `news_data`, `sentiments`, `reports_data` patterns in `dashboard.py`

### Schema
All tables live in the `stock_data` PostgreSQL schema (not `public`). The constant `SCHEMA = "stock_data"` is defined in `db/models.py` and referenced in all `ForeignKey()` definitions as `f"{SCHEMA}.table_name"`. `db/init_db.py` creates the database (if missing on local), the schema, and all tables.

### Data flow
```
yfinance        → data/prices.py        (daily OHLCV, PE, EPS, 52W high/low, debt/equity)
yfinance        → data/financials.py    (latest 4-5 quarters)
SEC EDGAR XBRL  → data/sec_edgar.py     (multi-year quarterly history — primary source)
yfinance        → data/news.py          (news headlines — free fallback)
FMP API         → data/news.py          (paid plan only)
FMP API         → data/transcripts.py   (paid plan only)
Local .md/.txt  → data/transcripts.py   (load_transcript_from_file — manual workflow)
                          ↓
                  db/models.py (upsert via ON CONFLICT DO UPDATE)
                          ↓
    analysis/moving_averages.py  (reads daily_prices,  writes moving_averages)
    analysis/metrics.py          (reads financials,    writes computed_metrics — latest only)
    analysis/quarterly.py        (reads everything,    has quarterly_metrics() helper for
                                                       per-quarter YOY/QOQ on the fly)
    analysis/sentiment.py        (reads transcripts,   calls Claude API, writes sentiment)
                          ↓
    notifications/email.py       (renders HTML, sends via Gmail SMTP)
    dashboard.py                 (Streamlit, reads local DB only)
```

### Historical financials strategy
- `yfinance` only returns ~5 quarters; insufficient for YOY calculations on most quarters
- `SEC EDGAR` (`data/sec_edgar.py`) is the primary source for historical data — free, official, 16+ years per company
- Always run `backfill-financials` after `add` (the `add` command does this automatically)
- SEC requires real contact info in `User-Agent` header — uses `REPORT_RECIPIENT_EMAIL` from config

**XBRL extraction gotchas** (each was a real bug — don't undo these):
- `_is_single_quarter()` filters to ~80-100 day duration entries — XBRL data also contains 6-month, 9-month, and 12-month YTD cumulative totals that look like quarterly entries via the `fp` field. Without this filter, revenue values get summed across periods.
- Quarter dedup is by **end_date** (calendar period), not the `fy`/`fp` tags. The `fy`/`fp` tags reflect which filing the entry appeared in, not the period it represents — comparison columns in 10-Qs share the filing's `fy`/`fp`.
- Among entries for the same calendar period, **prefer those whose `frame` matches `CY{year}Q{q}`** — the canonical frame is set on the single-quarter entry and absent on YTD-cumulative duplicates from the same filing.
- `_extract_concept()` **merges across all listed concepts** — Apple uses different XBRL tags in different years (`SalesRevenueNet` pre-2018, `Revenues` briefly, then `RevenueFromContractWithCustomerExcludingAssessedTax`). Picking just the first concept with data gives stale historical values.
- Insurance/financial companies (Cigna) report quarterly net income under `NetIncomeLossAvailableToCommonStockholdersBasic`, not `NetIncomeLoss` (which is annual-only for them). The fallback list handles this.
- `_extract_quarterly_q4_from_annual()` derives the **fiscal-year-end quarter** from FY totals — for Apple this is calendar Q3, not Q4 (their FY ends in September). Uses the FY entry's end_date to determine the target calendar quarter.
- All quarter labels are **calendar quarters**, matching yfinance's labeling. AAPL's "fiscal Q1 2026" is stored as calendar Q4 2025 (the holiday quarter).
- **EPS is a duration concept, not an instantaneous one** — it must go through the same single-quarter filter as revenue. It was previously extracted with `duration="any"`, which let the FY annual EPS land on the fiscal-year-end quarter (both end on the same date, and the 10-K carries no standalone Q4 column). Every Q4 EPS in the table was silently a full-year figure.
- EPS uses `prefer_latest_filed=True` to flip dedup priority from `(canonical, filed)` to `(filed, canonical)`. SEC pins the canonical `CY{y}Q{q}` frame to the **original** filing, so canonical-first keeps pre-split values. **Do not set this flag for absolute-dollar concepts** — there the canonical frame is the defense against YTD duplicates.
- `_split_adjust_eps()` normalizes EPS onto the current share basis. XBRL stores EPS as-reported, and a company only restates the single comparative period in each 10-Q — a rolling one-year window — so a split leaves the series mixing bases indefinitely. An entry is already adjusted iff filed after the split, so it divides by the ratio of splits occurring after **both** the quarter end and the filing date (compounds correctly across multiple splits). Split history comes from yfinance.
- The fiscal-year-end quarter legitimately has **no EPS** from EDGAR for most companies. It's left NULL rather than derived — net income ÷ shares doesn't reconcile with diluted EPS. `fetch-financials` (yfinance) refills it for the ~5 recent quarters it covers, so **run `fetch-financials` after `backfill-financials`** when EPS matters.
- SEC's `_store()` skips `None` values in its `ON CONFLICT` set (so it never clobbers yfinance data), which means a backfill **cannot clear** a previously-written bad value. Fresh tickers are fine; repairing already-backfilled rows needs an explicit UPDATE.

### numpy type handling
yfinance 1.x and pandas operations return `numpy.float64` values. psycopg2 cannot serialize these — it interprets the type prefix as a schema name (`schema "np" does not exist`). **Always cast to `float()` before inserting into the DB**. Established patterns:
- `_f(v)` helper in `data/prices.py`
- `float(round(...))` in `analysis/moving_averages.py` and `analysis/metrics.py`

### Claude API usage
`analysis/sentiment.py` and `data/news.py` both instantiate `anthropic.Anthropic` at module load time. Model is `claude-sonnet-4-6`. `max_tokens=2048` for sentiment, `1024` for news filtering.

**JSON parsing pattern**: Claude sometimes wraps JSON in markdown fences or explanatory prose. Both modules use the same extraction approach: find the first `{` (or `[`) and the last matching `}` (or `]`), then `json.loads()` that substring. Never call `json.loads()` directly on the raw response.

Sentiment analysis truncates transcripts to 40,000 characters before sending.

### FMP API status (free tier is severely limited)
- Even `profile`, `income-statement`, `cash-flow-statement`, `stock_news` return 402/403 on the free tier
- Free tier is essentially unusable for this project's needs
- Transcripts and news both fail gracefully with informative messages
- News falls back to yfinance (works free); transcripts fall back to local file loading via `load-transcript`

### Earnings transcripts (manual workflow)
Save transcripts as `$TRANSCRIPTS_DIR/{TICKER}/{YEAR}_Q{N}.md` (or `.txt`). Default `TRANSCRIPTS_DIR` is `~/Documents/earnings_transcripts`. The `load-transcript` command:
1. Looks up the file (case-insensitive ticker folder)
2. Stores the raw text in `transcripts` table on both DBs
3. Calls `analyze_and_store_sentiment()` which sends to Claude
4. Writes structured sentiment back to the `sentiment` table on both DBs

### Scheduler
`scheduler.py` runs two APScheduler jobs:
- **Daily** (weekdays 5 PM ET): prices + news + recompute MAs for every stock
- **Quarterly** (1st of Jan/Apr/Jul/Oct, 6 AM ET): financials + metrics + email report

Run as a long-lived process with `python main.py start-scheduler`. There is no scheduled job for transcripts/sentiment — those are manually triggered after the user saves a transcript file.

### Quarterly vs TTM revenue
Everything in `financials` is **single-quarter**, but Yahoo and most finance sites headline **TTM** revenue — so the portfolio looks ~4x smaller for the same company. `analysis/quarterly.py:ttm_revenue()` sums the last 4 quarters and is surfaced as "TTM Revenue" in `portfolio-summary`, the dashboard overview table, Stock Detail key metrics, and the email report. It returns `None` unless all 4 quarters have revenue — a partial sum reads as a collapse rather than as missing data. Per-quarter tables and charts are labeled "quarterly" to keep the distinction visible.

### Dashboard refresh date convention
Every Streamlit page surfaces a "data as of" caption from the underlying table's timestamp:
- Portfolio Overview → latest `daily_prices.date`
- Stock Detail → `daily_prices.date` + `financials.reported_date`
- News Feed → max(`news.fetched_at`)
- Earnings Sentiment → `transcripts.fetched_at` + `sentiment.analyzed_at`

Maintain this pattern when adding new pages or sections.
