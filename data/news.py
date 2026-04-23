import json
import requests
from datetime import datetime
import yfinance as yf
import anthropic
from sqlalchemy.dialects.postgresql import insert
from config import FMP_API_KEY, FMP_BASE_URL, ANTHROPIC_API_KEY
from db.connection import get_sessions
from db.models import News, Stock

_claude = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)

_SIGNIFICANCE_PROMPT = """You are a financial news analyst. From the list of news headlines below, return ONLY those that represent a major, market-moving event such as:
- Earnings surprise (beat or miss)
- Merger, acquisition, or strategic partnership
- Regulatory action, lawsuit, or government investigation
- CEO or CFO change
- Significant guidance revision (raised or lowered)
- Major product launch or recall
- Dividend initiation, suspension, or significant change
- Bankruptcy or restructuring

Return a JSON array. Each item must have: "headline", "url", "reason" (why it's significant).
If none are significant, return an empty array [].

Headlines:
{headlines}"""


def fetch_and_store_news(ticker: str, limit: int = 20):
    headlines = _fetch_headlines(ticker, limit)
    if not headlines:
        return 0

    significant = _filter_significant(headlines)
    sig_urls = {item["url"] for item in significant}

    def _store(session, stock_id):
        for item in headlines:
            is_sig = item["url"] in sig_urls
            reason = next((s["reason"] for s in significant if s["url"] == item["url"]), None)
            stmt = insert(News).values(
                stock_id=stock_id,
                headline=item["headline"],
                url=item["url"],
                source=item.get("source"),
                published_at=item.get("published_at"),
                is_significant=is_sig,
                significance_reason=reason,
                fetched_at=datetime.utcnow(),
            )
            stmt = stmt.on_conflict_do_update(
                index_elements=["stock_id", "url"],
                set_={"is_significant": is_sig, "significance_reason": reason},
            )
            session.execute(stmt)

    with get_sessions() as (local, neon):
        stock_local = local.query(Stock).filter_by(ticker=ticker.upper()).first()
        stock_neon = neon.query(Stock).filter_by(ticker=ticker.upper()).first()
        if not stock_local:
            raise ValueError(f"Ticker {ticker} not found in portfolio.")
        _store(local, stock_local.id)
        _store(neon, stock_neon.id)

    return len(significant)


def _fetch_headlines(ticker: str, limit: int) -> list[dict]:
    items = []

    try:
        url = f"{FMP_BASE_URL}/stock_news"
        resp = requests.get(url, params={"tickers": ticker.upper(), "limit": limit, "apikey": FMP_API_KEY}, timeout=15)
        resp.raise_for_status()
        for article in resp.json():
            items.append({
                "headline": article.get("title", ""),
                "url": article.get("url", ""),
                "source": article.get("site", ""),
                "published_at": _parse_dt(article.get("publishedDate")),
            })
    except Exception as e:
        print(f"FMP news fetch failed: {e}")

    try:
        t = yf.Ticker(ticker.upper())
        for article in (t.news or []):
            url = article.get("link") or article.get("url", "")
            if url and not any(i["url"] == url for i in items):
                items.append({
                    "headline": article.get("title", ""),
                    "url": url,
                    "source": article.get("publisher", ""),
                    "published_at": datetime.fromtimestamp(article["providerPublishTime"]) if article.get("providerPublishTime") else None,
                })
    except Exception as e:
        print(f"yfinance news fetch failed: {e}")

    return items


def _filter_significant(headlines: list[dict]) -> list[dict]:
    if not headlines:
        return []

    formatted = "\n".join(f"- {h['headline']} | {h['url']}" for h in headlines)
    try:
        msg = _claude.messages.create(
            model="claude-sonnet-4-6",
            max_tokens=1024,
            messages=[{"role": "user", "content": _SIGNIFICANCE_PROMPT.format(headlines=formatted)}],
        )
        text = msg.content[0].text.strip()
        start = text.find("[")
        end = text.rfind("]") + 1
        if start >= 0 and end > start:
            return json.loads(text[start:end])
    except Exception as e:
        print(f"Claude news filtering failed: {e}")
    return []


def _parse_dt(s: str | None) -> datetime | None:
    if not s:
        return None
    try:
        return datetime.fromisoformat(s.replace("Z", "+00:00"))
    except Exception:
        return None
