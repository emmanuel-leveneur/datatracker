from sqlalchemy import create_engine, text
from sqlalchemy.orm import DeclarativeBase, sessionmaker

DATABASE_URL = "sqlite:///./datatracker.db"

engine = create_engine(
    DATABASE_URL,
    connect_args={"check_same_thread": False},
)

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


class Base(DeclarativeBase):
    pass


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def create_tables():
    from app import models  # noqa: F401
    Base.metadata.create_all(bind=engine)
    _run_migrations()


def _run_migrations():
    """Migrations incrémentales pour les colonnes ajoutées après la création initiale."""
    # table_name → list of (column_name, ALTER statement)
    migrations_by_table = {
        "activity_logs": [
            ("table_id", "ALTER TABLE activity_logs ADD COLUMN table_id INTEGER"),
        ],
        "data_tables": [
            ("deleted_at", "ALTER TABLE data_tables ADD COLUMN deleted_at DATETIME"),
        ],
        "table_rows": [
            ("deleted_at", "ALTER TABLE table_rows ADD COLUMN deleted_at DATETIME"),
        ],
    }
    with engine.connect() as conn:
        for table_name, columns in migrations_by_table.items():
            existing = {
                row[1]
                for row in conn.execute(text(f"PRAGMA table_info({table_name})"))
            }
            for col_name, stmt in columns:
                if col_name not in existing:
                    conn.execute(text(stmt))
                    conn.commit()
