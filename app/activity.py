from sqlalchemy.orm import Session
from app.models import ActivityLog, User


def log_action(
    db: Session,
    actor: User,
    action: str,
    resource_type: str,
    resource_id: int | None = None,
    resource_name: str = "",
    details: str = "",
) -> None:
    """
    Enregistre une action dans le journal d'activité.
    À appeler avant db.commit() pour que l'entrée soit dans la même transaction.
    """
    db.add(ActivityLog(
        user_id=actor.id,
        username=actor.username,
        action=action,
        resource_type=resource_type,
        resource_id=resource_id,
        resource_name=resource_name,
        details=details,
    ))
