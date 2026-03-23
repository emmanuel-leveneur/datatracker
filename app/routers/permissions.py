from fastapi import APIRouter, Depends, Form, HTTPException, Request, status
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session
from app.activity import log_action
from app.database import get_db
from app.dependencies import get_current_user, get_table_or_404, is_table_owner
from app.models import (
    ColumnPermission, DataTable, PermissionLevel,
    TableOwner, TablePermission, User,
)

router = APIRouter(prefix="/tables", tags=["permissions"])
templates = Jinja2Templates(directory="app/templates")


def _require_owner_or_admin(table: DataTable, user: User, db: Session):
    if not is_table_owner(table, user, db) and not user.is_admin:
        raise HTTPException(status_code=403, detail="Accès refusé")


@router.get("/{table_id}/permissions", response_class=HTMLResponse)
def permissions_page(
    request: Request,
    table: DataTable = Depends(get_table_or_404),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    _require_owner_or_admin(table, user, db)

    owner_ids = {to.user_id for to in table.co_owners}
    all_users = db.query(User).order_by(User.username).all()
    non_owner_users = [u for u in all_users if u.id not in owner_ids]
    owner_users = [u for u in all_users if u.id in owner_ids]

    table_perms = {tp.user_id: tp for tp in table.permissions}

    col_perms: dict[int, dict[int, ColumnPermission]] = {}
    for col in table.columns:
        col_perms[col.id] = {}
        for cp in col.column_permissions:
            col_perms[col.id][cp.user_id] = cp

    return templates.TemplateResponse(
        request, "permissions/manage.html",
        {
            "user": user,
            "table": table,
            "owner_users": owner_users,
            "owner_ids": owner_ids,
            "all_users": non_owner_users,
            "table_perms": table_perms,
            "col_perms": col_perms,
            "perm_levels": [e.value for e in PermissionLevel],
        },
    )


@router.post("/{table_id}/permissions/bulk")
async def bulk_set_permissions(
    request: Request,
    table_id: int,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Save all permissions from the permissions form in one POST."""
    table = db.get(DataTable, table_id)
    if not table:
        raise HTTPException(status_code=404)
    _require_owner_or_admin(table, user, db)

    form = await request.form()
    owner_ids = {to.user_id for to in table.co_owners}
    all_users = db.query(User).filter(~User.id.in_(owner_ids)).all()

    # Capture state before modification
    old_table_perms = {tp.user_id: tp.level.value for tp in table.permissions}
    old_col_perms: dict[tuple, dict] = {}
    for col in table.columns:
        for cp in col.column_permissions:
            old_col_perms[(col.id, cp.user_id)] = {"hidden": cp.hidden, "readonly": cp.readonly}

    diff = []

    for u in all_users:
        # Table permission
        table_level = form.get(f"table_perm_{u.id}")
        new_level = table_level if table_level and table_level in [e.value for e in PermissionLevel] else "none"
        old_level = old_table_perms.get(u.id, "none")
        if old_level != new_level:
            diff.append(f'Accès "{u.username}" : "{old_level}" → "{new_level}"')

        tp = db.query(TablePermission).filter_by(table_id=table_id, user_id=u.id).first()
        if new_level != "none":
            if tp:
                tp.level = PermissionLevel(new_level)
            else:
                db.add(TablePermission(table_id=table_id, user_id=u.id, level=PermissionLevel(new_level)))
        else:
            if tp:
                db.delete(tp)

        # Column permissions
        for col in table.columns:
            cp = db.query(ColumnPermission).filter_by(column_id=col.id, user_id=u.id).first()
            hidden = form.get(f"col_hidden_{col.id}_{u.id}") == "on"
            readonly = form.get(f"col_readonly_{col.id}_{u.id}") == "on"

            old_cp = old_col_perms.get((col.id, u.id), {"hidden": False, "readonly": False})
            if old_cp["hidden"] != hidden or old_cp["readonly"] != readonly:
                old_desc = ", ".join(filter(None, [
                    "masquée" if old_cp["hidden"] else "",
                    "lecture seule" if old_cp["readonly"] else "",
                ])) or "aucune restriction"
                new_desc = ", ".join(filter(None, [
                    "masquée" if hidden else "",
                    "lecture seule" if readonly else "",
                ])) or "aucune restriction"
                diff.append(f'Colonne "{col.name}" / {u.username} : "{old_desc}" → "{new_desc}"')

            if hidden or readonly:
                if cp:
                    cp.hidden = hidden
                    cp.readonly = readonly
                else:
                    db.add(ColumnPermission(column_id=col.id, user_id=u.id, hidden=hidden, readonly=readonly))
            else:
                if cp:
                    db.delete(cp)

    log_action(db, user, "update_permissions", "permission",
               resource_id=table.id, resource_name=table.name, table_id=table.id,
               details="\n".join(diff) if diff else "Aucune modification")
    db.commit()
    return RedirectResponse(
        url=f"/tables/{table_id}/permissions",
        status_code=status.HTTP_303_SEE_OTHER,
    )


@router.post("/{table_id}/owners")
def add_owner(
    table_id: int,
    new_owner_id: int = Form(...),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    table = db.get(DataTable, table_id)
    if not table:
        raise HTTPException(status_code=404)
    _require_owner_or_admin(table, user, db)

    target = db.get(User, new_owner_id)
    if not target:
        raise HTTPException(status_code=404, detail="Utilisateur introuvable")

    existing = db.query(TableOwner).filter_by(table_id=table_id, user_id=new_owner_id).first()
    if not existing:
        db.add(TableOwner(table_id=table_id, user_id=new_owner_id))
        log_action(db, user, "add_owner", "table",
                   resource_id=table.id, resource_name=table.name, table_id=table.id,
                   details=f"Propriétaire ajouté : {target.email.split('@')[0]}")
        db.commit()
    return RedirectResponse(
        url=f"/tables/{table_id}/permissions",
        status_code=status.HTTP_303_SEE_OTHER,
    )


@router.post("/{table_id}/owners/{owner_id}/remove")
def remove_owner(
    table_id: int,
    owner_id: int,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    table = db.get(DataTable, table_id)
    if not table:
        raise HTTPException(status_code=404)
    _require_owner_or_admin(table, user, db)

    owners = db.query(TableOwner).filter_by(table_id=table_id).all()
    if len(owners) <= 1:
        raise HTTPException(status_code=400, detail="Impossible de retirer le dernier propriétaire")

    target_ownership = db.query(TableOwner).filter_by(table_id=table_id, user_id=owner_id).first()
    if not target_ownership:
        raise HTTPException(status_code=404, detail="Cet utilisateur n'est pas propriétaire")

    target = db.get(User, owner_id)
    db.delete(target_ownership)
    log_action(db, user, "remove_owner", "table",
               resource_id=table.id, resource_name=table.name, table_id=table.id,
               details=f"Propriétaire retiré : {target.email.split('@')[0] if target else owner_id}")
    db.commit()
    return RedirectResponse(
        url=f"/tables/{table_id}/permissions",
        status_code=status.HTTP_303_SEE_OTHER,
    )
