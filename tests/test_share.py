"""Tests : partage d'une ligne / de plusieurs lignes par email (texte libre + destinataires)."""
import re

import pytest

from app.config import settings
from app.models import (
    ActivityLog, ColumnPermission, ColumnType, PermissionLevel, RowAttachment,
    TablePermission, TableRow, CellValue,
)
from app.routers.share import BULK_SHARE_MAX_ROWS, MAX_SHARE_ATTACHMENTS_MB
from tests.helpers import make_table


@pytest.fixture
def upload_dir(tmp_path, monkeypatch):
    """Redirige les uploads vers un répertoire temporaire isolé par test."""
    monkeypatch.setattr(settings, "UPLOAD_DIR", str(tmp_path))
    return tmp_path


def _make_attachment(db, row, user, upload_dir, name="rapport.pdf", content=b"%PDF test content", size=None):
    """Crée un RowAttachment en base ET le fichier correspondant sur disque."""
    import os
    import uuid
    stored_name = uuid.uuid4().hex + ".pdf"
    with open(os.path.join(str(upload_dir), stored_name), "wb") as f:
        f.write(content)
    att = RowAttachment(
        row_id=row.id, table_id=row.table_id, uploaded_by=user.id,
        original_name=name, stored_name=stored_name, mime_type="application/pdf",
        size=size if size is not None else len(content),
    )
    db.add(att)
    db.commit()
    db.refresh(att)
    return att


def _make_rows(db, table, col, values, user):
    rows = []
    for val in values:
        row = TableRow(table_id=table.id, created_by_id=user.id)
        db.add(row)
        db.flush()
        db.add(CellValue(row_id=row.id, column_id=col.id, value=val))
        rows.append(row)
    db.commit()
    return rows


# ── Partage d'une ligne ─────────────────────────────────────────────────────────

def test_share_row_modal_renders(admin_client, db, admin_user):
    table, cols = make_table(db, admin_user, columns=[("Nom", ColumnType.TEXT)])
    rows = _make_rows(db, table, cols[0], ["Dupont"], admin_user)

    resp = admin_client.get(f"/tables/{table.id}/rows/{rows[0].id}/share")

    assert resp.status_code == 200
    assert "Destinataire" in resp.text


def test_share_row_send_returns_eml_download_and_logs(admin_client, db, admin_user, monkeypatch):
    table, cols = make_table(db, admin_user, columns=[("Nom", ColumnType.TEXT)])
    rows = _make_rows(db, table, cols[0], ["Dupont"], admin_user)

    captured = {}

    def fake_build(**kwargs):
        captured.update(kwargs)
        return b"RAW-EML-BYTES"

    monkeypatch.setattr("app.routers.share.build_row_share_eml", fake_build)

    resp = admin_client.post(
        f"/tables/{table.id}/rows/{rows[0].id}/share",
        data={"recipients": "a@exemple.com, b@exemple.com", "message": "Voici la fiche."},
    )

    assert resp.status_code == 200
    assert resp.headers["content-type"] == "message/rfc822"
    assert ".eml" in resp.headers["content-disposition"]
    assert resp.content == b"RAW-EML-BYTES"
    assert captured["to_addresses"] == ["a@exemple.com", "b@exemple.com"]
    assert captured["from_address"] == admin_user.email
    assert captured["message"] == "Voici la fiche."
    assert captured["cells"] == {cols[0].id: "Dupont"}
    assert captured["brand_title"] == "DataTracker"  # pas de titre fourni -> défaut

    db.expire_all()
    log = db.query(ActivityLog).filter_by(action="share_row_email", table_id=table.id).first()
    assert log is not None
    assert "a@exemple.com" in log.details


def test_share_row_rejects_missing_recipient(admin_client, db, admin_user):
    table, cols = make_table(db, admin_user, columns=[("Nom", ColumnType.TEXT)])
    rows = _make_rows(db, table, cols[0], ["Dupont"], admin_user)

    resp = admin_client.post(
        f"/tables/{table.id}/rows/{rows[0].id}/share",
        data={"recipients": "", "message": "Test"},
    )

    assert resp.status_code == 200
    assert "destinataire" in resp.text.lower()
    db.expire_all()
    assert db.query(ActivityLog).filter_by(action="share_row_email").first() is None


def test_share_row_rejects_invalid_email(admin_client, db, admin_user):
    table, cols = make_table(db, admin_user, columns=[("Nom", ColumnType.TEXT)])
    rows = _make_rows(db, table, cols[0], ["Dupont"], admin_user)

    resp = admin_client.post(
        f"/tables/{table.id}/rows/{rows[0].id}/share",
        data={"recipients": "pas-un-email", "message": "Test"},
    )

    assert resp.status_code == 200
    assert "invalide" in resp.text.lower()


def test_share_row_rejects_too_many_recipients(admin_client, db, admin_user):
    table, cols = make_table(db, admin_user, columns=[("Nom", ColumnType.TEXT)])
    rows = _make_rows(db, table, cols[0], ["Dupont"], admin_user)
    many = ", ".join(f"user{i}@exemple.com" for i in range(11))

    resp = admin_client.post(
        f"/tables/{table.id}/rows/{rows[0].id}/share",
        data={"recipients": many, "message": "Test"},
    )

    assert resp.status_code == 200
    assert "maximum" in resp.text.lower()


def test_share_row_requires_at_least_read_access(user_client, db, admin_user, regular_user):
    table, cols = make_table(db, admin_user, columns=[("Nom", ColumnType.TEXT)])
    rows = _make_rows(db, table, cols[0], ["Dupont"], admin_user)

    resp = user_client.get(f"/tables/{table.id}/rows/{rows[0].id}/share")
    assert resp.status_code == 403

    db.add(TablePermission(table_id=table.id, user_id=regular_user.id, level=PermissionLevel.READ))
    db.commit()

    resp = user_client.get(f"/tables/{table.id}/rows/{rows[0].id}/share")
    assert resp.status_code == 200


def test_share_row_never_exposes_hidden_column(admin_client, db, admin_user, regular_user, user_client, monkeypatch):
    table, cols = make_table(
        db, admin_user,
        columns=[("Nom", ColumnType.TEXT), ("Secret", ColumnType.TEXT)],
    )
    nom_col, secret_col = cols
    row = TableRow(table_id=table.id, created_by_id=admin_user.id)
    db.add(row)
    db.flush()
    db.add(CellValue(row_id=row.id, column_id=nom_col.id, value="Dupont"))
    db.add(CellValue(row_id=row.id, column_id=secret_col.id, value="confidentiel"))
    db.add(TablePermission(table_id=table.id, user_id=regular_user.id, level=PermissionLevel.READ))
    db.add(ColumnPermission(column_id=secret_col.id, user_id=regular_user.id, hidden=True))
    db.commit()

    captured = {}

    def fake_build(**kw):
        # Capturer les ids tout de suite : les objets ORM deviennent détachés dès que
        # la session de la requête se ferme, bien avant que le test ne les inspecte.
        captured["column_ids"] = {c.id for c in kw["columns"]}
        return b"RAW-EML-BYTES"

    monkeypatch.setattr("app.routers.share.build_row_share_eml", fake_build)

    resp = user_client.post(
        f"/tables/{table.id}/rows/{row.id}/share",
        data={"recipients": "a@exemple.com", "message": "x"},
    )

    assert resp.status_code == 200
    assert secret_col.id not in captured["column_ids"]
    assert nom_col.id in captured["column_ids"]


# ── Partage en masse ─────────────────────────────────────────────────────────────

def test_bulk_share_modal_renders(admin_client, db, admin_user):
    table, cols = make_table(db, admin_user, columns=[("Nom", ColumnType.TEXT)])
    resp = admin_client.get(f"/tables/{table.id}/rows/bulk-share")
    assert resp.status_code == 200
    assert "Colonnes" in resp.text


def test_bulk_share_returns_eml_download_for_selected_rows_and_columns(admin_client, db, admin_user, monkeypatch):
    table, cols = make_table(
        db, admin_user,
        columns=[("Nom", ColumnType.TEXT), ("Statut", ColumnType.TEXT)],
    )
    nom_col, statut_col = cols
    rows = _make_rows(db, table, nom_col, ["Dupont", "Martin", "Bernard"], admin_user)
    for row, statut in zip(rows, ["Ouvert", "Fermé", "Ouvert"]):
        db.add(CellValue(row_id=row.id, column_id=statut_col.id, value=statut))
    db.commit()

    captured = {}

    def fake_build(**kw):
        captured["row_count"] = kw["row_count"]
        captured["column_ids"] = {c.id for c in kw["columns"]}
        captured["rows"] = kw["rows"]
        return b"RAW-EML-BYTES"

    monkeypatch.setattr("app.routers.share.build_bulk_rows_share_eml", fake_build)

    selected = rows[:2]
    resp = admin_client.post(
        f"/tables/{table.id}/rows/bulk-share",
        data={
            "row_ids": [r.id for r in selected],
            "col_ids": [nom_col.id],
            "recipients": "a@exemple.com",
            "message": "Lot restreint.",
        },
    )

    assert resp.status_code == 200
    assert resp.headers["content-type"] == "message/rfc822"
    assert resp.content == b"RAW-EML-BYTES"
    assert captured["row_count"] == 2
    assert captured["column_ids"] == {nom_col.id}
    assert captured["rows"] == [{nom_col.id: "Dupont"}, {nom_col.id: "Martin"}]

    db.expire_all()
    log = db.query(ActivityLog).filter_by(action="share_rows_email", table_id=table.id).first()
    assert log is not None


def test_bulk_share_rejects_no_rows_selected(admin_client, db, admin_user):
    table, cols = make_table(db, admin_user, columns=[("Nom", ColumnType.TEXT)])
    resp = admin_client.post(
        f"/tables/{table.id}/rows/bulk-share",
        data={"row_ids": [], "col_ids": [cols[0].id], "recipients": "a@exemple.com", "message": ""},
    )
    assert resp.status_code == 200
    assert "aucune ligne" in resp.text.lower()


def test_bulk_share_rejects_no_columns_selected(admin_client, db, admin_user):
    table, cols = make_table(db, admin_user, columns=[("Nom", ColumnType.TEXT)])
    rows = _make_rows(db, table, cols[0], ["Dupont"], admin_user)
    resp = admin_client.post(
        f"/tables/{table.id}/rows/bulk-share",
        data={"row_ids": [rows[0].id], "col_ids": [], "recipients": "a@exemple.com", "message": ""},
    )
    assert resp.status_code == 200
    assert "colonne" in resp.text.lower()


def test_bulk_share_rejects_too_many_rows(admin_client, db, admin_user):
    table, cols = make_table(db, admin_user, columns=[("Nom", ColumnType.TEXT)])
    rows = _make_rows(db, table, cols[0], ["V"] * (BULK_SHARE_MAX_ROWS + 1), admin_user)
    resp = admin_client.post(
        f"/tables/{table.id}/rows/bulk-share",
        data={
            "row_ids": [r.id for r in rows],
            "col_ids": [cols[0].id],
            "recipients": "a@exemple.com",
            "message": "",
        },
    )
    assert resp.status_code == 200
    assert "impossible de partager" in resp.text.lower()


def test_bulk_share_never_exposes_hidden_column_even_if_forged(
    db, admin_user, regular_user, user_client, monkeypatch
):
    table, cols = make_table(
        db, admin_user,
        columns=[("Nom", ColumnType.TEXT), ("Secret", ColumnType.TEXT)],
    )
    nom_col, secret_col = cols
    rows = _make_rows(db, table, nom_col, ["Dupont"], admin_user)
    db.add(CellValue(row_id=rows[0].id, column_id=secret_col.id, value="confidentiel"))
    db.add(TablePermission(table_id=table.id, user_id=regular_user.id, level=PermissionLevel.READ))
    db.add(ColumnPermission(column_id=secret_col.id, user_id=regular_user.id, hidden=True))
    db.commit()

    captured = {}

    def fake_build(**kw):
        captured["column_ids"] = {c.id for c in kw["columns"]}
        return b"RAW-EML-BYTES"

    monkeypatch.setattr("app.routers.share.build_bulk_rows_share_eml", fake_build)

    # Le client forge col_ids avec la colonne masquée en plus de la colonne visible.
    resp = user_client.post(
        f"/tables/{table.id}/rows/bulk-share",
        data={
            "row_ids": [rows[0].id],
            "col_ids": [nom_col.id, secret_col.id],
            "recipients": "a@exemple.com",
            "message": "",
        },
    )

    assert resp.status_code == 200
    assert secret_col.id not in captured["column_ids"]
    assert nom_col.id in captured["column_ids"]


def test_bulk_share_requires_at_least_read_access(user_client, db, admin_user):
    table, cols = make_table(db, admin_user, columns=[("Nom", ColumnType.TEXT)])
    resp = user_client.get(f"/tables/{table.id}/rows/bulk-share")
    assert resp.status_code == 403


# ── Génération réelle du .eml (sans mock) ─────────────────────────────────────────

def test_share_row_eml_is_a_real_mime_message(admin_client, db, admin_user):
    import email as email_pkg

    table, cols = make_table(db, admin_user, columns=[("Nom", ColumnType.TEXT)])
    rows = _make_rows(db, table, cols[0], ["Dupont"], admin_user)

    resp = admin_client.post(
        f"/tables/{table.id}/rows/{rows[0].id}/share",
        data={"recipients": "a@exemple.com", "message": "Voici la fiche."},
    )

    assert resp.status_code == 200
    msg = email_pkg.message_from_bytes(resp.content)
    assert msg["From"] == admin_user.email
    assert msg["To"] == "a@exemple.com"
    parts = [p.get_payload(decode=True).decode("utf-8") for p in msg.walk() if p.get_content_maintype() == "text"]
    assert any("Dupont" in p for p in parts)


def test_share_row_custom_title_replaces_datatracker_brand(admin_client, db, admin_user):
    import email as email_pkg

    table, cols = make_table(db, admin_user, columns=[("Nom", ColumnType.TEXT)])
    rows = _make_rows(db, table, cols[0], ["Dupont"], admin_user)

    resp = admin_client.post(
        f"/tables/{table.id}/rows/{rows[0].id}/share",
        data={"recipients": "a@exemple.com", "message": "", "email_title": "Service RH"},
    )

    assert resp.status_code == 200
    msg = email_pkg.message_from_bytes(resp.content)
    parts = [p.get_payload(decode=True).decode("utf-8") for p in msg.walk() if p.get_content_maintype() == "text"]
    assert all("DataTracker" not in p for p in parts)
    assert any("Service RH" in p for p in parts)


def test_bulk_share_custom_title_replaces_datatracker_brand(admin_client, db, admin_user):
    import email as email_pkg

    table, cols = make_table(db, admin_user, columns=[("Nom", ColumnType.TEXT)])
    rows = _make_rows(db, table, cols[0], ["Dupont"], admin_user)

    resp = admin_client.post(
        f"/tables/{table.id}/rows/bulk-share",
        data={
            "row_ids": [rows[0].id], "col_ids": [cols[0].id],
            "recipients": "a@exemple.com", "message": "", "email_title": "Suivi fournisseurs",
        },
    )

    assert resp.status_code == 200
    msg = email_pkg.message_from_bytes(resp.content)
    parts = [p.get_payload(decode=True).decode("utf-8") for p in msg.walk() if p.get_content_maintype() == "text"]
    assert all("DataTracker" not in p for p in parts)
    assert any("Suivi fournisseurs" in p for p in parts)


def test_eml_filename_is_sanitized(admin_client, db, admin_user):
    table, cols = make_table(db, admin_user, name="Clients à l'étranger !!", columns=[("Nom", ColumnType.TEXT)])
    rows = _make_rows(db, table, cols[0], ["Dupont"], admin_user)

    resp = admin_client.post(
        f"/tables/{table.id}/rows/{rows[0].id}/share",
        data={"recipients": "a@exemple.com", "message": ""},
    )

    assert resp.status_code == 200
    cd = resp.headers["content-disposition"]
    m = re.search(r'filename="([^"]+)"', cd)
    assert m is not None
    filename = m.group(1)
    assert filename.endswith(".eml")
    assert re.match(r'^[A-Za-z0-9_\-]+\.eml$', filename)


# ── Envoi direct (action=send) ────────────────────────────────────────────────────

def test_share_row_modal_shows_send_button_only_when_smtp_configured(admin_client, db, admin_user, monkeypatch):
    table, cols = make_table(db, admin_user, columns=[("Nom", ColumnType.TEXT)])
    rows = _make_rows(db, table, cols[0], ["Dupont"], admin_user)

    monkeypatch.setattr(settings, "SMTP_HOST", "smtp.exemple.com")
    resp = admin_client.get(f"/tables/{table.id}/rows/{rows[0].id}/share")
    assert 'value="send"' in resp.text

    monkeypatch.setattr(settings, "SMTP_HOST", "")
    resp = admin_client.get(f"/tables/{table.id}/rows/{rows[0].id}/share")
    assert 'value="send"' not in resp.text
    assert "indisponible" in resp.text.lower()


def test_share_row_send_action_dispatches_and_logs(admin_client, db, admin_user, monkeypatch):
    table, cols = make_table(db, admin_user, columns=[("Nom", ColumnType.TEXT)])
    rows = _make_rows(db, table, cols[0], ["Dupont"], admin_user)

    captured = {}

    def fake_send(**kwargs):
        captured.update(kwargs)

    monkeypatch.setattr("app.routers.share.send_row_share_email", fake_send)

    resp = admin_client.post(
        f"/tables/{table.id}/rows/{rows[0].id}/share",
        data={"share_action": "send", "recipients": "a@exemple.com, b@exemple.com", "message": "Voici la fiche."},
    )

    assert resp.status_code == 200
    data = resp.json()
    assert data["sent"] is True
    assert data["recipients"] == ["a@exemple.com", "b@exemple.com"]
    assert captured["to_addresses"] == ["a@exemple.com", "b@exemple.com"]
    assert captured["reply_to"] == admin_user.email  # jamais from_address=user.email
    assert "from_address" not in captured  # décidé en interne par send_row_share_email (compte technique)
    assert captured["message"] == "Voici la fiche."

    db.expire_all()
    log = db.query(ActivityLog).filter_by(action="share_row_email", table_id=table.id).first()
    assert log is not None
    assert "envoyé" in log.details.lower()


def test_share_row_send_action_handles_smtp_failure_gracefully(admin_client, db, admin_user, monkeypatch):
    table, cols = make_table(db, admin_user, columns=[("Nom", ColumnType.TEXT)])
    rows = _make_rows(db, table, cols[0], ["Dupont"], admin_user)

    def fake_send(**kwargs):
        raise RuntimeError("SMTP non configuré — envoi direct indisponible.")

    monkeypatch.setattr("app.routers.share.send_row_share_email", fake_send)

    resp = admin_client.post(
        f"/tables/{table.id}/rows/{rows[0].id}/share",
        data={"share_action": "send", "recipients": "a@exemple.com", "message": ""},
    )

    assert resp.status_code == 200
    assert "échec" in resp.text.lower()
    db.expire_all()
    assert db.query(ActivityLog).filter_by(action="share_row_email").first() is None


def test_bulk_share_send_action_dispatches_and_logs(admin_client, db, admin_user, monkeypatch):
    table, cols = make_table(db, admin_user, columns=[("Nom", ColumnType.TEXT)])
    rows = _make_rows(db, table, cols[0], ["Dupont", "Martin"], admin_user)

    captured = {}

    def fake_send(**kwargs):
        captured.update(kwargs)

    monkeypatch.setattr("app.routers.share.send_bulk_rows_share_email", fake_send)

    resp = admin_client.post(
        f"/tables/{table.id}/rows/bulk-share",
        data={
            "share_action": "send",
            "row_ids": [r.id for r in rows],
            "col_ids": [cols[0].id],
            "recipients": "a@exemple.com",
            "message": "",
        },
    )

    assert resp.status_code == 200
    data = resp.json()
    assert data["sent"] is True
    assert captured["reply_to"] == admin_user.email
    assert "from_address" not in captured

    db.expire_all()
    log = db.query(ActivityLog).filter_by(action="share_rows_email", table_id=table.id).first()
    assert log is not None
    assert "envoyé" in log.details.lower()


def test_send_row_share_email_uses_technical_account_as_from(monkeypatch):
    """
    Vérifie directement (sans mock du dispatch SMTP) que send_row_share_email()
    utilise bien le compte technique en From et l'utilisateur en Reply-To — jamais
    l'inverse, pour éviter un From usurpant une adresse non autorisée par le relais.
    """
    from unittest.mock import MagicMock, patch
    import email as email_pkg
    from app import email_utils

    monkeypatch.setattr(settings, "SMTP_HOST", "smtp.exemple.com")
    monkeypatch.setattr(settings, "SMTP_FROM", "noreply@exemple.com")
    monkeypatch.setattr(settings, "SMTP_USER", "")
    monkeypatch.setattr(settings, "SMTP_PASSWORD", "")

    class FakeCol:
        def __init__(self, id, name, col_type):
            self.id = id
            self.name = name
            self.col_type = type("T", (), {"value": col_type})()

    sent = {}

    def fake_smtp(*a, **k):
        m = MagicMock()
        m.sendmail = lambda frm, to, msg: sent.update(frm=frm, to=to, msg=msg)
        return m

    with patch("smtplib.SMTP", side_effect=fake_smtp):
        email_utils.send_row_share_email(
            to_addresses=["dest@exemple.com"],
            reply_to="emmanuel@exemple.com",
            shared_by="emmanuel",
            table_name="Clients",
            table_id=1,
            row_id=1,
            message="x",
            columns=[FakeCol(1, "Nom", "text")],
            cells={1: "Dupont"},
        )

    assert sent["frm"] == "noreply@exemple.com"
    msg = email_pkg.message_from_string(sent["msg"])
    assert msg["From"] == "noreply@exemple.com"
    assert msg["Reply-To"] == "emmanuel@exemple.com"


def test_send_row_share_email_raises_when_smtp_not_configured(monkeypatch):
    from app import email_utils

    monkeypatch.setattr(settings, "SMTP_HOST", "")

    with pytest.raises(RuntimeError):
        email_utils.send_row_share_email(
            to_addresses=["dest@exemple.com"], reply_to="e@exemple.com", shared_by="e",
            table_name="Clients", table_id=1, row_id=1, message="x", columns=[], cells={},
        )


# ── Pièces jointes de la ligne ────────────────────────────────────────────────────

def test_share_row_modal_shows_attachment_checkboxes(admin_client, db, admin_user, upload_dir):
    table, cols = make_table(db, admin_user, columns=[("Nom", ColumnType.TEXT)])
    rows = _make_rows(db, table, cols[0], ["Dupont"], admin_user)
    att = _make_attachment(db, rows[0], admin_user, upload_dir)

    resp = admin_client.get(f"/tables/{table.id}/rows/{rows[0].id}/share")

    assert resp.status_code == 200
    assert "Pièces jointes" in resp.text
    assert att.original_name in resp.text


def test_share_row_send_includes_selected_attachment(admin_client, db, admin_user, upload_dir, monkeypatch):
    table, cols = make_table(db, admin_user, columns=[("Nom", ColumnType.TEXT)])
    rows = _make_rows(db, table, cols[0], ["Dupont"], admin_user)
    att = _make_attachment(db, rows[0], admin_user, upload_dir, name="rapport.pdf", content=b"PDF-BYTES")

    captured = {}

    def fake_build(**kwargs):
        captured.update(kwargs)
        return b"RAW-EML-BYTES"

    monkeypatch.setattr("app.routers.share.build_row_share_eml", fake_build)

    resp = admin_client.post(
        f"/tables/{table.id}/rows/{rows[0].id}/share",
        data={"recipients": "a@exemple.com", "message": "", "attachment_ids": [att.id]},
    )

    assert resp.status_code == 200
    assert captured["attachments"] == [("rapport.pdf", b"PDF-BYTES")]


def test_share_row_excludes_unchecked_attachment(admin_client, db, admin_user, upload_dir, monkeypatch):
    table, cols = make_table(db, admin_user, columns=[("Nom", ColumnType.TEXT)])
    rows = _make_rows(db, table, cols[0], ["Dupont"], admin_user)
    _make_attachment(db, rows[0], admin_user, upload_dir)

    captured = {}

    def fake_build(**kwargs):
        captured.update(kwargs)
        return b"RAW-EML-BYTES"

    monkeypatch.setattr("app.routers.share.build_row_share_eml", fake_build)

    resp = admin_client.post(
        f"/tables/{table.id}/rows/{rows[0].id}/share",
        data={"recipients": "a@exemple.com", "message": ""},  # pas de attachment_ids
    )

    assert resp.status_code == 200
    assert captured["attachments"] == []


def test_share_row_ignores_attachment_from_another_row(admin_client, db, admin_user, upload_dir, monkeypatch):
    table, cols = make_table(db, admin_user, columns=[("Nom", ColumnType.TEXT)])
    rows = _make_rows(db, table, cols[0], ["Dupont", "Martin"], admin_user)
    other_att = _make_attachment(db, rows[1], admin_user, upload_dir)  # appartient à l'AUTRE ligne

    captured = {}

    def fake_build(**kwargs):
        captured.update(kwargs)
        return b"RAW-EML-BYTES"

    monkeypatch.setattr("app.routers.share.build_row_share_eml", fake_build)

    # Le client forge l'id de la PJ de l'autre ligne pour la ligne partagée ici.
    resp = admin_client.post(
        f"/tables/{table.id}/rows/{rows[0].id}/share",
        data={"recipients": "a@exemple.com", "message": "", "attachment_ids": [other_att.id]},
    )

    assert resp.status_code == 200
    assert captured["attachments"] == []


def test_share_row_rejects_attachments_exceeding_size_cap(admin_client, db, admin_user, upload_dir):
    table, cols = make_table(db, admin_user, columns=[("Nom", ColumnType.TEXT)])
    rows = _make_rows(db, table, cols[0], ["Dupont"], admin_user)
    # Taille déclarée en base dépasse le plafond (le fichier réel sur disque reste petit).
    att = _make_attachment(
        db, rows[0], admin_user, upload_dir,
        size=(MAX_SHARE_ATTACHMENTS_MB + 1) * 1024 * 1024,
    )

    resp = admin_client.post(
        f"/tables/{table.id}/rows/{rows[0].id}/share",
        data={"recipients": "a@exemple.com", "message": "", "attachment_ids": [att.id]},
    )

    assert resp.status_code == 200
    assert "volumineuses" in resp.text.lower()


def test_share_row_eml_contains_real_attachment(admin_client, db, admin_user, upload_dir):
    import email as email_pkg

    table, cols = make_table(db, admin_user, columns=[("Nom", ColumnType.TEXT)])
    rows = _make_rows(db, table, cols[0], ["Dupont"], admin_user)
    att = _make_attachment(db, rows[0], admin_user, upload_dir, name="contrat.pdf", content=b"CONTENU-PDF")

    resp = admin_client.post(
        f"/tables/{table.id}/rows/{rows[0].id}/share",
        data={"recipients": "a@exemple.com", "message": "", "attachment_ids": [att.id]},
    )

    assert resp.status_code == 200
    msg = email_pkg.message_from_bytes(resp.content)
    assert msg.get_content_type() == "multipart/mixed"
    attachment_parts = [p for p in msg.walk() if p.get_filename() == "contrat.pdf"]
    assert len(attachment_parts) == 1
    assert attachment_parts[0].get_payload(decode=True) == b"CONTENU-PDF"
