"""Tests : tri serveur par colonne (porte sur l'ensemble des lignes, pas uniquement la page).

Cas central : les colonnes DATE sont stockées en ISO mais affichées en DD/MM/YYYY ;
le tri doit rester chronologique (sur la valeur stockée), pas alphabétique sur l'affichage.
"""
from app.models import CellValue, ColumnType, TableRow
from tests.helpers import make_table


def _add_row(db, table, owner, col, value):
    row = TableRow(table_id=table.id, created_by_id=owner.id)
    db.add(row)
    db.flush()
    if value is not None:
        db.add(CellValue(row_id=row.id, column_id=col.id, value=value))
    db.commit()
    return row


def test_sort_text_column_asc_desc(admin_client, db, admin_user):
    table, cols = make_table(db, admin_user, columns=[("Nom", ColumnType.TEXT)])
    col = cols[0]
    _add_row(db, table, admin_user, col, "Bob")
    _add_row(db, table, admin_user, col, "Alice")

    resp = admin_client.get(f"/tables/{table.id}/rows", params={"sort_col": col.id, "sort_dir": "asc"})
    assert resp.status_code == 200
    assert resp.text.index("Alice") < resp.text.index("Bob")

    resp = admin_client.get(f"/tables/{table.id}/rows", params={"sort_col": col.id, "sort_dir": "desc"})
    assert resp.status_code == 200
    assert resp.text.index("Bob") < resp.text.index("Alice")


def test_sort_date_column_is_chronological_not_alphabetical(admin_client, db, admin_user):
    table, cols = make_table(db, admin_user, columns=[("Echeance", ColumnType.DATE)])
    col = cols[0]
    # Affichés respectivement 05/01/2026, 20/12/2025, 15/01/2026 : un tri texte sur
    # l'affichage DD/MM/YYYY donnerait 05/01 < 15/01 < 20/12, ce qui est faux chronologiquement.
    _add_row(db, table, admin_user, col, "2026-01-05")
    _add_row(db, table, admin_user, col, "2025-12-20")
    _add_row(db, table, admin_user, col, "2026-01-15")

    resp = admin_client.get(f"/tables/{table.id}/rows", params={"sort_col": col.id, "sort_dir": "asc"})
    assert resp.status_code == 200
    text = resp.text
    assert text.index("20/12/2025") < text.index("05/01/2026") < text.index("15/01/2026")


def test_sort_integer_column_is_numeric_not_alphabetical(admin_client, db, admin_user):
    table, cols = make_table(db, admin_user, columns=[("Qte", ColumnType.INTEGER)])
    col = cols[0]
    # Tri alphabétique donnerait "10" < "2" < "9" ; tri numérique doit donner 2 < 9 < 10.
    _add_row(db, table, admin_user, col, "9")
    _add_row(db, table, admin_user, col, "10")
    _add_row(db, table, admin_user, col, "2")

    resp = admin_client.get(f"/tables/{table.id}/rows", params={"sort_col": col.id, "sort_dir": "asc"})
    assert resp.status_code == 200
    text = resp.text
    assert text.index('title="2"') < text.index('title="9"') < text.index('title="10"')


def test_sort_combines_with_column_filter(admin_client, db, admin_user):
    table, cols = make_table(db, admin_user, columns=[("Nom", ColumnType.TEXT), ("Ville", ColumnType.TEXT)])
    nom, ville = cols
    r1 = _add_row(db, table, admin_user, nom, "Bob")
    db.add(CellValue(row_id=r1.id, column_id=ville.id, value="Paris"))
    r2 = _add_row(db, table, admin_user, nom, "Alice")
    db.add(CellValue(row_id=r2.id, column_id=ville.id, value="Paris"))
    r3 = _add_row(db, table, admin_user, nom, "Zoe")
    db.add(CellValue(row_id=r3.id, column_id=ville.id, value="Lyon"))
    db.commit()

    resp = admin_client.get(
        f"/tables/{table.id}/rows",
        params={"sort_col": nom.id, "sort_dir": "asc", f"filter_{ville.id}": "Paris"},
    )
    assert resp.status_code == 200
    text = resp.text
    assert "Zoe" not in text
    assert text.index("Alice") < text.index("Bob")


def test_sort_col_from_other_table_is_ignored(admin_client, db, admin_user):
    table_a, cols_a = make_table(db, admin_user, name="A", columns=[("Nom", ColumnType.TEXT)])
    table_b, cols_b = make_table(db, admin_user, name="B", columns=[("Autre", ColumnType.TEXT)])
    _add_row(db, table_a, admin_user, cols_a[0], "Bob")
    _add_row(db, table_a, admin_user, cols_a[0], "Alice")

    resp = admin_client.get(f"/tables/{table_a.id}/rows", params={"sort_col": cols_b[0].id, "sort_dir": "asc"})
    assert resp.status_code == 200
    assert "Bob" in resp.text and "Alice" in resp.text


def test_sort_on_relation_column_ignored_server_side(admin_client, db, admin_user):
    table, cols = make_table(db, admin_user, columns=[("Nom", ColumnType.TEXT)])
    col = cols[0]
    from app.models import TableColumn
    rel = TableColumn(table_id=table.id, name="Lien", col_type=ColumnType.RELATION, order=1)
    db.add(rel)
    db.commit()
    _add_row(db, table, admin_user, col, "Bob")

    resp = admin_client.get(f"/tables/{table.id}/rows", params={"sort_col": rel.id, "sort_dir": "asc"})
    assert resp.status_code == 200
    assert "Bob" in resp.text


def test_table_detail_accepts_sort_params(admin_client, db, admin_user):
    table, cols = make_table(db, admin_user, columns=[("Echeance", ColumnType.DATE)])
    col = cols[0]
    _add_row(db, table, admin_user, col, "2026-01-05")
    _add_row(db, table, admin_user, col, "2025-12-20")

    resp = admin_client.get(f"/tables/{table.id}", params={"sort_col": col.id, "sort_dir": "asc"})
    assert resp.status_code == 200
    text = resp.text
    assert text.index("20/12/2025") < text.index("05/01/2026")
