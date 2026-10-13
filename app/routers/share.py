"""
Partage par email d'une ligne (fiche complète) ou d'une sélection de lignes (colonnes
choisies), avec un texte libre, vers des destinataires saisis librement par
l'utilisateur (pas forcément des comptes DataTracker — c'est tout le but du partage).

Deux façons d'envoyer, au choix de l'utilisateur dans la modale (champ "share_action") :
- "send" : DataTracker envoie directement par SMTP, avec le compte technique de
  l'app comme expéditeur (jamais l'adresse de l'utilisateur — elle n'est en général
  pas autorisée à émettre via ce relais) et Reply-To = l'utilisateur, pour que les
  réponses lui arrivent. Nécessite SMTP_HOST configuré.
- "download" (par défaut) : construit un fichier .eml (déjà rempli, HTML conservé)
  et le propose en téléchargement, From = l'utilisateur lui-même — à ouvrir/éditer/
  envoyer depuis son propre client mail. Ne dépend pas de SMTP_HOST.

Accès en lecture suffisant (comme l'export Excel) : partager ne modifie aucune donnée.
Respecte toujours les colonnes masquées (ColumnPermission.hidden) via
get_visible_columns() — jamais contournable depuis le formulaire.
"""
import re

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session

from app.activity import log_action
from app.config import settings
from app.database import get_db
from app.dependencies import can_access_table, get_current_user, get_table_or_404, get_visible_columns
from app.email_utils import (
    build_bulk_rows_share_eml, build_row_share_eml,
    send_bulk_rows_share_email, send_row_share_email,
)
from app.models import DataTable, TableRow, User

router = APIRouter(prefix="/tables", tags=["share"])
templates = Jinja2Templates(directory="app/templates")

MAX_RECIPIENTS = 10
BULK_SHARE_MAX_ROWS = 200
_EMAIL_RE = re.compile(r'^[^@\s]+@[^@\s]+\.[^@\s]+$')


def _parse_recipients(raw: str) -> list[str]:
    """
    Parse une liste de destinataires séparés par virgule/point-virgule/espace.
    Lève ValueError avec un message présentable à l'utilisateur si invalide.
    """
    parts = [p.strip() for p in re.split(r"[,;\s]+", raw or "") if p.strip()]
    seen: list[str] = []
    for p in parts:
        if p not in seen:
            seen.append(p)
    if not seen:
        raise ValueError("Indiquez au moins un destinataire.")
    if len(seen) > MAX_RECIPIENTS:
        raise ValueError(
            f"Maximum {MAX_RECIPIENTS} destinataires par envoi ({len(seen)} indiqués)."
        )
    invalid = [p for p in seen if not _EMAIL_RE.match(p)]
    if invalid:
        raise ValueError("Adresse(s) email invalide(s) : " + ", ".join(invalid))
    return seen


def _eml_filename(*parts: str) -> str:
    """Nom de fichier .eml sûr à partir de fragments (nom de table, etc.)."""
    safe = "_".join(p.strip().replace(" ", "_") for p in parts if p.strip())
    safe = re.sub(r"[^A-Za-z0-9_\-]", "", safe) or "partage"
    return f"{safe}.eml"


def _eml_response(raw: bytes, filename: str) -> Response:
    return Response(
        content=raw,
        media_type="message/rfc822",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


def _sent_response(recipients: list[str]) -> JSONResponse:
    return JSONResponse({"sent": True, "recipients": recipients})


# ── Partage d'une ligne ─────────────────────────────────────────────────────────

@router.get("/{table_id}/rows/{row_id}/share", response_class=HTMLResponse)
def share_row_modal(
    request: Request,
    table_id: int,
    row_id: int,
    table: DataTable = Depends(get_table_or_404),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    if not can_access_table(table, user, db):
        raise HTTPException(status_code=403)
    row = db.get(TableRow, row_id)
    if not row or row.table_id != table_id or row.deleted_at is not None:
        raise HTTPException(status_code=404)
    return templates.TemplateResponse(
        request, "partials/share_row_modal.html",
        {
            "table": table, "row": row, "columns": get_visible_columns(table, user, db),
            "smtp_configured": bool(settings.SMTP_HOST),
        },
    )


@router.post("/{table_id}/rows/{row_id}/share", response_class=HTMLResponse)
async def share_row_send(
    request: Request,
    table_id: int,
    row_id: int,
    table: DataTable = Depends(get_table_or_404),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    if not can_access_table(table, user, db):
        raise HTTPException(status_code=403)
    row = db.get(TableRow, row_id)
    if not row or row.table_id != table_id or row.deleted_at is not None:
        raise HTTPException(status_code=404)

    form = await request.form()
    action = str(form.get("share_action", "download"))
    recipients_raw = str(form.get("recipients", ""))
    message = str(form.get("message", "")).strip()
    email_title = str(form.get("email_title", "")).strip()[:80]
    columns = get_visible_columns(table, user, db)

    def _error(err: str):
        return templates.TemplateResponse(
            request, "partials/share_row_modal.html",
            {
                "table": table, "row": row, "columns": columns,
                "error": err, "recipients_value": recipients_raw,
                "message_value": message, "title_value": email_title,
                "smtp_configured": bool(settings.SMTP_HOST),
            },
        )

    try:
        recipients = _parse_recipients(recipients_raw)
    except ValueError as exc:
        return _error(str(exc))

    cells = {cv.column_id: cv.value for cv in row.cell_values}

    if action == "send":
        try:
            send_row_share_email(
                to_addresses=recipients,
                reply_to=user.email,
                shared_by=user.username,
                table_name=table.name,
                table_id=table.id,
                row_id=row.id,
                message=message,
                columns=columns,
                cells=cells,
                brand_title=email_title or "DataTracker",
            )
        except Exception:
            return _error("Échec de l'envoi — vérifiez la configuration SMTP ou réessayez plus tard.")
        log_action(
            db, user, "share_row_email", "row",
            resource_id=row.id, resource_name=table.name, table_id=table.id,
            details=(
                f"Ligne #{row.id} : email envoyé à {len(recipients)} "
                f"destinataire(s) : {', '.join(recipients)}"
            ),
        )
        db.commit()
        return _sent_response(recipients)

    raw = build_row_share_eml(
        to_addresses=recipients,
        from_address=user.email,
        shared_by=user.username,
        table_name=table.name,
        table_id=table.id,
        row_id=row.id,
        message=message,
        columns=columns,
        cells=cells,
        brand_title=email_title or "DataTracker",
    )
    log_action(
        db, user, "share_row_email", "row",
        resource_id=row.id, resource_name=table.name, table_id=table.id,
        details=(
            f"Ligne #{row.id} : brouillon .eml généré pour {len(recipients)} "
            f"destinataire(s) : {', '.join(recipients)}"
        ),
    )
    db.commit()

    return _eml_response(raw, _eml_filename("partage", table.name, f"ligne{row.id}"))


# ── Partage en masse ─────────────────────────────────────────────────────────────

@router.get("/{table_id}/rows/bulk-share", response_class=HTMLResponse)
def bulk_share_modal(
    request: Request,
    table: DataTable = Depends(get_table_or_404),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    if not can_access_table(table, user, db):
        raise HTTPException(status_code=403)
    return templates.TemplateResponse(
        request, "partials/share_bulk_modal.html",
        {
            "table": table, "columns": get_visible_columns(table, user, db),
            "smtp_configured": bool(settings.SMTP_HOST),
        },
    )


@router.post("/{table_id}/rows/bulk-share", response_class=HTMLResponse)
async def bulk_share_send(
    request: Request,
    table: DataTable = Depends(get_table_or_404),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    if not can_access_table(table, user, db):
        raise HTTPException(status_code=403)

    form = await request.form()
    action = str(form.get("share_action", "download"))
    recipients_raw = str(form.get("recipients", ""))
    message = str(form.get("message", "")).strip()
    email_title = str(form.get("email_title", "")).strip()[:80]
    visible_columns = get_visible_columns(table, user, db)
    visible_col_ids = {c.id for c in visible_columns}

    try:
        selected_col_ids = {int(i) for i in form.getlist("col_ids")}
    except ValueError:
        selected_col_ids = set()
    # Jamais une colonne masquée, même forgée côté client.
    selected_col_ids &= visible_col_ids

    try:
        row_ids = {int(i) for i in form.getlist("row_ids")}
    except ValueError:
        row_ids = set()

    def _error(err: str):
        return templates.TemplateResponse(
            request, "partials/share_bulk_modal.html",
            {
                "table": table, "columns": visible_columns,
                "error": err, "recipients_value": recipients_raw,
                "message_value": message, "title_value": email_title,
                "checked_col_ids": selected_col_ids,
                "smtp_configured": bool(settings.SMTP_HOST),
            },
        )

    try:
        recipients = _parse_recipients(recipients_raw)
    except ValueError as exc:
        return _error(str(exc))

    if not row_ids:
        return _error("Aucune ligne sélectionnée.")
    if len(row_ids) > BULK_SHARE_MAX_ROWS:
        return _error(
            f"Impossible de partager plus de {BULK_SHARE_MAX_ROWS} lignes en une fois "
            f"({len(row_ids)} sélectionnées)."
        )
    if not selected_col_ids:
        return _error("Choisissez au moins une colonne à inclure.")

    columns = [c for c in visible_columns if c.id in selected_col_ids]

    rows = (
        db.query(TableRow)
        .filter(
            TableRow.table_id == table.id,
            TableRow.id.in_(row_ids),
            TableRow.deleted_at.is_(None),
        )
        .order_by(TableRow.id.asc())
        .all()
    )
    if not rows:
        return _error("Les lignes sélectionnées ne sont plus disponibles.")

    rows_cells = [
        {cv.column_id: cv.value for cv in row.cell_values if cv.column_id in selected_col_ids}
        for row in rows
    ]

    if action == "send":
        try:
            send_bulk_rows_share_email(
                to_addresses=recipients,
                reply_to=user.email,
                shared_by=user.username,
                table_name=table.name,
                table_id=table.id,
                row_count=len(rows),
                message=message,
                columns=columns,
                rows=rows_cells,
                brand_title=email_title or "DataTracker",
            )
        except Exception:
            return _error("Échec de l'envoi — vérifiez la configuration SMTP ou réessayez plus tard.")
        log_action(
            db, user, "share_rows_email", "table",
            resource_id=table.id, resource_name=table.name, table_id=table.id,
            details=(
                f"{len(rows)} ligne(s), {len(columns)} colonne(s) : email envoyé "
                f"à {len(recipients)} destinataire(s) : {', '.join(recipients)}"
            ),
        )
        db.commit()
        return _sent_response(recipients)

    raw = build_bulk_rows_share_eml(
        to_addresses=recipients,
        from_address=user.email,
        shared_by=user.username,
        table_name=table.name,
        table_id=table.id,
        row_count=len(rows),
        message=message,
        columns=columns,
        rows=rows_cells,
        brand_title=email_title or "DataTracker",
    )
    log_action(
        db, user, "share_rows_email", "table",
        resource_id=table.id, resource_name=table.name, table_id=table.id,
        details=(
            f"{len(rows)} ligne(s), {len(columns)} colonne(s) : brouillon .eml généré "
            f"pour {len(recipients)} destinataire(s) : {', '.join(recipients)}"
        ),
    )
    db.commit()

    return _eml_response(raw, _eml_filename("partage", table.name))
