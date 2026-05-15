"""Tests : gestion des permissions par table et par colonne."""
import pytest
from fastapi.testclient import TestClient

from app.models import (
    ColumnPermission, ColumnType, DataTable, PermissionLevel,
    TableColumn, TableOwner, TablePermission, TableRow, CellValue,
)
from tests.helpers import make_table


# ── Page de gestion des permissions ──────────────────────────────────────────

def test_permissions_page_accessible_by_owner(admin_client, db, admin_user):
    table, _ = make_table(db, admin_user)

    resp = admin_client.get(f"/tables/{table.id}/permissions")

    assert resp.status_code == 200


def test_permissions_page_forbidden_for_non_owner(user_client, db, admin_user):
    table, _ = make_table(db, admin_user)

    resp = user_client.get(f"/tables/{table.id}/permissions")

    assert resp.status_code == 403


def test_permissions_page_accessible_by_admin_even_if_not_owner(admin_client, db, regular_user):
    table, _ = make_table(db, regular_user, name="OwnedByAlice")

    resp = admin_client.get(f"/tables/{table.id}/permissions")

    assert resp.status_code == 200


# ── Bulk permissions : table ──────────────────────────────────────────────────

def test_bulk_permissions_grant_read(admin_client, db, admin_user, regular_user):
    table, _ = make_table(db, admin_user)

    resp = admin_client.post(
        f"/tables/{table.id}/permissions/bulk",
        data={f"table_perm_{regular_user.id}": "read"},
    )

    assert resp.status_code == 303
    db.expire_all()
    perm = db.query(TablePermission).filter_by(table_id=table.id, user_id=regular_user.id).first()
    assert perm is not None
    assert perm.level == PermissionLevel.READ


def test_bulk_permissions_upgrade_to_write(admin_client, db, admin_user, regular_user):
    table, _ = make_table(db, admin_user)
    db.add(TablePermission(table_id=table.id, user_id=regular_user.id, level=PermissionLevel.READ))
    db.commit()

    admin_client.post(
        f"/tables/{table.id}/permissions/bulk",
        data={f"table_perm_{regular_user.id}": "write"},
    )

    db.expire_all()
    perm = db.query(TablePermission).filter_by(table_id=table.id, user_id=regular_user.id).first()
    assert perm.level == PermissionLevel.WRITE


def test_bulk_permissions_revoke(admin_client, db, admin_user, regular_user):
    table, _ = make_table(db, admin_user)
    db.add(TablePermission(table_id=table.id, user_id=regular_user.id, level=PermissionLevel.READ))
    db.commit()

    admin_client.post(
        f"/tables/{table.id}/permissions/bulk",
        data={f"table_perm_{regular_user.id}": "none"},
    )

    db.expire_all()
    assert db.query(TablePermission).filter_by(table_id=table.id, user_id=regular_user.id).first() is None


# ── Bulk permissions : colonnes ───────────────────────────────────────────────

def test_bulk_permissions_set_column_hidden(admin_client, db, admin_user, regular_user):
    table, cols = make_table(db, admin_user, columns=[("Secret", ColumnType.TEXT)])
    col = cols[0]

    admin_client.post(
        f"/tables/{table.id}/permissions/bulk",
        data={
            f"table_perm_{regular_user.id}": "read",
            f"col_hidden_{col.id}_{regular_user.id}": "on",
        },
    )

    db.expire_all()
    cp = db.query(ColumnPermission).filter_by(column_id=col.id, user_id=regular_user.id).first()
    assert cp is not None
    assert cp.hidden is True


def test_bulk_permissions_set_column_readonly(admin_client, db, admin_user, regular_user):
    table, cols = make_table(db, admin_user, columns=[("Verrouillé", ColumnType.TEXT)])
    col = cols[0]

    admin_client.post(
        f"/tables/{table.id}/permissions/bulk",
        data={
            f"table_perm_{regular_user.id}": "write",
            f"col_readonly_{col.id}_{regular_user.id}": "on",
        },
    )

    db.expire_all()
    cp = db.query(ColumnPermission).filter_by(column_id=col.id, user_id=regular_user.id).first()
    assert cp is not None
    assert cp.readonly is True


def test_bulk_permissions_remove_column_permission(admin_client, db, admin_user, regular_user):
    table, cols = make_table(db, admin_user, columns=[("Col", ColumnType.TEXT)])
    col = cols[0]
    db.add(ColumnPermission(column_id=col.id, user_id=regular_user.id, hidden=True))
    db.commit()

    # Soumettre sans la case cochée → suppression de la ColumnPermission
    admin_client.post(
        f"/tables/{table.id}/permissions/bulk",
        data={f"table_perm_{regular_user.id}": "read"},
    )

    db.expire_all()
    cp = db.query(ColumnPermission).filter_by(column_id=col.id, user_id=regular_user.id).first()
    assert cp is None


# ── Enforcement des permissions en lecture/écriture ───────────────────────────

def test_table_not_visible_without_permission(user_client, db, admin_user):
    table, _ = make_table(db, admin_user, name="Private")

    resp = user_client.get(f"/tables/{table.id}")

    assert resp.status_code == 403


def test_table_visible_with_read_permission(user_client, db, admin_user, regular_user):
    table, _ = make_table(db, admin_user, name="Shared")
    db.add(TablePermission(table_id=table.id, user_id=regular_user.id, level=PermissionLevel.READ))
    db.commit()

    resp = user_client.get(f"/tables/{table.id}")

    assert resp.status_code == 200


def test_hidden_column_not_in_response(user_client, db, admin_user, regular_user):
    table, cols = make_table(
        db, admin_user,
        columns=[("Public", ColumnType.TEXT), ("Secret", ColumnType.TEXT)],
    )
    col_public, col_secret = cols
    db.add(TablePermission(table_id=table.id, user_id=regular_user.id, level=PermissionLevel.READ))
    db.add(ColumnPermission(column_id=col_secret.id, user_id=regular_user.id, hidden=True))
    row = TableRow(table_id=table.id, created_by_id=admin_user.id)
    db.add(row)
    db.flush()
    db.add(CellValue(row_id=row.id, column_id=col_public.id, value="visible"))
    db.add(CellValue(row_id=row.id, column_id=col_secret.id, value="confidentiel"))
    db.commit()

    resp = user_client.get(f"/tables/{table.id}")

    assert resp.status_code == 200
    assert "visible" in resp.text
    assert "confidentiel" not in resp.text
    assert "Secret" not in resp.text


def test_edit_table_forbidden_for_non_owner(user_client, db, admin_user):
    table, _ = make_table(db, admin_user)

    resp = user_client.post(
        f"/tables/{table.id}/edit",
        data={"name": "Hack", "description": "", "col_ids": [], "col_names": [],
              "col_types": [], "col_required": [], "col_options": []},
    )

    assert resp.status_code == 403


def test_delete_table_forbidden_for_non_owner(user_client, db, admin_user):
    table, _ = make_table(db, admin_user)

    resp = user_client.post(f"/tables/{table.id}/delete")

    assert resp.status_code == 403


# ── Co-propriété ──────────────────────────────────────────────────────────────

def test_add_owner(admin_client, db, admin_user, regular_user):
    table, _ = make_table(db, admin_user)

    resp = admin_client.post(
        f"/tables/{table.id}/owners",
        data={"new_owner_id": str(regular_user.id)},
    )

    assert resp.status_code == 303
    db.expire_all()
    owners = db.query(TableOwner).filter_by(table_id=table.id).all()
    assert any(o.user_id == regular_user.id for o in owners)


def test_co_owner_can_access_table(user_client, db, admin_user, regular_user):
    table, _ = make_table(db, admin_user)
    db.add(TableOwner(table_id=table.id, user_id=regular_user.id))
    db.commit()

    resp = user_client.get(f"/tables/{table.id}")

    assert resp.status_code == 200


def test_co_owner_can_edit_table(user_client, db, admin_user, regular_user):
    table, cols = make_table(db, admin_user, columns=[("Col", ColumnType.TEXT)])
    db.add(TableOwner(table_id=table.id, user_id=regular_user.id))
    db.commit()

    resp = user_client.post(
        f"/tables/{table.id}/edit",
        data={
            "name": "Renommée", "description": "",
            "col_ids": [str(cols[0].id)], "col_names": ["Col"],
            "col_types": ["text"], "col_required": [], "col_options": [""],
        },
    )

    assert resp.status_code == 303


def test_co_owner_can_manage_permissions(user_client, db, admin_user, regular_user):
    table, _ = make_table(db, admin_user)
    db.add(TableOwner(table_id=table.id, user_id=regular_user.id))
    db.commit()

    resp = user_client.get(f"/tables/{table.id}/permissions")

    assert resp.status_code == 200


def test_remove_owner(admin_client, db, admin_user, regular_user):
    table, _ = make_table(db, admin_user)
    db.add(TableOwner(table_id=table.id, user_id=regular_user.id))
    db.commit()

    resp = admin_client.post(f"/tables/{table.id}/owners/{regular_user.id}/remove")

    assert resp.status_code == 303
    db.expire_all()
    assert db.query(TableOwner).filter_by(table_id=table.id, user_id=regular_user.id).first() is None


def test_cannot_remove_last_owner(admin_client, db, admin_user):
    table, _ = make_table(db, admin_user)

    resp = admin_client.post(f"/tables/{table.id}/owners/{admin_user.id}/remove")

    assert resp.status_code == 400


def test_add_owner_creates_log(admin_client, db, admin_user, regular_user):
    from app.models import ActivityLog
    table, _ = make_table(db, admin_user)

    admin_client.post(
        f"/tables/{table.id}/owners",
        data={"new_owner_id": str(regular_user.id)},
    )

    db.expire_all()
    log = db.query(ActivityLog).filter_by(action="add_owner").first()
    assert log is not None
    assert "alice" in log.details


def test_remove_owner_creates_log(admin_client, db, admin_user, regular_user):
    from app.models import ActivityLog
    table, _ = make_table(db, admin_user)
    db.add(TableOwner(table_id=table.id, user_id=regular_user.id))
    db.commit()

    admin_client.post(f"/tables/{table.id}/owners/{regular_user.id}/remove")

    db.expire_all()
    log = db.query(ActivityLog).filter_by(action="remove_owner").first()
    assert log is not None


# ── Pagination : soumission partielle du formulaire ───────────────────────────

def test_bulk_permissions_partial_form_preserves_absent_user_table_perm(
    admin_client, db, admin_user, regular_user, second_user
):
    """Soumettre uniquement la page 1 (alice) ne doit pas effacer les droits de bob (page 2)."""
    table, _ = make_table(db, admin_user)
    db.add(TablePermission(table_id=table.id, user_id=regular_user.id, level=PermissionLevel.READ))
    db.add(TablePermission(table_id=table.id, user_id=second_user.id, level=PermissionLevel.WRITE))
    db.commit()

    # Formulaire partiel : seul alice est soumis (bob absent = autre page DataTables)
    admin_client.post(
        f"/tables/{table.id}/permissions/bulk",
        data={f"table_perm_{regular_user.id}": "none"},  # on révoque alice
    )

    db.expire_all()
    # alice révoquée
    assert db.query(TablePermission).filter_by(table_id=table.id, user_id=regular_user.id).first() is None
    # bob inchangé
    perm = db.query(TablePermission).filter_by(table_id=table.id, user_id=second_user.id).first()
    assert perm is not None
    assert perm.level == PermissionLevel.WRITE


def test_bulk_permissions_partial_form_preserves_absent_user_column_perm(
    admin_client, db, admin_user, regular_user, second_user
):
    """Les permissions de colonne d'un utilisateur absent du formulaire ne doivent pas être supprimées."""
    table, cols = make_table(db, admin_user, columns=[("Confidentiel", ColumnType.TEXT)])
    col = cols[0]
    db.add(TablePermission(table_id=table.id, user_id=regular_user.id, level=PermissionLevel.READ))
    db.add(TablePermission(table_id=table.id, user_id=second_user.id, level=PermissionLevel.READ))
    db.add(ColumnPermission(column_id=col.id, user_id=second_user.id, hidden=True))
    db.commit()

    # Formulaire partiel : seul alice est soumis, bob est absent
    admin_client.post(
        f"/tables/{table.id}/permissions/bulk",
        data={f"table_perm_{regular_user.id}": "read"},
    )

    db.expire_all()
    # La ColumnPermission de bob doit être intacte
    cp = db.query(ColumnPermission).filter_by(column_id=col.id, user_id=second_user.id).first()
    assert cp is not None
    assert cp.hidden is True
