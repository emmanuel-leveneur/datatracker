import io
from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session
from openpyxl import Workbook
from openpyxl.styles import Font, PatternFill, Alignment
from app.database import get_db
from app.dependencies import (
    can_access_table, get_current_user, get_table_or_404,
    get_visible_columns,
)
from app.models import DataTable, TableRow, User

router = APIRouter(prefix="/tables", tags=["export"])


@router.get("/{table_id}/export/excel")
def export_excel(
    table: DataTable = Depends(get_table_or_404),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    if not can_access_table(table, user, db):
        raise HTTPException(status_code=403)

    visible_cols = get_visible_columns(table, user, db)
    visible_ids = {c.id for c in visible_cols}

    wb = Workbook()
    ws = wb.active
    ws.title = table.name[:31]  # Excel sheet name limit

    # Header row
    header_font = Font(bold=True, color="FFFFFF")
    header_fill = PatternFill(start_color="2563EB", end_color="2563EB", fill_type="solid")
    header_align = Alignment(horizontal="center", vertical="center")

    for col_idx, col in enumerate(visible_cols, start=1):
        cell = ws.cell(row=1, column=col_idx, value=col.name)
        cell.font = header_font
        cell.fill = header_fill
        cell.alignment = header_align
        ws.column_dimensions[cell.column_letter].width = max(15, len(col.name) + 4)

    # Data rows
    rows = (
        db.query(TableRow)
        .filter_by(table_id=table.id)
        .order_by(TableRow.created_at.asc())
        .all()
    )
    for row_idx, row in enumerate(rows, start=2):
        cells = {cv.column_id: cv.value for cv in row.cell_values if cv.column_id in visible_ids}
        for col_idx, col in enumerate(visible_cols, start=1):
            value = cells.get(col.id, "")
            ws.cell(row=row_idx, column=col_idx, value=value)

    # Auto-filter
    if visible_cols:
        ws.auto_filter.ref = f"A1:{ws.cell(row=1, column=len(visible_cols)).column_letter}1"

    buffer = io.BytesIO()
    wb.save(buffer)
    buffer.seek(0)

    filename = f"{table.name.replace(' ', '_')}.xlsx"
    return StreamingResponse(
        buffer,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )
