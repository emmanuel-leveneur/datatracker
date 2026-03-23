from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session
from app.activity import log_action
from app.database import get_db
from app.dependencies import require_admin
from app.models import (
    ColumnPermission, DataTable, PermissionLevel,
    TablePermission, User,
)

router = APIRouter(prefix="/admin", tags=["admin"])
templates = Jinja2Templates(directory="app/templates")


@router.get("/users", response_class=HTMLResponse)
def users_list(
    request: Request,
    current_user: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    users = db.query(User).order_by(User.username).all()
    return templates.TemplateResponse(
        request, "admin/users.html",
        {"user": current_user, "users": users},
    )


@router.post("/users/{user_id}/toggle-admin")
def toggle_admin(
    user_id: int,
    current_user: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    target = db.get(User, user_id)
    if not target:
        raise HTTPException(status_code=404)
    if target.id == current_user.id:
        raise HTTPException(status_code=400, detail="Impossible de modifier son propre rôle")
    new_role = not target.is_admin
    target.is_admin = new_role
    log_action(db, current_user, "toggle_admin", "user",
               resource_id=target.id, resource_name=target.username,
               details="Rôle admin attribué" if new_role else "Rôle admin retiré")
    db.commit()
    return RedirectResponse(url="/admin/users", status_code=status.HTTP_303_SEE_OTHER)


@router.post("/users/{user_id}/delete")
def delete_user(
    user_id: int,
    current_user: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    target = db.get(User, user_id)
    if not target:
        raise HTTPException(status_code=404)
    if target.id == current_user.id:
        raise HTTPException(status_code=400, detail="Impossible de supprimer son propre compte")
    log_action(db, current_user, "delete_user", "user",
               resource_id=target.id, resource_name=target.username)
    db.delete(target)
    db.commit()
    return RedirectResponse(url="/admin/users", status_code=status.HTTP_303_SEE_OTHER)


@router.get("/users/{user_id}/permissions", response_class=HTMLResponse)
def user_permissions_page(
    user_id: int,
    request: Request,
    current_user: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    target = db.get(User, user_id)
    if not target:
        raise HTTPException(status_code=404)

    all_tables = db.query(DataTable).order_by(DataTable.name).all()

    # {table_id: TablePermission}
    table_perms = {
        tp.table_id: tp
        for tp in db.query(TablePermission).filter_by(user_id=user_id).all()
    }

    # {column_id: ColumnPermission}
    col_perms = {
        cp.column_id: cp
        for cp in db.query(ColumnPermission).filter_by(user_id=user_id).all()
    }

    return templates.TemplateResponse(
        request, "admin/user_permissions.html",
        {
            "user": current_user,
            "target": target,
            "all_tables": all_tables,
            "table_perms": table_perms,
            "col_perms": col_perms,
            "perm_levels": [e.value for e in PermissionLevel],
        },
    )


@router.post("/users/{user_id}/permissions")
async def save_user_permissions(
    user_id: int,
    request: Request,
    current_user: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    target = db.get(User, user_id)
    if not target:
        raise HTTPException(status_code=404)

    form = await request.form()
    all_tables = db.query(DataTable).all()

    for table in all_tables:
        # L'owner a toujours accès complet, pas besoin de permission
        if table.created_by_id == user_id:
            continue

        table_level = form.get(f"table_perm_{table.id}")
        tp = db.query(TablePermission).filter_by(table_id=table.id, user_id=user_id).first()

        if table_level and table_level in [e.value for e in PermissionLevel]:
            if tp:
                tp.level = PermissionLevel(table_level)
            else:
                db.add(TablePermission(table_id=table.id, user_id=user_id, level=PermissionLevel(table_level)))
        else:  # "none"
            if tp:
                db.delete(tp)

        for col in table.columns:
            cp = db.query(ColumnPermission).filter_by(column_id=col.id, user_id=user_id).first()
            hidden = form.get(f"col_hidden_{col.id}") == "on"
            readonly = form.get(f"col_readonly_{col.id}") == "on"
            if hidden or readonly:
                if cp:
                    cp.hidden = hidden
                    cp.readonly = readonly
                else:
                    db.add(ColumnPermission(column_id=col.id, user_id=user_id, hidden=hidden, readonly=readonly))
            else:
                if cp:
                    db.delete(cp)

    log_action(db, current_user, "update_user_permissions", "permission",
               resource_id=target.id, resource_name=target.username)
    db.commit()
    return RedirectResponse(
        url=f"/admin/users/{user_id}/permissions",
        status_code=status.HTTP_303_SEE_OTHER,
    )
