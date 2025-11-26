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


def ensure_zoom_setting_text() -> None:
    """Ensure zoom_setting is varchar (text) to allow non-numeric values."""
    check_sql = """
    SELECT data_type FROM information_schema.columns
    WHERE table_name='maptech_users' AND column_name='zoom_setting';
    """
    alter_sql = """
    ALTER TABLE maptech_users
    ALTER COLUMN zoom_setting TYPE VARCHAR USING zoom_setting::text;
    """
    with engine.begin() as conn:
        current = conn.execute(text(check_sql)).scalar()
        # If column exists and is not character varying/text, alter it.
        if current and "char" not in current.lower():
            conn.execute(text(alter_sql))


def init_db(seed: bool = True) -> None:
    Base.metadata.create_all(bind=engine)
    ensure_password_column()
    ensure_visit_end_nullable()
    ensure_zoom_setting_text()
    if seed:
        seed_if_empty()


if __name__ == "__main__":
    init_db()
