from datetime import datetime
from sqlalchemy import (
    Column, Integer, String, Float, Boolean, Date, DateTime,
    Text, ForeignKey, UniqueConstraint
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import declarative_base, relationship

Base = declarative_base()


class Stock(Base):
    __tablename__ = "stocks"

    id = Column(Integer, primary_key=True)
    ticker = Column(String(10), unique=True, nullable=False)
    company_name = Column(String(200))
    added_at = Column(DateTime, default=datetime.utcnow)

    prices = relationship("DailyPrice", back_populates="stock", cascade="all, delete-orphan")
    financials = relationship("Financials", back_populates="stock", cascade="all, delete-orphan")
    moving_averages = relationship("MovingAverage", back_populates="stock", cascade="all, delete-orphan")
    computed_metrics = relationship("ComputedMetrics", back_populates="stock", cascade="all, delete-orphan")
    transcripts = relationship("Transcript", back_populates="stock", cascade="all, delete-orphan")
    news = relationship("News", back_populates="stock", cascade="all, delete-orphan")


class DailyPrice(Base):
    __tablename__ = "daily_prices"
    __table_args__ = (UniqueConstraint("stock_id", "date"),)

    id = Column(Integer, primary_key=True)
    stock_id = Column(Integer, ForeignKey("stocks.id"), nullable=False)
    date = Column(Date, nullable=False)
    open = Column(Float)
    high = Column(Float)
    low = Column(Float)
    close = Column(Float)
    volume = Column(Float)
    adj_close = Column(Float)
    pe_ratio = Column(Float)
    eps = Column(Float)
    fifty_two_week_high = Column(Float)
    fifty_two_week_low = Column(Float)
    debt_to_equity = Column(Float)

    stock = relationship("Stock", back_populates="prices")


class MovingAverage(Base):
    __tablename__ = "moving_averages"
    __table_args__ = (UniqueConstraint("stock_id", "date"),)

    id = Column(Integer, primary_key=True)
    stock_id = Column(Integer, ForeignKey("stocks.id"), nullable=False)
    date = Column(Date, nullable=False)
    ma_30 = Column(Float)
    ma_60 = Column(Float)
    ma_90 = Column(Float)

    stock = relationship("Stock", back_populates="moving_averages")


class Financials(Base):
    __tablename__ = "financials"
    __table_args__ = (UniqueConstraint("stock_id", "fiscal_year", "fiscal_quarter"),)

    id = Column(Integer, primary_key=True)
    stock_id = Column(Integer, ForeignKey("stocks.id"), nullable=False)
    fiscal_year = Column(Integer, nullable=False)
    fiscal_quarter = Column(Integer, nullable=False)
    revenue = Column(Float)
    net_income = Column(Float)
    eps = Column(Float)
    free_cash_flow = Column(Float)
    reported_date = Column(Date)

    stock = relationship("Stock", back_populates="financials")


class ComputedMetrics(Base):
    __tablename__ = "computed_metrics"
    __table_args__ = (UniqueConstraint("stock_id", "computed_date"),)

    id = Column(Integer, primary_key=True)
    stock_id = Column(Integer, ForeignKey("stocks.id"), nullable=False)
    computed_date = Column(Date, nullable=False)
    yoy_revenue_growth = Column(Float)
    yoy_earnings_growth = Column(Float)
    fcf_yoy = Column(Float)
    fcf_qoq = Column(Float)

    stock = relationship("Stock", back_populates="computed_metrics")


class Transcript(Base):
    __tablename__ = "transcripts"
    __table_args__ = (UniqueConstraint("stock_id", "fiscal_year", "fiscal_quarter"),)

    id = Column(Integer, primary_key=True)
    stock_id = Column(Integer, ForeignKey("stocks.id"), nullable=False)
    fiscal_year = Column(Integer, nullable=False)
    fiscal_quarter = Column(Integer, nullable=False)
    transcript_text = Column(Text)
    fetched_at = Column(DateTime, default=datetime.utcnow)

    stock = relationship("Stock", back_populates="transcripts")
    sentiment = relationship("Sentiment", back_populates="transcript", uselist=False, cascade="all, delete-orphan")


class Sentiment(Base):
    __tablename__ = "sentiment"

    id = Column(Integer, primary_key=True)
    transcript_id = Column(Integer, ForeignKey("transcripts.id"), unique=True, nullable=False)
    overall_score = Column(Float)
    tone_label = Column(String(20))
    key_themes = Column(JSONB)
    management_confidence = Column(String(20))
    guidance_sentiment = Column(String(20))
    summary = Column(Text)
    analyzed_at = Column(DateTime, default=datetime.utcnow)

    transcript = relationship("Transcript", back_populates="sentiment")


class News(Base):
    __tablename__ = "news"
    __table_args__ = (UniqueConstraint("stock_id", "url"),)

    id = Column(Integer, primary_key=True)
    stock_id = Column(Integer, ForeignKey("stocks.id"), nullable=False)
    headline = Column(Text, nullable=False)
    url = Column(Text)
    source = Column(String(100))
    published_at = Column(DateTime)
    is_significant = Column(Boolean, default=False)
    significance_reason = Column(Text)
    fetched_at = Column(DateTime, default=datetime.utcnow)

    stock = relationship("Stock", back_populates="news")


class QuarterlyReport(Base):
    __tablename__ = "quarterly_reports"

    id = Column(Integer, primary_key=True)
    generated_at = Column(DateTime, default=datetime.utcnow)
    sent_at = Column(DateTime)
    report_html = Column(Text)
