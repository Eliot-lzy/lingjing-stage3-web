from __future__ import annotations

from pathlib import Path
from typing import Iterator

from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker


APP_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = APP_DIR.parent
DATA_DIR = PROJECT_ROOT / "data"
DATA_DIR.mkdir(parents=True, exist_ok=True)

DATABASE_PATH = DATA_DIR / "app.db"
DATABASE_URL = f"sqlite:///{DATABASE_PATH.as_posix()}"

engine = create_engine(
    DATABASE_URL,
    connect_args={"check_same_thread": False},
)

SessionLocal = sessionmaker(
    bind=engine,
    autoflush=False,
    autocommit=False,
)


class Base(DeclarativeBase):
    pass


def ensure_schema() -> None:
    with engine.begin() as connection:
        rows = connection.exec_driver_sql("PRAGMA table_info(tasks)").fetchall()
        columns = {row[1] for row in rows}

        if "title" not in columns:
            connection.exec_driver_sql(
                "ALTER TABLE tasks ADD COLUMN title VARCHAR(255)"
            )

        if "owner_id" not in columns:
            connection.exec_driver_sql(
                "ALTER TABLE tasks ADD COLUMN owner_id VARCHAR(36)"
            )

        connection.exec_driver_sql(
            "UPDATE tasks SET title = original_name "
            "WHERE title IS NULL OR title = ''"
        )
        connection.exec_driver_sql(
            "CREATE INDEX IF NOT EXISTS ix_tasks_owner_id "
            "ON tasks (owner_id)"
        )


def get_db() -> Iterator[Session]:
    database = SessionLocal()
    try:
        yield database
    finally:
        database.close()
