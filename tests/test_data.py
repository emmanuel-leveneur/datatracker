"""Tests : CRUD des lignes, import CSV, enforcement des permissions d'écriture."""
import io
import pytest
from fastapi.testclient import TestClient

from app.models import (
    CellValue, ColumnPermission, ColumnType, PermissionLevel,
    TablePermission, TableRow,
)
from tests.helpers import make_table


# ── Création de lignes ────────────────────────────────────────────────────────

def test_create_row_as_owner(admin_client, db, admin_user):
    table, cols = make_table(db, admin_user, columns=[("Nom", ColumnType.TEXT)])
    col = cols[0]

    resp = admin_client.post(f"/tables/{table.id}/rows/new", data={f"col_{col.id}": "Alice"})

    assert resp.status_code in (200, 303)
    db.expire_all()
    row = db.query(TableRow).filter_by(table_id=table.id).first()
    assert row is not None
    cell = db.query(CellValue).filter_by(row_id=row.id, column_id=col.id).first()
    assert cell.value == "Alice"


def test_create_row_requires_write_permission(user_client, db, admin_user, regular_user):
    table, cols = make_table(db, admin_user, columns=[("Nom", ColumnType.TEXT)])
    col = cols[0]
    db.add(TablePermission(table_id=table.id, user_id=regular_user.id, level=PermissionLevel.READ))
    db.commit()

    resp = user_client.post(f"/tables/{table.id}/rows/new", data={f"col_{col.id}": "X"})

    assert resp.status_code == 403


def test_create_row_with_write_permission_succeeds(user_client, db, admin_user, regular_user):
    table, cols = make_table(db, admin_user, columns=[("Nom", ColumnType.TEXT)])
    col = cols[0]
    db.add(TablePermission(table_id=table.id, user_id=regular_user.id, level=PermissionLevel.WRITE))
    db.commit()

    resp = user_client.post(f"/tables/{table.id}/rows/new", data={f"col_{col.id}": "Alice"})

    assert resp.status_code in (200, 303)
    db.expire_all()
    assert db.query(TableRow).filter_by(table_id=table.id).count() == 1


def test_create_row_without_any_permission_is_forbidden(user_client, db, admin_user):
    table, cols = make_table(db, admin_user, columns=[("Nom", ColumnType.TEXT)])

    resp = user_client.post(f"/tables/{table.id}/rows/new", data={f"col_{cols[0].id}": "X"})

    assert resp.status_code == 403


# ── Édition de lignes ─────────────────────────────────────────────────────────

def test_edit_row_updates_cell(admin_client, db, admin_user):
    table, cols = make_table(db, admin_user, columns=[("Nom", ColumnType.TEXT)])
    col = cols[0]
    row = TableRow(table_id=table.id, created_by_id=admin_user.id)
    db.add(row)
    db.flush()
    db.add(CellValue(row_id=row.id, column_id=col.id, value="Avant"))
    db.commit()

    resp = admin_client.post(f"/tables/{table.id}/rows/{row.id}/edit", data={f"col_{col.id}": "Après"})

    assert resp.status_code in (200, 303)
    db.expire_all()
    assert db.query(CellValue).filter_by(row_id=row.id, column_id=col.id).first().value == "Après"


def test_edit_row_success_triggers_modal_close(admin_client, db, admin_user):
    """Le formulaire d'édition vit dans une modale : un succès doit déclencher sa fermeture côté client."""
    table, cols = make_table(db, admin_user, columns=[("Nom", ColumnType.TEXT)])
    col = cols[0]
    row = TableRow(table_id=table.id, created_by_id=admin_user.id)
    db.add(row)
    db.flush()
    db.add(CellValue(row_id=row.id, column_id=col.id, value="Avant"))
    db.commit()

    resp = admin_client.post(
        f"/tables/{table.id}/rows/{row.id}/edit",
        data={f"col_{col.id}": "Après"},
        headers={"HX-Request": "true"},
    )

    assert resp.status_code == 200
    assert resp.headers.get("HX-Trigger") == "closeEditRowModal"


def test_edit_row_unique_violation_retargets_modal_body(admin_client, db, admin_user):
    """Une erreur d'unicité doit ré-afficher le formulaire dans le corps de la modale, pas l'ancienne zone inline."""
    table, cols = make_table(db, admin_user, columns=[("Code", ColumnType.TEXT)])
    col = cols[0]
    col.is_unique = True
    db.commit()
    row1 = TableRow(table_id=table.id, created_by_id=admin_user.id)
    row2 = TableRow(table_id=table.id, created_by_id=admin_user.id)
    db.add_all([row1, row2])
    db.flush()
    db.add(CellValue(row_id=row1.id, column_id=col.id, value="A"))
    db.add(CellValue(row_id=row2.id, column_id=col.id, value="B"))
    db.commit()

    resp = admin_client.post(
        f"/tables/{table.id}/rows/{row2.id}/edit",
        data={f"col_{col.id}": "A"},
        headers={"HX-Request": "true"},
    )

    assert resp.status_code == 200
    assert resp.headers.get("HX-Retarget") == "#edit-row-modal-body"
    db.expire_all()
    assert db.query(CellValue).filter_by(row_id=row2.id, column_id=col.id).first().value == "B"


def test_edit_row_readonly_column_not_overwritten(user_client, db, admin_user, regular_user):
    """Une colonne marquée readonly pour l'utilisateur ne doit pas être modifiée."""
    table, cols = make_table(db, admin_user, columns=[("Verrouillé", ColumnType.TEXT)])
    col = cols[0]
    db.add(TablePermission(table_id=table.id, user_id=regular_user.id, level=PermissionLevel.WRITE))
    db.add(ColumnPermission(column_id=col.id, user_id=regular_user.id, readonly=True))
    row = TableRow(table_id=table.id, created_by_id=admin_user.id)
    db.add(row)
    db.flush()
    db.add(CellValue(row_id=row.id, column_id=col.id, value="valeur_originale"))
    db.commit()

    # L'utilisateur tente d'écraser la valeur
    user_client.post(f"/tables/{table.id}/rows/{row.id}/edit", data={f"col_{col.id}": "tentative"})

    db.expire_all()
    cell = db.query(CellValue).filter_by(row_id=row.id, column_id=col.id).first()
    assert cell.value == "valeur_originale"


def test_edit_row_forbidden_without_write_permission(user_client, db, admin_user, regular_user):
    table, cols = make_table(db, admin_user, columns=[("Nom", ColumnType.TEXT)])
    col = cols[0]
    db.add(TablePermission(table_id=table.id, user_id=regular_user.id, level=PermissionLevel.READ))
    row = TableRow(table_id=table.id, created_by_id=admin_user.id)
    db.add(row)
    db.flush()
    db.add(CellValue(row_id=row.id, column_id=col.id, value="x"))
    db.commit()

    resp = user_client.post(f"/tables/{table.id}/rows/{row.id}/edit", data={f"col_{col.id}": "y"})

    assert resp.status_code == 403


# ── Suppression de lignes ─────────────────────────────────────────────────────

def test_delete_row_moves_to_trash(admin_client, db, admin_user):
    table, _ = make_table(db, admin_user)
    row = TableRow(table_id=table.id, created_by_id=admin_user.id)
    db.add(row)
    db.commit()
    row_id = row.id

    resp = admin_client.post(f"/tables/{table.id}/rows/{row_id}/delete")

    assert resp.status_code in (200, 303)
    db.expire_all()
    r = db.get(TableRow, row_id)
    assert r is not None
    assert r.deleted_at is not None


def test_restore_row(admin_client, db, admin_user):
    from datetime import datetime
    table, _ = make_table(db, admin_user)
    row = TableRow(table_id=table.id, created_by_id=admin_user.id, deleted_at=datetime.utcnow())
    db.add(row)
    db.commit()

    resp = admin_client.post(f"/tables/{table.id}/rows/{row.id}/restore")

    assert resp.status_code == 303
    db.expire_all()
    assert db.get(TableRow, row.id).deleted_at is None


def test_delete_row_permanent(admin_client, db, admin_user):
    from datetime import datetime
    table, _ = make_table(db, admin_user)
    row = TableRow(table_id=table.id, created_by_id=admin_user.id, deleted_at=datetime.utcnow())
    db.add(row)
    db.commit()
    row_id = row.id

    resp = admin_client.post(f"/tables/{table.id}/rows/{row_id}/delete-permanent")

    assert resp.status_code == 303
    db.expire_all()
    assert db.get(TableRow, row_id) is None


def test_delete_row_forbidden_without_write_permission(user_client, db, admin_user, regular_user):
    table, _ = make_table(db, admin_user)
    db.add(TablePermission(table_id=table.id, user_id=regular_user.id, level=PermissionLevel.READ))
    row = TableRow(table_id=table.id, created_by_id=admin_user.id)
    db.add(row)
    db.commit()

    resp = user_client.post(f"/tables/{table.id}/rows/{row.id}/delete")

    assert resp.status_code == 403


def test_delete_nonexistent_row_returns_404(admin_client, db, admin_user):
    table, _ = make_table(db, admin_user)

    resp = admin_client.post(f"/tables/{table.id}/rows/99999/delete")

    assert resp.status_code == 404


# ── Import CSV ────────────────────────────────────────────────────────────────

def test_import_csv_creates_rows(admin_client, db, admin_user):
    table, cols = make_table(
        db, admin_user,
        columns=[("Produit", ColumnType.TEXT), ("Prix", ColumnType.FLOAT)],
    )
    csv_data = "Produit,Prix\nPomme,1.5\nBanane,0.8\n"

    resp = admin_client.post(
        f"/tables/{table.id}/import",
        files={"file": ("data.csv", io.BytesIO(csv_data.encode()), "text/csv")},
    )

    assert resp.status_code == 200
    assert "2" in resp.text
    db.expire_all()
    assert db.query(TableRow).filter_by(table_id=table.id).count() == 2


def test_import_csv_maps_columns_by_name(admin_client, db, admin_user):
    table, cols = make_table(db, admin_user, columns=[("Nom", ColumnType.TEXT)])
    col = cols[0]
    csv_data = "Nom\nAlice\n"

    admin_client.post(
        f"/tables/{table.id}/import",
        files={"file": ("data.csv", io.BytesIO(csv_data.encode()), "text/csv")},
    )

    db.expire_all()
    row = db.query(TableRow).filter_by(table_id=table.id).first()
    cell = db.query(CellValue).filter_by(row_id=row.id, column_id=col.id).first()
    assert cell.value == "Alice"


def test_import_csv_forbidden_without_write_permission(user_client, db, admin_user, regular_user):
    table, _ = make_table(db, admin_user, columns=[("Nom", ColumnType.TEXT)])
    db.add(TablePermission(table_id=table.id, user_id=regular_user.id, level=PermissionLevel.READ))
    db.commit()
    csv_data = "Nom\nX\n"

    resp = user_client.post(
        f"/tables/{table.id}/import",
        files={"file": ("data.csv", io.BytesIO(csv_data.encode()), "text/csv")},
    )

    assert resp.status_code == 403


# ── Import CSV : détection/conversion des dates ─────────────────────────────────

def test_import_csv_converts_fr_date_to_iso(admin_client, db, admin_user):
    table, cols = make_table(db, admin_user, columns=[("Naissance", ColumnType.DATE)])
    col = cols[0]
    csv_data = "Naissance\n18/08/2026\n"

    resp = admin_client.post(
        f"/tables/{table.id}/import",
        files={"file": ("data.csv", io.BytesIO(csv_data.encode()), "text/csv")},
    )

    assert resp.status_code == 200
    db.expire_all()
    row = db.query(TableRow).filter_by(table_id=table.id).first()
    cell = db.query(CellValue).filter_by(row_id=row.id, column_id=col.id).first()
    assert cell.value == "2026-08-18"


def test_import_csv_keeps_iso_date_unchanged(admin_client, db, admin_user):
    table, cols = make_table(db, admin_user, columns=[("Naissance", ColumnType.DATE)])
    col = cols[0]
    csv_data = "Naissance\n2026-08-18\n"

    admin_client.post(
        f"/tables/{table.id}/import",
        files={"file": ("data.csv", io.BytesIO(csv_data.encode()), "text/csv")},
    )

    db.expire_all()
    row = db.query(TableRow).filter_by(table_id=table.id).first()
    cell = db.query(CellValue).filter_by(row_id=row.id, column_id=col.id).first()
    assert cell.value == "2026-08-18"


def test_import_csv_converts_fr_datetime_to_iso(admin_client, db, admin_user):
    table, cols = make_table(db, admin_user, columns=[("Horodatage", ColumnType.DATETIME)])
    col = cols[0]
    csv_data = "Horodatage\n18/08/2026 14:30\n"

    admin_client.post(
        f"/tables/{table.id}/import",
        files={"file": ("data.csv", io.BytesIO(csv_data.encode()), "text/csv")},
    )

    db.expire_all()
    row = db.query(TableRow).filter_by(table_id=table.id).first()
    cell = db.query(CellValue).filter_by(row_id=row.id, column_id=col.id).first()
    assert cell.value == "2026-08-18T14:30"


def test_import_csv_unrecognized_date_format_reports_error_and_rolls_back(admin_client, db, admin_user):
    table, cols = make_table(db, admin_user, columns=[("Naissance", ColumnType.DATE)])
    csv_data = "Naissance\n18 août 2026\n"

    resp = admin_client.post(
        f"/tables/{table.id}/import",
        files={"file": ("data.csv", io.BytesIO(csv_data.encode()), "text/csv")},
    )

    assert resp.status_code == 200
    assert "n&#39;est pas une date reconnue" in resp.text
    db.expire_all()
    assert db.query(TableRow).filter_by(table_id=table.id).count() == 0


def test_import_csv_empty_date_value_is_allowed(admin_client, db, admin_user):
    table, cols = make_table(
        db, admin_user,
        columns=[("Nom", ColumnType.TEXT), ("Naissance", ColumnType.DATE)],
    )
    csv_data = "Nom,Naissance\nAlice,\n"

    resp = admin_client.post(
        f"/tables/{table.id}/import",
        files={"file": ("data.csv", io.BytesIO(csv_data.encode()), "text/csv")},
    )

    assert resp.status_code == 200
    db.expire_all()
    assert db.query(TableRow).filter_by(table_id=table.id).count() == 1


# ── Import CSV : séparateurs et encodage ──────────────────────────────────────

def _import(client, table, payload: bytes):
    return client.post(
        f"/tables/{table.id}/import",
        files={"file": ("data.csv", io.BytesIO(payload), "text/csv")},
    )


def _cell(db, table, col):
    db.expire_all()
    row = db.query(TableRow).filter_by(table_id=table.id).first()
    return db.query(CellValue).filter_by(row_id=row.id, column_id=col.id).first().value


def test_import_csv_semicolon_separator(admin_client, db, admin_user):
    table, cols = make_table(
        db, admin_user,
        columns=[("Produit", ColumnType.TEXT), ("Stock", ColumnType.INTEGER)],
    )

    resp = _import(admin_client, table, b"Produit;Stock\nPomme;12\nBanane;7\n")

    assert resp.status_code == 200
    db.expire_all()
    assert db.query(TableRow).filter_by(table_id=table.id).count() == 2
    assert _cell(db, table, cols[0]) in ("Pomme", "Banane")


def test_import_csv_semicolon_with_comma_decimals(admin_client, db, admin_user):
    """Cas Excel FR : ';' comme séparateur et ',' décimale dans les valeurs."""
    table, cols = make_table(
        db, admin_user,
        columns=[("Produit", ColumnType.TEXT), ("Prix", ColumnType.TEXT)],
    )

    resp = _import(admin_client, table, b"Produit;Prix\nPomme;3,5\n")

    assert resp.status_code == 200
    assert _cell(db, table, cols[0]) == "Pomme"
    assert _cell(db, table, cols[1]) == "3,5"


def test_import_csv_comma_with_quoted_semicolon(admin_client, db, admin_user):
    table, cols = make_table(
        db, admin_user,
        columns=[("Nom", ColumnType.TEXT), ("Note", ColumnType.TEXT)],
    )

    resp = _import(admin_client, table, b'Nom,Note\n"Dupont; Jean",ok\n"Martin; Paul",ko\n')

    assert resp.status_code == 200
    db.expire_all()
    values = {c.value for c in db.query(CellValue).filter_by(column_id=cols[0].id)}
    assert values == {"Dupont; Jean", "Martin; Paul"}


def test_import_csv_unmatched_headers_reports_error(admin_client, db, admin_user):
    table, _ = make_table(db, admin_user, columns=[("Nom", ColumnType.TEXT)])

    resp = _import(admin_client, table, b"Produit|Prix\nPomme|3\n")

    assert resp.status_code == 200
    assert "Aucune colonne du fichier ne correspond" in resp.text
    assert "ligne(s) importée(s)" not in resp.text
    db.expire_all()
    assert db.query(TableRow).filter_by(table_id=table.id).count() == 0


def test_import_csv_extra_fields_do_not_crash(admin_client, db, admin_user):
    table, cols = make_table(
        db, admin_user,
        columns=[("Nom", ColumnType.TEXT), ("Ville", ColumnType.TEXT)],
    )

    resp = _import(admin_client, table, b"Nom,Ville\nAlice,Paris,en trop\nBob,Lyon\n")

    assert resp.status_code == 200
    db.expire_all()
    assert db.query(TableRow).filter_by(table_id=table.id).count() == 2


def test_import_csv_cp1252_encoding(admin_client, db, admin_user):
    table, cols = make_table(db, admin_user, columns=[("Libellé", ColumnType.TEXT)])

    resp = _import(admin_client, table, "Libellé\nCœur à 5 €\n".encode("cp1252"))

    assert resp.status_code == 200
    assert _cell(db, table, cols[0]) == "Cœur à 5 €"


# ── Import CSV : validation et normalisation par type ─────────────────────────

def _import_one(client, db, admin_user, col_type, raw, **col_attrs):
    """Importe une seule cellule dans une table à une colonne « Val »."""
    table, cols = make_table(db, admin_user, columns=[("Val", col_type)])
    for k, v in col_attrs.items():
        setattr(cols[0], k, v)
    db.commit()
    resp = _import(client, table, f"Val\n{raw}\n".encode())
    db.expire_all()
    row = db.query(TableRow).filter_by(table_id=table.id).first()
    stored = None
    if row:
        stored = db.query(CellValue).filter_by(row_id=row.id, column_id=cols[0].id).first().value
    return resp, stored


@pytest.mark.parametrize("col_type, raw, expected", [
    (ColumnType.INTEGER, "42", "42"),
    (ColumnType.INTEGER, "-7", "-7"),
    (ColumnType.INTEGER, "1 200", "1200"),
    (ColumnType.INTEGER, "12,0", "12"),
    (ColumnType.FLOAT, "3,5", "3.5"),
    (ColumnType.FLOAT, "1 234,56", "1234.56"),
    (ColumnType.FLOAT, "1.234,56", "1234.56"),
    (ColumnType.FLOAT, "1,234.56", "1234.56"),
    (ColumnType.FLOAT, "-0.25", "-0.25"),
    (ColumnType.LATITUDE, "48,8566", "48.8566"),
    (ColumnType.LONGITUDE, "-2,35", "-2.35"),
    (ColumnType.BOOLEAN, "Oui", "true"),
    (ColumnType.BOOLEAN, "non", "false"),
    (ColumnType.BOOLEAN, "VRAI", "true"),
    (ColumnType.BOOLEAN, "0", "false"),
    (ColumnType.EMAIL, " a.b@exemple.fr ", "a.b@exemple.fr"),
])
def test_import_csv_normalizes_typed_values(admin_client, db, admin_user, col_type, raw, expected):
    resp, stored = _import_one(admin_client, db, admin_user, col_type, raw)
    assert resp.status_code == 200
    assert stored == expected


@pytest.mark.parametrize("col_type, raw, message", [
    (ColumnType.INTEGER, "3,5", "n&#39;est pas un nombre entier"),
    (ColumnType.INTEGER, "abc", "n&#39;est pas un nombre entier"),
    (ColumnType.FLOAT, "douze", "n&#39;est pas un nombre"),
    (ColumnType.FLOAT, "nan", "n&#39;est pas un nombre"),
    (ColumnType.LATITUDE, "95", "doit être compris entre -90 et 90"),
    (ColumnType.LONGITUDE, "-181", "doit être compris entre -180 et 180"),
    (ColumnType.BOOLEAN, "peut-être", "n&#39;est pas un booléen"),
    (ColumnType.EMAIL, "pas-un-email", "n&#39;est pas une adresse email valide"),
])
def test_import_csv_rejects_invalid_typed_values(admin_client, db, admin_user, col_type, raw, message):
    resp, stored = _import_one(admin_client, db, admin_user, col_type, raw)
    assert resp.status_code == 200
    assert message in resp.text
    assert "Ligne 2 — Val" in resp.text
    assert stored is None  # rollback : aucune ligne créée


def test_import_csv_empty_typed_values_are_allowed(admin_client, db, admin_user):
    table, cols = make_table(
        db, admin_user,
        columns=[("Nom", ColumnType.TEXT), ("N", ColumnType.INTEGER),
                 ("B", ColumnType.BOOLEAN), ("E", ColumnType.EMAIL)],
    )
    resp = _import(admin_client, table, b"Nom,N,B,E\nAlice,,,\n")
    assert resp.status_code == 200
    db.expire_all()
    assert db.query(TableRow).filter_by(table_id=table.id).count() == 1


def test_import_csv_select_matches_option_case_insensitively(admin_client, db, admin_user):
    resp, stored = _import_one(
        admin_client, db, admin_user, ColumnType.SELECT, "en cours",
        select_options="À faire, En cours, Terminé",
    )
    assert resp.status_code == 200
    assert stored == "En cours"


def test_import_csv_select_rejects_unknown_option(admin_client, db, admin_user):
    resp, stored = _import_one(
        admin_client, db, admin_user, ColumnType.SELECT, "Annulé",
        select_options="À faire, En cours, Terminé",
    )
    assert "ne fait pas partie des choix (À faire, En cours, Terminé)" in resp.text
    assert stored is None


def test_import_csv_select_without_options_accepts_free_text(admin_client, db, admin_user):
    resp, stored = _import_one(admin_client, db, admin_user, ColumnType.SELECT, "Libre")
    assert stored == "Libre"


def test_import_csv_text_is_not_altered(admin_client, db, admin_user):
    resp, stored = _import_one(admin_client, db, admin_user, ColumnType.TEXT, "007")
    assert stored == "007"


def test_import_csv_unique_check_uses_normalized_value(admin_client, db, admin_user):
    table, cols = make_table(db, admin_user, columns=[("Code", ColumnType.INTEGER)])
    cols[0].is_unique = True
    db.commit()
    resp = _import(admin_client, table, b"Code\n1200\n1 200\n")
    assert "est en doublon dans le fichier" in resp.text


# ── Import CSV : colonnes relation ────────────────────────────────────────────

def _make_relation(db, admin_user, value_col=False):
    """Table « Clients » (Nom, Code) avec 3 lignes + table « Commandes » liée."""
    clients, (c_nom, c_code) = make_table(
        db, admin_user, name="Clients",
        columns=[("Nom", ColumnType.TEXT), ("Code", ColumnType.TEXT)],
    )
    ids = {}
    for nom, code in [("Dupont", "C1"), ("Martin", "C2"), ("Martin", "C3")]:
        row = TableRow(table_id=clients.id, created_by_id=admin_user.id)
        db.add(row)
        db.flush()
        db.add(CellValue(row_id=row.id, column_id=c_nom.id, value=nom))
        db.add(CellValue(row_id=row.id, column_id=c_code.id, value=code))
        ids[code] = row.id
    cmd, (rel,) = make_table(db, admin_user, name="Commandes", columns=[("Client", ColumnType.RELATION)])
    rel.related_table_id = clients.id
    rel.related_display_col_id = c_nom.id
    if value_col:
        rel.related_value_col_id = c_code.id
    db.commit()
    return cmd, rel, ids


def test_import_csv_relation_by_label(admin_client, db, admin_user):
    cmd, rel, ids = _make_relation(db, admin_user)
    resp = _import(admin_client, cmd, b"Client\ndupont\n")
    assert resp.status_code == 200
    assert _cell(db, cmd, rel) == str(ids["C1"])


def test_import_csv_relation_by_stored_value(admin_client, db, admin_user):
    cmd, rel, ids = _make_relation(db, admin_user, value_col=True)
    resp = _import(admin_client, cmd, b"Client\nC3\n")
    assert resp.status_code == 200
    assert _cell(db, cmd, rel) == "C3"


def test_import_csv_relation_ambiguous_label(admin_client, db, admin_user):
    cmd, rel, ids = _make_relation(db, admin_user)
    resp = _import(admin_client, cmd, b"Client\nMartin\n")
    assert "correspond à plusieurs lignes de la table liée" in resp.text
    db.expire_all()
    assert db.query(TableRow).filter_by(table_id=cmd.id).count() == 0


def test_import_csv_relation_unknown(admin_client, db, admin_user):
    cmd, rel, ids = _make_relation(db, admin_user)
    resp = _import(admin_client, cmd, b"Client\nDurand\n")
    assert "n&#39;existe pas dans la table liée" in resp.text


# ── Import CSV : mode « Mettre à jour et ajouter » ────────────────────────────

def _make_upsert_table(db, admin_user):
    """Table Ref (unique) / Nom / Stock avec deux lignes existantes."""
    table, cols = make_table(
        db, admin_user,
        columns=[("Ref", ColumnType.TEXT), ("Nom", ColumnType.TEXT), ("Stock", ColumnType.INTEGER)],
    )
    cols[0].is_unique = True
    rows = {}
    for ref, nom, stock in [("A1", "Pomme", "10"), ("B2", "Poire", "5")]:
        row = TableRow(table_id=table.id, created_by_id=admin_user.id)
        db.add(row)
        db.flush()
        for col, v in zip(cols, (ref, nom, stock)):
            db.add(CellValue(row_id=row.id, column_id=col.id, value=v))
        rows[ref] = row.id
    db.commit()
    return table, cols, rows


def _upsert(client, table, key_col, payload: bytes):
    return client.post(
        f"/tables/{table.id}/import",
        data={"mode": "upsert", "key_col_id": str(key_col.id)},
        files={"file": ("data.csv", io.BytesIO(payload), "text/csv")},
    )


def _values(db, row_id, cols):
    db.expire_all()
    cells = {cv.column_id: cv.value for cv in db.query(CellValue).filter_by(row_id=row_id)}
    return [cells.get(c.id, "") for c in cols]


def _active_rows(db, table):
    db.expire_all()
    return db.query(TableRow).filter_by(table_id=table.id, deleted_at=None).count()


def test_upsert_updates_existing_and_adds_new(admin_client, db, admin_user):
    table, cols, rows = _make_upsert_table(db, admin_user)

    resp = _upsert(admin_client, table, cols[0], b"Ref;Nom;Stock\nA1;Pomme verte;12\nC3;Kiwi;7\n")

    assert resp.status_code == 200
    assert "1 ligne(s) ajoutée(s), 1 mise(s) à jour, 0 inchangée(s)" in resp.text
    assert _values(db, rows["A1"], cols) == ["A1", "Pomme verte", "12"]
    assert _values(db, rows["B2"], cols) == ["B2", "Poire", "5"]
    assert _active_rows(db, table) == 3


def test_upsert_empty_cell_keeps_existing_value(admin_client, db, admin_user):
    table, cols, rows = _make_upsert_table(db, admin_user)

    _upsert(admin_client, table, cols[0], b"Ref;Nom;Stock\nA1;;99\n")

    assert _values(db, rows["A1"], cols) == ["A1", "Pomme", "99"]


def test_upsert_columns_absent_from_file_are_untouched(admin_client, db, admin_user):
    table, cols, rows = _make_upsert_table(db, admin_user)

    _upsert(admin_client, table, cols[0], b"Ref;Stock\nA1;0\n")

    assert _values(db, rows["A1"], cols) == ["A1", "Pomme", "0"]


def test_upsert_key_matches_case_insensitively(admin_client, db, admin_user):
    table, cols, rows = _make_upsert_table(db, admin_user)

    resp = _upsert(admin_client, table, cols[0], b"Ref;Stock\na1;3\n")

    assert "0 ligne(s) ajoutée(s), 1 mise(s) à jour" in resp.text
    assert _values(db, rows["A1"], cols)[2] == "3"
    assert _active_rows(db, table) == 2


def test_upsert_key_matches_after_type_normalization(admin_client, db, admin_user):
    table, cols = make_table(
        db, admin_user, columns=[("Code", ColumnType.INTEGER), ("Nom", ColumnType.TEXT)],
    )
    cols[0].is_unique = True
    row = TableRow(table_id=table.id, created_by_id=admin_user.id)
    db.add(row)
    db.flush()
    db.add(CellValue(row_id=row.id, column_id=cols[0].id, value="1200"))
    db.commit()

    resp = _upsert(admin_client, table, cols[0], b"Code;Nom\n1 200;Lot\n")

    assert "1 mise(s) à jour" in resp.text
    assert _values(db, row.id, cols) == ["1200", "Lot"]


def test_upsert_identical_row_counts_as_unchanged_without_log(admin_client, db, admin_user):
    from app.models import ActivityLog
    table, cols, rows = _make_upsert_table(db, admin_user)

    resp = _upsert(admin_client, table, cols[0], b"Ref;Nom;Stock\nA1;Pomme;10\n")

    assert "0 ligne(s) ajoutée(s), 0 mise(s) à jour, 1 inchangée(s)" in resp.text
    db.expire_all()
    assert db.query(ActivityLog).filter_by(action="update_row", resource_id=rows["A1"]).count() == 0


def test_upsert_logs_diff_for_updated_row(admin_client, db, admin_user):
    from app.models import ActivityLog
    table, cols, rows = _make_upsert_table(db, admin_user)

    _upsert(admin_client, table, cols[0], b"Ref;Nom;Stock\nA1;Pomme;11\n")

    db.expire_all()
    log = db.query(ActivityLog).filter_by(action="update_row", resource_id=rows["A1"]).one()
    assert log.table_id == table.id
    assert '"Stock" : "10" → "11"' in log.details
    assert "Nom" not in log.details
    summary = db.query(ActivityLog).filter_by(action="import_csv", table_id=table.id).one()
    assert "1 mise(s) à jour" in summary.details


def test_upsert_empty_key_reports_error_and_rolls_back(admin_client, db, admin_user):
    table, cols, rows = _make_upsert_table(db, admin_user)

    resp = _upsert(admin_client, table, cols[0], b"Ref;Stock\nA1;1\n;2\n")

    assert "Ligne 3 — Ref : la clé est vide." in resp.text
    assert _values(db, rows["A1"], cols)[2] == "10"  # rollback de la ligne 2


def test_upsert_duplicate_key_in_file(admin_client, db, admin_user):
    table, cols, rows = _make_upsert_table(db, admin_user)

    resp = _upsert(admin_client, table, cols[0], b"Ref;Stock\nA1;1\na1;2\n")

    assert "est en doublon dans le fichier" in resp.text
    assert _values(db, rows["A1"], cols)[2] == "10"


def test_upsert_unique_conflict_with_another_row(admin_client, db, admin_user):
    table, cols, rows = _make_upsert_table(db, admin_user)
    cols[1].is_unique = True  # Nom unique
    db.commit()

    resp = _upsert(admin_client, table, cols[0], b"Ref;Nom\nA1;Poire\n")

    assert "« Poire » existe déjà en base" in resp.text
    assert _values(db, rows["A1"], cols)[1] == "Pomme"


def test_upsert_own_unique_value_is_not_a_conflict(admin_client, db, admin_user):
    table, cols, rows = _make_upsert_table(db, admin_user)
    cols[1].is_unique = True
    db.commit()

    resp = _upsert(admin_client, table, cols[0], b"Ref;Nom;Stock\nA1;Pomme;1\n")

    assert "1 mise(s) à jour" in resp.text


def test_upsert_ignores_trashed_rows(admin_client, db, admin_user):
    from datetime import datetime
    table, cols, rows = _make_upsert_table(db, admin_user)
    db.get(TableRow, rows["B2"]).deleted_at = datetime.now()
    db.commit()

    resp = _upsert(admin_client, table, cols[0], b"Ref;Stock\nB2;8\n")

    assert "1 ligne(s) ajoutée(s), 0 mise(s) à jour" in resp.text
    assert _values(db, rows["B2"], cols)[2] == "5"


def test_upsert_requires_key_column_in_file(admin_client, db, admin_user):
    table, cols, rows = _make_upsert_table(db, admin_user)

    resp = _upsert(admin_client, table, cols[0], b"Nom;Stock\nPomme;1\n")

    assert "La colonne clé « Ref » est absente du fichier." in resp.text
    assert _active_rows(db, table) == 2


def test_upsert_rejects_non_unique_key_column(admin_client, db, admin_user):
    table, cols, rows = _make_upsert_table(db, admin_user)

    resp = _upsert(admin_client, table, cols[1], b"Ref;Nom\nA1;X\n")

    assert "Choisissez une colonne clé" in resp.text
    assert _values(db, rows["A1"], cols)[1] == "Pomme"


def test_add_mode_still_rejects_existing_unique_value(admin_client, db, admin_user):
    table, cols, rows = _make_upsert_table(db, admin_user)

    resp = _import(admin_client, table, b"Ref;Nom\nA1;X\n")

    assert "existe déjà en base" in resp.text
    assert _active_rows(db, table) == 2


def test_import_page_offers_upsert_only_with_unique_column(admin_client, db, admin_user):
    plain, _ = make_table(db, admin_user, name="Plain", columns=[("Nom", ColumnType.TEXT)])
    keyed, cols, _ = _make_upsert_table(db, admin_user)

    resp_plain = admin_client.get(f"/tables/{plain.id}/import")
    resp_keyed = admin_client.get(f"/tables/{keyed.id}/import")

    assert "Nécessite une colonne marquée « unique »" in resp_plain.text
    assert 'name="key_col_id"' not in resp_plain.text
    assert f'<option value="{cols[0].id}"' in resp_keyed.text


def test_readonly_unique_column_is_not_offered_as_key(user_client, db, admin_user, regular_user):
    table, cols, rows = _make_upsert_table(db, admin_user)
    db.add(TablePermission(table_id=table.id, user_id=regular_user.id, level=PermissionLevel.WRITE))
    db.add(ColumnPermission(column_id=cols[0].id, user_id=regular_user.id, readonly=True))
    db.commit()

    page = user_client.get(f"/tables/{table.id}/import")
    resp = _upsert(user_client, table, cols[0], b"Ref;Stock\nA1;1\n")

    assert 'name="key_col_id"' not in page.text
    assert "Choisissez une colonne clé" in resp.text
