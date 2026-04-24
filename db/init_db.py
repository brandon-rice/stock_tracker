from sqlalchemy import text
from db.connection import local_engine, neon_engine
from db.models import Base, SCHEMA


def init_db():
    for engine, label in ((local_engine, "Local"), (neon_engine, "Neon")):
        with engine.connect() as conn:
            conn.execute(text(f"CREATE SCHEMA IF NOT EXISTS {SCHEMA}"))
            conn.commit()
        Base.metadata.create_all(engine)
        print(f"{label} DB: schema '{SCHEMA}' and tables created.")


if __name__ == "__main__":
    init_db()
