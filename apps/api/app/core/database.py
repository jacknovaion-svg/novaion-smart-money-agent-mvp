import os
from typing import Generator

from sqlalchemy import create_engine, event, text
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from app.core.config import get_settings


class Base(DeclarativeBase):
    pass


settings = get_settings()

if settings.database_url.startswith("sqlite:///"):
    sqlite_path = settings.database_url.replace("sqlite:///", "", 1)
    sqlite_dir = os.path.dirname(sqlite_path)
    if sqlite_dir:
        os.makedirs(sqlite_dir, exist_ok=True)

connect_args = {"check_same_thread": False} if settings.database_url.startswith("sqlite") else {}
engine = create_engine(settings.database_url, connect_args=connect_args)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


@event.listens_for(engine, "connect")
def set_sqlite_pragma(dbapi_connection, _connection_record):
    if settings.database_url.startswith("sqlite"):
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA journal_mode=WAL")
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()


def get_db() -> Generator[Session, None, None]:
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def init_db() -> None:
    from app.models import discovery, market_data, ops, signal, system_log, wallet  # noqa: F401

    Base.metadata.create_all(bind=engine)
    _ensure_sqlite_columns()


def _ensure_sqlite_columns() -> None:
    if not settings.database_url.startswith("sqlite"):
        return
    table_columns = {
        "discovery_candidates": {
            "gross_profit": "FLOAT DEFAULT 0",
            "avg_leverage": "FLOAT DEFAULT 0",
            "max_drawdown": "FLOAT DEFAULT 0",
            "risk_score": "INTEGER DEFAULT 0",
            "grade": "VARCHAR(20) DEFAULT 'Watch'",
            "aggregation_confidence": "VARCHAR(20) DEFAULT 'low'",
            "metrics_estimated": "INTEGER DEFAULT 1",
            "funding_included": "INTEGER DEFAULT 0",
            "drawdown_estimation_method": "VARCHAR(80) DEFAULT 'current_account_value'",
            "hard_filter_pass": "INTEGER DEFAULT 0",
            "soft_watch_eligible": "INTEGER DEFAULT 0",
            "failed_reasons": "TEXT DEFAULT '[]'",
            "failure_reason": "TEXT DEFAULT ''",
        },
        "discovery_runs": {
            "scanned_count": "INTEGER DEFAULT 0",
            "recommended_count": "INTEGER DEFAULT 0",
            "failed_count": "INTEGER DEFAULT 0",
            "no_activity_count": "INTEGER DEFAULT 0",
        },
        "paper_trades": {
            "raw_pnl": "FLOAT DEFAULT 0",
            "fees": "FLOAT DEFAULT 0",
            "slippage_adjustment": "FLOAT DEFAULT 0",
            "net_pnl": "FLOAT DEFAULT 0",
            "mark_price": "FLOAT DEFAULT 0",
            "unrealized_pnl": "FLOAT DEFAULT 0",
            "unrealized_pnl_pct": "FLOAT DEFAULT 0",
            "updated_at": "DATETIME",
        },
    }
    with engine.begin() as connection:
        for table, columns in table_columns.items():
            existing = {row[1] for row in connection.execute(text(f"PRAGMA table_info({table})")).fetchall()}
            for column, definition in columns.items():
                if column not in existing:
                    connection.execute(text(f"ALTER TABLE {table} ADD COLUMN {column} {definition}"))
