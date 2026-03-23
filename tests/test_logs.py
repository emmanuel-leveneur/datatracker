"""Tests : journal d'activité — accès et traçabilité des actions."""
import io
import pytest
from fastapi.testclient import TestClient

from app.models import ActivityLog, ColumnType, DataTable, TableColumn, TableRow
from tests.helpers import make_table


# ── Accès à la page ───────────────────────────────────────────────────────────

def test_logs_page_requires_admin(user_client):
    resp = user_client.get("/admin/logs")
    assert resp.status_code == 403


def test_logs_page_requires_auth(client):
    resp = client.get("/admin/logs")
    assert resp.status_code in (303, 307)


def test_logs_page_accessible_by_admin(admin_client):
    resp = admin_client.get("/admin/logs")
    assert resp.status_code == 200


def test_logs_page_empty_state(admin_client):
    resp = admin_client.get("/admin/logs")
    assert resp.status_code == 200
    # Aucune entrée → message d'état vide
    assert "0 entrée" in resp.text


# ── Auth ──────────────────────────────────────────────────────────────────────

def test_login_creates_log_entry(client, db, admin_user):
    client.post("/auth/login", data={"username": "admin", "password": "password123"})

    db.expire_all()
    log = db.query(ActivityLog).filter_by(action="login", username="admin").first()
    assert log is not None
    assert log.resource_type == "user"


def test_register_creates_log_entry(client, db):
    client.post("/auth/register", data={
        "username": "newuser", "email": "new@test.com", "password": "password123",
    })

    db.expire_all()
    log = db.query(ActivityLog).filter_by(action="register", username="newuser").first()
    assert log is not None


def test_register_first_user_log_has_admin_detail(client, db):
    client.post("/auth/register", data={
        "username": "premier", "email": "p@test.com", "password": "pass",
    })

    db.expire_all()
    log = db.query(ActivityLog).filter_by(action="register").first()
    assert "Admin" in log.details


# ── Tables ────────────────────────────────────────────────────────────────────

def test_create_table_creates_log(admin_client, db):
    admin_client.post("/tables/create", data={
        "name": "JournalTest",
        "col_names": ["A"], "col_types": ["text"],
        "col_required": [], "col_options": [""],
    })

    db.expire_all()
    log = db.query(ActivityLog).filter_by(action="create_table").first()
    assert log is not None
    assert log.resource_name == "JournalTest"
    assert log.username == "admin"


def test_edit_table_creates_log(admin_client, db, admin_user):
    table, cols = make_table(db, admin_user, columns=[("Col", ColumnType.TEXT)])
    col = cols[0]

    admin_client.post(f"/tables/{table.id}/edit", data={
        "name": "Renommée", "description": "",
        "col_ids": [str(col.id)], "col_names": ["Col"],
        "col_types": ["text"], "col_required": [], "col_options": [""],
    })

    db.expire_all()
    log = db.query(ActivityLog).filter_by(action="edit_table").first()
    assert log is not None
    assert log.resource_name == "Renommée"


def test_delete_table_creates_log(admin_client, db, admin_user):
    table, _ = make_table(db, admin_user, name="ASupprimer")
    table_name = table.name

    admin_client.post(f"/tables/{table.id}/delete")

    db.expire_all()
    log = db.query(ActivityLog).filter_by(action="delete_table").first()
    assert log is not None
    assert log.resource_name == table_name


# ── Lignes ────────────────────────────────────────────────────────────────────

def test_create_row_creates_log(admin_client, db, admin_user):
    table, cols = make_table(db, admin_user, columns=[("Val", ColumnType.TEXT)])

    admin_client.post(f"/tables/{table.id}/rows/new", data={f"col_{cols[0].id}": "x"})

    db.expire_all()
    log = db.query(ActivityLog).filter_by(action="create_row").first()
    assert log is not None
    assert log.resource_name == table.name


def test_delete_row_creates_log(admin_client, db, admin_user):
    table, _ = make_table(db, admin_user)
    row = TableRow(table_id=table.id, created_by_id=admin_user.id)
    db.add(row)
    db.commit()

    admin_client.post(f"/tables/{table.id}/rows/{row.id}/delete")

    db.expire_all()
    log = db.query(ActivityLog).filter_by(action="delete_row").first()
    assert log is not None


def test_import_csv_creates_log(admin_client, db, admin_user):
    table, _ = make_table(db, admin_user, columns=[("Nom", ColumnType.TEXT)])
    csv_data = "Nom\nAlice\nBob\n"

    admin_client.post(
        f"/tables/{table.id}/import",
        files={"file": ("data.csv", io.BytesIO(csv_data.encode()), "text/csv")},
    )

    db.expire_all()
    log = db.query(ActivityLog).filter_by(action="import_csv").first()
    assert log is not None
    assert "2" in log.details


# ── Admin : utilisateurs ──────────────────────────────────────────────────────

def test_toggle_admin_creates_log(admin_client, db, regular_user):
    admin_client.post(f"/admin/users/{regular_user.id}/toggle-admin")

    db.expire_all()
    log = db.query(ActivityLog).filter_by(action="toggle_admin").first()
    assert log is not None
    assert log.resource_name == regular_user.username
    assert "admin" in log.details.lower()


def test_delete_user_creates_log(admin_client, db, regular_user):
    username = regular_user.username

    admin_client.post(f"/admin/users/{regular_user.id}/delete")

    db.expire_all()
    log = db.query(ActivityLog).filter_by(action="delete_user").first()
    assert log is not None
    # username dénormalisé — lisible même après suppression
    assert log.username == "admin"
    assert log.resource_name == username


# ── Admin : permissions ───────────────────────────────────────────────────────

def test_update_permissions_creates_log(admin_client, db, admin_user, regular_user):
    table, _ = make_table(db, admin_user, name="PermLog")

    admin_client.post(
        f"/tables/{table.id}/permissions/bulk",
        data={f"table_perm_{regular_user.id}": "read"},
    )

    db.expire_all()
    log = db.query(ActivityLog).filter_by(action="update_permissions").first()
    assert log is not None
    assert log.resource_name == "PermLog"


def test_update_user_permissions_creates_log(admin_client, db, admin_user, regular_user):
    table, _ = make_table(db, admin_user)

    admin_client.post(
        f"/admin/users/{regular_user.id}/permissions",
        data={f"table_perm_{table.id}": "write"},
    )

    db.expire_all()
    log = db.query(ActivityLog).filter_by(action="update_user_permissions").first()
    assert log is not None
    assert log.resource_name == regular_user.username
