import json
import re
from fastapi import APIRouter, Depends, Form, HTTPException, Request, status
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session

from app.alerts import evaluate_alerts_for_row
from app.database import get_db
from app.dependencies import can_access_table, get_current_user, get_table_or_404, is_table_owner
from sqlalchemy import and_, exists, or_

from app.models import (
    Alert, AlertNotification, AlertRecipient, AlertScope, AlertState,
    DataTable, TableOwner, TablePermission, TableRow, User,
)

router = APIRouter(tags=["alerts"])
templates = Jinja2Templates(directory="app/templates")
templates.env.filters["from_json"] = json.loads

MAX_CONDITIONS = 5


# ── Helpers ───────────────────────────────────────────────────────────────────

def _get_alert_or_404(alert_id: int, db: Session) -> Alert:
    alert = db.get(Alert, alert_id)
    if not alert:
        raise HTTPException(status_code=404)
    return alert


def _check_alert_owner(alert: Alert, user: User) -> None:
    if not user.is_admin and alert.created_by_id != user.id:
        raise HTTPException(status_code=403)


def _build_conditions(col_ids: list[str], operators: list[str], values: list[str],
                      logics: list[str], value_types: list[str] | None = None,
                      value_col_ids: list[str] | None = None) -> list[dict]:
    conditions = []
    for i, col_id in enumerate(col_ids):
        if not col_id:
            continue
        vtype = (value_types[i] if value_types and i < len(value_types) else "") or "literal"
        cond: dict = {
            "col_id": int(col_id),
            "operator": operators[i] if i < len(operators) else "eq",
            "value": values[i] if i < len(values) else "",
            "logic": logics[i] if i < len(logics) else "AND",
            "value_type": vtype,
        }
        if vtype == "column":
            vcol_str = (value_col_ids[i] if value_col_ids and i < len(value_col_ids) else "") or ""
            try:
                cond["value_col_id"] = int(vcol_str)
                cond["value"] = ""
            except (ValueError, TypeError):
                cond["value_type"] = "literal"  # référence invalide → retour littéral
        conditions.append(cond)
    return conditions[:MAX_CONDITIONS]


def _get_table_users(table: DataTable, db: Session) -> list[dict]:
    """Retourne tous les utilisateurs ayant accès à la table (pour le picker de destinataires)."""
    seen: set[int] = set()
    result: list[dict] = []

    owner = db.get(User, table.created_by_id)
    if owner:
        seen.add(owner.id)
        result.append({"id": owner.id, "label": f"{owner.username} — {owner.email}", "level": "propriétaire"})

    for co in db.query(TableOwner).filter_by(table_id=table.id).all():
        if co.user_id not in seen:
            u = db.get(User, co.user_id)
            if u:
                seen.add(u.id)
                result.append({"id": u.id, "label": f"{u.username} — {u.email}", "level": "co-propriétaire"})

    for perm in db.query(TablePermission).filter_by(table_id=table.id).all():
        if perm.user_id not in seen:
            u = db.get(User, perm.user_id)
            if u:
                seen.add(u.id)
                level_label = "Lecture / Écriture" if perm.level.value == "write" else "Lecture"
                result.append({"id": u.id, "label": f"{u.username} — {u.email}", "level": level_label})

    return result


def _panel_context(table: DataTable, user: User, db: Session) -> dict:
    # Alertes visibles :
    #   - globales (tous)
    #   - privées du créateur uniquement
    #   - personnalisées : créateur OU destinataire explicite
    alerts = (
        db.query(Alert)
        .filter(
            Alert.table_id == table.id,
            or_(
                Alert.scope == AlertScope.GLOBAL,
                Alert.created_by_id == user.id,
                and_(
                    Alert.scope == AlertScope.CUSTOM,
                    exists().where(
                        and_(
                            AlertRecipient.alert_id == Alert.id,
                            AlertRecipient.user_id == user.id,
                        )
                    ),
                ),
            ),
        )
        .order_by(Alert.created_at.desc())
        .all()
    )
    columns_json = json.dumps([
        {"id": col.id, "name": col.name, "type": col.col_type.value}
        for col in table.columns
    ])
    table_users_json = json.dumps(_get_table_users(table, db))
    return {
        "table": table,
        "user": user,
        "alerts": alerts,
        "columns": table.columns,
        "columns_json": columns_json,
        "table_users_json": table_users_json,
        "is_owner": is_table_owner(table, user, db),
    }


# ── Panel & form ──────────────────────────────────────────────────────────────

@router.get("/tables/{table_id}/alerts/panel", response_class=HTMLResponse)
def alerts_panel(
    request: Request,
    table: DataTable = Depends(get_table_or_404),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    if not can_access_table(table, user, db):
        raise HTTPException(status_code=403)
    ctx = _panel_context(table, user, db)
    return templates.TemplateResponse(request, "alerts/panel.html", ctx)


@router.post("/tables/{table_id}/alerts", response_class=HTMLResponse)
async def create_alert(
    request: Request,
    table_id: int,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    table = db.get(DataTable, table_id)
    if not table:
        raise HTTPException(status_code=404)
    if not can_access_table(table, user, db):
        raise HTTPException(status_code=403)

    form = await request.form()
    name = str(form.get("name", "")).strip()
    scope_val = str(form.get("scope", "private"))
    col_ids = form.getlist("col_ids")
    operators = form.getlist("operators")
    values = form.getlist("values")
    logics = form.getlist("logics")
    value_types = form.getlist("value_types")
    value_col_ids = form.getlist("value_col_ids")
    recipient_ids_raw = form.getlist("recipient_user_ids")

    # Scope global/custom réservé aux propriétaires/admins
    if scope_val in ("global", "custom") and not (user.is_admin or is_table_owner(table, user, db)):
        scope_val = "private"

    # Validation des destinataires pour le scope custom
    recipient_ids: list[int] = []
    if scope_val == "custom":
        valid_user_ids = {u["id"] for u in _get_table_users(table, db)}
        recipient_ids = [int(x) for x in recipient_ids_raw if x.strip().isdigit() and int(x) in valid_user_ids]

    # Validation
    errors: list[str] = []
    if not name:
        errors.append("Le nom de l'alerte est obligatoire.")
    conditions = _build_conditions(col_ids, operators, values, logics, value_types, value_col_ids)
    if not conditions:
        errors.append("Au moins une condition est requise.")
    if scope_val == "custom" and not recipient_ids:
        errors.append("Au moins un destinataire est requis pour une alerte personnalisée.")

    if errors:
        ctx = _panel_context(table, user, db)
        ctx["form_errors"] = errors
        ctx["form_open"] = True
        return templates.TemplateResponse(request, "alerts/panel.html", ctx)

    # Actions
    notify_inapp = form.get("notify_inapp") == "1"
    notify_email = form.get("notify_email") == "1"
    hl_enabled = form.get("highlight_enabled") == "1"
    hl_mode = str(form.get("highlight_mode", "row"))
    hl_color = str(form.get("highlight_color", "#fbbf24"))
    if not re.match(r'^#[0-9a-fA-F]{6}$', hl_color):
        hl_color = "#fbbf24"
    actions = {
        "notify_inapp": notify_inapp,
        "notify_email": notify_email,
        "highlight": {
            "enabled": hl_enabled,
            "mode": hl_mode if hl_mode in ("row", "cells") else "row",
            "color": hl_color,
        },
    }

    alert = Alert(
        table_id=table_id,
        created_by_id=user.id,
        name=name,
        scope=AlertScope(scope_val),
        conditions=json.dumps(conditions),
        actions=json.dumps(actions),
        is_active=True,
    )
    db.add(alert)
    db.flush()  # obtenir alert.id avant d'ajouter les destinataires

    if scope_val == "custom":
        for uid in recipient_ids:
            db.add(AlertRecipient(alert_id=alert.id, user_id=uid))

    db.commit()

    # Réévaluation initiale sur les lignes existantes : couleurs uniquement, sans notifications
    rows = db.query(TableRow).filter(
        TableRow.table_id == table_id,
        TableRow.deleted_at == None,
    ).all()
    for row in rows:
        evaluate_alerts_for_row(db, row, table, silent=True)
    if rows:
        db.commit()

    ctx = _panel_context(table, user, db)
    ctx["flash_success"] = f"Alerte « {name} » créée."
    response = templates.TemplateResponse(request, "alerts/panel.html", ctx)
    response.headers["HX-Trigger"] = "refreshTable"
    return response


@router.get("/tables/{table_id}/alerts/{alert_id}/edit-form", response_class=HTMLResponse)
def edit_alert_form(
    request: Request,
    table_id: int,
    alert_id: int,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    alert = _get_alert_or_404(alert_id, db)
    _check_alert_owner(alert, user)
    table = db.get(DataTable, table_id)
    if not table:
        raise HTTPException(status_code=404)
    columns_json = json.dumps([
        {"id": col.id, "name": col.name, "type": col.col_type.value}
        for col in table.columns
    ])
    alert_recipients_json = json.dumps([r.user_id for r in alert.recipients])
    return templates.TemplateResponse(request, "alerts/edit_form.html", {
        "table": table,
        "user": user,
        "alert": alert,
        "columns": table.columns,
        "columns_json": columns_json,
        "table_users_json": json.dumps(_get_table_users(table, db)),
        "alert_recipients_json": alert_recipients_json,
        "is_owner": is_table_owner(table, user, db),
        "conditions_json": alert.conditions,
        "actions_json": alert.actions or "{}",
    })


@router.post("/tables/{table_id}/alerts/{alert_id}/edit", response_class=HTMLResponse)
async def update_alert(
    request: Request,
    table_id: int,
    alert_id: int,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    alert = _get_alert_or_404(alert_id, db)
    _check_alert_owner(alert, user)
    table = db.get(DataTable, table_id)
    if not table:
        raise HTTPException(status_code=404)

    form = await request.form()
    name = str(form.get("name", "")).strip()
    scope_val = str(form.get("scope", "private"))
    col_ids = form.getlist("col_ids")
    operators = form.getlist("operators")
    values = form.getlist("values")
    logics = form.getlist("logics")
    value_types = form.getlist("value_types")
    value_col_ids = form.getlist("value_col_ids")
    recipient_ids_raw = form.getlist("recipient_user_ids")

    # Scope global/custom réservé aux propriétaires/admins
    if scope_val in ("global", "custom") and not (user.is_admin or is_table_owner(table, user, db)):
        scope_val = "private"

    # Validation des destinataires pour le scope custom
    recipient_ids: list[int] = []
    if scope_val == "custom":
        valid_user_ids = {u["id"] for u in _get_table_users(table, db)}
        recipient_ids = [int(x) for x in recipient_ids_raw if x.strip().isdigit() and int(x) in valid_user_ids]

    errors: list[str] = []
    if not name:
        errors.append("Le nom de l'alerte est obligatoire.")
    conditions = _build_conditions(col_ids, operators, values, logics, value_types, value_col_ids)
    if not conditions:
        errors.append("Au moins une condition est requise.")
    if scope_val == "custom" and not recipient_ids:
        errors.append("Au moins un destinataire est requis pour une alerte personnalisée.")

    if errors:
        columns_json = json.dumps([
            {"id": col.id, "name": col.name, "type": col.col_type.value}
            for col in table.columns
        ])
        return templates.TemplateResponse(request, "alerts/edit_form.html", {
            "table": table,
            "user": user,
            "alert": alert,
            "columns": table.columns,
            "columns_json": columns_json,
            "table_users_json": json.dumps(_get_table_users(table, db)),
            "alert_recipients_json": json.dumps([r.user_id for r in alert.recipients]),
            "is_owner": is_table_owner(table, user, db),
            "conditions_json": json.dumps(conditions) if conditions else alert.conditions,
            "actions_json": alert.actions or "{}",
            "form_errors": errors,
        })

    notify_inapp = form.get("notify_inapp") == "1"
    notify_email = form.get("notify_email") == "1"
    hl_enabled = form.get("highlight_enabled") == "1"
    hl_mode = str(form.get("highlight_mode", "row"))
    hl_color = str(form.get("highlight_color", "#fbbf24"))
    if not re.match(r'^#[0-9a-fA-F]{6}$', hl_color):
        hl_color = "#fbbf24"
    actions = {
        "notify_inapp": notify_inapp,
        "notify_email": notify_email,
        "highlight": {
            "enabled": hl_enabled,
            "mode": hl_mode if hl_mode in ("row", "cells") else "row",
            "color": hl_color,
        },
    }

    alert.name = name
    alert.scope = AlertScope(scope_val)
    alert.conditions = json.dumps(conditions)
    alert.actions = json.dumps(actions)

    # Mise à jour des destinataires : on remplace entièrement la liste
    db.query(AlertRecipient).filter_by(alert_id=alert.id).delete()
    if scope_val == "custom":
        for uid in recipient_ids:
            db.add(AlertRecipient(alert_id=alert.id, user_id=uid))

    db.commit()

    # Réévaluation initiale sur les lignes existantes : couleurs uniquement, sans notifications
    rows = db.query(TableRow).filter(
        TableRow.table_id == table_id, TableRow.deleted_at == None
    ).all()
    for row in rows:
        evaluate_alerts_for_row(db, row, table, silent=True)
    if rows:
        db.commit()

    ctx = _panel_context(table, user, db)
    ctx["flash_success"] = f"Alerte « {name} » mise à jour."
    response = templates.TemplateResponse(request, "alerts/panel.html", ctx)
    response.headers["HX-Trigger"] = "refreshTable"
    return response


@router.post("/tables/{table_id}/alerts/{alert_id}/toggle", response_class=HTMLResponse)
def toggle_alert(
    request: Request,
    table_id: int,
    alert_id: int,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    alert = _get_alert_or_404(alert_id, db)
    _check_alert_owner(alert, user)
    alert.is_active = not alert.is_active
    db.commit()

    # Réévaluation : couleurs uniquement, sans notifications (toggle = action admin, pas événement data)
    table = db.get(DataTable, table_id)
    if table:
        rows = db.query(TableRow).filter(
            TableRow.table_id == table_id, TableRow.deleted_at == None
        ).all()
        for row in rows:
            evaluate_alerts_for_row(db, row, table, silent=True)
        if rows:
            db.commit()

    ctx = _panel_context(db.get(DataTable, table_id), user, db)
    response = templates.TemplateResponse(request, "alerts/panel.html", ctx)
    response.headers["HX-Trigger"] = "refreshTable"
    return response


@router.post("/tables/{table_id}/alerts/{alert_id}/delete", response_class=HTMLResponse)
def delete_alert(
    request: Request,
    table_id: int,
    alert_id: int,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    alert = _get_alert_or_404(alert_id, db)
    _check_alert_owner(alert, user)
    db.query(AlertNotification).filter(AlertNotification.alert_id == alert_id).update(
        {AlertNotification.alert_id: None}
    )
    db.delete(alert)
    db.commit()

    table = db.get(DataTable, table_id)
    ctx = _panel_context(table, user, db)
    response = templates.TemplateResponse(request, "alerts/panel.html", ctx)
    response.headers["HX-Trigger"] = "refreshTable"
    return response


# ── Notifications ─────────────────────────────────────────────────────────────

@router.get("/notifications", response_class=HTMLResponse)
def notifications_page(
    request: Request,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    notifs = (
        db.query(AlertNotification)
        .filter_by(user_id=user.id)
        .order_by(AlertNotification.created_at.desc())
        .limit(200)
        .all()
    )
    unread_count = sum(1 for n in notifs if not n.is_read)
    return templates.TemplateResponse(
        request, "notifications/index.html",
        {"user": user, "notifs": notifs, "unread_count": unread_count},
    )


@router.post("/notifications/{notif_id}/read")
def mark_read(
    notif_id: int,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    notif = db.get(AlertNotification, notif_id)
    if not notif or notif.user_id != user.id:
        raise HTTPException(status_code=404)
    notif.is_read = True
    db.commit()
    return RedirectResponse(url="/notifications", status_code=status.HTTP_303_SEE_OTHER)


@router.post("/notifications/read-all")
def mark_all_read(
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    db.query(AlertNotification).filter_by(user_id=user.id, is_read=False).update(
        {AlertNotification.is_read: True}
    )
    db.commit()
    return RedirectResponse(url="/notifications", status_code=status.HTTP_303_SEE_OTHER)


@router.get("/api/notifications/count", response_class=HTMLResponse)
def notifications_count(
    request: Request,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    count = db.query(AlertNotification).filter_by(user_id=user.id, is_read=False).count()
    return templates.TemplateResponse(
        request, "partials/notif_badge.html", {"count": count}
    )
