"""
Engine d'évaluation des alertes.
evaluate_alerts_for_row() est appelé après chaque modification de ligne,
avant db.commit().
"""
import json
from datetime import date, datetime, timedelta
from sqlalchemy.orm import Session

from app.models import (
    Alert, AlertNotification, AlertScope, AlertState,
    ColumnType, DataTable, TableColumn, TableOwner, TablePermission, TableRow,
)

OPERATOR_LABELS: dict[str, str] = {
    "eq": "=", "neq": "≠", "gt": ">", "lt": "<", "gte": "≥", "lte": "≤",
    "contains": "contient", "not_contains": "ne contient pas",
    "before": "avant", "after": "après",
    "today": "est aujourd'hui", "yesterday": "était hier", "tomorrow": "sera demain",
    "in": "est dans", "not_in": "n'est pas dans",
    "is_true": "est vrai", "is_false": "est faux",
}

# Opérateurs qui n'ont pas de valeur cible (comparaison dynamique)
NO_VALUE_OPERATORS = {"today", "yesterday", "tomorrow", "is_true", "is_false"}


def _evaluate_condition(condition: dict, cells: dict[int, str], columns: dict[int, TableColumn]) -> bool:
    col_id = condition.get("col_id")
    operator = condition.get("operator", "eq")
    target = str(condition.get("value", ""))

    if col_id not in columns:
        return False

    raw = cells.get(col_id, "")
    col_type = columns[col_id].col_type

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
        if operator == "today":     return raw_date == today
        if operator == "yesterday": return raw_date == today - timedelta(days=1)
        if operator == "tomorrow":  return raw_date == today + timedelta(days=1)
        if raw_date is None:
            return False
        try:
            target_date = date.fromisoformat(target)
        except ValueError:
            return False
        if operator == "eq":     return raw_date == target_date
        if operator == "before": return raw_date < target_date
        if operator == "after":  return raw_date > target_date

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

    # Global : tous les utilisateurs ayant accès à la table
    user_ids: set[int] = {alert.created_by_id}
    for o in db.query(TableOwner).filter_by(table_id=table_id).all():
        user_ids.add(o.user_id)
    for p in db.query(TablePermission).filter_by(table_id=table_id).all():
        user_ids.add(p.user_id)
    return list(user_ids)


def _build_message(alert_name: str, conditions: list[dict], col_names: dict[int, str],
                   table_name: str, row_id: int) -> str:
    parts: list[str] = []
    for i, c in enumerate(conditions):
        col_name = col_names.get(c.get("col_id"), "?")
        op_label = OPERATOR_LABELS.get(c.get("operator", "eq"), c.get("operator", "?"))
        val = c.get("value", "")
        if i > 0:
            parts.append(c.get("logic", "ET"))
        if val:
            parts.append(f"{col_name} {op_label} {val}")
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

        # Notifier uniquement si passage False → True ET notify_inapp activé
        if is_triggered_now and not was_triggered:
            try:
                actions = json.loads(alert.actions or "{}")
            except Exception:
                actions = {}
            if actions.get("notify_inapp", True):
                try:
                    conditions = json.loads(alert.conditions)
                except Exception:
                    conditions = []
                message = _build_message(alert.name, conditions, col_names, table.name, row.id)
                user_ids = _get_user_ids_to_notify(alert, table.id, db)
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


def get_alert_row_data(db: Session, table_id: int) -> dict[int, dict]:
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

        if actions.get("notify_inapp", True):
            rows[row_id]["has_notification"] = True

        hl = actions.get("highlight", {})
        if not hl.get("enabled"):
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

    return rows


def get_alerted_row_ids(db: Session, table_id: int) -> set[int]:
    """Wrapper conservé pour compatibilité."""
    return set(get_alert_row_data(db, table_id).keys())
