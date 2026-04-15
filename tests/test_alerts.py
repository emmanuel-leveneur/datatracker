"""Tests pour la fonctionnalité d'alertes."""
import json
import pytest
from tests.helpers import make_table
from app.models import Alert, AlertNotification, AlertRecipient, AlertScope, AlertState, CellValue, ColumnType, TableRow


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


def _make_alert(db, table, admin_user, conditions, scope="private", name="Test Alert", recipients=None):
    scope_map = {"private": AlertScope.PRIVATE, "global": AlertScope.GLOBAL, "custom": AlertScope.CUSTOM}
    alert = Alert(
        table_id=table.id,
        created_by_id=admin_user.id,
        name=name,
        scope=scope_map.get(scope, AlertScope.PRIVATE),
        conditions=json.dumps(conditions),
        is_active=True,
    )
    db.add(alert)
    db.flush()
    if scope == "custom" and recipients:
        for uid in recipients:
            db.add(AlertRecipient(alert_id=alert.id, user_id=uid))
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

    def test_date_before_today(self, db, admin_user):
        from datetime import date, timedelta
        from app.alerts import _evaluate_condition
        from app.models import TableColumn, ColumnType
        col = TableColumn(id=999, name="Échéance", col_type=ColumnType.DATE)
        columns = {999: col}
        yesterday = (date.today() - timedelta(days=1)).isoformat()
        tomorrow = (date.today() + timedelta(days=1)).isoformat()
        assert _evaluate_condition({"col_id": 999, "operator": "before_today"}, {999: yesterday}, columns)
        assert not _evaluate_condition({"col_id": 999, "operator": "before_today"}, {999: tomorrow}, columns)
        assert not _evaluate_condition({"col_id": 999, "operator": "before_today"}, {999: date.today().isoformat()}, columns)

    def test_date_after_today(self, db, admin_user):
        from datetime import date, timedelta
        from app.alerts import _evaluate_condition
        from app.models import TableColumn, ColumnType
        col = TableColumn(id=998, name="Deadline", col_type=ColumnType.DATE)
        columns = {998: col}
        yesterday = (date.today() - timedelta(days=1)).isoformat()
        tomorrow = (date.today() + timedelta(days=1)).isoformat()
        assert _evaluate_condition({"col_id": 998, "operator": "after_today"}, {998: tomorrow}, columns)
        assert not _evaluate_condition({"col_id": 998, "operator": "after_today"}, {998: yesterday}, columns)
        assert not _evaluate_condition({"col_id": 998, "operator": "after_today"}, {998: date.today().isoformat()}, columns)

    def test_date_today_or_before(self, db, admin_user):
        from datetime import date, timedelta
        from app.alerts import _evaluate_condition
        from app.models import TableColumn, ColumnType
        col = TableColumn(id=997, name="Date", col_type=ColumnType.DATE)
        columns = {997: col}
        yesterday = (date.today() - timedelta(days=1)).isoformat()
        tomorrow = (date.today() + timedelta(days=1)).isoformat()
        today = date.today().isoformat()
        assert _evaluate_condition({"col_id": 997, "operator": "today_or_before"}, {997: yesterday}, columns)
        assert _evaluate_condition({"col_id": 997, "operator": "today_or_before"}, {997: today}, columns)
        assert not _evaluate_condition({"col_id": 997, "operator": "today_or_before"}, {997: tomorrow}, columns)

    def test_date_today_or_after(self, db, admin_user):
        from datetime import date, timedelta
        from app.alerts import _evaluate_condition
        from app.models import TableColumn, ColumnType
        col = TableColumn(id=996, name="Date", col_type=ColumnType.DATE)
        columns = {996: col}
        yesterday = (date.today() - timedelta(days=1)).isoformat()
        tomorrow = (date.today() + timedelta(days=1)).isoformat()
        today = date.today().isoformat()
        assert _evaluate_condition({"col_id": 996, "operator": "today_or_after"}, {996: tomorrow}, columns)
        assert _evaluate_condition({"col_id": 996, "operator": "today_or_after"}, {996: today}, columns)
        assert not _evaluate_condition({"col_id": 996, "operator": "today_or_after"}, {996: yesterday}, columns)


    def test_datetime_before_today(self, db, admin_user):
        from datetime import date, timedelta
        from app.alerts import _evaluate_condition
        from app.models import TableColumn, ColumnType
        col = TableColumn(id=990, name="CreatedAt", col_type=ColumnType.DATETIME)
        columns = {990: col}
        yesterday_dt = (date.today() - timedelta(days=1)).isoformat() + "T10:00"
        tomorrow_dt = (date.today() + timedelta(days=1)).isoformat() + "T10:00"
        assert _evaluate_condition({"col_id": 990, "operator": "before_today"}, {990: yesterday_dt}, columns)
        assert not _evaluate_condition({"col_id": 990, "operator": "before_today"}, {990: tomorrow_dt}, columns)

    def test_datetime_eq(self, db, admin_user):
        from app.alerts import _evaluate_condition
        from app.models import TableColumn, ColumnType
        col = TableColumn(id=991, name="RDV", col_type=ColumnType.DATETIME)
        columns = {991: col}
        assert _evaluate_condition(
            {"col_id": 991, "operator": "eq", "value": "2025-03-15T14:30"},
            {991: "2025-03-15T14:30"}, columns
        )
        assert not _evaluate_condition(
            {"col_id": 991, "operator": "eq", "value": "2025-03-15T14:30"},
            {991: "2025-03-15T09:00"}, columns
        )

    def test_datetime_before_after(self, db, admin_user):
        from app.alerts import _evaluate_condition
        from app.models import TableColumn, ColumnType
        col = TableColumn(id=992, name="Event", col_type=ColumnType.DATETIME)
        columns = {992: col}
        assert _evaluate_condition(
            {"col_id": 992, "operator": "before", "value": "2025-06-01T00:00"},
            {992: "2025-01-01T00:00"}, columns
        )
        assert _evaluate_condition(
            {"col_id": 992, "operator": "after", "value": "2025-01-01T00:00"},
            {992: "2025-06-01T00:00"}, columns
        )

    def test_column_comparison_integer_lt(self, db, admin_user):
        from app.alerts import _evaluate_condition
        from app.models import TableColumn, ColumnType
        col_a = TableColumn(id=980, name="Stock actuel", col_type=ColumnType.INTEGER)
        col_b = TableColumn(id=981, name="Stock minimum", col_type=ColumnType.INTEGER)
        columns = {980: col_a, 981: col_b}
        cond = {"col_id": 980, "operator": "lt", "value_type": "column", "value_col_id": 981}
        assert _evaluate_condition(cond, {980: "5", 981: "10"}, columns)
        assert not _evaluate_condition(cond, {980: "15", 981: "10"}, columns)

    def test_column_comparison_date_after(self, db, admin_user):
        from app.alerts import _evaluate_condition
        from app.models import TableColumn, ColumnType
        col_reelle = TableColumn(id=982, name="Livraison réelle", col_type=ColumnType.DATE)
        col_prevue = TableColumn(id=983, name="Livraison prévue", col_type=ColumnType.DATE)
        columns = {982: col_reelle, 983: col_prevue}
        cond = {"col_id": 982, "operator": "after", "value_type": "column", "value_col_id": 983}
        assert _evaluate_condition(cond, {982: "2026-01-25", 983: "2026-01-20"}, columns)
        assert not _evaluate_condition(cond, {982: "2026-01-18", 983: "2026-01-20"}, columns)

    def test_column_comparison_missing_target_returns_false(self, db, admin_user):
        from app.alerts import _evaluate_condition
        from app.models import TableColumn, ColumnType
        col = TableColumn(id=984, name="Prix vente", col_type=ColumnType.FLOAT)
        columns = {984: col}
        cond = {"col_id": 984, "operator": "gt", "value_type": "column", "value_col_id": 999}
        assert not _evaluate_condition(cond, {984: "100"}, columns)

    def test_column_comparison_float_vente_inferieur_achat(self, db, admin_user):
        from app.alerts import _evaluate_condition
        from app.models import TableColumn, ColumnType
        col_vente = TableColumn(id=985, name="Prix vente", col_type=ColumnType.FLOAT)
        col_achat = TableColumn(id=986, name="Prix achat", col_type=ColumnType.FLOAT)
        columns = {985: col_vente, 986: col_achat}
        cond = {"col_id": 985, "operator": "lt", "value_type": "column", "value_col_id": 986}
        assert _evaluate_condition(cond, {985: "70.0", 986: "80.0"}, columns)
        assert not _evaluate_condition(cond, {985: "100.0", 986: "80.0"}, columns)


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

    def test_private_alert_invisible_to_admin(self, admin_client, db, admin_user, regular_user):
        """Une alerte privée d'un utilisateur ne doit pas apparaître dans le panneau de l'admin.
        Note: admin_client et user_client partagent le même objet client HTTP — on crée
        l'alerte directement via la DB pour éviter le conflit de cookies."""
        table, cols = make_table(db, admin_user, columns=[("Val", ColumnType.INTEGER)])
        col = cols[0]
        # Créer l'alerte privée directement comme regular_user
        alert = Alert(
            table_id=table.id,
            created_by_id=regular_user.id,
            name="Alerte privée utilisateur",
            scope=AlertScope.PRIVATE,
            conditions=json.dumps([{"col_id": col.id, "operator": "gt", "value": "0", "logic": "AND"}]),
            is_active=True,
        )
        db.add(alert)
        db.commit()
        # L'admin ne doit pas la voir dans son panneau
        r = admin_client.get(f"/tables/{table.id}/alerts/panel")
        assert r.status_code == 200
        assert "Alerte privée utilisateur" not in r.text

    def test_private_alert_visible_to_creator(self, user_client, db, admin_user, regular_user):
        """Une alerte privée doit être visible par son créateur."""
        from app.models import TablePermission, PermissionLevel
        table, cols = make_table(db, admin_user, columns=[("Val", ColumnType.INTEGER)])
        col = cols[0]
        db.add(TablePermission(table_id=table.id, user_id=regular_user.id, level=PermissionLevel.WRITE))
        db.commit()
        alert = Alert(
            table_id=table.id,
            created_by_id=regular_user.id,
            name="Mon alerte privée",
            scope=AlertScope.PRIVATE,
            conditions=json.dumps([{"col_id": col.id, "operator": "gt", "value": "0", "logic": "AND"}]),
            is_active=True,
        )
        db.add(alert)
        db.commit()
        r = user_client.get(f"/tables/{table.id}/alerts/panel")
        assert r.status_code == 200
        assert "Mon alerte privée" in r.text

    def test_global_alert_visible_to_regular_user(self, user_client, db, admin_user, regular_user):
        """Une alerte globale doit être visible par tous les utilisateurs ayant accès."""
        from app.models import TablePermission, PermissionLevel
        table, cols = make_table(db, admin_user, columns=[("Val", ColumnType.INTEGER)])
        col = cols[0]
        db.add(TablePermission(table_id=table.id, user_id=regular_user.id, level=PermissionLevel.READ))
        db.commit()
        alert = Alert(
            table_id=table.id,
            created_by_id=admin_user.id,
            name="Alerte globale admin",
            scope=AlertScope.GLOBAL,
            conditions=json.dumps([{"col_id": col.id, "operator": "gt", "value": "0", "logic": "AND"}]),
            is_active=True,
        )
        db.add(alert)
        db.commit()
        r = user_client.get(f"/tables/{table.id}/alerts/panel")
        assert r.status_code == 200
        assert "Alerte globale admin" in r.text

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


# ── Scope personnalisé ────────────────────────────────────────────────────────

class TestCustomScopeAlerts:
    """Tests pour le scope CUSTOM (alerte personnalisée)."""

    def test_custom_alert_notifies_only_recipients(self, db, admin_user, regular_user, table_with_cols):
        """Une alerte personnalisée ne notifie que les destinataires explicites."""
        from app.alerts import evaluate_alerts_for_row
        from app.models import TablePermission, PermissionLevel
        table, cols = table_with_cols
        col = cols[0]

        db.add(TablePermission(table_id=table.id, user_id=regular_user.id, level=PermissionLevel.READ))
        db.commit()

        # Alerte avec regular_user comme seul destinataire (pas admin_user)
        alert = _make_alert(db, table, admin_user, [
            {"col_id": col.id, "operator": "gt", "value": "100", "logic": "AND"}
        ], scope="custom", recipients=[regular_user.id])

        row = _make_row(db, table, admin_user, {col.id: "200"})
        evaluate_alerts_for_row(db, row, table)
        db.commit()

        admin_notifs = db.query(AlertNotification).filter_by(user_id=admin_user.id).all()
        user_notifs = db.query(AlertNotification).filter_by(user_id=regular_user.id).all()
        assert len(admin_notifs) == 0   # admin non destinataire → pas notifié
        assert len(user_notifs) == 1    # regular_user destinataire → notifié

    def test_custom_alert_excludes_user_who_lost_access(self, db, admin_user, regular_user, table_with_cols):
        """Un destinataire ayant perdu son accès à la table n'est plus notifié."""
        from app.alerts import evaluate_alerts_for_row
        from app.models import TablePermission, PermissionLevel
        table, cols = table_with_cols
        col = cols[0]

        perm = TablePermission(table_id=table.id, user_id=regular_user.id, level=PermissionLevel.READ)
        db.add(perm)
        db.commit()

        alert = _make_alert(db, table, admin_user, [
            {"col_id": col.id, "operator": "gt", "value": "100", "logic": "AND"}
        ], scope="custom", recipients=[regular_user.id])

        # Retrait de l'accès AVANT le déclenchement
        db.delete(perm)
        db.commit()

        row = _make_row(db, table, admin_user, {col.id: "200"})
        evaluate_alerts_for_row(db, row, table)
        db.commit()

        user_notifs = db.query(AlertNotification).filter_by(user_id=regular_user.id).all()
        assert len(user_notifs) == 0  # accès perdu → pas notifié

    def test_custom_alert_visible_to_recipient_in_panel(self, user_client, db, admin_user, regular_user):
        """Un destinataire voit l'alerte personnalisée dans le panneau."""
        from app.models import TablePermission, PermissionLevel
        table, cols = make_table(db, admin_user, columns=[("Val", ColumnType.INTEGER)])
        col = cols[0]
        db.add(TablePermission(table_id=table.id, user_id=regular_user.id, level=PermissionLevel.READ))
        db.commit()

        alert = _make_alert(db, table, admin_user, [
            {"col_id": col.id, "operator": "gt", "value": "0", "logic": "AND"}
        ], scope="custom", name="Alerte perso", recipients=[regular_user.id])

        r = user_client.get(f"/tables/{table.id}/alerts/panel")
        assert r.status_code == 200
        assert "Alerte perso" in r.text
        assert "Personnalisée" in r.text

    def test_custom_alert_invisible_to_non_recipient(self, user_client, db, admin_user, regular_user, second_user):
        """Un utilisateur non destinataire ne voit pas l'alerte personnalisée."""
        from app.models import TablePermission, PermissionLevel
        table, cols = make_table(db, admin_user, columns=[("Val", ColumnType.INTEGER)])
        col = cols[0]
        # regular_user a accès mais n'est PAS destinataire
        db.add(TablePermission(table_id=table.id, user_id=regular_user.id, level=PermissionLevel.READ))
        # second_user est destinataire mais user_client correspond à regular_user
        db.add(TablePermission(table_id=table.id, user_id=second_user.id, level=PermissionLevel.READ))
        db.commit()

        _make_alert(db, table, admin_user, [
            {"col_id": col.id, "operator": "gt", "value": "0", "logic": "AND"}
        ], scope="custom", name="Alerte réservée", recipients=[second_user.id])

        r = user_client.get(f"/tables/{table.id}/alerts/panel")
        assert r.status_code == 200
        assert "Alerte réservée" not in r.text

    def test_create_custom_alert_via_route(self, admin_client, db, admin_user, regular_user):
        """La création d'une alerte personnalisée via la route sauvegarde les destinataires."""
        from app.models import TablePermission, PermissionLevel
        table, cols = make_table(db, admin_user, columns=[("Prix", ColumnType.FLOAT)])
        col = cols[0]
        db.add(TablePermission(table_id=table.id, user_id=regular_user.id, level=PermissionLevel.READ))
        db.commit()

        r = admin_client.post(f"/tables/{table.id}/alerts", data={
            "name": "Alerte custom",
            "scope": "custom",
            "col_ids": [str(col.id)],
            "operators": ["gt"],
            "values": ["500"],
            "logics": ["AND"],
            "recipient_user_ids": [str(regular_user.id)],
        })
        assert r.status_code == 200
        alert = db.query(Alert).filter_by(table_id=table.id).first()
        assert alert is not None
        assert alert.scope == AlertScope.CUSTOM
        recipients = db.query(AlertRecipient).filter_by(alert_id=alert.id).all()
        assert len(recipients) == 1
        assert recipients[0].user_id == regular_user.id

    def test_create_custom_alert_requires_recipient(self, admin_client, db, admin_user):
        """La création d'une alerte personnalisée sans destinataire retourne une erreur."""
        table, cols = make_table(db, admin_user, columns=[("Prix", ColumnType.FLOAT)])
        col = cols[0]
        r = admin_client.post(f"/tables/{table.id}/alerts", data={
            "name": "Sans destinataire",
            "scope": "custom",
            "col_ids": [str(col.id)],
            "operators": ["gt"],
            "values": ["0"],
            "logics": ["AND"],
        })
        assert r.status_code == 200
        assert "destinataire" in r.text
        assert db.query(Alert).filter_by(table_id=table.id).first() is None

    def test_regular_user_cannot_create_custom_alert(self, user_client, db, admin_user, regular_user):
        """Un utilisateur non propriétaire voit son scope custom downgrade en private."""
        from app.models import TablePermission, PermissionLevel
        table, cols = make_table(db, admin_user, columns=[("Val", ColumnType.INTEGER)])
        col = cols[0]
        db.add(TablePermission(table_id=table.id, user_id=regular_user.id, level=PermissionLevel.WRITE))
        db.commit()
        r = user_client.post(f"/tables/{table.id}/alerts", data={
            "name": "Tentative custom",
            "scope": "custom",
            "col_ids": [str(col.id)],
            "operators": ["gt"],
            "values": ["0"],
            "logics": ["AND"],
            "recipient_user_ids": [str(admin_user.id)],
        })
        assert r.status_code == 200
        alert = db.query(Alert).filter_by(table_id=table.id).first()
        # Downgrade en private
        assert alert is None or alert.scope == AlertScope.PRIVATE

    def test_update_custom_alert_replaces_recipients(self, admin_client, db, admin_user, regular_user, second_user):
        """La modification d'une alerte personnalisée remplace les destinataires."""
        from app.models import TablePermission, PermissionLevel
        table, cols = make_table(db, admin_user, columns=[("Val", ColumnType.INTEGER)])
        col = cols[0]
        db.add(TablePermission(table_id=table.id, user_id=regular_user.id, level=PermissionLevel.READ))
        db.add(TablePermission(table_id=table.id, user_id=second_user.id, level=PermissionLevel.READ))
        db.commit()

        alert = _make_alert(db, table, admin_user, [
            {"col_id": col.id, "operator": "gt", "value": "0", "logic": "AND"}
        ], scope="custom", recipients=[regular_user.id])
        assert db.query(AlertRecipient).filter_by(alert_id=alert.id).count() == 1

        # Modification : on remplace regular_user par second_user
        r = admin_client.post(f"/tables/{table.id}/alerts/{alert.id}/edit", data={
            "name": alert.name,
            "scope": "custom",
            "col_ids": [str(col.id)],
            "operators": ["gt"],
            "values": ["0"],
            "logics": ["AND"],
            "recipient_user_ids": [str(second_user.id)],
        })
        assert r.status_code == 200
        db.expire_all()
        recipients = db.query(AlertRecipient).filter_by(alert_id=alert.id).all()
        assert len(recipients) == 1
        assert recipients[0].user_id == second_user.id

    def test_delete_custom_alert_cascades_recipients(self, admin_client, db, admin_user, regular_user):
        """La suppression d'une alerte personnalisée supprime ses destinataires."""
        from app.models import TablePermission, PermissionLevel
        table, cols = make_table(db, admin_user, columns=[("Val", ColumnType.INTEGER)])
        col = cols[0]
        db.add(TablePermission(table_id=table.id, user_id=regular_user.id, level=PermissionLevel.READ))
        db.commit()

        alert = _make_alert(db, table, admin_user, [
            {"col_id": col.id, "operator": "gt", "value": "0", "logic": "AND"}
        ], scope="custom", recipients=[regular_user.id])
        alert_id = alert.id
        assert db.query(AlertRecipient).filter_by(alert_id=alert_id).count() == 1

        admin_client.post(f"/tables/{table.id}/alerts/{alert_id}/delete")
        db.expire_all()
        assert db.query(Alert).filter_by(id=alert_id).first() is None
        assert db.query(AlertRecipient).filter_by(alert_id=alert_id).count() == 0

    def test_custom_alert_highlight_visible_to_creator(self, db, admin_user, regular_user, table_with_cols):
        """Le créateur d'une alerte custom voit la surbrillance même s'il n'est pas destinataire."""
        from app.alerts import evaluate_alerts_for_row, get_alert_row_data
        from app.models import TablePermission, PermissionLevel
        table, cols = table_with_cols
        col = cols[0]
        db.add(TablePermission(table_id=table.id, user_id=regular_user.id, level=PermissionLevel.READ))
        db.commit()

        alert = Alert(
            table_id=table.id,
            created_by_id=admin_user.id,
            name="Custom HL",
            scope=AlertScope.CUSTOM,
            conditions=json.dumps([{"col_id": col.id, "operator": "gt", "value": "0", "logic": "AND"}]),
            actions=json.dumps({"highlight": {"enabled": True, "mode": "row", "color": "#ff0000"}}),
            is_active=True,
        )
        db.add(alert)
        db.flush()
        db.add(AlertRecipient(alert_id=alert.id, user_id=regular_user.id))
        db.commit()

        row = _make_row(db, table, admin_user, {col.id: "5"})
        evaluate_alerts_for_row(db, row, table)
        db.commit()

        # Créateur voit la surbrillance (même non destinataire)
        data_admin = get_alert_row_data(db, table.id, user_id=admin_user.id)
        assert row.id in data_admin
        assert data_admin[row.id]["row_style"] != ""

        # Destinataire voit aussi la surbrillance
        data_user = get_alert_row_data(db, table.id, user_id=regular_user.id)
        assert row.id in data_user
        assert data_user[row.id]["row_style"] != ""

    def test_custom_alert_highlight_invisible_to_non_recipient(self, db, admin_user, regular_user, second_user, table_with_cols):
        """Un utilisateur non destinataire d'une alerte custom ne voit pas la surbrillance."""
        from app.alerts import evaluate_alerts_for_row, get_alert_row_data
        from app.models import TablePermission, PermissionLevel
        table, cols = table_with_cols
        col = cols[0]
        db.add(TablePermission(table_id=table.id, user_id=regular_user.id, level=PermissionLevel.READ))
        db.add(TablePermission(table_id=table.id, user_id=second_user.id, level=PermissionLevel.READ))
        db.commit()

        alert = Alert(
            table_id=table.id,
            created_by_id=admin_user.id,
            name="Custom HL",
            scope=AlertScope.CUSTOM,
            conditions=json.dumps([{"col_id": col.id, "operator": "gt", "value": "0", "logic": "AND"}]),
            actions=json.dumps({"highlight": {"enabled": True, "mode": "row", "color": "#ff0000"}}),
            is_active=True,
        )
        db.add(alert)
        db.flush()
        db.add(AlertRecipient(alert_id=alert.id, user_id=regular_user.id))  # seul regular_user
        db.commit()

        row = _make_row(db, table, admin_user, {col.id: "5"})
        evaluate_alerts_for_row(db, row, table)
        db.commit()

        # second_user non destinataire → pas de surbrillance
        data = get_alert_row_data(db, table.id, user_id=second_user.id)
        if row.id in data:
            assert data[row.id]["row_style"] == ""


# ── Mode silencieux ───────────────────────────────────────────────────────────

class TestSilentMode:
    """
    silent=True : les AlertState sont créés (couleurs + amorçage anti-spam)
    mais aucune notification in-app ni email n'est générée.
    """

    def test_silent_creates_state_but_no_notification(self, db, admin_user, table_with_cols):
        """En mode silencieux, l'état est créé mais aucune notification n'est émise."""
        from app.alerts import evaluate_alerts_for_row
        table, cols = table_with_cols
        col = cols[0]
        alert = _make_alert(db, table, admin_user, [
            {"col_id": col.id, "operator": "gt", "value": "100", "logic": "AND"}
        ])

        row = _make_row(db, table, admin_user, {col.id: "200"})
        evaluate_alerts_for_row(db, row, table, silent=True)
        db.commit()

        state = db.query(AlertState).filter_by(alert_id=alert.id, row_id=row.id).first()
        assert state is not None
        assert state.is_triggered is True  # état bien enregistré pour les couleurs

        notifs = db.query(AlertNotification).filter_by(user_id=admin_user.id).all()
        assert len(notifs) == 0  # aucune notification

    def test_silent_primes_antispam_no_notification_on_next_live_eval(self, db, admin_user, table_with_cols):
        """
        Après une réévaluation silencieuse (création d'alerte), une modification live
        sur une ligne déjà en état True ne génère pas de notification (anti-spam actif).
        """
        from app.alerts import evaluate_alerts_for_row
        table, cols = table_with_cols
        col = cols[0]
        alert = _make_alert(db, table, admin_user, [
            {"col_id": col.id, "operator": "gt", "value": "100", "logic": "AND"}
        ])

        row = _make_row(db, table, admin_user, {col.id: "200"})

        # Réévaluation initiale silencieuse (simule create_alert)
        evaluate_alerts_for_row(db, row, table, silent=True)
        db.commit()

        # Modification live de la ligne (condition toujours vraie)
        evaluate_alerts_for_row(db, row, table, silent=False)
        db.commit()

        notifs = db.query(AlertNotification).filter_by(user_id=admin_user.id).all()
        assert len(notifs) == 0  # état déjà True → anti-spam → pas de notification

    def test_live_eval_notifies_after_false_to_true_following_silent_init(self, db, admin_user, table_with_cols):
        """
        Après réévaluation silencieuse (ligne ne matchait pas), une modification live
        qui fait passer la condition à True génère bien une notification.
        """
        from app.alerts import evaluate_alerts_for_row
        table, cols = table_with_cols
        col = cols[0]
        alert = _make_alert(db, table, admin_user, [
            {"col_id": col.id, "operator": "gt", "value": "100", "logic": "AND"}
        ])

        # Ligne qui ne matche pas au moment de la création de l'alerte
        row = _make_row(db, table, admin_user, {col.id: "50"})
        evaluate_alerts_for_row(db, row, table, silent=True)
        db.commit()

        state = db.query(AlertState).filter_by(alert_id=alert.id, row_id=row.id).first()
        assert state.is_triggered is False

        # L'utilisateur modifie la ligne → condition passe à True
        cell = next(cv for cv in row.cell_values if cv.column_id == col.id)
        cell.value = "200"
        db.flush()
        evaluate_alerts_for_row(db, row, table, silent=False)
        db.commit()

        notifs = db.query(AlertNotification).filter_by(user_id=admin_user.id).all()
        assert len(notifs) == 1  # vrai passage False → True → notification envoyée

    def test_create_alert_route_generates_no_notification_for_existing_rows(
        self, admin_client, db, admin_user, table_with_cols
    ):
        """La création d'une alerte via la route ne génère aucune notification
        pour les lignes existantes qui matchent déjà."""
        from app.alerts import evaluate_alerts_for_row
        table, cols = table_with_cols
        col = cols[0]

        # Créer des lignes AVANT l'alerte
        row1 = _make_row(db, table, admin_user, {col.id: "500"})
        row2 = _make_row(db, table, admin_user, {col.id: "10"})
        db.commit()

        admin_client.post(f"/tables/{table.id}/alerts", data={
            "name": "Alerte silencieuse",
            "scope": "private",
            "col_ids": [str(col.id)],
            "operators": ["gt"],
            "values": ["100"],
            "logics": ["AND"],
        })

        notifs = db.query(AlertNotification).filter_by(user_id=admin_user.id).all()
        assert len(notifs) == 0  # aucune notification rétroactive

        # Vérifier que l'état est quand même créé (pour les couleurs)
        alert = db.query(Alert).filter_by(table_id=table.id).first()
        state = db.query(AlertState).filter_by(alert_id=alert.id, row_id=row1.id).first()
        assert state is not None
        assert state.is_triggered is True

    def test_toggle_alert_generates_no_notification(self, admin_client, db, admin_user, table_with_cols):
        """La réactivation d'une alerte ne génère pas de notifications."""
        from app.alerts import evaluate_alerts_for_row
        table, cols = table_with_cols
        col = cols[0]
        alert = _make_alert(db, table, admin_user, [
            {"col_id": col.id, "operator": "gt", "value": "0", "logic": "AND"}
        ])
        row = _make_row(db, table, admin_user, {col.id: "1"})
        db.commit()

        # Désactiver puis réactiver
        admin_client.post(f"/tables/{table.id}/alerts/{alert.id}/toggle")  # désactive
        admin_client.post(f"/tables/{table.id}/alerts/{alert.id}/toggle")  # réactive

        notifs = db.query(AlertNotification).filter_by(user_id=admin_user.id).all()
        assert len(notifs) == 0


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
