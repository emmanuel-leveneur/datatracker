"""Tests : pièces jointes par ligne (upload, download, suppression, permissions)."""
import os
from datetime import datetime, timezone

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.models import (
    ActivityLog, ColumnType, RowAttachment, TablePermission, TableRow,
    PermissionLevel,
)
from tests.helpers import make_table


# ── Fixtures ──────────────────────────────────────────────────────────────────

@pytest.fixture
def upload_dir(tmp_path, monkeypatch):
    """Redirige les uploads vers un répertoire temporaire isolé par test."""
    monkeypatch.setattr("app.config.settings.UPLOAD_DIR", str(tmp_path))
    monkeypatch.setattr("app.routers.attachments.settings.UPLOAD_DIR", str(tmp_path))
    return tmp_path


def _make_row(db: Session, table, user) -> TableRow:
    row = TableRow(table_id=table.id, created_by_id=user.id)
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


def _make_attachment(db: Session, row: TableRow, user, upload_dir) -> RowAttachment:
    """Crée un RowAttachment en base ET le fichier correspondant sur disque."""
    stored_name = "testfile_abc123.pdf"
    path = os.path.join(str(upload_dir), stored_name)
    with open(path, "wb") as f:
        f.write(b"%PDF test content")
    att = RowAttachment(
        row_id=row.id,
        table_id=row.table_id,
        uploaded_by=user.id,
        original_name="rapport.pdf",
        stored_name=stored_name,
        mime_type="application/pdf",
        size=17,
    )
    db.add(att)
    db.commit()
    db.refresh(att)
    return att


# ── Panneau (GET /attachments/panel) ─────────────────────────────────────────

def test_panel_renders_for_owner(admin_client, db, admin_user, upload_dir):
    table, _ = make_table(db, admin_user)
    row = _make_row(db, table, admin_user)

    resp = admin_client.get(f"/tables/{table.id}/rows/{row.id}/attachments/panel")

    assert resp.status_code == 200
    assert "Pièces jointes" in resp.text


def test_panel_forbidden_without_access(user_client, db, admin_user, upload_dir):
    table, _ = make_table(db, admin_user)
    row = _make_row(db, table, admin_user)

    resp = user_client.get(f"/tables/{table.id}/rows/{row.id}/attachments/panel")

    assert resp.status_code == 403


def test_panel_shows_existing_attachment(admin_client, db, admin_user, upload_dir):
    table, _ = make_table(db, admin_user)
    row = _make_row(db, table, admin_user)
    _make_attachment(db, row, admin_user, upload_dir)

    resp = admin_client.get(f"/tables/{table.id}/rows/{row.id}/attachments/panel")

    assert resp.status_code == 200
    assert "rapport.pdf" in resp.text


def test_panel_shows_upload_form_for_write_user(admin_client, db, admin_user, upload_dir):
    table, _ = make_table(db, admin_user)
    row = _make_row(db, table, admin_user)

    resp = admin_client.get(f"/tables/{table.id}/rows/{row.id}/attachments/panel")

    assert resp.status_code == 200
    assert "Ajouter" in resp.text


def test_panel_hides_upload_for_read_only_user(
    user_client, db, admin_user, regular_user, upload_dir
):
    table, _ = make_table(db, admin_user)
    row = _make_row(db, table, admin_user)
    db.add(TablePermission(table_id=table.id, user_id=regular_user.id, level=PermissionLevel.READ))
    db.commit()

    resp = user_client.get(f"/tables/{table.id}/rows/{row.id}/attachments/panel")

    assert resp.status_code == 200
    assert "Ajouter" not in resp.text


# ── Upload (POST /attachments) ────────────────────────────────────────────────

def test_upload_valid_pdf_creates_attachment(admin_client, db, admin_user, upload_dir):
    table, _ = make_table(db, admin_user)
    row = _make_row(db, table, admin_user)

    resp = admin_client.post(
        f"/tables/{table.id}/rows/{row.id}/attachments",
        files={"file": ("facture.pdf", b"%PDF hello", "application/pdf")},
    )

    assert resp.status_code == 200
    db.expire_all()
    att = db.query(RowAttachment).filter_by(row_id=row.id).first()
    assert att is not None
    assert att.original_name == "facture.pdf"
    assert att.mime_type == "application/pdf"
    assert os.path.isfile(os.path.join(str(upload_dir), att.stored_name))


def test_upload_invalid_mime_type_rejected(admin_client, db, admin_user, upload_dir):
    table, _ = make_table(db, admin_user)
    row = _make_row(db, table, admin_user)

    resp = admin_client.post(
        f"/tables/{table.id}/rows/{row.id}/attachments",
        files={"file": ("malware.exe", b"MZ...", "application/octet-stream")},
    )

    assert resp.status_code == 400
    assert db.query(RowAttachment).filter_by(row_id=row.id).count() == 0


def test_upload_too_large_rejected(admin_client, db, admin_user, upload_dir, monkeypatch):
    monkeypatch.setattr("app.routers.attachments.MAX_BYTES", 5)
    table, _ = make_table(db, admin_user)
    row = _make_row(db, table, admin_user)

    resp = admin_client.post(
        f"/tables/{table.id}/rows/{row.id}/attachments",
        files={"file": ("big.pdf", b"%PDF " + b"x" * 100, "application/pdf")},
    )

    assert resp.status_code == 400
    assert db.query(RowAttachment).filter_by(row_id=row.id).count() == 0


def test_upload_forbidden_without_write(user_client, db, admin_user, regular_user, upload_dir):
    table, _ = make_table(db, admin_user)
    row = _make_row(db, table, admin_user)
    db.add(TablePermission(table_id=table.id, user_id=regular_user.id, level=PermissionLevel.READ))
    db.commit()

    resp = user_client.post(
        f"/tables/{table.id}/rows/{row.id}/attachments",
        files={"file": ("doc.pdf", b"%PDF x", "application/pdf")},
    )

    assert resp.status_code == 403


def test_upload_max_files_per_row_enforced(admin_client, db, admin_user, upload_dir):
    from app.routers.attachments import MAX_FILES_PER_ROW
    table, _ = make_table(db, admin_user)
    row = _make_row(db, table, admin_user)

    for i in range(MAX_FILES_PER_ROW):
        admin_client.post(
            f"/tables/{table.id}/rows/{row.id}/attachments",
            files={"file": (f"file{i}.pdf", b"%PDF x", "application/pdf")},
        )

    resp = admin_client.post(
        f"/tables/{table.id}/rows/{row.id}/attachments",
        files={"file": ("overflow.pdf", b"%PDF x", "application/pdf")},
    )

    assert resp.status_code == 400
    db.expire_all()
    assert db.query(RowAttachment).filter_by(row_id=row.id).count() == MAX_FILES_PER_ROW


def test_upload_logs_activity(admin_client, db, admin_user, upload_dir):
    table, _ = make_table(db, admin_user)
    row = _make_row(db, table, admin_user)

    admin_client.post(
        f"/tables/{table.id}/rows/{row.id}/attachments",
        files={"file": ("doc.pdf", b"%PDF x", "application/pdf")},
    )

    db.expire_all()
    log = db.query(ActivityLog).filter_by(action="upload_attachment", resource_id=row.id).first()
    assert log is not None
    assert log.details == "doc.pdf"


# ── Download (GET /attachments/{id}/download) ─────────────────────────────────

def test_download_existing_file(admin_client, db, admin_user, upload_dir):
    table, _ = make_table(db, admin_user)
    row = _make_row(db, table, admin_user)
    att = _make_attachment(db, row, admin_user, upload_dir)

    resp = admin_client.get(
        f"/tables/{table.id}/rows/{row.id}/attachments/{att.id}/download"
    )

    assert resp.status_code == 200
    assert b"%PDF" in resp.content
    assert "rapport.pdf" in resp.headers.get("content-disposition", "")


def test_download_forbidden_without_access(user_client, db, admin_user, upload_dir):
    table, _ = make_table(db, admin_user)
    row = _make_row(db, table, admin_user)
    att = _make_attachment(db, row, admin_user, upload_dir)

    resp = user_client.get(
        f"/tables/{table.id}/rows/{row.id}/attachments/{att.id}/download"
    )

    assert resp.status_code == 403


def test_download_wrong_attachment_id(admin_client, db, admin_user, upload_dir):
    table, _ = make_table(db, admin_user)
    row = _make_row(db, table, admin_user)

    resp = admin_client.get(
        f"/tables/{table.id}/rows/{row.id}/attachments/99999/download"
    )

    assert resp.status_code == 404


def test_download_missing_file_on_disk(admin_client, db, admin_user, upload_dir):
    table, _ = make_table(db, admin_user)
    row = _make_row(db, table, admin_user)
    att = _make_attachment(db, row, admin_user, upload_dir)
    os.remove(os.path.join(str(upload_dir), att.stored_name))

    resp = admin_client.get(
        f"/tables/{table.id}/rows/{row.id}/attachments/{att.id}/download"
    )

    assert resp.status_code == 404


# ── Vue inline image (GET /attachments/{id}/view) ────────────────────────────

def _make_image_attachment(db: Session, row: TableRow, user, upload_dir) -> RowAttachment:
    stored_name = "testimg_abc123.png"
    path = os.path.join(str(upload_dir), stored_name)
    with open(path, "wb") as f:
        f.write(b"\x89PNG fake image content")
    att = RowAttachment(
        row_id=row.id,
        table_id=row.table_id,
        uploaded_by=user.id,
        original_name="photo.png",
        stored_name=stored_name,
        mime_type="image/png",
        size=22,
    )
    db.add(att)
    db.commit()
    db.refresh(att)
    return att


def test_view_image_returns_inline(admin_client, db, admin_user, upload_dir):
    table, _ = make_table(db, admin_user)
    row = _make_row(db, table, admin_user)
    att = _make_image_attachment(db, row, admin_user, upload_dir)

    resp = admin_client.get(
        f"/tables/{table.id}/rows/{row.id}/attachments/{att.id}/view"
    )

    assert resp.status_code == 200
    assert resp.headers.get("content-type", "").startswith("image/png")
    assert "inline" in resp.headers.get("content-disposition", "inline")


def test_view_non_image_rejected(admin_client, db, admin_user, upload_dir):
    table, _ = make_table(db, admin_user)
    row = _make_row(db, table, admin_user)
    att = _make_attachment(db, row, admin_user, upload_dir)  # PDF

    resp = admin_client.get(
        f"/tables/{table.id}/rows/{row.id}/attachments/{att.id}/view"
    )

    assert resp.status_code == 400


def test_view_forbidden_without_access(user_client, db, admin_user, upload_dir):
    table, _ = make_table(db, admin_user)
    row = _make_row(db, table, admin_user)
    att = _make_image_attachment(db, row, admin_user, upload_dir)

    resp = user_client.get(
        f"/tables/{table.id}/rows/{row.id}/attachments/{att.id}/view"
    )

    assert resp.status_code == 403


# ── Suppression (POST /attachments/{id}/delete) ───────────────────────────────

def test_delete_removes_db_record_and_file(admin_client, db, admin_user, upload_dir):
    table, _ = make_table(db, admin_user)
    row = _make_row(db, table, admin_user)
    att = _make_attachment(db, row, admin_user, upload_dir)
    att_id = att.id
    file_path = os.path.join(str(upload_dir), att.stored_name)
    assert os.path.isfile(file_path)

    resp = admin_client.post(
        f"/tables/{table.id}/rows/{row.id}/attachments/{att_id}/delete"
    )

    assert resp.status_code == 200
    db.expire_all()
    assert db.query(RowAttachment).filter_by(id=att_id).first() is None
    assert not os.path.isfile(file_path)


def test_delete_forbidden_without_write(user_client, db, admin_user, regular_user, upload_dir):
    table, _ = make_table(db, admin_user)
    row = _make_row(db, table, admin_user)
    att = _make_attachment(db, row, admin_user, upload_dir)
    db.add(TablePermission(table_id=table.id, user_id=regular_user.id, level=PermissionLevel.READ))
    db.commit()

    resp = user_client.post(
        f"/tables/{table.id}/rows/{row.id}/attachments/{att.id}/delete"
    )

    assert resp.status_code == 403
    assert db.query(RowAttachment).filter_by(id=att.id).first() is not None


def test_delete_wrong_attachment_id(admin_client, db, admin_user, upload_dir):
    table, _ = make_table(db, admin_user)
    row = _make_row(db, table, admin_user)

    resp = admin_client.post(
        f"/tables/{table.id}/rows/{row.id}/attachments/99999/delete"
    )

    assert resp.status_code == 404


def test_delete_logs_activity(admin_client, db, admin_user, upload_dir):
    table, _ = make_table(db, admin_user)
    row = _make_row(db, table, admin_user)
    att = _make_attachment(db, row, admin_user, upload_dir)

    admin_client.post(
        f"/tables/{table.id}/rows/{row.id}/attachments/{att.id}/delete"
    )

    db.expire_all()
    log = db.query(ActivityLog).filter_by(action="delete_attachment", resource_id=row.id).first()
    assert log is not None
    assert log.details == "rapport.pdf"


# ── Intégration : suppression de ligne ────────────────────────────────────────

def test_empty_trash_deletes_attachment_files(admin_client, db, admin_user, upload_dir):
    table, _ = make_table(db, admin_user)
    row = _make_row(db, table, admin_user)
    att = _make_attachment(db, row, admin_user, upload_dir)
    att_id = att.id
    file_path = os.path.join(str(upload_dir), att.stored_name)

    # Mise à la corbeille
    row.deleted_at = datetime.now(timezone.utc)
    db.commit()

    admin_client.post(f"/tables/{table.id}/trash/empty")

    assert not os.path.isfile(file_path)
    db.expire_all()
    assert db.query(RowAttachment).filter_by(id=att_id).first() is None
