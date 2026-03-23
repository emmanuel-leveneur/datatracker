from fastapi import Depends, HTTPException, Request, status
from sqlalchemy.orm import Session
from app.auth import get_session_user_id
from app.database import get_db
from app.models import User, DataTable, TablePermission, TableOwner, PermissionLevel


def get_current_user(request: Request, db: Session = Depends(get_db)) -> User:
    user_id = get_session_user_id(request)
    if not user_id:
        raise HTTPException(
            status_code=status.HTTP_303_SEE_OTHER,
            headers={"Location": "/auth/login"},
        )
    user = db.get(User, user_id)
    if not user:
        raise HTTPException(
            status_code=status.HTTP_303_SEE_OTHER,
            headers={"Location": "/auth/login"},
        )
    return user


def get_current_user_optional(
    request: Request, db: Session = Depends(get_db)
) -> User | None:
    user_id = get_session_user_id(request)
    if not user_id:
        return None
    return db.get(User, user_id)


def require_admin(current_user: User = Depends(get_current_user)) -> User:
    if not current_user.is_admin:
        raise HTTPException(status_code=403, detail="Admin access required")
    return current_user


def get_table_or_404(table_id: int, db: Session = Depends(get_db)) -> DataTable:
    table = db.get(DataTable, table_id)
    if not table:
        raise HTTPException(status_code=404, detail="Table not found")
    return table


def is_table_owner(table: DataTable, user: User, db: Session) -> bool:
    """Returns True if the user is a co-owner of the table."""
    return (
        db.query(TableOwner)
        .filter_by(table_id=table.id, user_id=user.id)
        .first()
    ) is not None


def can_access_table(
    table: DataTable,
    user: User,
    db: Session,
    require_write: bool = False,
) -> bool:
    """Returns True if the user can access (and optionally write to) the table."""
    if user.is_admin or is_table_owner(table, user, db):
        return True
    perm = (
        db.query(TablePermission)
        .filter_by(table_id=table.id, user_id=user.id)
        .first()
    )
    if not perm:
        return False
    if require_write:
        return perm.level == PermissionLevel.WRITE
    return True


def get_visible_columns(table: DataTable, user: User, db: Session) -> list:
    """Returns columns the user can see (respects ColumnPermission.hidden)."""
    from app.models import ColumnPermission

    if user.is_admin or is_table_owner(table, user, db):
        return list(table.columns)

    visible = []
    for col in table.columns:
        cp = (
            db.query(ColumnPermission)
            .filter_by(column_id=col.id, user_id=user.id)
            .first()
        )
        if cp and cp.hidden:
            continue
        visible.append(col)
    return visible


def is_column_readonly(column, user: User, db: Session) -> bool:
    """Returns True if the column is readonly for the user."""
    from app.models import ColumnPermission

    if user.is_admin:
        return False
    cp = (
        db.query(ColumnPermission)
        .filter_by(column_id=column.id, user_id=user.id)
        .first()
    )
    return bool(cp and cp.readonly)
