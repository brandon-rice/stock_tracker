from contextlib import contextmanager
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, Session
from config import LOCAL_DB_URL, NEON_DB_URL

local_engine = create_engine(LOCAL_DB_URL, pool_pre_ping=True)
neon_engine = create_engine(NEON_DB_URL, pool_pre_ping=True)

LocalSession = sessionmaker(bind=local_engine)
NeonSession = sessionmaker(bind=neon_engine)


@contextmanager
def get_sessions():
    local = LocalSession()
    neon = NeonSession()
    try:
        yield local, neon
        local.commit()
        neon.commit()
    except Exception:
        local.rollback()
        neon.rollback()
        raise
    finally:
        local.close()
        neon.close()


def dual_write(fn, *args, **kwargs):
    """Execute fn(session, *args, **kwargs) against both DBs. Rolls back both on any failure."""
    with get_sessions() as (local, neon):
        fn(local, *args, **kwargs)
        fn(neon, *args, **kwargs)
