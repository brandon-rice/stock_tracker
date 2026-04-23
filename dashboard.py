import streamlit as st
import pandas as pd
import plotly.graph_objects as go
import plotly.express as px
from datetime import date, timedelta
from db.connection import get_sessions
from db.models import Stock, DailyPrice, MovingAverage, Financials, ComputedMetrics, Sentiment, Transcript, News, QuarterlyReport

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

    df = pd.DataFrame(rows)
    st.dataframe(df, use_container_width=True, hide_index=True)


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

    with get_sessions() as (local, _):
        q = local.query(News).filter_by(is_significant=True).order_by(News.published_at.desc())
        if selected != "All":
            s = local.query(Stock).filter_by(ticker=selected).first()
            if s:
                q = q.filter_by(stock_id=s.id)
        news_items = q.limit(50).all()

    if not news_items:
        st.info("No significant news found yet.")
    else:
        for n in news_items:
            with local.no_autoflush:
                pass
            st.markdown(f"**[{n.headline}]({n.url})**")
            st.caption(f"{n.source} · {str(n.published_at)[:10] if n.published_at else ''} · {n.significance_reason or ''}")
            st.divider()


# ── PAGE: Earnings Sentiment ──────────────────────────────────────────────────

elif page == "Earnings Sentiment":
    st.title("Earnings Sentiment")

    stocks = get_stocks()
    if not stocks:
        st.info("No stocks in portfolio.")
        st.stop()

    ticker = st.selectbox("Select Stock", [t for t, _ in stocks])

    with get_sessions() as (local, _):
        s = local.query(Stock).filter_by(ticker=ticker).first()
        transcripts = (
            local.query(Transcript)
            .filter_by(stock_id=s.id)
            .order_by(Transcript.fiscal_year, Transcript.fiscal_quarter)
            .all()
        )

        sentiments = [(t, t.sentiment) for t in transcripts if t.sentiment]

    if not sentiments:
        st.info(f"No sentiment data for {ticker}. Run `fetch-transcript` to add some.")
    else:
        labels = [f"Q{t.fiscal_quarter} {t.fiscal_year}" for t, _ in sentiments]
        scores = [snt.overall_score for _, snt in sentiments]

        fig = go.Figure(go.Bar(
            x=labels, y=scores,
            marker_color=["#27ae60" if sc > 0.1 else ("#e74c3c" if sc < -0.1 else "#f39c12") for sc in scores],
        ))
        fig.add_hline(y=0, line_dash="dash", line_color="gray")
        fig.update_layout(title=f"{ticker} Earnings Sentiment Over Time", yaxis_range=[-1, 1], height=300)
        st.plotly_chart(fig, use_container_width=True)

        latest_t, latest_s = sentiments[-1]
        st.subheader(f"Latest: Q{latest_t.fiscal_quarter} {latest_t.fiscal_year}")
        col1, col2, col3 = st.columns(3)
        col1.metric("Tone", latest_s.tone_label.title() if latest_s.tone_label else "N/A")
        col2.metric("Mgmt Confidence", latest_s.management_confidence.title() if latest_s.management_confidence else "N/A")
        col3.metric("Guidance", latest_s.guidance_sentiment.replace("_", " ").title() if latest_s.guidance_sentiment else "N/A")

        if latest_s.summary:
            st.info(latest_s.summary)

        if latest_s.key_themes:
            st.write("**Key Themes:**", ", ".join(latest_s.key_themes))


# ── PAGE: Reports ─────────────────────────────────────────────────────────────

elif page == "Reports":
    st.title("Quarterly Reports")

    with get_sessions() as (local, _):
        reports = local.query(QuarterlyReport).order_by(QuarterlyReport.generated_at.desc()).limit(20).all()

    if not reports:
        st.info("No reports generated yet. Run `python main.py send-report`.")
    else:
        for r in reports:
            sent = f"Sent: {str(r.sent_at)[:16]}" if r.sent_at else "Not sent"
            with st.expander(f"Report — {str(r.generated_at)[:16]} ({sent})"):
                if r.report_html:
                    st.components.v1.html(r.report_html, height=600, scrolling=True)
