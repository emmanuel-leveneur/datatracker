"""Tests : CRUD des lignes, import CSV, enforcement des permissions d'écriture."""
import io
import pytest
from fastapi.testclient import TestClient

from app.models import (
    CellValue, ColumnPermission, ColumnType, PermissionLevel,
    TablePermission, TableRow,
)
from tests.helpers import make_table


# ── Création de lignes ────────────────────────────────────────────────────────

def test_create_row_as_owner(admin_client, db, admin_user):
    table, cols = make_table(db, admin_user, columns=[("Nom", ColumnType.TEXT)])
    col = cols[0]

    resp = admin_client.post(f"/tables/{table.id}/rows/new", data={f"col_{col.id}": "Alice"})

    assert resp.status_code in (200, 303)
    db.expire_all()
    row = db.query(TableRow).filter_by(table_id=table.id).first()
    assert row is not None
    cell = db.query(CellValue).filter_by(row_id=row.id, column_id=col.id).first()
    assert cell.value == "Alice"


def test_create_row_requires_write_permission(user_client, db, admin_user, regular_user):
    table, cols = make_table(db, admin_user, columns=[("Nom", ColumnType.TEXT)])
    col = cols[0]
    db.add(TablePermission(table_id=table.id, user_id=regular_user.id, level=PermissionLevel.READ))
    db.commit()

    resp = user_client.post(f"/tables/{table.id}/rows/new", data={f"col_{col.id}": "X"})

    assert resp.status_code == 403


def test_create_row_with_write_permission_succeeds(user_client, db, admin_user, regular_user):
    table, cols = make_table(db, admin_user, columns=[("Nom", ColumnType.TEXT)])
    col = cols[0]
    db.add(TablePermission(table_id=table.id, user_id=regular_user.id, level=PermissionLevel.WRITE))
    db.commit()

    resp = user_client.post(f"/tables/{table.id}/rows/new", data={f"col_{col.id}": "Alice"})

    assert resp.status_code in (200, 303)
    db.expire_all()
    assert db.query(TableRow).filter_by(table_id=table.id).count() == 1


def test_create_row_without_any_permission_is_forbidden(user_client, db, admin_user):
    table, cols = make_table(db, admin_user, columns=[("Nom", ColumnType.TEXT)])

    resp = user_client.post(f"/tables/{table.id}/rows/new", data={f"col_{cols[0].id}": "X"})

    assert resp.status_code == 403


# ── Édition de lignes ─────────────────────────────────────────────────────────

def test_edit_row_updates_cell(admin_client, db, admin_user):
    table, cols = make_table(db, admin_user, columns=[("Nom", ColumnType.TEXT)])
    col = cols[0]
    row = TableRow(table_id=table.id, created_by_id=admin_user.id)
    db.add(row)
    db.flush()
    db.add(CellValue(row_id=row.id, column_id=col.id, value="Avant"))
    db.commit()

    resp = admin_client.post(f"/tables/{table.id}/rows/{row.id}/edit", data={f"col_{col.id}": "Après"})

    assert resp.status_code in (200, 303)
    db.expire_all()
    assert db.query(CellValue).filter_by(row_id=row.id, column_id=col.id).first().value == "Après"


def test_edit_row_readonly_column_not_overwritten(user_client, db, admin_user, regular_user):
    """Une colonne marquée readonly pour l'utilisateur ne doit pas être modifiée."""
    table, cols = make_table(db, admin_user, columns=[("Verrouillé", ColumnType.TEXT)])
    col = cols[0]
    db.add(TablePermission(table_id=table.id, user_id=regular_user.id, level=PermissionLevel.WRITE))
    db.add(ColumnPermission(column_id=col.id, user_id=regular_user.id, readonly=True))
    row = TableRow(table_id=table.id, created_by_id=admin_user.id)
    db.add(row)
    db.flush()
    db.add(CellValue(row_id=row.id, column_id=col.id, value="valeur_originale"))
    db.commit()

    # L'utilisateur tente d'écraser la valeur
    user_client.post(f"/tables/{table.id}/rows/{row.id}/edit", data={f"col_{col.id}": "tentative"})

    db.expire_all()
    cell = db.query(CellValue).filter_by(row_id=row.id, column_id=col.id).first()
    assert cell.value == "valeur_originale"


def test_edit_row_forbidden_without_write_permission(user_client, db, admin_user, regular_user):
    table, cols = make_table(db, admin_user, columns=[("Nom", ColumnType.TEXT)])
    col = cols[0]
    db.add(TablePermission(table_id=table.id, user_id=regular_user.id, level=PermissionLevel.READ))
    row = TableRow(table_id=table.id, created_by_id=admin_user.id)
    db.add(row)
    db.flush()
    db.add(CellValue(row_id=row.id, column_id=col.id, value="x"))
    db.commit()

    resp = user_client.post(f"/tables/{table.id}/rows/{row.id}/edit", data={f"col_{col.id}": "y"})

    assert resp.status_code == 403


# ── Suppression de lignes ─────────────────────────────────────────────────────

def test_delete_row_moves_to_trash(admin_client, db, admin_user):
    table, _ = make_table(db, admin_user)
    row = TableRow(table_id=table.id, created_by_id=admin_user.id)
    db.add(row)
    db.commit()
    row_id = row.id

    resp = admin_client.post(f"/tables/{table.id}/rows/{row_id}/delete")

    assert resp.status_code in (200, 303)
    db.expire_all()
    r = db.get(TableRow, row_id)
    assert r is not None
    assert r.deleted_at is not None


def test_restore_row(admin_client, db, admin_user):
    from datetime import datetime
    table, _ = make_table(db, admin_user)
    row = TableRow(table_id=table.id, created_by_id=admin_user.id, deleted_at=datetime.utcnow())
    db.add(row)
    db.commit()

    resp = admin_client.post(f"/tables/{table.id}/rows/{row.id}/restore")

    assert resp.status_code == 303
    db.expire_all()
    assert db.get(TableRow, row.id).deleted_at is None


def test_delete_row_permanent(admin_client, db, admin_user):
    from datetime import datetime
    table, _ = make_table(db, admin_user)
    row = TableRow(table_id=table.id, created_by_id=admin_user.id, deleted_at=datetime.utcnow())
    db.add(row)
    db.commit()
    row_id = row.id

    resp = admin_client.post(f"/tables/{table.id}/rows/{row_id}/delete-permanent")

    assert resp.status_code == 303
    db.expire_all()
    assert db.get(TableRow, row_id) is None


def test_delete_row_forbidden_without_write_permission(user_client, db, admin_user, regular_user):
    table, _ = make_table(db, admin_user)
    db.add(TablePermission(table_id=table.id, user_id=regular_user.id, level=PermissionLevel.READ))
    row = TableRow(table_id=table.id, created_by_id=admin_user.id)
    db.add(row)
    db.commit()

    resp = user_client.post(f"/tables/{table.id}/rows/{row.id}/delete")

    assert resp.status_code == 403


def test_delete_nonexistent_row_returns_404(admin_client, db, admin_user):
    table, _ = make_table(db, admin_user)

    resp = admin_client.post(f"/tables/{table.id}/rows/99999/delete")

    assert resp.status_code == 404


# ── Import CSV ────────────────────────────────────────────────────────────────

def test_import_csv_creates_rows(admin_client, db, admin_user):
    table, cols = make_table(
        db, admin_user,
        columns=[("Produit", ColumnType.TEXT), ("Prix", ColumnType.FLOAT)],
    )
    csv_data = "Produit,Prix\nPomme,1.5\nBanane,0.8\n"

    resp = admin_client.post(
        f"/tables/{table.id}/import",
        files={"file": ("data.csv", io.BytesIO(csv_data.encode()), "text/csv")},
    )

    assert resp.status_code == 200
    assert "2" in resp.text
    db.expire_all()
    assert db.query(TableRow).filter_by(table_id=table.id).count() == 2


def test_import_csv_maps_columns_by_name(admin_client, db, admin_user):
    table, cols = make_table(db, admin_user, columns=[("Nom", ColumnType.TEXT)])
    col = cols[0]
    csv_data = "Nom\nAlice\n"

    admin_client.post(
        f"/tables/{table.id}/import",
        files={"file": ("data.csv", io.BytesIO(csv_data.encode()), "text/csv")},
    )

    db.expire_all()
    row = db.query(TableRow).filter_by(table_id=table.id).first()
    cell = db.query(CellValue).filter_by(row_id=row.id, column_id=col.id).first()
    assert cell.value == "Alice"


def test_import_csv_forbidden_without_write_permission(user_client, db, admin_user, regular_user):
    table, _ = make_table(db, admin_user, columns=[("Nom", ColumnType.TEXT)])
    db.add(TablePermission(table_id=table.id, user_id=regular_user.id, level=PermissionLevel.READ))
    db.commit()
    csv_data = "Nom\nX\n"

    resp = user_client.post(
        f"/tables/{table.id}/import",
        files={"file": ("data.csv", io.BytesIO(csv_data.encode()), "text/csv")},
    )

    assert resp.status_code == 403
