"""Tests : module d'administration (gestion des utilisateurs et de leurs permissions)."""
import pytest
from fastapi.testclient import TestClient

from app.models import (
    ColumnPermission, ColumnType, DataTable, PermissionLevel,
    TablePermission, User,
)
from app.auth import hash_password
from tests.helpers import make_table


# ── Page liste des utilisateurs ───────────────────────────────────────────────

def test_users_page_requires_admin(user_client):
    resp = user_client.get("/admin/users")
    assert resp.status_code == 403


def test_users_page_requires_auth(client):
    resp = client.get("/admin/users")
    assert resp.status_code in (303, 307)


def test_users_page_shows_all_users(admin_client, regular_user):
    resp = admin_client.get("/admin/users")
    assert resp.status_code == 200
    assert "alice" in resp.text


# ── Toggle admin ──────────────────────────────────────────────────────────────

def test_toggle_admin_grants_flag(admin_client, db, regular_user):
    resp = admin_client.post(f"/admin/users/{regular_user.id}/toggle-admin")
    assert resp.status_code == 303
    db.expire_all()
    db.refresh(regular_user)
    assert regular_user.is_admin is True


def test_toggle_admin_revokes_flag(admin_client, db, second_user):
    second_user.is_admin = True
    db.commit()

    resp = admin_client.post(f"/admin/users/{second_user.id}/toggle-admin")

    assert resp.status_code == 303
    db.expire_all()
    db.refresh(second_user)
    assert second_user.is_admin is False


def test_toggle_own_admin_returns_400(admin_client, admin_user):
    resp = admin_client.post(f"/admin/users/{admin_user.id}/toggle-admin")
    assert resp.status_code == 400


def test_toggle_admin_nonexistent_user_returns_404(admin_client):
    resp = admin_client.post("/admin/users/99999/toggle-admin")
    assert resp.status_code == 404


# ── Suppression d'utilisateur ─────────────────────────────────────────────────

def test_delete_user(admin_client, db, regular_user):
    user_id = regular_user.id

    resp = admin_client.post(f"/admin/users/{user_id}/delete")

    assert resp.status_code == 303
    db.expire_all()
    assert db.get(User, user_id) is None


def test_delete_own_account_returns_400(admin_client, admin_user):
    resp = admin_client.post(f"/admin/users/{admin_user.id}/delete")
    assert resp.status_code == 400
    # L'admin est toujours en base
    assert admin_user.id is not None


def test_delete_nonexistent_user_returns_404(admin_client):
    resp = admin_client.post("/admin/users/99999/delete")
    assert resp.status_code == 404


# ── Page permissions d'un utilisateur ─────────────────────────────────────────

def test_user_permissions_page_accessible_by_admin(admin_client, regular_user):
    resp = admin_client.get(f"/admin/users/{regular_user.id}/permissions")
    assert resp.status_code == 200


def test_user_permissions_page_requires_admin(user_client, regular_user):
    resp = user_client.get(f"/admin/users/{regular_user.id}/permissions")
    assert resp.status_code == 403


def test_user_permissions_page_404_on_unknown_user(admin_client):
    resp = admin_client.get("/admin/users/99999/permissions")
    assert resp.status_code == 404


def test_user_permissions_page_shows_tables(admin_client, db, admin_user, regular_user):
    make_table(db, admin_user, name="MaTable")

    resp = admin_client.get(f"/admin/users/{regular_user.id}/permissions")

    assert resp.status_code == 200
    assert "MaTable" in resp.text


# ── Sauvegarde des permissions via l'admin ────────────────────────────────────

def test_save_user_permissions_grants_write(admin_client, db, admin_user, regular_user):
    table, _ = make_table(db, admin_user, name="AdminShare")

    resp = admin_client.post(
        f"/admin/users/{regular_user.id}/permissions",
        data={f"table_perm_{table.id}": "write"},
    )

    assert resp.status_code == 303
    db.expire_all()
    perm = db.query(TablePermission).filter_by(table_id=table.id, user_id=regular_user.id).first()
    assert perm is not None
    assert perm.level == PermissionLevel.WRITE


def test_save_user_permissions_revokes_access(admin_client, db, admin_user, regular_user):
    table, _ = make_table(db, admin_user)
    db.add(TablePermission(table_id=table.id, user_id=regular_user.id, level=PermissionLevel.READ))
    db.commit()

    admin_client.post(
        f"/admin/users/{regular_user.id}/permissions",
        data={f"table_perm_{table.id}": "none"},
    )

    db.expire_all()
    assert db.query(TablePermission).filter_by(table_id=table.id, user_id=regular_user.id).first() is None


def test_save_user_permissions_sets_column_hidden(admin_client, db, admin_user, regular_user):
    table, cols = make_table(db, admin_user, columns=[("Col", ColumnType.TEXT)])
    col = cols[0]

    admin_client.post(
        f"/admin/users/{regular_user.id}/permissions",
        data={
            f"table_perm_{table.id}": "read",
            f"col_hidden_{col.id}": "on",
        },
    )

    db.expire_all()
    cp = db.query(ColumnPermission).filter_by(column_id=col.id, user_id=regular_user.id).first()
    assert cp is not None
    assert cp.hidden is True


def test_save_user_permissions_skips_owned_tables(admin_client, db, admin_user, regular_user):
    """Les tables dont l'utilisateur est propriétaire ne reçoivent pas de TablePermission."""
    table, _ = make_table(db, regular_user, name="OwnedByAlice")

    admin_client.post(
        f"/admin/users/{regular_user.id}/permissions",
        data={f"table_perm_{table.id}": "read"},
    )

    db.expire_all()
    # Aucune permission créée — propriétaire = accès complet implicite
    assert db.query(TablePermission).filter_by(table_id=table.id, user_id=regular_user.id).first() is None
