from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session
from app.database import get_db
from app.dependencies import require_admin
from app.models import ActivityLog, User

router = APIRouter(prefix="/admin", tags=["logs"])
templates = Jinja2Templates(directory="app/templates")

MAX_LOGS = 1000

ACTION_LABELS = {
    "create_table": "Création de table",
    "edit_table": "Modification de table",
    "trash_table": "Table mise à la corbeille",
    "restore_table": "Table restaurée",
    "delete_table": "Suppression définitive (table)",
    "create_row": "Ajout de ligne",
    "update_row": "Modification de ligne",
    "trash_row": "Ligne mise à la corbeille",
    "restore_row": "Ligne restaurée",
    "delete_row": "Suppression définitive (ligne)",
    "import_csv": "Import CSV",
    "create_comment": "Commentaire ajouté",
    "edit_comment": "Commentaire modifié",
    "delete_comment": "Commentaire supprimé",
    "update_permissions": "Modification des permissions",
    "update_user_permissions": "Permissions utilisateur",
    "add_owner": "Propriétaire ajouté",
    "remove_owner": "Propriétaire retiré",
    "toggle_admin": "Modification rôle admin",
    "delete_user": "Suppression d'utilisateur",
    "register": "Inscription",
    "login": "Connexion",
}

RESOURCE_LABELS = {
    "table": "Table",
    "row": "Ligne",
    "comment": "Commentaire",
    "permission": "Permission",
    "user": "Utilisateur",
}


@router.get("/logs", response_class=HTMLResponse)
def logs_page(
    request: Request,
    current_user: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    logs = (
        db.query(ActivityLog)
        .order_by(ActivityLog.timestamp.desc())
        .limit(MAX_LOGS)
        .all()
    )

    return templates.TemplateResponse(
        request, "admin/logs.html",
        {
            "user": current_user,
            "logs": logs,
            "action_labels": ACTION_LABELS,
            "resource_labels": RESOURCE_LABELS,
            "total": len(logs),
            "max_logs": MAX_LOGS,
        },
    )
