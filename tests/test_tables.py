import pytest
from fastapi.testclient import TestClient
from app.models import DataTable, TableColumn, ColumnType


def test_list_tables_requires_auth(client: TestClient):
    resp = client.get("/tables/")
    assert resp.status_code in (303, 307)


def test_create_table(admin_client: TestClient, db):
    resp = admin_client.post("/tables/create", data={
        "name": "Inventaire",
        "description": "Stock de produits",
        "col_names": ["Produit", "Quantité"],
        "col_types": ["text", "integer"],
        "col_required": [],
        "col_options": ["", ""],
    })
    assert resp.status_code == 303
    table = db.query(DataTable).filter_by(name="Inventaire").first()
    assert table is not None
    assert len(table.columns) == 2


def test_create_table_with_select_column(admin_client: TestClient, db):
    resp = admin_client.post("/tables/create", data={
        "name": "Statuts",
        "col_names": ["Statut"],
        "col_types": ["select"],
        "col_required": [],
        "col_options": ["actif,inactif,suspendu"],
    })
    assert resp.status_code == 303
    table = db.query(DataTable).filter_by(name="Statuts").first()
    assert table.columns[0].select_options == "actif,inactif,suspendu"


def test_table_detail_visible(admin_client: TestClient, db, admin_user):
    table = DataTable(name="Test", created_by_id=admin_user.id)
    db.add(table)
    db.commit()
    resp = admin_client.get(f"/tables/{table.id}")
    assert resp.status_code == 200
    assert "Test" in resp.text


def test_table_detail_forbidden_for_non_member(user_client: TestClient, db, admin_user):
    table = DataTable(name="Private", created_by_id=admin_user.id)
    db.add(table)
    db.commit()
    resp = user_client.get(f"/tables/{table.id}")
    assert resp.status_code == 403


def test_delete_table(admin_client: TestClient, db, admin_user):
    table = DataTable(name="ToDelete", created_by_id=admin_user.id)
    db.add(table)
    db.commit()
    table_id = table.id
    resp = admin_client.post(f"/tables/{table_id}/delete")
    assert resp.status_code == 303
    db.expire_all()
    assert db.get(DataTable, table_id) is None


def test_edit_table(admin_client: TestClient, db, admin_user):
    table = DataTable(name="Original", created_by_id=admin_user.id)
    col = TableColumn(name="Colonne A", col_type=ColumnType.TEXT, order=0)
    table.columns.append(col)
    db.add(table)
    db.commit()

    resp = admin_client.post(f"/tables/{table.id}/edit", data={
        "name": "Renommée",
        "description": "Nouvelle desc",
        "col_ids": [str(col.id)],
        "col_names": ["Colonne A modifiée"],
        "col_types": ["text"],
        "col_required": [],
        "col_options": [""],
    })
    assert resp.status_code == 303
    db.expire_all()
    db.refresh(table)
    assert table.name == "Renommée"
    assert table.columns[0].name == "Colonne A modifiée"


def test_add_and_read_row(admin_client: TestClient, db, admin_user):
    table = DataTable(name="Data", created_by_id=admin_user.id)
    col = TableColumn(name="Valeur", col_type=ColumnType.TEXT, order=0)
    table.columns.append(col)
    db.add(table)
    db.commit()

    resp = admin_client.post(f"/tables/{table.id}/rows/new", data={
        f"col_{col.id}": "Hello"
    })
    assert resp.status_code in (200, 303)

    resp = admin_client.get(f"/tables/{table.id}")
    assert resp.status_code == 200
    assert "Hello" in resp.text


def test_export_excel(admin_client: TestClient, db, admin_user):
    table = DataTable(name="Export", created_by_id=admin_user.id)
    col = TableColumn(name="Nom", col_type=ColumnType.TEXT, order=0)
    table.columns.append(col)
    db.add(table)
    db.commit()

    resp = admin_client.get(f"/tables/{table.id}/export/excel")
    assert resp.status_code == 200
    assert "spreadsheetml" in resp.headers["content-type"]


def test_permissions_table_access(user_client: TestClient, db, admin_user, regular_user):
    from app.models import TablePermission, PermissionLevel
    table = DataTable(name="Shared", created_by_id=admin_user.id)
    db.add(table)
    db.flush()
    perm = TablePermission(table_id=table.id, user_id=regular_user.id, level=PermissionLevel.READ)
    db.add(perm)
    db.commit()

    resp = user_client.get(f"/tables/{table.id}")
    assert resp.status_code == 200


def test_column_hidden_for_user(user_client: TestClient, db, admin_user, regular_user):
    from app.models import TablePermission, ColumnPermission, PermissionLevel, TableRow, CellValue

    table = DataTable(name="Hidden Col Test", created_by_id=admin_user.id)
    col_visible = TableColumn(name="Public", col_type=ColumnType.TEXT, order=0)
    col_hidden = TableColumn(name="Secret", col_type=ColumnType.TEXT, order=1)
    table.columns = [col_visible, col_hidden]
    db.add(table)
    db.flush()

    # Give read access
    db.add(TablePermission(table_id=table.id, user_id=regular_user.id, level=PermissionLevel.READ))
    # Hide col_hidden for regular_user
    db.add(ColumnPermission(column_id=col_hidden.id, user_id=regular_user.id, hidden=True))

    row = TableRow(table_id=table.id, created_by_id=admin_user.id)
    db.add(row)
    db.flush()
    db.add(CellValue(row_id=row.id, column_id=col_visible.id, value="visible_value"))
    db.add(CellValue(row_id=row.id, column_id=col_hidden.id, value="secret_value"))
    db.commit()

    resp = user_client.get(f"/tables/{table.id}")
    assert resp.status_code == 200
    assert "visible_value" in resp.text
    assert "secret_value" not in resp.text
    assert "Secret" not in resp.text
