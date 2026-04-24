from sqlalchemy import create_engine, text
from db.connection import local_engine, neon_engine
from db.models import Base, SCHEMA
from config import LOCAL_DB_URL


def _create_local_db_if_missing():
    # Connect to the default 'postgres' DB to create our database
    default_url = LOCAL_DB_URL.rsplit("/", 1)[0] + "/postgres"
    engine = create_engine(default_url, isolation_level="AUTOCOMMIT")
    db_name = LOCAL_DB_URL.rsplit("/", 1)[-1]
    with engine.connect() as conn:
        exists = conn.execute(
            text("SELECT 1 FROM pg_database WHERE datname = :name"), {"name": db_name}
        ).fetchone()
        if not exists:
            conn.execute(text(f'CREATE DATABASE "{db_name}"'))
            print(f"Local DB: created database '{db_name}'")
        else:
            print(f"Local DB: database '{db_name}' already exists")
    engine.dispose()


def init_db():
    _create_local_db_if_missing()

    for engine, label in ((local_engine, "Local"), (neon_engine, "Neon")):
        with engine.connect() as conn:
            conn.execute(text(f"CREATE SCHEMA IF NOT EXISTS {SCHEMA}"))
            conn.commit()
        Base.metadata.create_all(engine)
        print(f"{label} DB: schema '{SCHEMA}' and tables created.")


if __name__ == "__main__":
    init_db()
