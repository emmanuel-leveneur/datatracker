"""Tests : module traçabilité par table."""
import pytest
from fastapi.testclient import TestClient

from app.models import ActivityLog, ColumnType, TablePermission, PermissionLevel, TableRow
from tests.helpers import make_table


# ── Accès à la page ───────────────────────────────────────────────────────────

def test_tracabilite_requires_auth(client, db, admin_user):
    table, _ = make_table(db, admin_user)
    resp = client.get(f"/tables/{table.id}/tracabilite")
    assert resp.status_code in (303, 307)


def test_tracabilite_accessible_by_owner(admin_client, db, admin_user):
    table, _ = make_table(db, admin_user)
    resp = admin_client.get(f"/tables/{table.id}/tracabilite")
    assert resp.status_code == 200


def test_tracabilite_accessible_with_read_permission(user_client, db, admin_user, regular_user):
    table, _ = make_table(db, admin_user)
    db.add(TablePermission(table_id=table.id, user_id=regular_user.id, level=PermissionLevel.READ))
    db.commit()
    resp = user_client.get(f"/tables/{table.id}/tracabilite")
    assert resp.status_code == 200


def test_tracabilite_accessible_with_write_permission(user_client, db, admin_user, regular_user):
    table, _ = make_table(db, admin_user)
    db.add(TablePermission(table_id=table.id, user_id=regular_user.id, level=PermissionLevel.WRITE))
    db.commit()
    resp = user_client.get(f"/tables/{table.id}/tracabilite")
    assert resp.status_code == 200


def test_tracabilite_forbidden_without_permission(user_client, db, admin_user):
    table, _ = make_table(db, admin_user)
    resp = user_client.get(f"/tables/{table.id}/tracabilite")
    assert resp.status_code == 403


def test_tracabilite_404_on_unknown_table(admin_client):
    resp = admin_client.get("/tables/99999/tracabilite")
    assert resp.status_code == 404


# ── Contenu de la traçabilité ─────────────────────────────────────────────────

def test_tracabilite_shows_table_creation(admin_client, db):
    """La création de la table doit apparaître dans sa propre traçabilité."""
    admin_client.post("/tables/create", data={
        "name": "TraceTest",
        "col_names": ["Col"], "col_types": ["text"],
        "col_required": [], "col_options": [""],
    })
    db.expire_all()
    from app.models import DataTable
    table = db.query(DataTable).filter_by(name="TraceTest").first()

    resp = admin_client.get(f"/tables/{table.id}/tracabilite")

    assert resp.status_code == 200
    assert "Création de table" in resp.text


def test_tracabilite_shows_row_actions(admin_client, db, admin_user):
    table, cols = make_table(db, admin_user, columns=[("Val", ColumnType.TEXT)])

    admin_client.post(f"/tables/{table.id}/rows/new", data={f"col_{cols[0].id}": "x"})

    resp = admin_client.get(f"/tables/{table.id}/tracabilite")
    assert "Ajout de ligne" in resp.text


def test_tracabilite_shows_permission_update(admin_client, db, admin_user, regular_user):
    table, _ = make_table(db, admin_user)

    admin_client.post(
        f"/tables/{table.id}/permissions/bulk",
        data={f"table_perm_{regular_user.id}": "read"},
    )

    resp = admin_client.get(f"/tables/{table.id}/tracabilite")
    assert "Modification des permissions" in resp.text


def test_tracabilite_only_shows_own_table_logs(admin_client, db, admin_user):
    """Les actions d'une autre table ne doivent pas apparaître."""
    table_a, cols_a = make_table(db, admin_user, name="TableA", columns=[("x", ColumnType.TEXT)])
    table_b, cols_b = make_table(db, admin_user, name="TableB", columns=[("y", ColumnType.TEXT)])

    admin_client.post(f"/tables/{table_a.id}/rows/new", data={f"col_{cols_a[0].id}": "ligne A"})
    admin_client.post(f"/tables/{table_b.id}/rows/new", data={f"col_{cols_b[0].id}": "ligne B"})

    db.expire_all()
    logs_a = db.query(ActivityLog).filter_by(table_id=table_a.id).all()
    logs_b = db.query(ActivityLog).filter_by(table_id=table_b.id).all()

    assert all(log.table_id == table_a.id for log in logs_a)
    assert all(log.table_id == table_b.id for log in logs_b)
    # Pas de croisement
    assert not any(log.table_id == table_b.id for log in logs_a)


def test_tracabilite_log_table_id_set_on_row_create(admin_client, db, admin_user):
    table, cols = make_table(db, admin_user, columns=[("Val", ColumnType.TEXT)])

    admin_client.post(f"/tables/{table.id}/rows/new", data={f"col_{cols[0].id}": "test"})

    db.expire_all()
    log = db.query(ActivityLog).filter_by(action="create_row", table_id=table.id).first()
    assert log is not None
    assert log.table_id == table.id


def test_tracabilite_log_table_id_set_on_import_csv(admin_client, db, admin_user):
    import io
    table, _ = make_table(db, admin_user, columns=[("Nom", ColumnType.TEXT)])
    csv_data = "Nom\nAlice\n"

    admin_client.post(
        f"/tables/{table.id}/import",
        files={"file": ("data.csv", io.BytesIO(csv_data.encode()), "text/csv")},
    )

    db.expire_all()
    log = db.query(ActivityLog).filter_by(action="import_csv", table_id=table.id).first()
    assert log is not None


def test_tracabilite_button_visible_on_table_detail(admin_client, db, admin_user):
    table, _ = make_table(db, admin_user)
    resp = admin_client.get(f"/tables/{table.id}")
    assert resp.status_code == 200
    assert "tracabilite" in resp.text


# ── Tri chronologique (data-order) ───────────────────────────────────────────

def test_tracabilite_date_cell_has_data_order(admin_client, db, admin_user):
    """Chaque cellule date doit exposer data-order pour que DataTables trie correctement."""
    table, cols = make_table(db, admin_user, columns=[("Val", ColumnType.TEXT)])
    admin_client.post(f"/tables/{table.id}/rows/new", data={f"col_{cols[0].id}": "x"})

    resp = admin_client.get(f"/tables/{table.id}/tracabilite")

    assert resp.status_code == 200
    assert 'data-order="' in resp.text


def test_tracabilite_data_order_is_sortable_format(admin_client, db, admin_user):
    """data-order doit être au format YYYYMMDDHHMMSS (14 chiffres, triable sans plugin)."""
    import re
    table, cols = make_table(db, admin_user, columns=[("Val", ColumnType.TEXT)])
    admin_client.post(f"/tables/{table.id}/rows/new", data={f"col_{cols[0].id}": "x"})

    resp = admin_client.get(f"/tables/{table.id}/tracabilite")

    match = re.search(r'data-order="(\d+)"', resp.text)
    assert match is not None, "Attribut data-order introuvable dans la traçabilité"
    assert len(match.group(1)) == 14, (
        f"Format attendu YYYYMMDDHHMMSS (14 chiffres), obtenu : {match.group(1)!r}"
    )


def test_tracabilite_data_order_matches_displayed_date(admin_client, db, admin_user):
    """data-order doit correspondre à la date affichée (même instant, formats différents)."""
    import re
    from datetime import datetime
    table, cols = make_table(db, admin_user, columns=[("Val", ColumnType.TEXT)])
    admin_client.post(f"/tables/{table.id}/rows/new", data={f"col_{cols[0].id}": "x"})

    resp = admin_client.get(f"/tables/{table.id}/tracabilite")

    order_match = re.search(r'data-order="(\d{14})"', resp.text)
    date_match = re.search(r'(\d{2}/\d{2}/\d{4} \d{2}:\d{2}:\d{2})', resp.text)
    assert order_match and date_match, "data-order ou date affichée introuvable"

    dt = datetime.strptime(date_match.group(1), "%d/%m/%Y %H:%M:%S")
    assert order_match.group(1) == dt.strftime("%Y%m%d%H%M%S")
