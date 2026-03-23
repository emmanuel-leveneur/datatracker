from sqlalchemy import create_engine
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
    migrations = [
        # feat/tracabilite : liaison des logs à une table spécifique
        "ALTER TABLE activity_logs ADD COLUMN table_id INTEGER",
    ]
    with engine.connect() as conn:
        existing = {
            row[1]
            for row in conn.execute(
                __import__("sqlalchemy").text("PRAGMA table_info(activity_logs)")
            )
        }
        for stmt in migrations:
            # Extrait le nom de colonne depuis "... ADD COLUMN <name> ..."
            col_name = stmt.split("ADD COLUMN")[1].strip().split()[0]
            if col_name not in existing:
                conn.execute(__import__("sqlalchemy").text(stmt))
                conn.commit()
