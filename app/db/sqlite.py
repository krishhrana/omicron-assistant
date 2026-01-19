from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

from app.core.settings import get_settings


SCHEMA_PATH = Path(__file__).resolve().with_name("schema.sql")


def _resolve_db_path() -> Path:
    settings = get_settings()
    db_path = Path(settings.sqlite_db_path)
    if not db_path.is_absolute():
        db_path = Path(__file__).resolve().parents[2] / db_path
    return db_path


def _ensure_schema(conn: sqlite3.Connection) -> None:
    schema_sql = SCHEMA_PATH.read_text(encoding="utf-8")
    conn.executescript(schema_sql)


@contextmanager
def get_connection() -> Iterator[sqlite3.Connection]:
    db_path = _resolve_db_path()
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db_path)
    try:
        _ensure_schema(conn)
        yield conn
        conn.commit()
    finally:
        conn.close()
