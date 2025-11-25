"""
Database initialization script.
Run separately from app startup to create tables and (optionally) seed sample data.

Usage:
  python -c "from init_db import init_db; init_db()"
  # without seeding:
  python -c "from init_db import init_db; init_db(seed=False)"
"""

from main import Base, engine, seed_if_empty


def init_db(seed: bool = True) -> None:
    Base.metadata.create_all(bind=engine)
    if seed:
        seed_if_empty()


if __name__ == "__main__":
    init_db()
