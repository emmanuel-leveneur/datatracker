import csv
import io
from fastapi import APIRouter, Depends, Form, HTTPException, Request, UploadFile, File, status
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session
from app.activity import log_action
from app.alerts import evaluate_alerts_for_row, get_alert_row_data
from app.database import get_db
from app.dependencies import (
    can_access_table, get_current_user, get_table_or_404,
    get_visible_columns, is_column_readonly,
)
from app.models import CellValue, DataTable, TableRow, User

router = APIRouter(prefix="/tables", tags=["data"])
templates = Jinja2Templates(directory="app/templates")


def _row_details(row, columns) -> str:
    """Formate le résumé d'une ligne pour les logs d'activité."""
    col_map = {col.id: col.name for col in columns}
    cells = {cv.column_id: cv.value for cv in row.cell_values}
    parts = [
        f"{col_map[cid]} -> {val}"
        for cid, val in cells.items()
        if cid in col_map and val not in (None, "")
    ]
    created = row.created_at.strftime("%d/%m/%Y %H:%M") if row.created_at else ""
    return f"Ligne #{row.id} avec {', '.join(parts)} créée le {created}"


@router.get("/{table_id}/rows", response_class=HTMLResponse)
def get_rows(
    request: Request,
    table_id: int,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Retourne le partial table_rows.html (utilisé pour le refresh HTMX après création d'alerte)."""
    table = db.get(DataTable, table_id)
    if not table:
        raise HTTPException(status_code=404)
    if not can_access_table(table, user, db):
        raise HTTPException(status_code=403)
    visible = get_visible_columns(table, user, db)
    visible_ids = {c.id for c in visible}
    col_readonly = {col.id: is_column_readonly(col, user, db) for col in visible}
    rows = db.query(TableRow).filter(
        TableRow.table_id == table_id, TableRow.deleted_at == None
    ).order_by(TableRow.created_at.desc()).all()
    rows_data = [
        {"row": r, "cells": {cv.column_id: cv.value for cv in r.cell_values if cv.column_id in visible_ids}}
        for r in rows
    ]
    return templates.TemplateResponse(
        request, "partials/table_rows.html",
        {
            "table": table,
            "columns": visible,
            "rows_data": rows_data,
            "user": user,
            "can_write": can_access_table(table, user, db, require_write=True),
            "col_readonly": col_readonly,
            "alerted_rows": get_alert_row_data(db, table_id),
        },
    )


@router.get("/{table_id}/rows/new", response_class=HTMLResponse)
def new_row_form(
    request: Request,
    table: DataTable = Depends(get_table_or_404),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    if not can_access_table(table, user, db, require_write=True):
        raise HTTPException(status_code=403)
    visible_cols = get_visible_columns(table, user, db)
    col_readonly = {col.id: is_column_readonly(col, user, db) for col in visible_cols}
    return templates.TemplateResponse(
        request, "partials/row_form.html",
        {
            "table": table,
            "columns": visible_cols,
            "col_readonly": col_readonly,
            "row": None,
            "cells": {},
        },
    )


@router.post("/{table_id}/rows/new")
async def create_row(
    request: Request,
    table_id: int,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    table = db.get(DataTable, table_id)
    if not table:
        raise HTTPException(status_code=404)
    if not can_access_table(table, user, db, require_write=True):
        raise HTTPException(status_code=403)

    form = await request.form()
    row = TableRow(table_id=table_id, created_by_id=user.id)
    db.add(row)
    db.flush()

    visible_cols = get_visible_columns(table, user, db)
    cell_parts = []
    for col in visible_cols:
        if is_column_readonly(col, user, db):
            continue
        value = str(form.get(f"col_{col.id}", ""))
        db.add(CellValue(row_id=row.id, column_id=col.id, value=value))
        if value:
            cell_parts.append(f"{col.name} -> {value}")

    from datetime import datetime as _dt
    created_str = _dt.utcnow().strftime("%d/%m/%Y %H:%M")
    details = f"Ligne #{row.id} avec {', '.join(cell_parts)} créée le {created_str}"
    log_action(db, user, "create_row", "row",
               resource_id=row.id, resource_name=table.name, table_id=table.id,
               details=details)
    db.flush()
    evaluate_alerts_for_row(db, row, table)
    db.commit()

    if request.headers.get("HX-Request"):
        visible = get_visible_columns(table, user, db)
        visible_ids = {c.id for c in visible}
        col_readonly = {col.id: is_column_readonly(col, user, db) for col in visible}
        rows = db.query(TableRow).filter(
            TableRow.table_id == table_id, TableRow.deleted_at == None
        ).order_by(TableRow.created_at.desc()).all()
        rows_data = [
            {"row": r, "cells": {cv.column_id: cv.value for cv in r.cell_values if cv.column_id in visible_ids}}
            for r in rows
        ]
        can_write = can_access_table(table, user, db, require_write=True)
        return templates.TemplateResponse(
            request, "partials/table_rows.html",
            {
                "table": table,
                "columns": visible,
                "rows_data": rows_data,
                "user": user,
                "can_write": can_write,
                "col_readonly": col_readonly,
                "alerted_rows": get_alert_row_data(db, table_id),
            },
        )
    return RedirectResponse(url=f"/tables/{table_id}", status_code=status.HTTP_303_SEE_OTHER)


@router.get("/{table_id}/rows/{row_id}/edit", response_class=HTMLResponse)
def edit_row_form(
    request: Request,
    table_id: int,
    row_id: int,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    table = db.get(DataTable, table_id)
    if not table:
        raise HTTPException(status_code=404)
    if not can_access_table(table, user, db, require_write=True):
        raise HTTPException(status_code=403)
    row = db.get(TableRow, row_id)
    if not row or row.table_id != table_id:
        raise HTTPException(status_code=404)

    visible_cols = get_visible_columns(table, user, db)
    col_readonly = {col.id: is_column_readonly(col, user, db) for col in visible_cols}
    cells = {cv.column_id: cv.value for cv in row.cell_values}

    return templates.TemplateResponse(
        request, "partials/row_form.html",
        {
            "table": table,
            "columns": visible_cols,
            "col_readonly": col_readonly,
            "row": row,
            "cells": cells,
        },
    )


@router.post("/{table_id}/rows/{row_id}/edit")
async def update_row(
    request: Request,
    table_id: int,
    row_id: int,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    table = db.get(DataTable, table_id)
    if not table:
        raise HTTPException(status_code=404)
    if not can_access_table(table, user, db, require_write=True):
        raise HTTPException(status_code=403)
    row = db.get(TableRow, row_id)
    if not row or row.table_id != table_id:
        raise HTTPException(status_code=404)

    form = await request.form()
    visible_cols = get_visible_columns(table, user, db)
    existing_cells = {cv.column_id: cv for cv in row.cell_values}

    # Capture old values before modification
    old_values = {cv.column_id: cv.value for cv in row.cell_values}

    for col in visible_cols:
        if is_column_readonly(col, user, db):
            continue
        value = form.get(f"col_{col.id}", "")
        if col.id in existing_cells:
            existing_cells[col.id].value = str(value)
        else:
            db.add(CellValue(row_id=row.id, column_id=col.id, value=str(value)))

    diff = []
    for col in visible_cols:
        if is_column_readonly(col, user, db):
            continue
        new_val = str(form.get(f"col_{col.id}", ""))
        old_val = old_values.get(col.id, "")
        if old_val != new_val:
            diff.append(f'"{col.name}" : "{old_val}" → "{new_val}"')

    log_action(db, user, "update_row", "row",
               resource_id=row.id, resource_name=table.name, table_id=table.id,
               details="\n".join(diff) if diff else "Aucune modification")
    db.flush()
    evaluate_alerts_for_row(db, row, table)
    db.commit()

    if request.headers.get("HX-Request"):
        visible = get_visible_columns(table, user, db)
        visible_ids = {c.id for c in visible}
        col_readonly = {col.id: is_column_readonly(col, user, db) for col in visible}
        rows = db.query(TableRow).filter(
            TableRow.table_id == table_id, TableRow.deleted_at == None
        ).order_by(TableRow.created_at.desc()).all()
        rows_data = [
            {"row": r, "cells": {cv.column_id: cv.value for cv in r.cell_values if cv.column_id in visible_ids}}
            for r in rows
        ]
        can_write = can_access_table(table, user, db, require_write=True)
        return templates.TemplateResponse(
            request, "partials/table_rows.html",
            {
                "table": table,
                "columns": visible,
                "rows_data": rows_data,
                "user": user,
                "can_write": can_write,
                "col_readonly": col_readonly,
                "alerted_rows": get_alert_row_data(db, table_id),
            },
        )
    return RedirectResponse(url=f"/tables/{table_id}", status_code=status.HTTP_303_SEE_OTHER)


@router.post("/{table_id}/rows/{row_id}/delete")
def trash_row(
    request: Request,
    table_id: int,
    row_id: int,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    from datetime import datetime
    table = db.get(DataTable, table_id)
    if not table:
        raise HTTPException(status_code=404)
    if not can_access_table(table, user, db, require_write=True):
        raise HTTPException(status_code=403)
    row = db.get(TableRow, row_id)
    if not row or row.table_id != table_id:
        raise HTTPException(status_code=404)
    row.deleted_at = datetime.utcnow()
    log_action(db, user, "trash_row", "row",
               resource_id=row.id, resource_name=table.name, table_id=table.id,
               details=_row_details(row, table.columns))
    db.commit()

    if request.headers.get("HX-Request"):
        visible = get_visible_columns(table, user, db)
        visible_ids = {c.id for c in visible}
        col_readonly = {col.id: is_column_readonly(col, user, db) for col in visible}
        rows = db.query(TableRow).filter(
            TableRow.table_id == table_id, TableRow.deleted_at == None
        ).order_by(TableRow.created_at.desc()).all()
        rows_data = [
            {"row": r, "cells": {cv.column_id: cv.value for cv in r.cell_values if cv.column_id in visible_ids}}
            for r in rows
        ]
        can_write = can_access_table(table, user, db, require_write=True)
        return templates.TemplateResponse(
            request, "partials/table_rows.html",
            {
                "table": table,
                "columns": visible,
                "rows_data": rows_data,
                "user": user,
                "can_write": can_write,
                "col_readonly": col_readonly,
                "alerted_rows": get_alert_row_data(db, table_id),
            },
        )
    return RedirectResponse(url=f"/tables/{table_id}", status_code=status.HTTP_303_SEE_OTHER)


@router.post("/{table_id}/rows/{row_id}/restore")
def restore_row(
    table_id: int,
    row_id: int,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    table = db.get(DataTable, table_id)
    if not table:
        raise HTTPException(status_code=404)
    if not can_access_table(table, user, db, require_write=True):
        raise HTTPException(status_code=403)
    row = db.get(TableRow, row_id)
    if not row or row.table_id != table_id:
        raise HTTPException(status_code=404)
    row.deleted_at = None
    log_action(db, user, "restore_row", "row",
               resource_id=row.id, resource_name=table.name, table_id=table.id,
               details=_row_details(row, table.columns))
    db.commit()
    return RedirectResponse(url=f"/tables/{table_id}", status_code=status.HTTP_303_SEE_OTHER)


@router.post("/{table_id}/rows/{row_id}/delete-permanent")
def delete_row_permanent(
    table_id: int,
    row_id: int,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    table = db.get(DataTable, table_id)
    if not table:
        raise HTTPException(status_code=404)
    if not can_access_table(table, user, db, require_write=True):
        raise HTTPException(status_code=403)
    row = db.get(TableRow, row_id)
    if not row or row.table_id != table_id:
        raise HTTPException(status_code=404)
    if row.deleted_at is None:
        raise HTTPException(status_code=400, detail="La ligne doit d'abord être mise à la corbeille")
    log_action(db, user, "delete_row", "row",
               resource_id=row.id, resource_name=table.name, table_id=table.id,
               details=_row_details(row, table.columns))
    db.delete(row)
    db.commit()
    return RedirectResponse(url=f"/tables/{table_id}", status_code=status.HTTP_303_SEE_OTHER)


@router.get("/{table_id}/import", response_class=HTMLResponse)
def import_page(
    request: Request,
    table: DataTable = Depends(get_table_or_404),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    if not can_access_table(table, user, db, require_write=True):
        raise HTTPException(status_code=403)
    visible_cols = get_visible_columns(table, user, db)
    return templates.TemplateResponse(
        request, "tables/import.html",
        {"table": table, "user": user, "columns": visible_cols},
    )


@router.post("/{table_id}/import")
async def import_csv(
    request: Request,
    table_id: int,
    file: UploadFile = File(...),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    table = db.get(DataTable, table_id)
    if not table:
        raise HTTPException(status_code=404)
    if not can_access_table(table, user, db, require_write=True):
        raise HTTPException(status_code=403)

    content = await file.read()
    try:
        text = content.decode("utf-8-sig")
    except UnicodeDecodeError:
        text = content.decode("latin-1")

    reader = csv.DictReader(io.StringIO(text))
    visible_cols = get_visible_columns(table, user, db)
    col_map = {col.name.lower(): col for col in visible_cols}

    imported = 0
    errors = []
    for csv_row in reader:
        row = TableRow(table_id=table_id, created_by_id=user.id)
        db.add(row)
        db.flush()
        for csv_col, value in csv_row.items():
            col = col_map.get(csv_col.strip().lower())
            if col and not is_column_readonly(col, user, db):
                db.add(CellValue(row_id=row.id, column_id=col.id, value=value or ""))
        db.flush()
        evaluate_alerts_for_row(db, row, table)
        imported += 1

    log_action(db, user, "import_csv", "row",
               resource_name=table.name, details=f"{imported} ligne(s) importée(s)",
               table_id=table.id)
    db.commit()
    return templates.TemplateResponse(
        request, "tables/import.html",
        {
            "table": table,
            "user": user,
            "columns": visible_cols,
            "success": f"{imported} ligne(s) importée(s)",
            "errors": errors,
        },
    )
