import streamlit as st
import pandas as pd
import plotly.graph_objects as go
import plotly.express as px
from datetime import date, timedelta, datetime
from db.connection import get_sessions
from db.models import Stock, DailyPrice, MovingAverage, Financials, ComputedMetrics, Sentiment, Transcript, News, QuarterlyReport
from analysis.quarterly import quarterly_metrics

st.set_page_config(page_title="Stock Portfolio Tracker", layout="wide", page_icon="📈")

# ── helpers ──────────────────────────────────────────────────────────────────

def get_stocks():
    with get_sessions() as (local, _):
        return [(s.ticker, s.company_name or s.ticker) for s in local.query(Stock).order_by(Stock.ticker).all()]


def _fmt(val, prefix="$", suffix="", decimals=2):
    if val is None:
        return "N/A"
    return f"{prefix}{val:,.{decimals}f}{suffix}"


def _pct(val):
    if val is None:
        return "N/A"
    return f"{'+' if val > 0 else ''}{val:.2f}%"


# ── sidebar nav ──────────────────────────────────────────────────────────────

page = st.sidebar.selectbox(
    "Navigation",
    ["Portfolio Overview", "Stock Detail", "News Feed", "Earnings Sentiment", "Reports"],
)
st.sidebar.markdown("---")
st.sidebar.caption("Stock Portfolio Tracker")

# ── PAGE: Portfolio Overview ──────────────────────────────────────────────────

if page == "Portfolio Overview":
    st.title("Portfolio Overview")

    stocks = get_stocks()
    if not stocks:
        st.info("No stocks in portfolio. Run `python main.py add <TICKER>` to add one.")
        st.stop()

    rows = []
    quarterly_by_ticker = {}
    latest_price_date = None

    with get_sessions() as (local, _):
        for ticker, name in stocks:
            s = local.query(Stock).filter_by(ticker=ticker).first()
            p = local.query(DailyPrice).filter_by(stock_id=s.id).order_by(DailyPrice.date.desc()).first()
            prev = local.query(DailyPrice).filter_by(stock_id=s.id).order_by(DailyPrice.date.desc()).offset(1).first()
            ma = local.query(MovingAverage).filter_by(stock_id=s.id).order_by(MovingAverage.date.desc()).first()
            m = local.query(ComputedMetrics).filter_by(stock_id=s.id).order_by(ComputedMetrics.computed_date.desc()).first()

            chg = None
            if p and prev and prev.close:
                chg = (p.close - prev.close) / prev.close * 100

            if p and (latest_price_date is None or p.date > latest_price_date):
                latest_price_date = p.date

            rows.append({
                "Ticker": ticker,
                "Company": name,
                "Price": _fmt(p.close if p else None),
                "Change": _pct(chg),
                "PE": _fmt(p.pe_ratio if p else None, prefix=""),
                "EPS": _fmt(p.eps if p else None),
                "52W High": _fmt(p.fifty_two_week_high if p else None),
                "52W Low": _fmt(p.fifty_two_week_low if p else None),
                "D/E": _fmt(p.debt_to_equity if p else None, prefix=""),
                "MA30": _fmt(ma.ma_30 if ma else None),
                "MA60": _fmt(ma.ma_60 if ma else None),
                "MA90": _fmt(ma.ma_90 if ma else None),
                "YOY Rev": _pct(m.yoy_revenue_growth if m else None),
                "YOY Earn": _pct(m.yoy_earnings_growth if m else None),
                "FCF YOY": _pct(m.fcf_yoy if m else None),
            })

            # Last 9 quarters needed so 5 displayed quarters can each compute YOY
            fin_rows = (
                local.query(Financials)
                .filter_by(stock_id=s.id)
                .order_by(Financials.fiscal_year.desc(), Financials.fiscal_quarter.desc())
                .limit(9)
                .all()
            )
            quarterly_by_ticker[ticker] = quarterly_metrics(fin_rows)[:5]

    if latest_price_date:
        st.caption(f"Latest price data as of: **{latest_price_date}**  |  Loaded: {datetime.now().strftime('%Y-%m-%d %H:%M')}")

    df = pd.DataFrame(rows)
    st.dataframe(df, use_container_width=True, hide_index=True)

    st.markdown("---")
    st.subheader("Last 5 Quarters by Stock")

    for ticker, qrows in quarterly_by_ticker.items():
        if not qrows:
            continue
        with st.expander(f"{ticker} — Quarterly Detail"):
            qdf = pd.DataFrame([{
                "Quarter": q["quarter"],
                "Revenue": _fmt(q["revenue"] / 1e9, prefix="$", suffix="B") if q["revenue"] else "N/A",
                "Net Income": _fmt(q["net_income"] / 1e9, prefix="$", suffix="B") if q["net_income"] else "N/A",
                "EPS": _fmt(q["eps"]) if q["eps"] else "N/A",
                "FCF": _fmt(q["fcf"] / 1e9, prefix="$", suffix="B") if q["fcf"] else "N/A",
                "YOY Rev": _pct(q["yoy_revenue"]),
                "YOY Earn": _pct(q["yoy_earnings"]),
                "FCF YOY": _pct(q["fcf_yoy"]),
                "FCF QOQ": _pct(q["fcf_qoq"]),
            } for q in qrows])
            st.dataframe(qdf, use_container_width=True, hide_index=True)


# ── PAGE: Stock Detail ────────────────────────────────────────────────────────

elif page == "Stock Detail":
    st.title("Stock Detail")

    stocks = get_stocks()
    if not stocks:
        st.info("No stocks in portfolio.")
        st.stop()

    ticker = st.selectbox("Select Stock", [t for t, _ in stocks])

    with get_sessions() as (local, _):
        s = local.query(Stock).filter_by(ticker=ticker).first()

        latest_p = local.query(DailyPrice).filter_by(stock_id=s.id).order_by(DailyPrice.date.desc()).first()
        latest_fin = local.query(Financials).filter_by(stock_id=s.id).order_by(Financials.reported_date.desc()).first()
        info_lines = []
        if latest_p:
            info_lines.append(f"Price as of: **{latest_p.date}**")
        if latest_fin and latest_fin.reported_date:
            info_lines.append(f"Financials reported: **{latest_fin.reported_date}**")
        if info_lines:
            st.caption("  |  ".join(info_lines))

        # Price + MA chart
        cutoff = date.today() - timedelta(days=95)
        prices = (
            local.query(DailyPrice)
            .filter(DailyPrice.stock_id == s.id, DailyPrice.date >= cutoff)
            .order_by(DailyPrice.date)
            .all()
        )
        mas = (
            local.query(MovingAverage)
            .filter(MovingAverage.stock_id == s.id, MovingAverage.date >= cutoff)
            .order_by(MovingAverage.date)
            .all()
        )

        if prices:
            fig = go.Figure()
            dates = [r.date for r in prices]
            fig.add_trace(go.Scatter(x=dates, y=[r.close for r in prices], name="Close", line=dict(color="#2c3e50", width=2)))
            if mas:
                ma_dates = [r.date for r in mas]
                fig.add_trace(go.Scatter(x=ma_dates, y=[r.ma_30 for r in mas], name="MA30", line=dict(color="#3498db", dash="dot")))
                fig.add_trace(go.Scatter(x=ma_dates, y=[r.ma_60 for r in mas], name="MA60", line=dict(color="#e67e22", dash="dot")))
                fig.add_trace(go.Scatter(x=ma_dates, y=[r.ma_90 for r in mas], name="MA90", line=dict(color="#9b59b6", dash="dot")))
            fig.update_layout(title=f"{ticker} Price & Moving Averages (90 days)", height=400, margin=dict(l=0, r=0, t=40, b=0))
            st.plotly_chart(fig, use_container_width=True)

        # Financials charts
        fin_rows = (
            local.query(Financials)
            .filter_by(stock_id=s.id)
            .order_by(Financials.fiscal_year, Financials.fiscal_quarter)
            .limit(8)
            .all()
        )

        if fin_rows:
            st.subheader("Quarterly Financials")
            labels = [f"Q{r.fiscal_quarter} {r.fiscal_year}" for r in fin_rows]

            col1, col2, col3 = st.columns(3)
            with col1:
                rev = [r.revenue / 1e9 if r.revenue else None for r in fin_rows]
                fig2 = px.bar(x=labels, y=rev, title="Revenue ($B)", color_discrete_sequence=["#3498db"])
                fig2.update_layout(height=300, margin=dict(l=0, r=0, t=40, b=0), showlegend=False)
                st.plotly_chart(fig2, use_container_width=True)
            with col2:
                ni = [r.net_income / 1e9 if r.net_income else None for r in fin_rows]
                fig3 = px.bar(x=labels, y=ni, title="Net Income ($B)", color_discrete_sequence=["#27ae60"])
                fig3.update_layout(height=300, margin=dict(l=0, r=0, t=40, b=0), showlegend=False)
                st.plotly_chart(fig3, use_container_width=True)
            with col3:
                fcf = [r.free_cash_flow / 1e9 if r.free_cash_flow else None for r in fin_rows]
                fig4 = px.bar(x=labels, y=fcf, title="Free Cash Flow ($B)", color_discrete_sequence=["#e67e22"])
                fig4.update_layout(height=300, margin=dict(l=0, r=0, t=40, b=0), showlegend=False)
                st.plotly_chart(fig4, use_container_width=True)

        # Key metrics
        p = local.query(DailyPrice).filter_by(stock_id=s.id).order_by(DailyPrice.date.desc()).first()
        m = local.query(ComputedMetrics).filter_by(stock_id=s.id).order_by(ComputedMetrics.computed_date.desc()).first()
        if p or m:
            st.subheader("Key Metrics")
            c1, c2, c3, c4, c5 = st.columns(5)
            c1.metric("PE Ratio", _fmt(p.pe_ratio if p else None, prefix=""))
            c2.metric("EPS", _fmt(p.eps if p else None))
            c3.metric("Debt/Equity", _fmt(p.debt_to_equity if p else None, prefix=""))
            c4.metric("52W High", _fmt(p.fifty_two_week_high if p else None))
            c5.metric("52W Low", _fmt(p.fifty_two_week_low if p else None))

            if m:
                c1b, c2b, c3b, c4b = st.columns(4)
                c1b.metric("YOY Revenue", _pct(m.yoy_revenue_growth))
                c2b.metric("YOY Earnings", _pct(m.yoy_earnings_growth))
                c3b.metric("FCF YOY", _pct(m.fcf_yoy))
                c4b.metric("FCF QOQ", _pct(m.fcf_qoq))


# ── PAGE: News Feed ───────────────────────────────────────────────────────────

elif page == "News Feed":
    st.title("Significant News")

    stocks = get_stocks()
    options = ["All"] + [t for t, _ in stocks]
    selected = st.selectbox("Filter by stock", options)

    news_data = []
    last_fetch_str = None
    with get_sessions() as (local, _):
        q = local.query(News).filter_by(is_significant=True).order_by(News.published_at.desc())
        if selected != "All":
            s = local.query(Stock).filter_by(ticker=selected).first()
            if s:
                q = q.filter_by(stock_id=s.id)
        for n in q.limit(50).all():
            news_data.append({
                "headline": n.headline,
                "url": n.url,
                "source": n.source,
                "published_at": str(n.published_at)[:10] if n.published_at else "",
                "reason": n.significance_reason or "",
            })
        last = local.query(News).order_by(News.fetched_at.desc()).first()
        if last:
            last_fetch_str = str(last.fetched_at)[:16]

    if last_fetch_str:
        st.caption(f"News last fetched: **{last_fetch_str}**")

    if not news_data:
        st.info("No significant news found yet.")
    else:
        for n in news_data:
            st.markdown(f"**[{n['headline']}]({n['url']})**")
            st.caption(f"{n['source']} · {n['published_at']} · {n['reason']}")
            st.divider()


# ── PAGE: Earnings Sentiment ──────────────────────────────────────────────────

elif page == "Earnings Sentiment":
    st.title("Earnings Sentiment")

    stocks = get_stocks()
    if not stocks:
        st.info("No stocks in portfolio.")
        st.stop()

    ticker = st.selectbox("Select Stock", [t for t, _ in stocks])

    sentiments = []
    with get_sessions() as (local, _):
        s = local.query(Stock).filter_by(ticker=ticker).first()
        transcripts = (
            local.query(Transcript)
            .filter_by(stock_id=s.id)
            .order_by(Transcript.fiscal_year, Transcript.fiscal_quarter)
            .all()
        )
        for t in transcripts:
            if t.sentiment:
                sentiments.append({
                    "label": f"Q{t.fiscal_quarter} {t.fiscal_year}",
                    "fiscal_year": t.fiscal_year,
                    "fiscal_quarter": t.fiscal_quarter,
                    "fetched_at": str(t.fetched_at)[:16] if t.fetched_at else "",
                    "score": t.sentiment.overall_score,
                    "tone": t.sentiment.tone_label,
                    "confidence": t.sentiment.management_confidence,
                    "guidance": t.sentiment.guidance_sentiment,
                    "summary": t.sentiment.summary,
                    "themes": list(t.sentiment.key_themes or []),
                    "analyzed_at": str(t.sentiment.analyzed_at)[:16] if t.sentiment.analyzed_at else "",
                })

    if not sentiments:
        st.info(f"No sentiment data for {ticker}. Run `load-transcript {ticker} YEAR Q` to add some.")
    else:
        labels = [s["label"] for s in sentiments]
        scores = [s["score"] for s in sentiments]

        fig = go.Figure(go.Bar(
            x=labels, y=scores,
            marker_color=["#27ae60" if sc > 0.1 else ("#e74c3c" if sc < -0.1 else "#f39c12") for sc in scores],
        ))
        fig.add_hline(y=0, line_dash="dash", line_color="gray")
        fig.update_layout(title=f"{ticker} Earnings Sentiment Over Time", yaxis_range=[-1, 1], height=300)
        st.plotly_chart(fig, use_container_width=True)

        latest = sentiments[-1]
        st.subheader(f"Latest: {latest['label']}")
        st.caption(
            f"Transcript loaded: **{latest['fetched_at']}**  |  "
            f"Sentiment analyzed: **{latest['analyzed_at']}**"
        )
        col1, col2, col3 = st.columns(3)
        col1.metric("Tone", latest["tone"].title() if latest["tone"] else "N/A")
        col2.metric("Mgmt Confidence", latest["confidence"].title() if latest["confidence"] else "N/A")
        col3.metric("Guidance", latest["guidance"].replace("_", " ").title() if latest["guidance"] else "N/A")

        if latest["summary"]:
            st.info(latest["summary"])
        if latest["themes"]:
            st.write("**Key Themes:**", ", ".join(latest["themes"]))


# ── PAGE: Reports ─────────────────────────────────────────────────────────────

elif page == "Reports":
    st.title("Portfolio Reports")

    reports_data = []
    with get_sessions() as (local, _):
        for r in local.query(QuarterlyReport).order_by(QuarterlyReport.generated_at.desc()).limit(20).all():
            reports_data.append({
                "generated_at": str(r.generated_at)[:16] if r.generated_at else "?",
                "sent_at": str(r.sent_at)[:16] if r.sent_at else None,
                "html": r.report_html,
            })

    if not reports_data:
        st.info("No reports generated yet. Run `python main.py send-report`.")
    else:
        for r in reports_data:
            sent = f"Sent: {r['sent_at']}" if r["sent_at"] else "Not sent"
            with st.expander(f"Report — {r['generated_at']} ({sent})"):
                if r["html"]:
                    st.components.v1.html(r["html"], height=600, scrolling=True)
