from db.connection import local_engine, neon_engine
from db.models import Base


def init_db():
    Base.metadata.create_all(local_engine)
    print("Local DB tables created.")
    Base.metadata.create_all(neon_engine)
    print("Neon DB tables created.")


if __name__ == "__main__":
    init_db()
