"""Tests pour la contrainte d'unicité par colonne."""
import io
import pytest
from app.models import CellValue, ColumnType, TableRow
from tests.helpers import make_table
from tests.conftest import _authenticated_client


# ── helpers ──────────────────────────────────────────────────────────────────

def _make_unique_table(db, owner):
    table, cols = make_table(db, owner, "Clients", columns=[
        ("Email", ColumnType.EMAIL),
        ("Nom", ColumnType.TEXT),
    ])
    cols[0].is_unique = True  # Email unique
    db.commit()
    db.refresh(table)
    return table, cols


def _add_row(db, table, owner, email="a@test.com", nom="Alice"):
    row = TableRow(table_id=table.id, created_by_id=owner.id)
    db.add(row)
    db.flush()
    db.add(CellValue(row_id=row.id, column_id=table.columns[0].id, value=email))
    db.add(CellValue(row_id=row.id, column_id=table.columns[1].id, value=nom))
    db.commit()
    db.refresh(row)
    return row


# ── create_row ────────────────────────────────────────────────────────────────

def test_create_row_unique_ok(admin_client, db, admin_user):
    table, cols = _make_unique_table(db, admin_user)
    resp = admin_client.post(
        f"/tables/{table.id}/rows/new",
        data={f"col_{cols[0].id}": "new@test.com", f"col_{cols[1].id}": "Alice"},
        headers={"HX-Request": "true"},
    )
    assert resp.status_code == 200
    assert db.query(TableRow).filter_by(table_id=table.id).count() == 1


def test_create_row_unique_violation(admin_client, db, admin_user):
    table, cols = _make_unique_table(db, admin_user)
    _add_row(db, table, admin_user, email="dup@test.com")

    resp = admin_client.post(
        f"/tables/{table.id}/rows/new",
        data={f"col_{cols[0].id}": "dup@test.com", f"col_{cols[1].id}": "Bob"},
        headers={"HX-Request": "true"},
    )
    assert resp.status_code == 200
    # Form re-rendered with error — row count still 1
    assert "existe déjà" in resp.text
    assert db.query(TableRow).filter_by(table_id=table.id).count() == 1


def test_create_row_unique_case_insensitive(admin_client, db, admin_user):
    table, cols = _make_unique_table(db, admin_user)
    _add_row(db, table, admin_user, email="Test@Example.com")

    resp = admin_client.post(
        f"/tables/{table.id}/rows/new",
        data={f"col_{cols[0].id}": "test@example.com", f"col_{cols[1].id}": "Bob"},
        headers={"HX-Request": "true"},
    )
    assert resp.status_code == 200
    assert "existe déjà" in resp.text
    assert db.query(TableRow).filter_by(table_id=table.id).count() == 1


def test_create_row_empty_value_not_unique(admin_client, db, admin_user):
    """Valeurs vides ne comptent pas pour l'unicité."""
    table, cols = _make_unique_table(db, admin_user)
    _add_row(db, table, admin_user, email="")

    resp = admin_client.post(
        f"/tables/{table.id}/rows/new",
        data={f"col_{cols[0].id}": "", f"col_{cols[1].id}": "Bob"},
        headers={"HX-Request": "true"},
    )
    assert resp.status_code == 200
    assert "existe déjà" not in resp.text
    assert db.query(TableRow).filter_by(table_id=table.id).count() == 2


# ── update_row ────────────────────────────────────────────────────────────────

def test_update_row_unique_ok(admin_client, db, admin_user):
    table, cols = _make_unique_table(db, admin_user)
    row1 = _add_row(db, table, admin_user, email="a@test.com")
    _add_row(db, table, admin_user, email="b@test.com")

    resp = admin_client.post(
        f"/tables/{table.id}/rows/{row1.id}/edit",
        data={f"col_{cols[0].id}": "a@test.com", f"col_{cols[1].id}": "Alice Updated"},
        headers={"HX-Request": "true"},
    )
    assert resp.status_code == 200
    assert "existe déjà" not in resp.text


def test_update_row_unique_violation(admin_client, db, admin_user):
    table, cols = _make_unique_table(db, admin_user)
    row1 = _add_row(db, table, admin_user, email="a@test.com")
    _add_row(db, table, admin_user, email="b@test.com")

    resp = admin_client.post(
        f"/tables/{table.id}/rows/{row1.id}/edit",
        data={f"col_{cols[0].id}": "b@test.com", f"col_{cols[1].id}": "Alice"},
        headers={"HX-Request": "true"},
    )
    assert resp.status_code == 200
    assert "existe déjà" in resp.text


def test_update_row_trashed_value_freed(admin_client, db, admin_user):
    """Une ligne à la corbeille libère sa valeur pour l'unicité."""
    from datetime import datetime
    table, cols = _make_unique_table(db, admin_user)
    row1 = _add_row(db, table, admin_user, email="freed@test.com")
    row1.deleted_at = datetime.utcnow()
    db.commit()

    row2 = _add_row(db, table, admin_user, email="other@test.com")
    resp = admin_client.post(
        f"/tables/{table.id}/rows/{row2.id}/edit",
        data={f"col_{cols[0].id}": "freed@test.com", f"col_{cols[1].id}": "Bob"},
        headers={"HX-Request": "true"},
    )
    assert resp.status_code == 200
    assert "existe déjà" not in resp.text


# ── edit column — activation sur données existantes ──────────────────────────

def test_edit_enable_unique_on_clean_column(admin_client, db, admin_user):
    table, cols = make_table(db, admin_user, "T1", columns=[("Ref", ColumnType.TEXT)])
    col = cols[0]
    # Rows with distinct values
    for i, val in enumerate(["A", "B", "C"]):
        row = TableRow(table_id=table.id, created_by_id=admin_user.id)
        db.add(row)
        db.flush()
        db.add(CellValue(row_id=row.id, column_id=col.id, value=val))
    db.commit()

    resp = admin_client.post(
        f"/tables/{table.id}/edit",
        data={
            "name": "T1", "description": "",
            "col_ids": [str(col.id)], "col_names": ["Ref"], "col_types": ["text"],
            "col_required": [], "col_unique": ["0"], "col_personal_data": [],
            "col_options": [""], "col_related_table_ids": [""],
            "col_related_display_col_ids": [""], "col_related_value_col_ids": [""],
        },
    )
    assert resp.status_code in (200, 303)
    db.refresh(col)
    assert col.is_unique is True


def test_edit_enable_unique_blocked_on_duplicates(admin_client, db, admin_user):
    table, cols = make_table(db, admin_user, "T2", columns=[("Ref", ColumnType.TEXT)])
    col = cols[0]
    for val in ["DUP", "dup"]:  # same value, different case
        row = TableRow(table_id=table.id, created_by_id=admin_user.id)
        db.add(row)
        db.flush()
        db.add(CellValue(row_id=row.id, column_id=col.id, value=val))
    db.commit()

    resp = admin_client.post(
        f"/tables/{table.id}/edit",
        data={
            "name": "T2", "description": "",
            "col_ids": [str(col.id)], "col_names": ["Ref"], "col_types": ["text"],
            "col_required": [], "col_unique": ["0"], "col_personal_data": [],
            "col_options": [""], "col_related_table_ids": [""],
            "col_related_display_col_ids": [""], "col_related_value_col_ids": [""],
        },
    )
    assert resp.status_code == 200
    assert "doublon" in resp.text.lower()
    db.refresh(col)
    assert col.is_unique is False  # not saved


# ── CSV import ────────────────────────────────────────────────────────────────

def _csv_file(content: str):
    return ("test.csv", io.BytesIO(content.encode()), "text/csv")


def test_import_csv_unique_ok(admin_client, db, admin_user):
    table, cols = _make_unique_table(db, admin_user)
    csv_content = f"Email,Nom\na@x.com,Alice\nb@x.com,Bob\n"
    resp = admin_client.post(
        f"/tables/{table.id}/import",
        files={"file": _csv_file(csv_content)},
    )
    assert resp.status_code == 200
    assert "importée" in resp.text
    assert db.query(TableRow).filter_by(table_id=table.id).count() == 2


def test_import_csv_intra_file_duplicate(admin_client, db, admin_user):
    table, cols = _make_unique_table(db, admin_user)
    csv_content = "Email,Nom\na@x.com,Alice\na@x.com,Bob\n"
    resp = admin_client.post(
        f"/tables/{table.id}/import",
        files={"file": _csv_file(csv_content)},
    )
    assert resp.status_code == 200
    assert "doublon" in resp.text
    assert db.query(TableRow).filter_by(table_id=table.id).count() == 0  # rollback


def test_import_csv_existing_db_duplicate(admin_client, db, admin_user):
    table, cols = _make_unique_table(db, admin_user)
    _add_row(db, table, admin_user, email="existing@x.com")

    csv_content = "Email,Nom\nexisting@x.com,Bob\nnew@x.com,Carol\n"
    resp = admin_client.post(
        f"/tables/{table.id}/import",
        files={"file": _csv_file(csv_content)},
    )
    assert resp.status_code == 200
    assert "existe déjà" in resp.text
    assert db.query(TableRow).filter_by(table_id=table.id).count() == 1  # only the pre-existing row


def test_import_csv_collects_all_errors(admin_client, db, admin_user):
    """Toutes les erreurs sont collectées, pas seulement la première."""
    table, cols = _make_unique_table(db, admin_user)
    _add_row(db, table, admin_user, email="a@x.com")
    _add_row(db, table, admin_user, email="b@x.com")

    csv_content = "Email,Nom\na@x.com,X\nb@x.com,Y\nc@x.com,Z\n"
    resp = admin_client.post(
        f"/tables/{table.id}/import",
        files={"file": _csv_file(csv_content)},
    )
    assert resp.status_code == 200
    # Both duplicates should be reported
    assert resp.text.count("existe déjà") == 2
