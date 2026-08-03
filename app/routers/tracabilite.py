from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import func
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

    # table_id n'est pas une FK (il doit survivre à la suppression définitive d'une table) et
    # SQLite peut réutiliser l'id d'une table supprimée pour une table créée ensuite : le
    # filtre sur la date exclut les logs d'une éventuelle ancienne table qui aurait eu le
    # même id avant la table actuelle.
    # Comparaison via strftime des deux côtés : server_default=func.now() (CURRENT_TIMESTAMP,
    # sans microsecondes) et un DateTime Python lié par SQLAlchemy (toujours avec .%06d) ont
    # des représentations texte différentes en SQLite — une comparaison directe échoue.
    ts_fmt = "%Y-%m-%d %H:%M:%S"
    logs = (
        db.query(ActivityLog)
        .filter(
            ActivityLog.table_id == table.id,
            func.strftime(ts_fmt, ActivityLog.timestamp) >= func.strftime(ts_fmt, table.created_at),
        )
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
