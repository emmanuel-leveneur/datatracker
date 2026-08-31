"""Tests : suppression en masse de plusieurs lignes (bulk-delete)."""
from app.models import ActivityLog, CellValue, ColumnType, PermissionLevel, TablePermission, TableRow
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


def test_bulk_delete_trashes_all_selected_rows(admin_client, db, admin_user):
    table, cols = make_table(db, admin_user, columns=[("Nom", ColumnType.TEXT)])
    col = cols[0]
    rows = _make_rows(db, table, col, ["A", "B", "C"], admin_user)

    resp = admin_client.post(
        f"/tables/{table.id}/rows/bulk-delete",
        data={"row_ids": [r.id for r in rows]},
    )

    assert resp.status_code in (200, 303)
    db.expire_all()
    for r in rows:
        db.refresh(r)
        assert r.deleted_at is not None
    assert db.query(TableRow).filter_by(table_id=table.id, deleted_at=None).count() == 0


def test_bulk_delete_leaves_unselected_rows_untouched(admin_client, db, admin_user):
    table, cols = make_table(db, admin_user, columns=[("Nom", ColumnType.TEXT)])
    col = cols[0]
    rows = _make_rows(db, table, col, ["A", "B", "C"], admin_user)

    admin_client.post(
        f"/tables/{table.id}/rows/bulk-delete",
        data={"row_ids": [rows[0].id]},
    )

    db.expire_all()
    db.refresh(rows[0])
    db.refresh(rows[1])
    db.refresh(rows[2])
    assert rows[0].deleted_at is not None
    assert rows[1].deleted_at is None
    assert rows[2].deleted_at is None


def test_bulk_delete_logs_one_trash_row_entry_per_row(admin_client, db, admin_user):
    table, cols = make_table(db, admin_user, columns=[("Nom", ColumnType.TEXT)])
    col = cols[0]
    rows = _make_rows(db, table, col, ["A", "B"], admin_user)

    admin_client.post(
        f"/tables/{table.id}/rows/bulk-delete",
        data={"row_ids": [r.id for r in rows]},
    )

    db.expire_all()
    logs = db.query(ActivityLog).filter_by(action="trash_row", table_id=table.id).all()
    assert len(logs) == 2


def test_bulk_delete_requires_write_permission(user_client, db, admin_user, regular_user):
    table, cols = make_table(db, admin_user, columns=[("Nom", ColumnType.TEXT)])
    col = cols[0]
    rows = _make_rows(db, table, col, ["A"], admin_user)
    db.add(TablePermission(table_id=table.id, user_id=regular_user.id, level=PermissionLevel.READ))
    db.commit()

    resp = user_client.post(
        f"/tables/{table.id}/rows/bulk-delete",
        data={"row_ids": [rows[0].id]},
    )

    assert resp.status_code == 403
    db.expire_all()
    db.refresh(rows[0])
    assert rows[0].deleted_at is None


def test_bulk_delete_with_write_permission_succeeds(user_client, db, admin_user, regular_user):
    table, cols = make_table(db, admin_user, columns=[("Nom", ColumnType.TEXT)])
    col = cols[0]
    rows = _make_rows(db, table, col, ["A"], admin_user)
    db.add(TablePermission(table_id=table.id, user_id=regular_user.id, level=PermissionLevel.WRITE))
    db.commit()

    resp = user_client.post(
        f"/tables/{table.id}/rows/bulk-delete",
        data={"row_ids": [rows[0].id]},
    )

    assert resp.status_code in (200, 303)
    db.expire_all()
    db.refresh(rows[0])
    assert rows[0].deleted_at is not None


def test_bulk_delete_empty_selection_reports_error(admin_client, db, admin_user):
    table, cols = make_table(db, admin_user, columns=[("Nom", ColumnType.TEXT)])
    col = cols[0]
    rows = _make_rows(db, table, col, ["A"], admin_user)

    resp = admin_client.post(
        f"/tables/{table.id}/rows/bulk-delete",
        data={"row_ids": []},
    )

    assert resp.status_code == 200
    assert "bulkDeleteError" in resp.headers.get("HX-Trigger", "")
    db.expire_all()
    db.refresh(rows[0])
    assert rows[0].deleted_at is None


def test_bulk_delete_rejects_more_than_max_rows(admin_client, db, admin_user):
    table, cols = make_table(db, admin_user, columns=[("Nom", ColumnType.TEXT)])
    col = cols[0]
    rows = _make_rows(db, table, col, ["A"] * (BULK_EDIT_MAX_ROWS + 1), admin_user)

    resp = admin_client.post(
        f"/tables/{table.id}/rows/bulk-delete",
        data={"row_ids": [r.id for r in rows]},
    )

    assert resp.status_code == 200
    assert "bulkDeleteError" in resp.headers.get("HX-Trigger", "")
    db.expire_all()
    assert db.query(TableRow).filter_by(table_id=table.id, deleted_at=None).count() == BULK_EDIT_MAX_ROWS + 1


def test_bulk_delete_ignores_row_ids_from_another_table(admin_client, db, admin_user):
    table_a, cols_a = make_table(db, admin_user, name="A", columns=[("Nom", ColumnType.TEXT)])
    table_b, cols_b = make_table(db, admin_user, name="B", columns=[("Nom", ColumnType.TEXT)])
    row_a = _make_rows(db, table_a, cols_a[0], ["X"], admin_user)[0]
    row_b = _make_rows(db, table_b, cols_b[0], ["Y"], admin_user)[0]

    admin_client.post(
        f"/tables/{table_a.id}/rows/bulk-delete",
        data={"row_ids": [row_a.id, row_b.id]},
    )

    db.expire_all()
    db.refresh(row_a)
    db.refresh(row_b)
    assert row_a.deleted_at is not None
    assert row_b.deleted_at is None


def test_bulk_delete_ignores_already_trashed_rows(admin_client, db, admin_user):
    from datetime import datetime

    table, cols = make_table(db, admin_user, columns=[("Nom", ColumnType.TEXT)])
    rows = _make_rows(db, table, cols[0], ["A", "B"], admin_user)
    rows[0].deleted_at = datetime.utcnow()
    db.commit()

    resp = admin_client.post(
        f"/tables/{table.id}/rows/bulk-delete",
        data={"row_ids": [r.id for r in rows]},
    )

    assert resp.status_code in (200, 303)
    db.expire_all()
    logs = db.query(ActivityLog).filter_by(action="trash_row", table_id=table.id).all()
    assert len(logs) == 1


def test_bulk_delete_rows_can_be_restored(admin_client, db, admin_user):
    table, cols = make_table(db, admin_user, columns=[("Nom", ColumnType.TEXT)])
    rows = _make_rows(db, table, cols[0], ["A"], admin_user)

    admin_client.post(
        f"/tables/{table.id}/rows/bulk-delete",
        data={"row_ids": [rows[0].id]},
    )
    admin_client.post(f"/tables/{table.id}/rows/{rows[0].id}/restore")

    db.expire_all()
    db.refresh(rows[0])
    assert rows[0].deleted_at is None
