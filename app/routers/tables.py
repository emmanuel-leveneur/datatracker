from fastapi import APIRouter, Depends, Form, HTTPException, Request, status
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session
from app.activity import log_action
from app.database import get_db
from app.dependencies import can_access_table, get_current_user, get_table_or_404
from app.models import ColumnType, DataTable, TableColumn, TableFavorite, TablePermission, User

router = APIRouter(prefix="/tables", tags=["tables"])
templates = Jinja2Templates(directory="app/templates")

COLUMN_TYPES = [e.value for e in ColumnType]


@router.get("/", response_class=HTMLResponse)
def list_tables(request: Request, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    if user.is_admin:
        tables = db.query(DataTable).filter(DataTable.deleted_at == None).order_by(DataTable.created_at.desc()).all()
        trashed_tables = db.query(DataTable).filter(DataTable.deleted_at != None).order_by(DataTable.deleted_at.desc()).all()
    else:
        owned = db.query(DataTable).filter(DataTable.created_by_id == user.id, DataTable.deleted_at == None).all()
        shared_ids = [r[0] for r in db.query(TablePermission.table_id).filter_by(user_id=user.id).all()]
        shared = db.query(DataTable).filter(DataTable.id.in_(shared_ids), DataTable.deleted_at == None).all()
        seen = {t.id for t in owned}
        tables = owned + [t for t in shared if t.id not in seen]
        trashed_tables = db.query(DataTable).filter(
            DataTable.created_by_id == user.id, DataTable.deleted_at != None
        ).order_by(DataTable.deleted_at.desc()).all()

    favorite_ids = {
        f.table_id for f in db.query(TableFavorite).filter_by(user_id=user.id).all()
    }
    favorites = [t for t in tables if t.id in favorite_ids]

    return templates.TemplateResponse(
        request, "tables/list.html",
        {
            "user": user,
            "tables": tables,
            "favorites": favorites,
            "favorite_ids": favorite_ids,
            "trashed_tables": trashed_tables,
        },
    )


@router.post("/{table_id}/favorite")
def toggle_favorite(
    table_id: int,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    table = db.get(DataTable, table_id)
    if not table:
        raise HTTPException(status_code=404)
    fav = db.query(TableFavorite).filter_by(user_id=user.id, table_id=table_id).first()
    if fav:
        db.delete(fav)
    else:
        db.add(TableFavorite(user_id=user.id, table_id=table_id))
    db.commit()
    return RedirectResponse(url="/tables/", status_code=status.HTTP_303_SEE_OTHER)


@router.get("/create", response_class=HTMLResponse)
def create_table_page(request: Request, user: User = Depends(get_current_user)):
    return templates.TemplateResponse(
        request, "tables/create.html",
        {"user": user, "column_types": COLUMN_TYPES},
    )


@router.post("/create")
def create_table(
    request: Request,
    name: str = Form(...),
    description: str = Form(""),
    col_names: list[str] = Form(default=[]),
    col_types: list[str] = Form(default=[]),
    col_required: list[str] = Form(default=[]),
    col_options: list[str] = Form(default=[]),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    table = DataTable(name=name, description=description, created_by_id=user.id)
    db.add(table)
    db.flush()

    required_set = set(col_required)
    for i, (cname, ctype) in enumerate(zip(col_names, col_types)):
        cname = cname.strip()
        if not cname:
            continue
        options = col_options[i] if i < len(col_options) else ""
        col = TableColumn(
            table_id=table.id,
            name=cname,
            col_type=ColumnType(ctype),
            order=i,
            required=(str(i) in required_set),
            select_options=options,
        )
        db.add(col)
    log_action(db, user, "create_table", "table",
               resource_id=table.id, resource_name=table.name,
               details=f"{len(col_names)} colonne(s)", table_id=table.id)
    db.commit()
    return RedirectResponse(url=f"/tables/{table.id}", status_code=status.HTTP_303_SEE_OTHER)


@router.get("/{table_id}", response_class=HTMLResponse)
def table_detail(
    request: Request,
    table: DataTable = Depends(get_table_or_404),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    if table.deleted_at is not None:
        raise HTTPException(status_code=404)
    if not can_access_table(table, user, db):
        raise HTTPException(status_code=403, detail="Accès refusé")
    from app.dependencies import get_visible_columns
    from app.models import TableRow

    visible_cols = get_visible_columns(table, user, db)
    visible_col_ids = {c.id for c in visible_cols}

    rows = db.query(TableRow).filter(
        TableRow.table_id == table.id, TableRow.deleted_at == None
    ).order_by(TableRow.created_at.desc()).all()
    rows_data = []
    for row in rows:
        cells = {cv.column_id: cv.value for cv in row.cell_values if cv.column_id in visible_col_ids}
        rows_data.append({"row": row, "cells": cells})

    trashed_rows = db.query(TableRow).filter(
        TableRow.table_id == table.id, TableRow.deleted_at != None
    ).order_by(TableRow.deleted_at.desc()).all()
    trashed_rows_data = []
    for row in trashed_rows:
        cells = {cv.column_id: cv.value for cv in row.cell_values if cv.column_id in visible_col_ids}
        trashed_rows_data.append({"row": row, "cells": cells})

    is_owner = table.created_by_id == user.id
    can_write = can_access_table(table, user, db, require_write=True)

    from app.dependencies import is_column_readonly
    col_readonly = {col.id: is_column_readonly(col, user, db) for col in visible_cols}

    return templates.TemplateResponse(
        request, "tables/detail.html",
        {
            "user": user,
            "table": table,
            "columns": visible_cols,
            "rows_data": rows_data,
            "trashed_rows_data": trashed_rows_data,
            "is_owner": is_owner,
            "can_write": can_write,
            "col_readonly": col_readonly,
            "column_types": COLUMN_TYPES,
        },
    )


@router.get("/{table_id}/edit", response_class=HTMLResponse)
def edit_table_page(
    request: Request,
    table: DataTable = Depends(get_table_or_404),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    if table.deleted_at is not None:
        raise HTTPException(status_code=404)
    if table.created_by_id != user.id and not user.is_admin:
        raise HTTPException(status_code=403, detail="Accès refusé")
    return templates.TemplateResponse(
        request, "tables/edit.html",
        {
            "user": user,
            "table": table,
            "column_types": COLUMN_TYPES,
        },
    )


@router.post("/{table_id}/edit")
def edit_table(
    request: Request,
    table_id: int,
    name: str = Form(...),
    description: str = Form(""),
    col_ids: list[str] = Form(default=[]),
    col_names: list[str] = Form(default=[]),
    col_types: list[str] = Form(default=[]),
    col_required: list[str] = Form(default=[]),
    col_options: list[str] = Form(default=[]),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    table = db.get(DataTable, table_id)
    if not table:
        raise HTTPException(status_code=404)
    if table.created_by_id != user.id and not user.is_admin:
        raise HTTPException(status_code=403)

    # ── Capture de l'état avant modification ──────────────────────────────
    old_name = table.name
    old_description = table.description or ""
    old_cols = {col.id: {"name": col.name, "type": col.col_type.value} for col in table.columns}

    table.name = name
    table.description = description

    existing_ids = {str(c.id) for c in table.columns}
    submitted_ids = set(col_ids)

    # Delete removed columns
    for col in list(table.columns):
        if str(col.id) not in submitted_ids:
            db.delete(col)

    required_set = set(col_required)
    for i, (cid, cname, ctype) in enumerate(zip(col_ids, col_names, col_types)):
        cname = cname.strip()
        if not cname:
            continue
        options = col_options[i] if i < len(col_options) else ""
        if cid and cid in existing_ids:
            col = db.get(TableColumn, int(cid))
            if col:
                col.name = cname
                col.col_type = ColumnType(ctype)
                col.order = i
                col.required = (str(i) in required_set)
                col.select_options = options
        else:
            col = TableColumn(
                table_id=table.id,
                name=cname,
                col_type=ColumnType(ctype),
                order=i,
                required=(str(i) in required_set),
                select_options=options,
            )
            db.add(col)

    # ── Construction du diff avant/après ──────────────────────────────────
    diff = []
    if old_name != name:
        diff.append(f'Nom : "{old_name}" → "{name}"')
    if old_description != (description or ""):
        diff.append(f'Description : "{old_description}" → "{description or ""}"')
    for col_id, old in old_cols.items():
        if str(col_id) not in submitted_ids:
            diff.append(f'Colonne supprimée : "{old["name"]}" ({old["type"]})')
    for i, (cid, cname, ctype) in enumerate(zip(col_ids, col_names, col_types)):
        cname = cname.strip()
        if not cname:
            continue
        if cid and cid in existing_ids:
            old = old_cols.get(int(cid))
            if old:
                if old["name"] != cname:
                    diff.append(f'Colonne : "{old["name"]}" → "{cname}"')
                if old["type"] != ctype:
                    diff.append(f'Type "{cname}" : {old["type"]} → {ctype}')
        else:
            diff.append(f'Colonne ajoutée : "{cname}" ({ctype})')

    log_action(db, user, "edit_table", "table",
               resource_id=table.id, resource_name=name, table_id=table.id,
               details="\n".join(diff) if diff else "Aucune modification")
    db.commit()
    return RedirectResponse(url=f"/tables/{table_id}", status_code=status.HTTP_303_SEE_OTHER)


@router.post("/{table_id}/delete")
def trash_table(
    table_id: int,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    from datetime import datetime
    table = db.get(DataTable, table_id)
    if not table:
        raise HTTPException(status_code=404)
    if table.created_by_id != user.id and not user.is_admin:
        raise HTTPException(status_code=403)
    table.deleted_at = datetime.utcnow()
    log_action(db, user, "trash_table", "table",
               resource_id=table.id, resource_name=table.name, table_id=table.id)
    db.commit()
    return RedirectResponse(url="/tables/", status_code=status.HTTP_303_SEE_OTHER)


@router.post("/{table_id}/restore")
def restore_table(
    table_id: int,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    table = db.get(DataTable, table_id)
    if not table:
        raise HTTPException(status_code=404)
    if table.created_by_id != user.id and not user.is_admin:
        raise HTTPException(status_code=403)
    table.deleted_at = None
    log_action(db, user, "restore_table", "table",
               resource_id=table.id, resource_name=table.name, table_id=table.id)
    db.commit()
    return RedirectResponse(url="/tables/", status_code=status.HTTP_303_SEE_OTHER)


@router.post("/{table_id}/delete-permanent")
def delete_table_permanent(
    table_id: int,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    table = db.get(DataTable, table_id)
    if not table:
        raise HTTPException(status_code=404)
    if table.created_by_id != user.id and not user.is_admin:
        raise HTTPException(status_code=403)
    if table.deleted_at is None:
        raise HTTPException(status_code=400, detail="La table doit d'abord être mise à la corbeille")
    log_action(db, user, "delete_table", "table",
               resource_id=table.id, resource_name=table.name, table_id=table.id)
    db.delete(table)
    db.commit()
    return RedirectResponse(url="/tables/", status_code=status.HTTP_303_SEE_OTHER)
