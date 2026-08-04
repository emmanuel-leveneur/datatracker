"""Tests : modification en masse de plusieurs lignes (bulk-edit)."""
from app.models import ActivityLog, CellValue, ColumnPermission, ColumnType, TableRow
from app.routers.data import BULK_EDIT_MAX_ROWS
from tests.helpers import make_table


def _make_rows(db, table, col, values, user):
    rows = []
    for val in values:
        row = TableRow(table_id=table.id, created_by_id=user.id)
        db.add(row)
        db.flush()
        db.add(CellValue(row_id=row.id, column_id=col.id, value=val))
        rows.append(row)
    db.commit()
    return rows


def test_bulk_edit_updates_all_selected_rows(admin_client, db, admin_user):
    table, cols = make_table(db, admin_user, columns=[("Statut", ColumnType.TEXT)])
    col = cols[0]
    rows = _make_rows(db, table, col, ["Ouvert", "Ouvert", "Ouvert"], admin_user)

    resp = admin_client.post(
        f"/tables/{table.id}/rows/bulk-edit",
        data={"row_ids": [r.id for r in rows], "col_id": col.id, "value": "Cloturé"},
    )

    assert resp.status_code in (200, 303)
    db.expire_all()
    values = [
        db.query(CellValue).filter_by(row_id=r.id, column_id=col.id).first().value
        for r in rows
    ]
    assert values == ["Cloturé", "Cloturé", "Cloturé"]


def test_bulk_edit_logs_one_update_row_entry_per_row(admin_client, db, admin_user):
    table, cols = make_table(db, admin_user, columns=[("Statut", ColumnType.TEXT)])
    col = cols[0]
    rows = _make_rows(db, table, col, ["Ouvert", "Ouvert"], admin_user)

    admin_client.post(
        f"/tables/{table.id}/rows/bulk-edit",
        data={"row_ids": [r.id for r in rows], "col_id": col.id, "value": "Cloturé"},
    )

    db.expire_all()
    logs = db.query(ActivityLog).filter_by(action="update_row", table_id=table.id).all()
    assert len(logs) == 2
    assert all("Cloturé" in (log.details or "") for log in logs)


def test_bulk_edit_skips_unchanged_rows_in_log(admin_client, db, admin_user):
    table, cols = make_table(db, admin_user, columns=[("Statut", ColumnType.TEXT)])
    col = cols[0]
    rows = _make_rows(db, table, col, ["Cloturé", "Ouvert"], admin_user)

    admin_client.post(
        f"/tables/{table.id}/rows/bulk-edit",
        data={"row_ids": [r.id for r in rows], "col_id": col.id, "value": "Cloturé"},
    )

    db.expire_all()
    logs = db.query(ActivityLog).filter_by(action="update_row", table_id=table.id).all()
    assert len(logs) == 1


def test_bulk_edit_requires_write_permission(user_client, db, admin_user, regular_user):
    from app.models import PermissionLevel, TablePermission

    table, cols = make_table(db, admin_user, columns=[("Statut", ColumnType.TEXT)])
    col = cols[0]
    rows = _make_rows(db, table, col, ["Ouvert"], admin_user)
    db.add(TablePermission(table_id=table.id, user_id=regular_user.id, level=PermissionLevel.READ))
    db.commit()

    resp = user_client.post(
        f"/tables/{table.id}/rows/bulk-edit",
        data={"row_ids": [rows[0].id], "col_id": col.id, "value": "Cloturé"},
    )

    assert resp.status_code == 403


def test_bulk_edit_rejects_readonly_column(user_client, db, admin_user, regular_user):
    from app.models import PermissionLevel, TablePermission

    table, cols = make_table(db, admin_user, columns=[("Statut", ColumnType.TEXT)])
    col = cols[0]
    rows = _make_rows(db, table, col, ["Ouvert"], admin_user)
    db.add(TablePermission(table_id=table.id, user_id=regular_user.id, level=PermissionLevel.WRITE))
    db.add(ColumnPermission(column_id=col.id, user_id=regular_user.id, readonly=True))
    db.commit()

    resp = user_client.post(
        f"/tables/{table.id}/rows/bulk-edit",
        data={"row_ids": [rows[0].id], "col_id": col.id, "value": "Cloturé"},
    )

    assert resp.status_code == 200  # ré-affiche la modale avec une erreur
    db.expire_all()
    assert db.query(CellValue).filter_by(row_id=rows[0].id, column_id=col.id).first().value == "Ouvert"


def test_bulk_edit_rejects_unique_column_with_multiple_rows(admin_client, db, admin_user):
    table, cols = make_table(db, admin_user, columns=[("Code", ColumnType.TEXT)])
    col = cols[0]
    col.is_unique = True
    db.commit()
    rows = _make_rows(db, table, col, ["A", "B"], admin_user)

    resp = admin_client.post(
        f"/tables/{table.id}/rows/bulk-edit",
        data={"row_ids": [r.id for r in rows], "col_id": col.id, "value": "MEME_CODE"},
    )

    assert resp.status_code == 200
    db.expire_all()
    values = {
        db.query(CellValue).filter_by(row_id=r.id, column_id=col.id).first().value
        for r in rows
    }
    assert values == {"A", "B"}  # rien n'a été modifié


def test_bulk_edit_rejects_more_than_max_rows(admin_client, db, admin_user):
    table, cols = make_table(db, admin_user, columns=[("Statut", ColumnType.TEXT)])
    col = cols[0]
    rows = _make_rows(db, table, col, ["Ouvert"] * (BULK_EDIT_MAX_ROWS + 1), admin_user)

    resp = admin_client.post(
        f"/tables/{table.id}/rows/bulk-edit",
        data={"row_ids": [r.id for r in rows], "col_id": col.id, "value": "Cloturé"},
    )

    assert resp.status_code == 200
    db.expire_all()
    unchanged = db.query(CellValue).filter_by(column_id=col.id, value="Ouvert").count()
    assert unchanged == BULK_EDIT_MAX_ROWS + 1


def test_bulk_edit_ignores_row_ids_from_another_table(admin_client, db, admin_user):
    table_a, cols_a = make_table(db, admin_user, name="A", columns=[("Statut", ColumnType.TEXT)])
    table_b, cols_b = make_table(db, admin_user, name="B", columns=[("Statut", ColumnType.TEXT)])
    row_a = _make_rows(db, table_a, cols_a[0], ["Ouvert"], admin_user)[0]
    row_b = _make_rows(db, table_b, cols_b[0], ["Ouvert"], admin_user)[0]

    resp = admin_client.post(
        f"/tables/{table_a.id}/rows/bulk-edit",
        data={"row_ids": [row_a.id, row_b.id], "col_id": cols_a[0].id, "value": "Cloturé"},
    )

    assert resp.status_code in (200, 303)
    db.expire_all()
    assert db.query(CellValue).filter_by(row_id=row_a.id).first().value == "Cloturé"
    assert db.query(CellValue).filter_by(row_id=row_b.id).first().value == "Ouvert"


def test_bulk_edit_field_widget_reflects_column_type(admin_client, db, admin_user):
    table, cols = make_table(db, admin_user, columns=[("Actif", ColumnType.BOOLEAN)])
    col = cols[0]

    resp = admin_client.get(f"/tables/{table.id}/rows/bulk-edit/field", params={"col_id": col.id})

    assert resp.status_code == 200
    assert 'name="value"' in resp.text
    assert "Oui" in resp.text and "Non" in resp.text


def test_bulk_edit_modal_excludes_relation_columns(admin_client, db, admin_user):
    table, cols = make_table(db, admin_user, columns=[
        ("Statut", ColumnType.TEXT),
        ("Fournisseur", ColumnType.RELATION),
    ])

    resp = admin_client.get(f"/tables/{table.id}/rows/bulk-edit")

    assert resp.status_code == 200
    assert "Statut" in resp.text
    assert "Fournisseur" not in resp.text
