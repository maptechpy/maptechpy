"""
Database initialization script.
Run separately from app startup to create tables and (optionally) seed sample data.

Usage:
  python -c "from init_db import init_db; init_db()"
  # without seeding:
  python -c "from init_db import init_db; init_db(seed=False)"
"""

from sqlalchemy import text

from main import Base, engine, seed_if_empty


def ensure_password_column() -> None:
    """Add password column to maptech_users if it doesn't exist (for existing DB)."""
    alter_sql = """
    ALTER TABLE maptech_users
    ADD COLUMN IF NOT EXISTS password VARCHAR;
    """
    with engine.begin() as conn:
        conn.execute(text(alter_sql))


def ensure_visit_end_nullable() -> None:
    """Allow end_at to be NULL for visit_schedules."""
    alter_sql = """
    ALTER TABLE visit_schedules
    ALTER COLUMN end_at DROP NOT NULL;
    """
    with engine.begin() as conn:
        conn.execute(text(alter_sql))


def init_db(seed: bool = True) -> None:
    Base.metadata.create_all(bind=engine)
    ensure_password_column()
    ensure_visit_end_nullable()
    if seed:
        seed_if_empty()


if __name__ == "__main__":
    init_db()
