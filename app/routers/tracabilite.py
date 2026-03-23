from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session

from app.database import get_db
from app.dependencies import can_access_table, get_current_user, get_table_or_404
from app.models import ActivityLog, DataTable, User
from app.routers.logs import ACTION_LABELS, RESOURCE_LABELS

router = APIRouter(prefix="/tables", tags=["tracabilite"])
templates = Jinja2Templates(directory="app/templates")


@router.get("/{table_id}/tracabilite", response_class=HTMLResponse)
def tracabilite_page(
    request: Request,
    table: DataTable = Depends(get_table_or_404),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    if not can_access_table(table, user, db):
        raise HTTPException(status_code=403, detail="Accès refusé")

    logs = (
        db.query(ActivityLog)
        .filter(ActivityLog.table_id == table.id)
        .order_by(ActivityLog.timestamp.desc())
        .limit(500)
        .all()
    )

    return templates.TemplateResponse(
        request, "tables/tracabilite.html",
        {
            "user": user,
            "table": table,
            "logs": logs,
            "action_labels": ACTION_LABELS,
            "resource_labels": RESOURCE_LABELS,
        },
    )
