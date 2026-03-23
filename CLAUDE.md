# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Commands

```bash
# Install dependencies
pip install -r requirements.txt

# Run development server
uvicorn app.main:app --reload

# Run all tests
pytest

# Run a single test file
pytest tests/test_auth.py

# Run a single test by name
pytest tests/test_tables.py::test_create_table -v
```

## Architecture

**DataTracker** is a FastAPI web application for managing dynamic data tables with role-based access control. It uses synchronous SQLAlchemy with SQLite, Jinja2 templates, and cookie-based session authentication.

### Data model

The schema is built around *dynamic* user-defined tables:

- `DataTable` → owns `TableColumn` (typed: TEXT, INTEGER, FLOAT, DATE, BOOLEAN, EMAIL, SELECT) and `TableRow`
- `TableRow` + `TableColumn` → `CellValue` (the actual data lives here, EAV-style)
- `TablePermission` — table-level READ/WRITE grants per user
- `ColumnPermission` — column-level HIDDEN/READONLY flags per user

The first registered user is automatically made admin. Admins see all tables; others only see tables they own or have been granted access to.

### Auth & sessions

`app/auth.py` handles bcrypt password hashing and ITSDangerous cookie-based sessions (`dt_session`, 7-day expiry). `app/dependencies.py` provides FastAPI dependency-injection helpers (`get_current_user`, `can_access_table`, `get_visible_columns`, etc.) used by all routers.

### Routers

All routers are mounted under `/auth` or `/tables`. The five routers in `app/routers/` cover:

| Router | Responsibility |
|---|---|
| `auth.py` | Login, register, logout |
| `tables.py` | Table CRUD + column schema editing |
| `data.py` | Row CRUD + CSV import (supports HTMX via `HX-Request` header) |
| `export.py` | Excel export (openpyxl, styled headers, respects column visibility) |
| `permissions.py` | Bulk table-level and column-level permission management |

### Background tasks

`app/scheduler.py` uses APScheduler to run a nightly cleanup (3 AM) that removes orphan rows (rows with no cell values).

### Tests

`tests/conftest.py` sets up an in-memory SQLite database and provides fixtures for an admin client and regular-user client. Tests are synchronous (FastAPI `TestClient`) despite `asyncio_mode = auto` in `pytest.ini`.
