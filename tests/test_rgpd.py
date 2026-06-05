"""Tests pour le rapport RGPD et les métadonnées RGPD des tables."""
import pytest
from app.models import ColumnType, TablePermission, PermissionLevel
from tests.helpers import make_table
from tests.conftest import _authenticated_client


# ── helpers ──────────────────────────────────────────────────────────────────

def _make_rgpd_table(db, owner):
    table, cols = make_table(db, owner, "Clients", columns=[
        ("Nom", ColumnType.TEXT),
        ("Email", ColumnType.EMAIL),
        ("Montant", ColumnType.FLOAT),
    ])
    table.rgpd_finalite = "Gestion de la clientèle"
    table.rgpd_base_legale = "contract"
    table.rgpd_duree_conservation = "5 ans"
    table.rgpd_responsable = "Service commercial"
    db.commit()
    db.refresh(table)
    return table, cols


# ── tests rapport ─────────────────────────────────────────────────────────────

def test_rgpd_report_accessible_by_owner(admin_client, db, admin_user):
    table, _ = _make_rgpd_table(db, admin_user)
    resp = admin_client.get(f"/tables/{table.id}/export/rgpd")
    assert resp.status_code == 200
    assert "Rapport RGPD" in resp.text
    assert "Clients" in resp.text


def test_rgpd_report_contains_fiche_traitement(admin_client, db, admin_user):
    table, _ = _make_rgpd_table(db, admin_user)
    resp = admin_client.get(f"/tables/{table.id}/export/rgpd")
    assert resp.status_code == 200
    assert "Gestion de la clientèle" in resp.text
    assert "nécessaire pour un contrat" in resp.text
    assert "5 ans" in resp.text
    assert "Service commercial" in resp.text


def test_rgpd_report_detects_pii_columns(admin_client, db, admin_user):
    table, _ = _make_rgpd_table(db, admin_user)
    resp = admin_client.get(f"/tables/{table.id}/export/rgpd")
    assert resp.status_code == 200
    # "Nom" and "Email" are PII, "Montant" is not
    # The template shows a badge count for PII columns
    assert "2 données personnelles" in resp.text


def test_rgpd_report_forbidden_for_non_owner(client, db, admin_user, regular_user):
    table, _ = _make_rgpd_table(db, admin_user)
    other_client = _authenticated_client(client, regular_user.id)
    resp = other_client.get(f"/tables/{table.id}/export/rgpd")
    assert resp.status_code == 403


def test_rgpd_report_accessible_by_admin_for_any_table(client, db, admin_user, regular_user):
    # regular_user owns the table, admin should still access the report
    table, _ = make_table(db, regular_user, "Private")
    admin_client = _authenticated_client(client, admin_user.id)
    resp = admin_client.get(f"/tables/{table.id}/export/rgpd")
    assert resp.status_code == 200


def test_rgpd_report_shows_access_matrix(admin_client, db, admin_user, regular_user):
    table, _ = _make_rgpd_table(db, admin_user)
    perm = TablePermission(table_id=table.id, user_id=regular_user.id, level=PermissionLevel.READ)
    db.add(perm)
    db.commit()

    resp = admin_client.get(f"/tables/{table.id}/export/rgpd")
    assert resp.status_code == 200
    assert "alice" in resp.text
    assert "Lecture" in resp.text


# ── tests edit RGPD fields ────────────────────────────────────────────────────

def test_edit_saves_rgpd_fields(admin_client, db, admin_user):
    table, cols = make_table(db, admin_user, "T1", columns=[("Col", ColumnType.TEXT)])
    resp = admin_client.post(
        f"/tables/{table.id}/edit",
        data={
            "name": "T1",
            "description": "",
            "col_ids": [str(cols[0].id)],
            "col_names": ["Col"],
            "col_types": ["text"],
            "col_required": [],
            "col_options": [""],
            "col_related_table_ids": [""],
            "col_related_display_col_ids": [""],
            "col_related_value_col_ids": [""],
            "rgpd_finalite": "Suivi RH",
            "rgpd_base_legale": "legal",
            "rgpd_duree_conservation": "10 ans",
            "rgpd_responsable": "DRH",
            "rgpd_destinataires": "Prestataire paie",
            "rgpd_hors_ue": "1",
        },
    )
    assert resp.status_code in (200, 303)
    db.refresh(table)
    assert table.rgpd_finalite == "Suivi RH"
    assert table.rgpd_base_legale == "legal"
    assert table.rgpd_duree_conservation == "10 ans"
    assert table.rgpd_responsable == "DRH"
    assert table.rgpd_destinataires == "Prestataire paie"
    assert table.rgpd_hors_ue is True


def test_edit_clears_rgpd_fields(admin_client, db, admin_user):
    table, cols = _make_rgpd_table(db, admin_user)
    resp = admin_client.post(
        f"/tables/{table.id}/edit",
        data={
            "name": "Clients",
            "description": "",
            "col_ids": [str(c.id) for c in cols],
            "col_names": [c.name for c in cols],
            "col_types": [c.col_type.value for c in cols],
            "col_required": [],
            "col_options": [""] * len(cols),
            "col_related_table_ids": [""] * len(cols),
            "col_related_display_col_ids": [""] * len(cols),
            "col_related_value_col_ids": [""] * len(cols),
            # RGPD fields intentionally blank
        },
    )
    assert resp.status_code in (200, 303)
    db.refresh(table)
    assert table.rgpd_finalite == ""
    assert table.rgpd_hors_ue is False
