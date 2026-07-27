"""Tests : structure HTML du tableau (thead statique / tbody+pagination swappés par HTMX).

Ces tests garantissent que le endpoint HTMX /tables/{id}/rows ne renvoie plus jamais
le <thead> (ce qui faisait perdre le focus du champ de recherche à chaque frappe),
et que la pagination continue d'être mise à jour via un swap hors-bande (hx-swap-oob).
"""
from app.models import CellValue, ColumnType, TableRow
from tests.helpers import make_table


def _add_row(db, table, owner, col, value):
    row = TableRow(table_id=table.id, created_by_id=owner.id)
    db.add(row)
    db.flush()
    db.add(CellValue(row_id=row.id, column_id=col.id, value=value))
    db.commit()
    return row


def test_rows_endpoint_response_has_no_thead_or_table_wrapper(admin_client, db, admin_user):
    table, cols = make_table(db, admin_user, columns=[("Nom", ColumnType.TEXT)])
    _add_row(db, table, admin_user, cols[0], "Alice")

    resp = admin_client.get(f"/tables/{table.id}/rows")

    assert resp.status_code == 200
    assert "<thead" not in resp.text
    assert "<table" not in resp.text
    assert 'id="filter-' not in resp.text
    assert "Alice" in resp.text


def test_rows_endpoint_includes_oob_pagination_update(admin_client, db, admin_user):
    table, cols = make_table(db, admin_user, columns=[("Nom", ColumnType.TEXT)])
    _add_row(db, table, admin_user, cols[0], "Alice")

    resp = admin_client.get(f"/tables/{table.id}/rows")

    assert resp.status_code == 200
    assert 'id="table-pagination"' in resp.text
    assert 'hx-swap-oob="true"' in resp.text
    assert "1 ligne(s)" in resp.text


def test_full_page_has_static_thead_wrapping_swappable_tbody(admin_client, db, admin_user):
    table, cols = make_table(db, admin_user, columns=[("Nom", ColumnType.TEXT)])
    _add_row(db, table, admin_user, cols[0], "Alice")

    resp = admin_client.get(f"/tables/{table.id}")

    assert resp.status_code == 200
    assert 'id="main-table"' in resp.text
    assert 'id="filter-' in resp.text
    assert '<tbody id="table-body"' in resp.text
    # La pagination n'est rendue qu'une seule fois sur la page complète (pas d'oob ici)
    assert resp.text.count('id="table-pagination"') == 1
    assert 'hx-swap-oob="true"' not in resp.text


def test_column_filter_narrows_rows_and_updates_pagination_count(admin_client, db, admin_user):
    table, cols = make_table(db, admin_user, columns=[("Nom", ColumnType.TEXT)])
    col = cols[0]
    _add_row(db, table, admin_user, col, "Alice")
    _add_row(db, table, admin_user, col, "Bob")

    resp = admin_client.get(f"/tables/{table.id}/rows", params={f"filter_{col.id}": "Ali"})

    assert resp.status_code == 200
    assert "Alice" in resp.text
    assert "Bob" not in resp.text
    assert "1 ligne(s)" in resp.text
