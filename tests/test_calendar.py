"""Tests : vue Calendrier — endpoint /events et détection des colonnes DATE/DATETIME."""
from app.models import CellValue, ColumnType, TableRow
from tests.helpers import make_table


def _make_dated_table(db, owner):
    """Table avec une colonne texte + une colonne DATE, 2 lignes datées + 1 sans date."""
    table, cols = make_table(db, owner, name="DatedTable", columns=[
        ("Nom", ColumnType.TEXT),
        ("Echeance", ColumnType.DATE),
    ])
    col_nom, col_date = cols
    for nom, date_val in [("Alice", "2026-03-10"), ("Bob", "2026-03-15")]:
        row = TableRow(table_id=table.id, created_by_id=owner.id)
        db.add(row)
        db.flush()
        db.add(CellValue(row_id=row.id, column_id=col_nom.id, value=nom))
        db.add(CellValue(row_id=row.id, column_id=col_date.id, value=date_val))
    # Ligne sans date renseignée : ne doit jamais apparaître dans les events
    row_no_date = TableRow(table_id=table.id, created_by_id=owner.id)
    db.add(row_no_date)
    db.flush()
    db.add(CellValue(row_id=row_no_date.id, column_id=col_nom.id, value="Sans date"))
    db.commit()
    return table, cols


def test_events_returns_dated_rows(admin_client, db, admin_user):
    table, cols = _make_dated_table(db, admin_user)
    col_date = cols[1]

    resp = admin_client.get(f"/tables/{table.id}/events", params={"date_col": col_date.id})

    assert resp.status_code == 200
    data = resp.json()
    assert len(data) == 2
    starts = {e["start"] for e in data}
    assert starts == {"2026-03-10", "2026-03-15"}


def test_events_title_uses_other_column(admin_client, db, admin_user):
    table, cols = _make_dated_table(db, admin_user)
    col_date = cols[1]

    resp = admin_client.get(f"/tables/{table.id}/events", params={"date_col": col_date.id})

    titles = {e["title"] for e in resp.json()}
    assert titles == {"Alice", "Bob"}


def test_events_carries_row_id_for_click_through(admin_client, db, admin_user):
    table, cols = _make_dated_table(db, admin_user)
    col_date = cols[1]

    resp = admin_client.get(f"/tables/{table.id}/events", params={"date_col": col_date.id})

    for event in resp.json():
        assert event["row_id"] == event["id"]


def test_events_filter_q(admin_client, db, admin_user):
    table, cols = _make_dated_table(db, admin_user)
    col_date = cols[1]

    resp = admin_client.get(f"/tables/{table.id}/events", params={"date_col": col_date.id, "q": "Alice"})

    data = resp.json()
    assert len(data) == 1
    assert data[0]["title"] == "Alice"


def test_events_filter_column(admin_client, db, admin_user):
    table, cols = _make_dated_table(db, admin_user)
    col_nom, col_date = cols

    resp = admin_client.get(
        f"/tables/{table.id}/events",
        params={"date_col": col_date.id, f"filter_{col_nom.id}": "Bob"},
    )

    data = resp.json()
    assert len(data) == 1
    assert data[0]["title"] == "Bob"


def test_events_invalid_date_col_returns_empty(admin_client, db, admin_user):
    """date_col pointant vers une colonne TEXT (pas DATE/DATETIME) -> liste vide, pas d'erreur 500."""
    table, cols = _make_dated_table(db, admin_user)
    col_nom = cols[0]

    resp = admin_client.get(f"/tables/{table.id}/events", params={"date_col": col_nom.id})

    assert resp.status_code == 200
    assert resp.json() == []


def test_events_unknown_date_col_returns_empty(admin_client, db, admin_user):
    table, _ = _make_dated_table(db, admin_user)

    resp = admin_client.get(f"/tables/{table.id}/events", params={"date_col": 999999})

    assert resp.status_code == 200
    assert resp.json() == []


def test_events_forbidden_without_access(user_client, db, admin_user):
    table, cols = _make_dated_table(db, admin_user)
    col_date = cols[1]

    resp = user_client.get(f"/tables/{table.id}/events", params={"date_col": col_date.id})

    assert resp.status_code == 403


def test_table_detail_exposes_date_cols_for_calendar_toggle(admin_client, db, admin_user):
    table, _ = _make_dated_table(db, admin_user)

    resp = admin_client.get(f"/tables/{table.id}")

    assert resp.status_code == 200
    assert 'id="btn-calendar-view"' in resp.text


def test_table_detail_hides_calendar_toggle_without_date_column(admin_client, db, admin_user):
    table, _ = make_table(db, admin_user, name="NoDate", columns=[("Texte", ColumnType.TEXT)])

    resp = admin_client.get(f"/tables/{table.id}")

    assert 'id="btn-calendar-view"' not in resp.text
