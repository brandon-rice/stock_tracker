from datetime import date, timedelta
import pandas as pd
from sqlalchemy.dialects.postgresql import insert
from db.connection import get_sessions
from db.models import Stock, DailyPrice, MovingAverage


def compute_and_store_moving_averages(ticker: str):
    with get_sessions() as (local, neon):
        stock = local.query(Stock).filter_by(ticker=ticker.upper()).first()
        if not stock:
            raise ValueError(f"Ticker {ticker} not found.")

        cutoff = date.today() - timedelta(days=95)
        rows = (
            local.query(DailyPrice)
            .filter(DailyPrice.stock_id == stock.id, DailyPrice.date >= cutoff)
            .order_by(DailyPrice.date)
            .all()
        )

        if not rows:
            return 0

        df = pd.DataFrame([{"date": r.date, "close": r.close} for r in rows])
        df = df.sort_values("date").set_index("date")
        df["ma_30"] = df["close"].rolling(30, min_periods=1).mean()
        df["ma_60"] = df["close"].rolling(60, min_periods=1).mean()
        df["ma_90"] = df["close"].rolling(90, min_periods=1).mean()

        ma_rows = []
        for d, row in df.iterrows():
            ma_rows.append({
                "date": d,
                "ma_30": round(row["ma_30"], 4) if pd.notna(row["ma_30"]) else None,
                "ma_60": round(row["ma_60"], 4) if pd.notna(row["ma_60"]) else None,
                "ma_90": round(row["ma_90"], 4) if pd.notna(row["ma_90"]) else None,
            })

        def _store(session, stock_id):
            for r in ma_rows:
                stmt = insert(MovingAverage).values(stock_id=stock_id, **r)
                stmt = stmt.on_conflict_do_update(
                    index_elements=["stock_id", "date"],
                    set_={k: v for k, v in r.items()},
                )
                session.execute(stmt)

        local_id = local.query(Stock).filter_by(ticker=ticker.upper()).first().id
        neon_id = neon.query(Stock).filter_by(ticker=ticker.upper()).first().id
        _store(local, local_id)
        _store(neon, neon_id)

    return len(ma_rows)
