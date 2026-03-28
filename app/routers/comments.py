from datetime import datetime, timezone
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session

from app.activity import log_action
from app.database import get_db
from app.dependencies import can_access_table, get_current_user, is_table_owner
from app.models import DataTable, RowComment, TableRow, User

router = APIRouter(tags=["comments"])
templates = Jinja2Templates(directory="app/templates")


# ── Filtre Jinja2 : timestamp relatif ─────────────────────────────────────────

def _relative_time(dt: datetime) -> str:
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    diff = now - dt.replace(tzinfo=None) if dt.tzinfo else now - dt
    seconds = int(diff.total_seconds())
    if seconds < 60:
        return "à l'instant"
    if seconds < 3600:
        m = seconds // 60
        return f"il y a {m} min"
    if seconds < 86400:
        h = seconds // 3600
        return f"il y a {h}h"
    if seconds < 172800:
        return "hier"
    if seconds < 604800:
        d = seconds // 86400
        return f"il y a {d} jours"
    return dt.strftime("%d/%m/%Y")


def _avatar_color(username: str) -> str:
    colors = [
        "bg-blue-500", "bg-emerald-500", "bg-violet-500",
        "bg-orange-500", "bg-rose-500", "bg-cyan-500", "bg-amber-500",
    ]
    return colors[sum(ord(c) for c in username) % len(colors)]


templates.env.filters["relative_time"] = _relative_time
templates.env.filters["avatar_color"] = _avatar_color


# ── Helpers ───────────────────────────────────────────────────────────────────

def _get_row_and_table(row_id: int, table_id: int, db: Session):
    row = db.get(TableRow, row_id)
    if not row or row.deleted_at is not None or row.table_id != table_id:
        raise HTTPException(status_code=404)
    table = db.get(DataTable, table_id)
    if not table or table.deleted_at is not None:
        raise HTTPException(status_code=404)
    return row, table


def _build_row_summary(row: TableRow, table: DataTable) -> list[tuple[str, str]]:
    """Retourne les 3 premières valeurs non-vides de la ligne avec leur nom de colonne."""
    cells = {cv.column_id: cv.value for cv in row.cell_values}
    result = []
    for col in sorted(table.columns, key=lambda c: c.order):
        if len(result) >= 3:
            break
        val = cells.get(col.id, "").strip()
        if not val:
            continue
        t = col.col_type.value
        if t == "date" and len(val) >= 10:
            display = f"{val[8:10]}/{val[5:7]}/{val[0:4]}"
        elif t == "datetime" and len(val) >= 16:
            display = f"{val[8:10]}/{val[5:7]}/{val[0:4]} {val[11:16]}"
        elif t == "boolean":
            display = "Oui" if val in ("true", "1", "True") else "Non"
        else:
            display = val[:60] + ("…" if len(val) > 60 else "")
        result.append((col.name, display))
    return result


def _comment_list_ctx(row: TableRow, table: DataTable, user: User, db: Session) -> dict:
    comments = (
        db.query(RowComment)
        .filter_by(row_id=row.id)
        .order_by(RowComment.created_at)
        .all()
    )
    return {
        "row": row,
        "table": table,
        "user": user,
        "comments": comments,
        "is_owner": is_table_owner(table, user, db),
    }


def _badge_oob_html(row_id: int, table_id: int, count: int) -> str:
    """Bouton commentaire complet pour mise à jour OOB immédiate dans le tableau."""
    if count > 0:
        btn_class = "inline-flex items-center gap-1 rounded-full transition bg-blue-100 text-blue-700 hover:bg-blue-200 px-2 py-0.5"
        inner = f'<i data-lucide="message-square" class="w-3.5 h-3.5"></i><span class="text-xs font-semibold leading-none">{count}</span>'
        title = f"Commentaires ({count})"
    else:
        btn_class = "inline-flex items-center gap-1 rounded-full transition text-gray-300 hover:text-blue-400 hover:bg-blue-50 p-1.5"
        inner = '<i data-lucide="message-square" class="w-3.5 h-3.5"></i>'
        title = "Commentaires"
    return (
        f'<button id="cc-btn-{row_id}" hx-swap-oob="true"'
        f' hx-get="/tables/{table_id}/rows/{row_id}/comments/panel"'
        f' hx-target="#comment-panel" hx-swap="innerHTML"'
        f' title="{title}" class="{btn_class}">'
        f'{inner}</button>'
    )


# ── Routes ────────────────────────────────────────────────────────────────────

@router.get("/tables/{table_id}/rows/{row_id}/comments/panel", response_class=HTMLResponse)
def comments_panel(
    request: Request,
    table_id: int,
    row_id: int,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    row, table = _get_row_and_table(row_id, table_id, db)
    if not can_access_table(table, user, db):
        raise HTTPException(status_code=403)
    ctx = _comment_list_ctx(row, table, user, db)
    ctx["row_summary"] = _build_row_summary(row, table)
    return templates.TemplateResponse(request, "comments/panel.html", ctx)


@router.post("/tables/{table_id}/rows/{row_id}/comments", response_class=HTMLResponse)
async def add_comment(
    request: Request,
    table_id: int,
    row_id: int,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    row, table = _get_row_and_table(row_id, table_id, db)
    if not can_access_table(table, user, db):
        raise HTTPException(status_code=403)

    form = await request.form()
    content = str(form.get("content", "")).strip()
    if not content:
        raise HTTPException(status_code=422, detail="Le commentaire ne peut pas être vide.")

    db.add(RowComment(row_id=row_id, user_id=user.id, content=content))
    log_action(db, user, "create_comment", "comment",
               resource_id=row_id, resource_name=table.name, table_id=table.id,
               details=f"Commentaire ajouté sur la ligne #{row_id} : {content[:120]}")
    db.commit()

    ctx = _comment_list_ctx(row, table, user, db)
    # OOB badge doit être défini AVANT la création du TemplateResponse
    ctx["_oob_badge"] = _badge_oob_html(row_id, table_id, len(ctx["comments"]))
    return templates.TemplateResponse(request, "comments/_list.html", ctx)


@router.post("/tables/{table_id}/rows/{row_id}/comments/{comment_id}/delete", response_class=HTMLResponse)
def delete_comment(
    request: Request,
    table_id: int,
    row_id: int,
    comment_id: int,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    row, table = _get_row_and_table(row_id, table_id, db)
    if not can_access_table(table, user, db):
        raise HTTPException(status_code=403)

    comment = db.get(RowComment, comment_id)
    if not comment or comment.row_id != row_id:
        raise HTTPException(status_code=404)
    # Seul l'auteur, un propriétaire de table, ou un admin peut supprimer
    if not (comment.user_id == user.id or user.is_admin or is_table_owner(table, user, db)):
        raise HTTPException(status_code=403)

    snippet = comment.content[:120]
    db.delete(comment)
    log_action(db, user, "delete_comment", "comment",
               resource_id=row_id, resource_name=table.name, table_id=table.id,
               details=f"Commentaire supprimé sur la ligne #{row_id} : {snippet}")
    db.commit()

    ctx = _comment_list_ctx(row, table, user, db)
    ctx["_oob_badge"] = _badge_oob_html(row_id, table_id, len(ctx["comments"]))
    return templates.TemplateResponse(request, "comments/_list.html", ctx)


@router.post("/tables/{table_id}/rows/{row_id}/comments/{comment_id}/edit", response_class=HTMLResponse)
async def edit_comment(
    request: Request,
    table_id: int,
    row_id: int,
    comment_id: int,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    row, table = _get_row_and_table(row_id, table_id, db)
    if not can_access_table(table, user, db):
        raise HTTPException(status_code=403)

    comment = db.get(RowComment, comment_id)
    if not comment or comment.row_id != row_id:
        raise HTTPException(status_code=404)
    if comment.user_id != user.id:
        raise HTTPException(status_code=403)

    form = await request.form()
    content = str(form.get("content", "")).strip()
    if not content:
        raise HTTPException(status_code=422)

    comment.content = content
    comment.edited_at = datetime.utcnow()
    log_action(db, user, "edit_comment", "comment",
               resource_id=row_id, resource_name=table.name, table_id=table.id,
               details=f"Commentaire modifié sur la ligne #{row_id} : {content[:120]}")
    db.commit()

    ctx = {
        "request": request,
        "comment": comment,
        "row": row,
        "table": table,
        "user": user,
        "is_owner": is_table_owner(table, user, db),
    }
    return templates.TemplateResponse(request, "comments/_comment.html", ctx)
