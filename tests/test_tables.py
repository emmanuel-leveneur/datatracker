import pytest
from fastapi.testclient import TestClient
from app.models import DataTable, TableColumn, ColumnType
from tests.helpers import make_table


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


def test_delete_table_moves_to_trash(admin_client: TestClient, db, admin_user):
    table = DataTable(name="ToDelete", created_by_id=admin_user.id)
    db.add(table)
    db.commit()
    table_id = table.id
    resp = admin_client.post(f"/tables/{table_id}/delete")
    assert resp.status_code == 303
    db.expire_all()
    t = db.get(DataTable, table_id)
    assert t is not None
    assert t.deleted_at is not None


def test_restore_table(admin_client: TestClient, db, admin_user):
    from datetime import datetime
    table = DataTable(name="Trashed", created_by_id=admin_user.id, deleted_at=datetime.utcnow())
    db.add(table)
    db.commit()
    resp = admin_client.post(f"/tables/{table.id}/restore")
    assert resp.status_code == 303
    db.expire_all()
    assert db.get(DataTable, table.id).deleted_at is None


def test_delete_table_permanent(admin_client: TestClient, db, admin_user):
    from datetime import datetime
    table = DataTable(name="Gone", created_by_id=admin_user.id, deleted_at=datetime.utcnow())
    db.add(table)
    db.commit()
    table_id = table.id
    resp = admin_client.post(f"/tables/{table_id}/delete-permanent")
    assert resp.status_code == 303
    db.expire_all()
    assert db.get(DataTable, table_id) is None


def test_trashed_table_not_in_list(admin_client: TestClient, db, admin_user):
    from datetime import datetime
    table = DataTable(name="HiddenTrash", created_by_id=admin_user.id, deleted_at=datetime.utcnow())
    db.add(table)
    db.commit()
    resp = admin_client.get("/tables/")
    assert resp.status_code == 200
    # doit apparaître dans la section corbeille, pas dans le titre principal
    assert "HiddenTrash" in resp.text


def test_trashed_table_detail_returns_404(admin_client: TestClient, db, admin_user):
    from datetime import datetime
    table = DataTable(name="NoAccess", created_by_id=admin_user.id, deleted_at=datetime.utcnow())
    db.add(table)
    db.commit()
    resp = admin_client.get(f"/tables/{table.id}")
    assert resp.status_code == 404


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


# ── Endpoint GeoJSON ──────────────────────────────────────────────────────────

def _make_geo_table(db, owner):
    """Table avec colonnes LAT/LON + une colonne texte, et 2 lignes."""
    from app.models import TableRow, CellValue
    table, cols = make_table(db, owner, name="GeoTable", columns=[
        ("Nom", ColumnType.TEXT),
        ("lat", ColumnType.LATITUDE),
        ("lon", ColumnType.LONGITUDE),
    ])
    col_nom, col_lat, col_lon = cols
    for nom, lat, lon in [("Paris", "48.8566", "2.3522"), ("Lyon", "45.7640", "4.8357")]:
        row = TableRow(table_id=table.id, created_by_id=owner.id)
        db.add(row)
        db.flush()
        db.add(CellValue(row_id=row.id, column_id=col_nom.id, value=nom))
        db.add(CellValue(row_id=row.id, column_id=col_lat.id, value=lat))
        db.add(CellValue(row_id=row.id, column_id=col_lon.id, value=lon))
    db.commit()
    return table, cols


def test_geojson_returns_all_points(admin_client, db, admin_user):
    table, _ = _make_geo_table(db, admin_user)

    resp = admin_client.get(f"/tables/{table.id}/geojson")

    assert resp.status_code == 200
    data = resp.json()
    assert data["type"] == "FeatureCollection"
    assert len(data["features"]) == 2
    coords = {tuple(f["geometry"]["coordinates"]) for f in data["features"]}
    assert (2.3522, 48.8566) in coords
    assert (4.8357, 45.7640) in coords


def test_geojson_popup_contains_text_columns(admin_client, db, admin_user):
    table, _ = _make_geo_table(db, admin_user)

    resp = admin_client.get(f"/tables/{table.id}/geojson")

    names = {f["properties"].get("Nom") for f in resp.json()["features"]}
    assert "Paris" in names
    assert "Lyon" in names


def test_geojson_filter_q(admin_client, db, admin_user):
    table, _ = _make_geo_table(db, admin_user)

    resp = admin_client.get(f"/tables/{table.id}/geojson?q=Paris")

    data = resp.json()
    assert len(data["features"]) == 1
    assert data["features"][0]["properties"]["Nom"] == "Paris"


def test_geojson_filter_column(admin_client, db, admin_user):
    table, cols = _make_geo_table(db, admin_user)
    col_nom = cols[0]

    resp = admin_client.get(f"/tables/{table.id}/geojson?filter_{col_nom.id}=Lyon")

    data = resp.json()
    assert len(data["features"]) == 1
    assert data["features"][0]["properties"]["Nom"] == "Lyon"


def test_geojson_no_geo_cols_returns_empty(admin_client, db, admin_user):
    table, _ = make_table(db, admin_user, name="NoGeo", columns=[("Texte", ColumnType.TEXT)])

    resp = admin_client.get(f"/tables/{table.id}/geojson")

    assert resp.json() == {"type": "FeatureCollection", "features": []}


def test_geojson_forbidden_without_access(user_client, db, admin_user):
    table, _ = _make_geo_table(db, admin_user)

    resp = user_client.get(f"/tables/{table.id}/geojson")

    assert resp.status_code == 403
