"""Tests pour la fonctionnalité d'alertes."""
import json
import pytest
from tests.helpers import make_table
from app.models import Alert, AlertNotification, AlertScope, AlertState, CellValue, ColumnType, TableRow


# ── Fixtures ─────────────────────────────────────────────────────────────────

@pytest.fixture
def table_with_cols(db, admin_user):
    table, cols = make_table(db, admin_user, columns=[
        ("Montant", ColumnType.FLOAT),
        ("Statut", ColumnType.SELECT),
        ("Actif", ColumnType.BOOLEAN),
        ("Libellé", ColumnType.TEXT),
    ])
    return table, cols


def _make_row(db, table, admin_user, values: dict[int, str]) -> TableRow:
    row = TableRow(table_id=table.id, created_by_id=admin_user.id)
    db.add(row)
    db.flush()
    for col_id, val in values.items():
        db.add(CellValue(row_id=row.id, column_id=col_id, value=val))
    db.flush()
    return row


def _make_alert(db, table, admin_user, conditions, scope="private", name="Test Alert"):
    alert = Alert(
        table_id=table.id,
        created_by_id=admin_user.id,
        name=name,
        scope=AlertScope.PRIVATE if scope == "private" else AlertScope.GLOBAL,
        conditions=json.dumps(conditions),
        is_active=True,
    )
    db.add(alert)
    db.commit()
    return alert


# ── Engine d'évaluation ───────────────────────────────────────────────────────

class TestEvaluateCondition:
    def test_float_gt(self, db, admin_user, table_with_cols):
        from app.alerts import _evaluate_condition
        table, cols = table_with_cols
        montant_col = cols[0]
        columns = {col.id: col for col in cols}
        cells = {montant_col.id: "15000"}

        assert _evaluate_condition({"col_id": montant_col.id, "operator": "gt", "value": "10000"}, cells, columns)
        assert not _evaluate_condition({"col_id": montant_col.id, "operator": "gt", "value": "20000"}, cells, columns)

    def test_float_lte(self, db, admin_user, table_with_cols):
        from app.alerts import _evaluate_condition
        table, cols = table_with_cols
        col = cols[0]
        columns = {c.id: c for c in cols}
        cells = {col.id: "100"}
        assert _evaluate_condition({"col_id": col.id, "operator": "lte", "value": "100"}, cells, columns)
        assert not _evaluate_condition({"col_id": col.id, "operator": "lte", "value": "99"}, cells, columns)

    def test_text_contains(self, db, admin_user, table_with_cols):
        from app.alerts import _evaluate_condition
        table, cols = table_with_cols
        col = cols[3]  # Libellé
        columns = {c.id: c for c in cols}
        cells = {col.id: "Facture urgent 2024"}
        assert _evaluate_condition({"col_id": col.id, "operator": "contains", "value": "urgent"}, cells, columns)
        assert not _evaluate_condition({"col_id": col.id, "operator": "contains", "value": "remboursement"}, cells, columns)

    def test_boolean_is_true(self, db, admin_user, table_with_cols):
        from app.alerts import _evaluate_condition
        table, cols = table_with_cols
        col = cols[2]  # Actif
        columns = {c.id: c for c in cols}
        assert _evaluate_condition({"col_id": col.id, "operator": "is_true"}, {col.id: "true"}, columns)
        assert not _evaluate_condition({"col_id": col.id, "operator": "is_true"}, {col.id: "false"}, columns)
        assert _evaluate_condition({"col_id": col.id, "operator": "is_false"}, {col.id: "false"}, columns)

    def test_select_in(self, db, admin_user, table_with_cols):
        from app.alerts import _evaluate_condition
        table, cols = table_with_cols
        col = cols[1]  # Statut
        columns = {c.id: c for c in cols}
        cells = {col.id: "urgent"}
        assert _evaluate_condition({"col_id": col.id, "operator": "in", "value": "urgent, critique"}, cells, columns)
        assert not _evaluate_condition({"col_id": col.id, "operator": "in", "value": "normal, faible"}, cells, columns)

    def test_unknown_column_returns_false(self, db, admin_user, table_with_cols):
        from app.alerts import _evaluate_condition
        table, cols = table_with_cols
        columns = {c.id: c for c in cols}
        assert not _evaluate_condition({"col_id": 99999, "operator": "eq", "value": "x"}, {}, columns)

    def test_empty_float_returns_false(self, db, admin_user, table_with_cols):
        from app.alerts import _evaluate_condition
        table, cols = table_with_cols
        col = cols[0]
        columns = {c.id: c for c in cols}
        assert not _evaluate_condition({"col_id": col.id, "operator": "gt", "value": "0"}, {col.id: ""}, columns)


class TestEvaluateAlert:
    def test_single_condition_true(self, db, admin_user, table_with_cols):
        from app.alerts import _evaluate_alert
        table, cols = table_with_cols
        col = cols[0]
        columns = {c.id: c for c in cols}
        cells = {col.id: "500"}
        alert = Alert(conditions=json.dumps([{"col_id": col.id, "operator": "gt", "value": "100", "logic": "AND"}]))
        assert _evaluate_alert(alert, cells, columns)

    def test_and_conditions_both_true(self, db, admin_user, table_with_cols):
        from app.alerts import _evaluate_alert
        table, cols = table_with_cols
        montant, statut = cols[0], cols[1]
        columns = {c.id: c for c in cols}
        cells = {montant.id: "15000", statut.id: "urgent"}
        alert = Alert(conditions=json.dumps([
            {"col_id": montant.id, "operator": "gt", "value": "10000", "logic": "AND"},
            {"col_id": statut.id, "operator": "eq", "value": "urgent", "logic": "AND"},
        ]))
        assert _evaluate_alert(alert, cells, columns)

    def test_and_conditions_one_false(self, db, admin_user, table_with_cols):
        from app.alerts import _evaluate_alert
        table, cols = table_with_cols
        montant, statut = cols[0], cols[1]
        columns = {c.id: c for c in cols}
        cells = {montant.id: "500", statut.id: "urgent"}
        alert = Alert(conditions=json.dumps([
            {"col_id": montant.id, "operator": "gt", "value": "10000", "logic": "AND"},
            {"col_id": statut.id, "operator": "eq", "value": "urgent", "logic": "AND"},
        ]))
        assert not _evaluate_alert(alert, cells, columns)

    def test_or_conditions(self, db, admin_user, table_with_cols):
        from app.alerts import _evaluate_alert
        table, cols = table_with_cols
        montant, statut = cols[0], cols[1]
        columns = {c.id: c for c in cols}
        # Montant faux, Statut vrai → OR = True
        cells = {montant.id: "500", statut.id: "urgent"}
        alert = Alert(conditions=json.dumps([
            {"col_id": montant.id, "operator": "gt", "value": "10000", "logic": "AND"},
            {"col_id": statut.id, "operator": "eq", "value": "urgent", "logic": "OR"},
        ]))
        assert _evaluate_alert(alert, cells, columns)

    def test_empty_conditions_returns_false(self, db, admin_user, table_with_cols):
        from app.alerts import _evaluate_alert
        table, cols = table_with_cols
        columns = {c.id: c for c in cols}
        alert = Alert(conditions="[]")
        assert not _evaluate_alert(alert, {}, columns)

    def test_invalid_json_returns_false(self, db, admin_user, table_with_cols):
        from app.alerts import _evaluate_alert
        table, cols = table_with_cols
        columns = {c.id: c for c in cols}
        alert = Alert(conditions="NOT JSON")
        assert not _evaluate_alert(alert, {}, columns)


# ── evaluate_alerts_for_row ────────────────────────────────────────────────────

class TestEvaluateAlertsForRow:
    def test_triggers_notification_on_false_to_true(self, db, admin_user, table_with_cols):
        from app.alerts import evaluate_alerts_for_row
        table, cols = table_with_cols
        col = cols[0]
        alert = _make_alert(db, table, admin_user, [
            {"col_id": col.id, "operator": "gt", "value": "100", "logic": "AND"}
        ])

        row = _make_row(db, table, admin_user, {col.id: "200"})
        evaluate_alerts_for_row(db, row, table)
        db.commit()

        state = db.query(AlertState).filter_by(alert_id=alert.id, row_id=row.id).first()
        assert state is not None
        assert state.is_triggered is True

        notifs = db.query(AlertNotification).filter_by(user_id=admin_user.id, alert_id=alert.id).all()
        assert len(notifs) == 1
        assert str(row.id) in notifs[0].message

    def test_no_duplicate_notification_while_condition_stays_true(self, db, admin_user, table_with_cols):
        from app.alerts import evaluate_alerts_for_row
        table, cols = table_with_cols
        col = cols[0]
        alert = _make_alert(db, table, admin_user, [
            {"col_id": col.id, "operator": "gt", "value": "100", "logic": "AND"}
        ])

        row = _make_row(db, table, admin_user, {col.id: "200"})
        # Premier appel → déclenche
        evaluate_alerts_for_row(db, row, table)
        db.commit()

        # Deuxième appel sans changement → pas de nouvelle notif
        evaluate_alerts_for_row(db, row, table)
        db.commit()

        notifs = db.query(AlertNotification).filter_by(user_id=admin_user.id, alert_id=alert.id).all()
        assert len(notifs) == 1

    def test_re_triggers_after_condition_reset(self, db, admin_user, table_with_cols):
        from app.alerts import evaluate_alerts_for_row
        table, cols = table_with_cols
        col = cols[0]
        alert = _make_alert(db, table, admin_user, [
            {"col_id": col.id, "operator": "gt", "value": "100", "logic": "AND"}
        ])

        row = _make_row(db, table, admin_user, {col.id: "200"})
        evaluate_alerts_for_row(db, row, table)
        db.commit()

        # La condition devient fausse
        cell = next(cv for cv in row.cell_values if cv.column_id == col.id)
        cell.value = "50"
        db.flush()
        evaluate_alerts_for_row(db, row, table)
        db.commit()
        state = db.query(AlertState).filter_by(alert_id=alert.id, row_id=row.id).first()
        assert state.is_triggered is False

        # La condition redevient vraie → nouvelle notif
        cell.value = "300"
        db.flush()
        evaluate_alerts_for_row(db, row, table)
        db.commit()

        notifs = db.query(AlertNotification).filter_by(user_id=admin_user.id, alert_id=alert.id).all()
        assert len(notifs) == 2

    def test_inactive_alert_not_evaluated(self, db, admin_user, table_with_cols):
        from app.alerts import evaluate_alerts_for_row
        table, cols = table_with_cols
        col = cols[0]
        alert = _make_alert(db, table, admin_user, [
            {"col_id": col.id, "operator": "gt", "value": "100", "logic": "AND"}
        ])
        alert.is_active = False
        db.commit()

        row = _make_row(db, table, admin_user, {col.id: "200"})
        evaluate_alerts_for_row(db, row, table)
        db.commit()

        notifs = db.query(AlertNotification).filter_by(user_id=admin_user.id).all()
        assert len(notifs) == 0

    def test_global_alert_notifies_all_users(self, db, admin_user, regular_user, table_with_cols):
        from app.alerts import evaluate_alerts_for_row
        from app.models import TablePermission, PermissionLevel
        table, cols = table_with_cols
        col = cols[0]

        # Donner accès à regular_user
        db.add(TablePermission(table_id=table.id, user_id=regular_user.id, level=PermissionLevel.READ))
        db.commit()

        alert = _make_alert(db, table, admin_user, [
            {"col_id": col.id, "operator": "gt", "value": "100", "logic": "AND"}
        ], scope="global")

        row = _make_row(db, table, admin_user, {col.id: "200"})
        evaluate_alerts_for_row(db, row, table)
        db.commit()

        admin_notifs = db.query(AlertNotification).filter_by(user_id=admin_user.id).all()
        user_notifs = db.query(AlertNotification).filter_by(user_id=regular_user.id).all()
        assert len(admin_notifs) == 1
        assert len(user_notifs) == 1


# ── Routes HTTP ───────────────────────────────────────────────────────────────

class TestAlertRoutes:
    def test_panel_requires_auth(self, client, db, admin_user):
        table, _ = make_table(db, admin_user)
        r = client.get(f"/tables/{table.id}/alerts/panel", follow_redirects=False)
        assert r.status_code in (303, 401, 403)

    def test_panel_returns_200(self, admin_client, db, admin_user):
        table, _ = make_table(db, admin_user)
        r = admin_client.get(f"/tables/{table.id}/alerts/panel")
        assert r.status_code == 200
        assert "Alertes" in r.text

    def test_create_alert_success(self, admin_client, db, admin_user):
        table, cols = make_table(db, admin_user, columns=[("Prix", ColumnType.FLOAT)])
        col = cols[0]
        r = admin_client.post(f"/tables/{table.id}/alerts", data={
            "name": "Prix élevé",
            "scope": "private",
            "col_ids": [str(col.id)],
            "operators": ["gt"],
            "values": ["1000"],
            "logics": ["AND"],
        })
        assert r.status_code == 200
        alert = db.query(Alert).filter_by(table_id=table.id).first()
        assert alert is not None
        assert alert.name == "Prix élevé"
        assert alert.is_active is True

    def test_create_alert_requires_name(self, admin_client, db, admin_user):
        table, cols = make_table(db, admin_user, columns=[("Prix", ColumnType.FLOAT)])
        col = cols[0]
        r = admin_client.post(f"/tables/{table.id}/alerts", data={
            "name": "",
            "scope": "private",
            "col_ids": [str(col.id)],
            "operators": ["gt"],
            "values": ["100"],
            "logics": ["AND"],
        })
        assert r.status_code == 200
        assert "obligatoire" in r.text

    def test_create_alert_requires_condition(self, admin_client, db, admin_user):
        table, _ = make_table(db, admin_user)
        r = admin_client.post(f"/tables/{table.id}/alerts", data={
            "name": "Mon alerte",
            "scope": "private",
        })
        assert r.status_code == 200
        assert "condition" in r.text

    def test_regular_user_cannot_create_global_alert(self, user_client, db, admin_user, regular_user):
        from app.models import TablePermission, PermissionLevel
        table, cols = make_table(db, admin_user, columns=[("Val", ColumnType.INTEGER)])
        col = cols[0]
        db.add(TablePermission(table_id=table.id, user_id=regular_user.id, level=PermissionLevel.WRITE))
        db.commit()
        r = user_client.post(f"/tables/{table.id}/alerts", data={
            "name": "Tentative globale",
            "scope": "global",
            "col_ids": [str(col.id)],
            "operators": ["gt"],
            "values": ["0"],
            "logics": ["AND"],
        })
        assert r.status_code == 200
        alert = db.query(Alert).filter_by(table_id=table.id).first()
        # Doit être downgrade en private
        assert alert is None or alert.scope == AlertScope.PRIVATE

    def test_toggle_alert(self, admin_client, db, admin_user, table_with_cols):
        table, cols = table_with_cols
        alert = _make_alert(db, table, admin_user, [
            {"col_id": cols[0].id, "operator": "gt", "value": "0", "logic": "AND"}
        ])
        assert alert.is_active is True

        r = admin_client.post(f"/tables/{table.id}/alerts/{alert.id}/toggle")
        assert r.status_code in (200, 303)
        db.refresh(alert)
        assert alert.is_active is False

    def test_delete_alert(self, admin_client, db, admin_user, table_with_cols):
        table, cols = table_with_cols
        alert = _make_alert(db, table, admin_user, [
            {"col_id": cols[0].id, "operator": "gt", "value": "0", "logic": "AND"}
        ])
        alert_id = alert.id

        r = admin_client.post(f"/tables/{table.id}/alerts/{alert_id}/delete")
        assert r.status_code in (200, 303)
        db.expire_all()
        assert db.query(Alert).filter_by(id=alert_id).first() is None

    def test_delete_alert_nullifies_notification_alert_id(self, admin_client, db, admin_user, table_with_cols):
        from app.alerts import evaluate_alerts_for_row
        table, cols = table_with_cols
        col = cols[0]
        alert = _make_alert(db, table, admin_user, [
            {"col_id": col.id, "operator": "gt", "value": "0", "logic": "AND"}
        ])
        row = _make_row(db, table, admin_user, {col.id: "1"})
        evaluate_alerts_for_row(db, row, table)
        db.commit()

        notif = db.query(AlertNotification).filter_by(user_id=admin_user.id).first()
        assert notif is not None

        admin_client.post(f"/tables/{table.id}/alerts/{alert.id}/delete")
        db.refresh(notif)
        assert notif.alert_id is None  # notification survit, alert_id nullifié

    def test_non_owner_cannot_delete_alert(self, user_client, db, admin_user, regular_user, table_with_cols):
        from app.models import TablePermission, PermissionLevel
        table, cols = table_with_cols
        db.add(TablePermission(table_id=table.id, user_id=regular_user.id, level=PermissionLevel.READ))
        db.commit()
        alert = _make_alert(db, table, admin_user, [
            {"col_id": cols[0].id, "operator": "gt", "value": "0", "logic": "AND"}
        ])
        r = user_client.post(f"/tables/{table.id}/alerts/{alert.id}/delete")
        assert r.status_code == 403
        assert db.get(Alert, alert.id) is not None


class TestNotificationRoutes:
    def test_notifications_page(self, admin_client):
        r = admin_client.get("/notifications")
        assert r.status_code == 200
        assert "Notifications" in r.text

    def test_notifications_count_endpoint(self, admin_client, db, admin_user):
        db.add(AlertNotification(user_id=admin_user.id, message="test", alert_name="A", table_name="T"))
        db.commit()
        r = admin_client.get("/api/notifications/count")
        assert r.status_code == 200
        assert "1" in r.text

    def test_mark_notification_read(self, admin_client, db, admin_user):
        notif = AlertNotification(user_id=admin_user.id, message="test", alert_name="A", table_name="T")
        db.add(notif)
        db.commit()

        r = admin_client.post(f"/notifications/{notif.id}/read")
        assert r.status_code in (200, 303)
        db.refresh(notif)
        assert notif.is_read is True

    def test_mark_all_read(self, admin_client, db, admin_user):
        for i in range(3):
            db.add(AlertNotification(user_id=admin_user.id, message=f"notif {i}", alert_name="A", table_name="T"))
        db.commit()

        admin_client.post("/notifications/read-all")
        unread = db.query(AlertNotification).filter_by(user_id=admin_user.id, is_read=False).count()
        assert unread == 0

    def test_count_returns_zero_badge_when_none(self, admin_client):
        r = admin_client.get("/api/notifications/count")
        assert r.status_code == 200
        # Aucun badge si 0 notifications
        assert "bg-red-500" not in r.text


# ── get_alerted_row_ids ───────────────────────────────────────────────────────

def test_get_alerted_row_ids(db, admin_user, table_with_cols):
    from app.alerts import evaluate_alerts_for_row, get_alerted_row_ids
    table, cols = table_with_cols
    col = cols[0]
    alert = _make_alert(db, table, admin_user, [
        {"col_id": col.id, "operator": "gt", "value": "100", "logic": "AND"}
    ])

    row_alert = _make_row(db, table, admin_user, {col.id: "500"})
    row_ok = _make_row(db, table, admin_user, {col.id: "10"})

    evaluate_alerts_for_row(db, row_alert, table)
    evaluate_alerts_for_row(db, row_ok, table)
    db.commit()

    alerted = get_alerted_row_ids(db, table.id)
    assert row_alert.id in alerted
    assert row_ok.id not in alerted
