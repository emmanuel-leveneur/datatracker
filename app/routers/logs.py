from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session
from app.database import get_db
from app.dependencies import require_admin
from app.models import ActivityLog, User

router = APIRouter(prefix="/admin", tags=["logs"])
templates = Jinja2Templates(directory="app/templates")

PAGE_SIZE = 50

ACTION_LABELS = {
    "create_table": "Création de table",
    "edit_table": "Modification de table",
    "delete_table": "Suppression de table",
    "create_row": "Ajout de ligne",
    "update_row": "Modification de ligne",
    "delete_row": "Suppression de ligne",
    "import_csv": "Import CSV",
    "update_permissions": "Modification des permissions",
    "update_user_permissions": "Permissions utilisateur",
    "toggle_admin": "Modification rôle admin",
    "delete_user": "Suppression d'utilisateur",
    "register": "Inscription",
    "login": "Connexion",
}

RESOURCE_LABELS = {
    "table": "Table",
    "row": "Ligne",
    "permission": "Permission",
    "user": "Utilisateur",
}


@router.get("/logs", response_class=HTMLResponse)
def logs_page(
    request: Request,
    current_user: User = Depends(require_admin),
    db: Session = Depends(get_db),
    resource_type: str = "",
    username: str = "",
    page: int = 1,
):
    query = db.query(ActivityLog)

    if resource_type:
        query = query.filter(ActivityLog.resource_type == resource_type)
    if username:
        query = query.filter(ActivityLog.username.ilike(f"%{username}%"))

    total = query.count()
    offset = (page - 1) * PAGE_SIZE
    logs = (
        query.order_by(ActivityLog.timestamp.desc())
        .offset(offset)
        .limit(PAGE_SIZE)
        .all()
    )

    total_pages = max(1, (total + PAGE_SIZE - 1) // PAGE_SIZE)

    return templates.TemplateResponse(
        request, "admin/logs.html",
        {
            "user": current_user,
            "logs": logs,
            "action_labels": ACTION_LABELS,
            "resource_labels": RESOURCE_LABELS,
            "resource_types": list(RESOURCE_LABELS.keys()),
            "filter_resource_type": resource_type,
            "filter_username": username,
            "page": page,
            "total_pages": total_pages,
            "total": total,
        },
    )
