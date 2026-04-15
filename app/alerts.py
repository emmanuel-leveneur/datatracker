"""
Engine d'évaluation des alertes.
evaluate_alerts_for_row() est appelé après chaque modification de ligne,
avant db.commit().
"""
import json
from datetime import date, datetime, timedelta
from sqlalchemy.orm import Session

from app.models import (
    Alert, AlertNotification, AlertRecipient, AlertScope, AlertState,
    ColumnType, DataTable, TableColumn, TableOwner, TablePermission, TableRow, User,
)

OPERATOR_LABELS: dict[str, str] = {
    "eq": "=", "neq": "≠", "gt": ">", "lt": "<", "gte": "≥", "lte": "≤",
    "contains": "contient", "not_contains": "ne contient pas",
    "before": "avant", "after": "après",
    "today": "est aujourd'hui", "yesterday": "était hier", "tomorrow": "sera demain",
    "before_today": "avant aujourd'hui", "after_today": "après aujourd'hui",
    "today_or_before": "aujourd'hui ou avant", "today_or_after": "aujourd'hui ou après",
    "in": "est dans", "not_in": "n'est pas dans",
    "is_true": "est vrai", "is_false": "est faux",
}

# Opérateurs qui n'ont pas de valeur cible (comparaison dynamique)
NO_VALUE_OPERATORS = {
    "today", "yesterday", "tomorrow", "is_true", "is_false",
    "before_today", "after_today", "today_or_before", "today_or_after",
}


def _evaluate_condition(condition: dict, cells: dict[int, str], columns: dict[int, TableColumn]) -> bool:
    col_id = condition.get("col_id")
    operator = condition.get("operator", "eq")

    if col_id not in columns:
        return False

    raw = cells.get(col_id, "")
    col_type = columns[col_id].col_type

    # Résolution de la valeur cible : colonne ou valeur littérale
    if condition.get("value_type") == "column":
        value_col_id = condition.get("value_col_id")
        if not value_col_id or value_col_id not in columns:
            return False  # colonne référencée supprimée → fallback sécurisé
        target = cells.get(value_col_id, "")
    else:
        target = str(condition.get("value", ""))

    if col_type in (ColumnType.INTEGER, ColumnType.FLOAT):
        try:
            raw_num = float(raw) if raw else None
            target_num = float(target) if target else None
        except (ValueError, TypeError):
            return False
        if raw_num is None:
            return False
        if operator == "eq":  return raw_num == target_num
        if operator == "neq": return raw_num != target_num
        if operator == "gt":  return target_num is not None and raw_num > target_num
        if operator == "lt":  return target_num is not None and raw_num < target_num
        if operator == "gte": return target_num is not None and raw_num >= target_num
        if operator == "lte": return target_num is not None and raw_num <= target_num

    elif col_type == ColumnType.BOOLEAN:
        raw_bool = raw.lower() in ("true", "1", "yes", "oui")
        if operator == "is_true":  return raw_bool
        if operator == "is_false": return not raw_bool

    elif col_type == ColumnType.DATE:
        try:
            raw_date = date.fromisoformat(raw) if raw else None
        except ValueError:
            raw_date = None
        today = date.today()
        if operator == "today":          return raw_date == today
        if operator == "yesterday":      return raw_date == today - timedelta(days=1)
        if operator == "tomorrow":       return raw_date == today + timedelta(days=1)
        if operator == "before_today":   return raw_date < today
        if operator == "after_today":    return raw_date > today
        if operator == "today_or_before": return raw_date <= today
        if operator == "today_or_after":  return raw_date >= today
        if raw_date is None:
            return False
        try:
            target_date = date.fromisoformat(target)
        except ValueError:
            return False
        if operator == "eq":     return raw_date == target_date
        if operator == "before": return raw_date < target_date
        if operator == "after":  return raw_date > target_date

    elif col_type == ColumnType.DATETIME:
        try:
            raw_dt = datetime.fromisoformat(raw) if raw else None
        except ValueError:
            raw_dt = None
        today = date.today()
        # Opérateurs relatifs : comparaison sur la partie date uniquement
        raw_d = raw_dt.date() if raw_dt else None
        if operator == "today":          return raw_d == today
        if operator == "yesterday":      return raw_d == today - timedelta(days=1)
        if operator == "tomorrow":       return raw_d == today + timedelta(days=1)
        if operator == "before_today":   return raw_d is not None and raw_d < today
        if operator == "after_today":    return raw_d is not None and raw_d > today
        if operator == "today_or_before": return raw_d is not None and raw_d <= today
        if operator == "today_or_after":  return raw_d is not None and raw_d >= today
        if raw_dt is None:
            return False
        try:
            target_dt = datetime.fromisoformat(target)
        except ValueError:
            return False
        if operator == "eq":     return raw_dt == target_dt
        if operator == "before": return raw_dt < target_dt
        if operator == "after":  return raw_dt > target_dt

    elif col_type == ColumnType.SELECT:
        if operator == "eq":      return raw == target
        if operator == "neq":     return raw != target
        if operator == "in":
            return raw in [v.strip() for v in target.split(",")]
        if operator == "not_in":
            return raw not in [v.strip() for v in target.split(",")]

    else:  # TEXT, EMAIL
        if operator == "eq":          return raw == target
        if operator == "neq":         return raw != target
        if operator == "contains":    return target.lower() in raw.lower()
        if operator == "not_contains": return target.lower() not in raw.lower()

    return False


def _evaluate_alert(alert: Alert, cells: dict[int, str], columns: dict[int, TableColumn]) -> bool:
    try:
        conditions = json.loads(alert.conditions)
    except (json.JSONDecodeError, TypeError):
        return False

    if not conditions:
        return False

    result: bool | None = None
    for cond in conditions:
        logic = cond.get("logic", "AND")
        cond_result = _evaluate_condition(cond, cells, columns)
        if result is None:
            result = cond_result
        elif logic == "OR":
            result = result or cond_result
        else:
            result = result and cond_result

    return bool(result)


def _get_user_ids_to_notify(alert: Alert, table_id: int, db: Session) -> list[int]:
    if alert.scope == AlertScope.PRIVATE:
        return [alert.created_by_id]

    if alert.scope == AlertScope.GLOBAL:
        # Tous les utilisateurs ayant accès à la table
        user_ids: set[int] = {alert.created_by_id}
        for o in db.query(TableOwner).filter_by(table_id=table_id).all():
            user_ids.add(o.user_id)
        for p in db.query(TablePermission).filter_by(table_id=table_id).all():
            user_ids.add(p.user_id)
        return list(user_ids)

    # CUSTOM : destinataires explicites ∩ utilisateurs ayant encore accès à la table
    recipient_ids = {r.user_id for r in db.query(AlertRecipient).filter_by(alert_id=alert.id).all()}
    if not recipient_ids:
        return []
    # Construire l'ensemble des utilisateurs avec accès courant
    has_access: set[int] = set()
    table_obj = db.query(DataTable).filter_by(id=table_id).first()
    if table_obj:
        has_access.add(table_obj.created_by_id)
    for o in db.query(TableOwner).filter_by(table_id=table_id).all():
        has_access.add(o.user_id)
    for p in db.query(TablePermission).filter_by(table_id=table_id).all():
        has_access.add(p.user_id)
    # Les admins gardent l'accès même sans entrée dans les tables de permission
    from sqlalchemy import or_ as sa_or
    admin_ids = {
        u.id for u in db.query(User).filter(
            User.id.in_(recipient_ids), User.is_admin == True
        ).all()
    }
    return list(recipient_ids & (has_access | admin_ids))


def _build_message(alert_name: str, conditions: list[dict], col_names: dict[int, str],
                   table_name: str, row_id: int) -> str:
    parts: list[str] = []
    for i, c in enumerate(conditions):
        col_name = col_names.get(c.get("col_id"), "?")
        op_label = OPERATOR_LABELS.get(c.get("operator", "eq"), c.get("operator", "?"))
        if i > 0:
            parts.append(c.get("logic", "ET"))
        if c.get("value_type") == "column":
            target_name = col_names.get(c.get("value_col_id"), "?")
            parts.append(f"{col_name} {op_label} {target_name}")
        elif c.get("value"):
            parts.append(f"{col_name} {op_label} {c['value']}")
        else:
            parts.append(f"{col_name} {op_label}")
    cond_str = " ".join(parts) if parts else "?"
    return f"Alerte « {alert_name} » : {cond_str} — ligne #{row_id} dans {table_name}"


def evaluate_alerts_for_row(db: Session, row: TableRow, table: DataTable) -> None:
    """
    Évalue toutes les alertes actives de la table sur la ligne donnée.
    Crée des notifications uniquement lors du passage False → True (anti-spam).
    À appeler après db.flush() (row.id et cell_values disponibles) et avant db.commit().
    """
    alerts = db.query(Alert).filter_by(table_id=table.id, is_active=True).all()
    if not alerts:
        return

    cells = {cv.column_id: cv.value for cv in row.cell_values}
    columns = {col.id: col for col in table.columns}
    col_names = {col.id: col.name for col in table.columns}

    for alert in alerts:
        is_triggered_now = _evaluate_alert(alert, cells, columns)

        state = db.query(AlertState).filter_by(alert_id=alert.id, row_id=row.id).first()
        was_triggered = state.is_triggered if state else False

        if state is None:
            state = AlertState(alert_id=alert.id, row_id=row.id, is_triggered=is_triggered_now)
            db.add(state)
        else:
            state.is_triggered = is_triggered_now

        if is_triggered_now:
            state.last_triggered_at = datetime.utcnow()

        # Notifier uniquement si passage False → True
        if is_triggered_now and not was_triggered:
            try:
                actions = json.loads(alert.actions or "{}")
            except Exception:
                actions = {}
            try:
                conditions = json.loads(alert.conditions)
            except Exception:
                conditions = []
            message = _build_message(alert.name, conditions, col_names, table.name, row.id)
            user_ids = _get_user_ids_to_notify(alert, table.id, db)

            if actions.get("notify_inapp", True):
                for uid in user_ids:
                    db.add(AlertNotification(
                        user_id=uid,
                        alert_id=alert.id,
                        alert_name=alert.name,
                        row_id=row.id,
                        table_id=table.id,
                        table_name=table.name,
                        message=message,
                    ))

            if actions.get("notify_email", False):
                from app.email_utils import send_alert_email
                users = db.query(User).filter(User.id.in_(user_ids), User.email != "").all()
                emails = [u.email for u in users if u.email]
                if emails:
                    trigger_col_ids = {c.get("col_id") for c in conditions}
                    send_alert_email(
                        to_addresses=emails,
                        alert_name=alert.name,
                        table_name=table.name,
                        table_id=table.id,
                        row_id=row.id,
                        message=message,
                        columns=list(table.columns),
                        cells=cells,
                        trigger_col_ids=trigger_col_ids,
                    )


def get_alert_row_data(db: Session, table_id: int, user_id: int | None = None) -> dict[int, dict]:
    """
    Retourne un dict {row_id: {"row_style": str, "cell_styles": {col_id: str}}}
    pour toutes les lignes actuellement en alerte sur une table.
    Si plusieurs alertes s'appliquent à la même ligne, la première couleur trouvée gagne.
    """
    rows: dict[int, dict] = {}

    pairs = (
        db.query(AlertState, Alert)
        .join(Alert, AlertState.alert_id == Alert.id)
        .filter(
            Alert.table_id == table_id,
            Alert.is_active == True,
            AlertState.is_triggered == True,
        )
        .all()
    )

    for state, alert in pairs:
        row_id = state.row_id
        if row_id not in rows:
            rows[row_id] = {"row_style": "", "cell_styles": {}, "has_notification": False}

        try:
            actions = json.loads(alert.actions or "{}")
        except Exception:
            actions = {}

        hl = actions.get("highlight", {})
        if not hl.get("enabled"):
            continue

        # Portée : privée → uniquement le créateur ; globale → tout le monde
        # personnalisée → créateur + destinataires explicites
        if alert.scope == AlertScope.PRIVATE and user_id is not None and alert.created_by_id != user_id:
            continue
        if alert.scope == AlertScope.CUSTOM and user_id is not None:
            recipient_ids = {r.user_id for r in db.query(AlertRecipient).filter_by(alert_id=alert.id).all()}
            if user_id not in recipient_ids and alert.created_by_id != user_id:
                continue

        color = hl.get("color", "#fbbf24")
        mode = hl.get("mode", "row")

        if mode == "row":
            if not rows[row_id]["row_style"]:
                rows[row_id]["row_style"] = f"background-color:{color}"
        elif mode == "cells":
            try:
                conditions = json.loads(alert.conditions or "[]")
            except Exception:
                conditions = []
            for cond in conditions:
                col_id = cond.get("col_id")
                if col_id and col_id not in rows[row_id]["cell_styles"]:
                    rows[row_id]["cell_styles"][col_id] = f"background-color:{color}"

    # Badge cloche : visible uniquement si l'utilisateur a une notification non lue sur cette ligne
    # On remonte aussi les noms des alertes responsables pour la tooltip.
    if user_id is not None and rows:
        unread_notifs = db.query(AlertNotification.row_id, AlertNotification.alert_name).filter(
            AlertNotification.user_id == user_id,
            AlertNotification.table_id == table_id,
            AlertNotification.is_read == False,
            AlertNotification.row_id != None,
        ).all()
        # Grouper les noms d'alertes par row_id (dédoublonnés)
        notif_names: dict[int, list[str]] = {}
        for row_id, alert_name in unread_notifs:
            if row_id not in notif_names:
                notif_names[row_id] = []
            if alert_name and alert_name not in notif_names[row_id]:
                notif_names[row_id].append(alert_name)
        for row_id in rows:
            names = notif_names.get(row_id, [])
            rows[row_id]["has_notification"] = bool(names)
            rows[row_id]["notification_names"] = names

    return rows


def get_alerted_row_ids(db: Session, table_id: int) -> set[int]:
    """Wrapper conservé pour compatibilité."""
    return set(get_alert_row_data(db, table_id).keys())
