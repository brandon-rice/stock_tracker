import json
from datetime import datetime
import anthropic
from sqlalchemy.dialects.postgresql import insert
from config import ANTHROPIC_API_KEY
from db.connection import get_sessions
from db.models import Sentiment, Transcript, Stock

_claude = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)

_PROMPT = """You are a financial analyst specializing in earnings call analysis. Analyze the following earnings call transcript and return a JSON object with exactly these fields:

- "overall_score": float from -1.0 (very negative) to 1.0 (very positive)
- "tone_label": one of "positive", "neutral", "cautious", "negative"
- "key_themes": array of 3-5 short strings (main topics discussed)
- "management_confidence": one of "high", "medium", "low"
- "guidance_sentiment": one of "raised", "maintained", "lowered", "withdrawn", "not_provided"
- "summary": 2-3 sentence narrative summarizing the overall tone and key takeaways

Return only valid JSON, no markdown.

Transcript:
{transcript}"""


def analyze_and_store_sentiment(ticker: str, year: int, quarter: int) -> dict | None:
    with get_sessions() as (local, neon):
        stock = local.query(Stock).filter_by(ticker=ticker.upper()).first()
        if not stock:
            raise ValueError(f"Ticker {ticker} not found.")

        transcript = local.query(Transcript).filter_by(
            stock_id=stock.id, fiscal_year=year, fiscal_quarter=quarter
        ).first()

        if not transcript:
            print(f"No transcript for {ticker} Q{quarter} {year}. Fetch it first.")
            return None

        result = _call_claude(transcript.transcript_text)
        if not result:
            return None

        def _store(session, transcript_id):
            stmt = insert(Sentiment).values(
                transcript_id=transcript_id,
                overall_score=result.get("overall_score"),
                tone_label=result.get("tone_label"),
                key_themes=result.get("key_themes"),
                management_confidence=result.get("management_confidence"),
                guidance_sentiment=result.get("guidance_sentiment"),
                summary=result.get("summary"),
                analyzed_at=datetime.utcnow(),
            )
            stmt = stmt.on_conflict_do_update(
                index_elements=["transcript_id"],
                set_={k: result.get(k) for k in ["overall_score", "tone_label", "key_themes",
                                                   "management_confidence", "guidance_sentiment", "summary"]},
            )
            session.execute(stmt)

        local_transcript_id = transcript.id
        neon_transcript = neon.query(Transcript).filter_by(
            stock_id=neon.query(Stock).filter_by(ticker=ticker.upper()).first().id,
            fiscal_year=year, fiscal_quarter=quarter
        ).first()

        _store(local, local_transcript_id)
        if neon_transcript:
            _store(neon, neon_transcript.id)

    return result


def _call_claude(transcript_text: str) -> dict | None:
    # Truncate very long transcripts to avoid token limits
    text = transcript_text[:40000] if len(transcript_text) > 40000 else transcript_text
    try:
        msg = _claude.messages.create(
            model="claude-sonnet-4-6",
            max_tokens=1024,
            messages=[{"role": "user", "content": _PROMPT.format(transcript=text)}],
        )
        raw = msg.content[0].text.strip()
        return json.loads(raw)
    except Exception as e:
        print(f"Claude sentiment analysis failed: {e}")
        return None
