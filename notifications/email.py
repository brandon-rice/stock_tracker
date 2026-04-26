import smtplib
from datetime import datetime
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from config import GMAIL_USER, GMAIL_APP_PASSWORD, REPORT_RECIPIENT_EMAIL


def _fmt(val, suffix="", prefix="", decimals=2, na="N/A"):
    if val is None:
        return na
    return f"{prefix}{val:,.{decimals}f}{suffix}"


def _pct(val):
    if val is None:
        return "N/A"
    sign = "+" if val > 0 else ""
    color = "#27ae60" if val > 0 else "#e74c3c"
    return f'<span style="color:{color}">{sign}{val:.2f}%</span>'


def render_html_report(report_data: list[dict]) -> str:
    now = datetime.now().strftime("%B %d, %Y at %I:%M %p")
    cards = ""

    for s in report_data:
        p = s["price"]
        ma = s["moving_averages"]
        m = s.get("metrics", {})
        sent = s.get("sentiment")
        news = s.get("significant_news", [])

        news_html = ""
        if news:
            items = "".join(
                f'<li><a href="{n["url"]}" style="color:#2980b9">{n["headline"]}</a>'
                f' <span style="color:#888;font-size:12px">— {n["source"]}</span></li>'
                for n in news[:3]
            )
            news_html = f"<ul style='margin:4px 0 0 16px;padding:0'>{items}</ul>"

        sent_html = ""
        if sent:
            score_color = "#27ae60" if sent["overall_score"] > 0.1 else ("#e74c3c" if sent["overall_score"] < -0.1 else "#f39c12")
            themes = ", ".join(sent["key_themes"] or [])
            sent_html = f"""
            <tr><td colspan="2" style="padding:8px 0 2px;font-weight:bold;color:#555">
                Earnings Call Sentiment ({sent.get('quarter','')})
            </td></tr>
            <tr>
                <td>Tone</td>
                <td style="color:{score_color}">{sent['tone_label'].title()} ({sent['overall_score']:+.2f})</td>
            </tr>
            <tr><td>Mgmt Confidence</td><td>{sent['management_confidence'].title()}</td></tr>
            <tr><td>Guidance</td><td>{sent['guidance_sentiment'].replace('_',' ').title()}</td></tr>
            <tr><td>Key Themes</td><td>{themes}</td></tr>
            <tr><td colspan="2" style="color:#555;font-style:italic;padding:4px 0">{sent['summary']}</td></tr>
            """

        qbreakdown = s.get("quarterly_breakdown") or []
        financials_rows = ""
        for q in qbreakdown:
            financials_rows += f"""
            <tr>
                <td>{q['quarter']}</td>
                <td>{_fmt(q['revenue'] and q['revenue']/1e9, suffix='B', prefix='$')}</td>
                <td>{_fmt(q['net_income'] and q['net_income']/1e9, suffix='B', prefix='$')}</td>
                <td>{_fmt(q['eps'], prefix='$')}</td>
                <td>{_fmt(q['fcf'] and q['fcf']/1e9, suffix='B', prefix='$')}</td>
                <td>{_pct(q['yoy_revenue'])}</td>
                <td>{_pct(q['yoy_earnings'])}</td>
                <td>{_pct(q['fcf_yoy'])}</td>
                <td>{_pct(q['fcf_qoq'])}</td>
            </tr>"""

        asof = s.get("data_as_of") or {}
        refresh_lines = []
        if asof.get("price_date"): refresh_lines.append(f"Price: {asof['price_date']}")
        if asof.get("financials_reported"): refresh_lines.append(f"Financials: {asof['financials_reported']}")
        if asof.get("sentiment_analyzed"): refresh_lines.append(f"Sentiment: {asof['sentiment_analyzed']}")
        refresh_html = " · ".join(refresh_lines)

        cards += f"""
        <div style="background:#fff;border:1px solid #ddd;border-radius:8px;padding:20px;margin-bottom:24px">
            <h2 style="margin:0 0 4px;color:#2c3e50">{s['ticker']}
                <span style="font-size:14px;font-weight:normal;color:#888">{s.get('company_name','')}</span>
            </h2>
            <p style="margin:0 0 4px;font-size:22px;font-weight:bold;color:#2c3e50">
                {_fmt(p.get('close'), prefix='$')}
                <span style="font-size:15px;margin-left:8px">{_pct(p.get('change_pct'))}</span>
            </p>
            <p style="margin:0 0 12px;font-size:11px;color:#888">Data as of — {refresh_html}</p>

            <table style="width:100%;border-collapse:collapse;font-size:14px">
                <tr style="background:#f8f8f8">
                    <td style="padding:6px 8px;width:50%"><b>Key Metrics</b></td>
                    <td style="padding:6px 8px"><b>Moving Averages</b></td>
                </tr>
                <tr>
                    <td style="padding:4px 8px;vertical-align:top">
                        <table style="width:100%;font-size:13px">
                            <tr><td>PE Ratio</td><td>{_fmt(p.get('pe_ratio'))}</td></tr>
                            <tr><td>EPS</td><td>{_fmt(p.get('eps'), prefix='$')}</td></tr>
                            <tr><td>52W High</td><td>{_fmt(p.get('high_52w'), prefix='$')}</td></tr>
                            <tr><td>52W Low</td><td>{_fmt(p.get('low_52w'), prefix='$')}</td></tr>
                            <tr><td>Debt/Equity</td><td>{_fmt(p.get('debt_to_equity'))}</td></tr>
                            <tr><td>YOY Rev Growth</td><td>{_pct(m.get('yoy_revenue_growth'))}</td></tr>
                            <tr><td>YOY Earnings Growth</td><td>{_pct(m.get('yoy_earnings_growth'))}</td></tr>
                            <tr><td>FCF YOY</td><td>{_pct(m.get('fcf_yoy'))}</td></tr>
                            <tr><td>FCF QOQ</td><td>{_pct(m.get('fcf_qoq'))}</td></tr>
                        </table>
                    </td>
                    <td style="padding:4px 8px;vertical-align:top">
                        <table style="width:100%;font-size:13px">
                            <tr><td>30-Day MA</td><td>{_fmt(ma.get('ma_30'), prefix='$')}</td></tr>
                            <tr><td>60-Day MA</td><td>{_fmt(ma.get('ma_60'), prefix='$')}</td></tr>
                            <tr><td>90-Day MA</td><td>{_fmt(ma.get('ma_90'), prefix='$')}</td></tr>
                        </table>
                    </td>
                </tr>

                {sent_html}

                {'<tr><td colspan="2" style="padding:8px 0 2px;font-weight:bold;color:#555">Last 5 Quarters</td></tr>' if financials_rows else ''}
                {'<tr><td colspan="2"><table style="width:100%;font-size:12px;border-collapse:collapse"><tr style="color:#888;border-bottom:1px solid #eee"><td>Quarter</td><td>Revenue</td><td>Net Income</td><td>EPS</td><td>FCF</td><td>YOY Rev</td><td>YOY Earn</td><td>FCF YOY</td><td>FCF QOQ</td></tr>' + financials_rows + '</table></td></tr>' if financials_rows else ''}

                {'<tr><td colspan="2" style="padding:8px 0 2px;font-weight:bold;color:#555">Significant News</td></tr>' if news_html else ''}
                {'<tr><td colspan="2">' + news_html + '</td></tr>' if news_html else ''}
            </table>
        </div>"""

    return f"""<!DOCTYPE html>
<html><head><meta charset="utf-8"></head>
<body style="font-family:Arial,sans-serif;background:#f5f5f5;padding:24px;color:#333">
    <div style="max-width:800px;margin:0 auto">
        <h1 style="color:#2c3e50;border-bottom:2px solid #3498db;padding-bottom:8px;margin-bottom:4px">
            Portfolio Report
        </h1>
        <p style="color:#888;font-size:13px;margin:0 0 24px">Generated: {now}</p>
        {cards}
        <p style="font-size:12px;color:#aaa;text-align:center;margin-top:24px">
            Generated by Stock Portfolio Tracker
        </p>
    </div>
</body></html>"""


def send_report(html: str, subject: str = None, to_email: str = None) -> bool:
    to = to_email or REPORT_RECIPIENT_EMAIL
    subject = subject or f"Portfolio Report — {datetime.now().strftime('%B %d, %Y')}"

    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"] = GMAIL_USER
    msg["To"] = to
    msg.attach(MIMEText(html, "html"))

    try:
        with smtplib.SMTP_SSL("smtp.gmail.com", 465) as server:
            server.login(GMAIL_USER, GMAIL_APP_PASSWORD)
            server.sendmail(GMAIL_USER, to, msg.as_string())
        return True
    except Exception as e:
        print(f"Email failed: {e}")
        return False
