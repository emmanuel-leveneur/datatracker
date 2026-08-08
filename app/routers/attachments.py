import os
import uuid

from fastapi import APIRouter, Depends, HTTPException, Query, Request, UploadFile, File, status
from fastapi.responses import FileResponse, HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session

from app.activity import log_action
from app.config import settings
from app.database import get_db
from app.dependencies import can_access_table, get_current_user, get_table_or_404
from app.models import DataTable, RowAttachment, TableRow, User

router = APIRouter(prefix="/tables", tags=["attachments"])
templates = Jinja2Templates(directory="app/templates")

MAX_FILES_PER_ROW = 5
MAX_BYTES = settings.MAX_UPLOAD_SIZE_MB * 1024 * 1024

ALLOWED_MIME_TYPES = {
    "application/pdf",
    "image/jpeg", "image/png", "image/gif", "image/webp",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    "application/vnd.ms-excel",
    "application/msword",
    "text/csv", "text/plain",
}

FRIENDLY_EXTENSIONS = {
    "application/pdf": ".pdf",
    "image/jpeg": ".jpg",
    "image/png": ".png",
    "image/gif": ".gif",
    "image/webp": ".webp",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document": ".docx",
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet": ".xlsx",
    "application/vnd.ms-excel": ".xls",
    "application/msword": ".doc",
    "text/csv": ".csv",
    "text/plain": ".txt",
}


def _upload_path(stored_name: str) -> str:
    os.makedirs(settings.UPLOAD_DIR, exist_ok=True)
    return os.path.join(settings.UPLOAD_DIR, stored_name)


def _delete_attachment_files(attachments: list) -> None:
    for att in attachments:
        path = _upload_path(att.stored_name)
        if os.path.isfile(path):
            os.remove(path)


def _get_row_or_404(table_id: int, row_id: int, db: Session) -> TableRow:
    row = db.get(TableRow, row_id)
    if not row or row.table_id != table_id or row.deleted_at is not None:
        raise HTTPException(status_code=404)
    return row


@router.get("/{table_id}/rows/{row_id}/attachments/panel", response_class=HTMLResponse)
def attachments_panel(
    request: Request,
    table_id: int,
    row_id: int,
    readonly: bool = Query(False),
    table: DataTable = Depends(get_table_or_404),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    if not can_access_table(table, user, db):
        raise HTTPException(status_code=403)
    row = _get_row_or_404(table_id, row_id, db)
    # readonly=1 : utilisé par la fiche détail (consultation), qui n'affiche jamais le
    # formulaire d'upload ni les boutons de suppression même pour un utilisateur en
    # écriture — ces actions vivent désormais exclusivement dans la modale d'édition.
    can_write = not readonly and can_access_table(table, user, db, require_write=True)
    return templates.TemplateResponse(
        request, "partials/row_attachments.html",
        {
            "table": table,
            "row": row,
            "attachments": row.attachments,
            "can_write": can_write,
            "max_files": MAX_FILES_PER_ROW,
            "max_size_mb": settings.MAX_UPLOAD_SIZE_MB,
        },
    )


@router.post("/{table_id}/rows/{row_id}/attachments", response_class=HTMLResponse)
async def upload_attachment(
    request: Request,
    table_id: int,
    row_id: int,
    file: UploadFile = File(...),
    table: DataTable = Depends(get_table_or_404),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    if not can_access_table(table, user, db, require_write=True):
        raise HTTPException(status_code=403)
    row = _get_row_or_404(table_id, row_id, db)

    if len(row.attachments) >= MAX_FILES_PER_ROW:
        raise HTTPException(status_code=400, detail=f"Maximum {MAX_FILES_PER_ROW} fichiers par ligne.")

    mime = file.content_type or ""
    if mime not in ALLOWED_MIME_TYPES:
        raise HTTPException(status_code=400, detail="Type de fichier non autorisé.")

    content = await file.read()
    if len(content) > MAX_BYTES:
        raise HTTPException(status_code=400, detail=f"Fichier trop volumineux (max {settings.MAX_UPLOAD_SIZE_MB} Mo).")

    ext = FRIENDLY_EXTENSIONS.get(mime, "")
    stored_name = uuid.uuid4().hex + ext
    with open(_upload_path(stored_name), "wb") as f:
        f.write(content)

    att = RowAttachment(
        row_id=row.id,
        table_id=table_id,
        uploaded_by=user.id,
        original_name=file.filename or stored_name,
        stored_name=stored_name,
        mime_type=mime,
        size=len(content),
    )
    db.add(att)
    log_action(db, user, "upload_attachment", "row",
               resource_id=row.id, table_id=table_id,
               details=file.filename)
    db.commit()
    db.refresh(row)

    can_write = can_access_table(table, user, db, require_write=True)
    return templates.TemplateResponse(
        request, "partials/row_attachments.html",
        {
            "table": table,
            "row": row,
            "attachments": row.attachments,
            "can_write": can_write,
            "max_files": MAX_FILES_PER_ROW,
            "max_size_mb": settings.MAX_UPLOAD_SIZE_MB,
        },
    )


@router.get("/{table_id}/rows/{row_id}/attachments/{att_id}/download")
def download_attachment(
    table_id: int,
    row_id: int,
    att_id: int,
    table: DataTable = Depends(get_table_or_404),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    if not can_access_table(table, user, db):
        raise HTTPException(status_code=403)
    att = db.get(RowAttachment, att_id)
    if not att or att.row_id != row_id or att.table_id != table_id:
        raise HTTPException(status_code=404)
    path = _upload_path(att.stored_name)
    if not os.path.isfile(path):
        raise HTTPException(status_code=404, detail="Fichier introuvable sur le serveur.")
    return FileResponse(
        path=path,
        filename=att.original_name,
        media_type=att.mime_type,
    )


@router.get("/{table_id}/rows/{row_id}/attachments/{att_id}/view")
def view_attachment(
    table_id: int,
    row_id: int,
    att_id: int,
    table: DataTable = Depends(get_table_or_404),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    if not can_access_table(table, user, db):
        raise HTTPException(status_code=403)
    att = db.get(RowAttachment, att_id)
    if not att or att.row_id != row_id or att.table_id != table_id:
        raise HTTPException(status_code=404)
    if not att.mime_type.startswith("image/") and att.mime_type != "application/pdf":
        raise HTTPException(status_code=400, detail="Prévisualisation non disponible pour ce type de fichier.")
    path = _upload_path(att.stored_name)
    if not os.path.isfile(path):
        raise HTTPException(status_code=404, detail="Fichier introuvable sur le serveur.")
    return FileResponse(path=path, media_type=att.mime_type,
                        headers={"Content-Disposition": "inline"})


@router.post("/{table_id}/rows/{row_id}/attachments/{att_id}/delete", response_class=HTMLResponse)
def delete_attachment(
    request: Request,
    table_id: int,
    row_id: int,
    att_id: int,
    table: DataTable = Depends(get_table_or_404),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    if not can_access_table(table, user, db, require_write=True):
        raise HTTPException(status_code=403)
    att = db.get(RowAttachment, att_id)
    if not att or att.row_id != row_id or att.table_id != table_id:
        raise HTTPException(status_code=404)
    row = _get_row_or_404(table_id, row_id, db)

    path = _upload_path(att.stored_name)
    if os.path.isfile(path):
        os.remove(path)

    log_action(db, user, "delete_attachment", "row",
               resource_id=row.id, table_id=table_id,
               details=att.original_name)
    db.delete(att)
    db.commit()
    db.refresh(row)

    can_write = can_access_table(table, user, db, require_write=True)
    return templates.TemplateResponse(
        request, "partials/row_attachments.html",
        {
            "table": table,
            "row": row,
            "attachments": row.attachments,
            "can_write": can_write,
            "max_files": MAX_FILES_PER_ROW,
            "max_size_mb": settings.MAX_UPLOAD_SIZE_MB,
        },
    )
