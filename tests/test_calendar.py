"""Tests : vue Calendrier — endpoint /events et détection des colonnes DATE/DATETIME."""
from app.models import CellValue, ColumnType, TableRow
from tests.helpers import make_table


def _make_dated_table(db, owner):
    """Table avec une colonne texte + une colonne DATE, 2 lignes datées + 1 sans date."""
    table, cols = make_table(db, owner, name="DatedTable", columns=[
        ("Nom", ColumnType.TEXT),
        ("Echeance", ColumnType.DATE),
    ])
    col_nom, col_date = cols
    for nom, date_val in [("Alice", "2026-03-10"), ("Bob", "2026-03-15")]:
        row = TableRow(table_id=table.id, created_by_id=owner.id)
        db.add(row)
        db.flush()
        db.add(CellValue(row_id=row.id, column_id=col_nom.id, value=nom))
        db.add(CellValue(row_id=row.id, column_id=col_date.id, value=date_val))
    # Ligne sans date renseignée : ne doit jamais apparaître dans les events
    row_no_date = TableRow(table_id=table.id, created_by_id=owner.id)
    db.add(row_no_date)
    db.flush()
    db.add(CellValue(row_id=row_no_date.id, column_id=col_nom.id, value="Sans date"))
    db.commit()
    return table, cols


def test_events_returns_dated_rows(admin_client, db, admin_user):
    table, cols = _make_dated_table(db, admin_user)
    col_date = cols[1]

    resp = admin_client.get(f"/tables/{table.id}/events", params={"date_col": col_date.id})

    assert resp.status_code == 200
    data = resp.json()
    assert len(data) == 2
    starts = {e["start"] for e in data}
    assert starts == {"2026-03-10", "2026-03-15"}


def test_events_title_uses_other_column(admin_client, db, admin_user):
    table, cols = _make_dated_table(db, admin_user)
    col_date = cols[1]

    resp = admin_client.get(f"/tables/{table.id}/events", params={"date_col": col_date.id})

    titles = {e["title"] for e in resp.json()}
    assert titles == {"Alice", "Bob"}


def test_events_carries_row_id_for_click_through(admin_client, db, admin_user):
    table, cols = _make_dated_table(db, admin_user)
    col_date = cols[1]

    resp = admin_client.get(f"/tables/{table.id}/events", params={"date_col": col_date.id})

    for event in resp.json():
        assert event["row_id"] == event["id"]


def test_events_filter_q(admin_client, db, admin_user):
    table, cols = _make_dated_table(db, admin_user)
    col_date = cols[1]

    resp = admin_client.get(f"/tables/{table.id}/events", params={"date_col": col_date.id, "q": "Alice"})

    data = resp.json()
    assert len(data) == 1
    assert data[0]["title"] == "Alice"


def test_events_filter_column(admin_client, db, admin_user):
    table, cols = _make_dated_table(db, admin_user)
    col_nom, col_date = cols

    resp = admin_client.get(
        f"/tables/{table.id}/events",
        params={"date_col": col_date.id, f"filter_{col_nom.id}": "Bob"},
    )

    data = resp.json()
    assert len(data) == 1
    assert data[0]["title"] == "Bob"


def test_events_invalid_date_col_returns_empty(admin_client, db, admin_user):
    """date_col pointant vers une colonne TEXT (pas DATE/DATETIME) -> liste vide, pas d'erreur 500."""
    table, cols = _make_dated_table(db, admin_user)
    col_nom = cols[0]

    resp = admin_client.get(f"/tables/{table.id}/events", params={"date_col": col_nom.id})

    assert resp.status_code == 200
    assert resp.json() == []


def test_events_unknown_date_col_returns_empty(admin_client, db, admin_user):
    table, _ = _make_dated_table(db, admin_user)

    resp = admin_client.get(f"/tables/{table.id}/events", params={"date_col": 999999})

    assert resp.status_code == 200
    assert resp.json() == []


def test_events_forbidden_without_access(user_client, db, admin_user):
    table, cols = _make_dated_table(db, admin_user)
    col_date = cols[1]

    resp = user_client.get(f"/tables/{table.id}/events", params={"date_col": col_date.id})

    assert resp.status_code == 403


def test_table_detail_exposes_date_cols_for_calendar_toggle(admin_client, db, admin_user):
    table, _ = _make_dated_table(db, admin_user)

    resp = admin_client.get(f"/tables/{table.id}")

    assert resp.status_code == 200
    assert 'id="btn-calendar-view"' in resp.text


def test_table_detail_hides_calendar_toggle_without_date_column(admin_client, db, admin_user):
    table, _ = make_table(db, admin_user, name="NoDate", columns=[("Texte", ColumnType.TEXT)])

    resp = admin_client.get(f"/tables/{table.id}")

    assert 'id="btn-calendar-view"' not in resp.text



# ── Colonne affichée (label_col) ───────────────────────────────────────────────

def _make_labelled_table(db, owner):
    """Table Nom + Commune + Echeance : la 2e ligne n'a pas de commune."""
    table, cols = make_table(db, owner, name="LabelTable", columns=[
        ("Nom", ColumnType.TEXT),
        ("Commune", ColumnType.TEXT),
        ("Echeance", ColumnType.DATE),
    ])
    col_nom, col_commune, col_date = cols
    for nom, commune, date_val in [("Alice", "Le Port", "2026-03-10"), ("Bob", "", "2026-03-15")]:
        row = TableRow(table_id=table.id, created_by_id=owner.id)
        db.add(row)
        db.flush()
        db.add(CellValue(row_id=row.id, column_id=col_nom.id, value=nom))
        db.add(CellValue(row_id=row.id, column_id=col_commune.id, value=commune))
        db.add(CellValue(row_id=row.id, column_id=col_date.id, value=date_val))
    db.commit()
    return table, cols


def test_events_title_uses_chosen_label_col(admin_client, db, admin_user):
    table, (col_nom, col_commune, col_date) = _make_labelled_table(db, admin_user)

    resp = admin_client.get(
        f"/tables/{table.id}/events",
        params={"date_col": col_date.id, "label_col": col_commune.id},
    )

    titles = {e["start"]: e["title"] for e in resp.json()}
    assert titles["2026-03-10"] == "Le Port"


def test_events_label_col_empty_value_falls_back_to_row_number(admin_client, db, admin_user):
    """Colonne choisie vide pour une ligne -> « #<id> », pas le contenu d'une autre colonne."""
    table, (col_nom, col_commune, col_date) = _make_labelled_table(db, admin_user)

    resp = admin_client.get(
        f"/tables/{table.id}/events",
        params={"date_col": col_date.id, "label_col": col_commune.id},
    )

    bob = next(e for e in resp.json() if e["start"] == "2026-03-15")
    assert bob["title"] == f"#{bob['row_id']}"


def test_events_unknown_label_col_keeps_automatic_title(admin_client, db, admin_user):
    table, (col_nom, col_commune, col_date) = _make_labelled_table(db, admin_user)

    resp = admin_client.get(
        f"/tables/{table.id}/events",
        params={"date_col": col_date.id, "label_col": 999999},
    )

    assert {e["title"] for e in resp.json()} == {"Alice", "Bob"}


def test_table_detail_offers_label_col_select(admin_client, db, admin_user):
    table, _ = _make_labelled_table(db, admin_user)

    resp = admin_client.get(f"/tables/{table.id}")

    assert 'id="calendar-label-col-select"' in resp.text


# ── Plusieurs colonnes date et couleurs (calendar_config) ─────────────────────

def _make_two_dates_table(db, owner):
    return make_table(db, owner, name="TwoDates", columns=[
        ("Site", ColumnType.TEXT),
        ("Date prog", ColumnType.DATE),
        ("Date realisation", ColumnType.DATE),
    ])


def _edit_payload(table, cols, **extra):
    """Formulaire « Modifier la table » minimal qui conserve toutes les colonnes."""
    data = {
        "name": table.name,
        "description": "",
        "col_ids": [str(c.id) for c in cols],
        "col_names": [c.name for c in cols],
        "col_types": [c.col_type.value for c in cols],
        "col_options": ["" for _ in cols],
    }
    data.update(extra)
    return data


def _legend(html):
    """{col_id: (couleur, affichée par défaut)} lu dans la légende du calendrier."""
    import re
    return {
        int(col): (color, default == "1")
        for col, color, default in re.findall(
            r'data-col="(\d+)" data-color="(#[0-9a-f]{6})" data-name="[^"]*" data-default="([01])"', html)
    }


def test_calendar_legend_defaults_to_first_date_column(admin_client, db, admin_user):
    table, (site, prog, real) = _make_two_dates_table(db, admin_user)

    legend = _legend(admin_client.get(f"/tables/{table.id}").text)

    assert set(legend) == {prog.id, real.id}
    assert legend[prog.id][1] is True
    assert legend[real.id][1] is False
    assert legend[prog.id][0] != legend[real.id][0]


def test_edit_table_saves_calendar_colors_and_defaults(admin_client, db, admin_user):
    import json
    table, cols = _make_two_dates_table(db, admin_user)
    site, prog, real = cols

    resp = admin_client.post(f"/tables/{table.id}/edit", data=_edit_payload(
        table, cols,
        cal_col_ids=[str(prog.id), str(real.id)],
        cal_colors=["#FF0000", "#00aa00"],
        cal_show=[str(prog.id), str(real.id)],
    ))

    assert resp.status_code == 303
    db.expire_all()
    db.refresh(table)
    assert json.loads(table.calendar_config) == [
        {"col": prog.id, "color": "#ff0000", "show": True},
        {"col": real.id, "color": "#00aa00", "show": True},
    ]
    legend = _legend(admin_client.get(f"/tables/{table.id}").text)
    assert legend == {prog.id: ("#ff0000", True), real.id: ("#00aa00", True)}


def test_edit_table_invalid_calendar_color_falls_back_to_palette(admin_client, db, admin_user):
    import json
    table, cols = _make_two_dates_table(db, admin_user)
    site, prog, real = cols

    admin_client.post(f"/tables/{table.id}/edit", data=_edit_payload(
        table, cols,
        cal_col_ids=[str(prog.id)],
        cal_colors=["red; background:url(x)"],
        cal_show=[str(prog.id)],
    ))

    db.expire_all()
    db.refresh(table)
    color = json.loads(table.calendar_config)[0]["color"]
    assert color.startswith("#") and len(color) == 7


def test_edit_table_ignores_non_date_column_in_calendar_config(admin_client, db, admin_user):
    import json
    table, cols = _make_two_dates_table(db, admin_user)
    site, prog, real = cols

    admin_client.post(f"/tables/{table.id}/edit", data=_edit_payload(
        table, cols,
        cal_col_ids=[str(site.id), str(prog.id)],
        cal_colors=["#111111", "#222222"],
        cal_show=[str(site.id), str(prog.id)],
    ))

    db.expire_all()
    db.refresh(table)
    assert [item["col"] for item in json.loads(table.calendar_config)] == [prog.id]


def test_edit_table_without_calendar_section_keeps_config(admin_client, db, admin_user):
    import json
    table, cols = _make_two_dates_table(db, admin_user)
    site, prog, real = cols
    table.calendar_config = json.dumps([{"col": real.id, "color": "#123456", "show": True}])
    db.commit()

    admin_client.post(f"/tables/{table.id}/edit", data=_edit_payload(table, cols))

    db.expire_all()
    db.refresh(table)
    assert json.loads(table.calendar_config) == [{"col": real.id, "color": "#123456", "show": True}]


def test_calendar_unchecked_everything_still_shows_first_date(admin_client, db, admin_user):
    table, cols = _make_two_dates_table(db, admin_user)
    site, prog, real = cols

    admin_client.post(f"/tables/{table.id}/edit", data=_edit_payload(
        table, cols,
        cal_col_ids=[str(prog.id), str(real.id)],
        cal_colors=["#ff0000", "#00aa00"],
        cal_show=[],
    ))

    legend = _legend(admin_client.get(f"/tables/{table.id}").text)
    assert legend[prog.id][1] is True
    assert legend[real.id][1] is False


def test_edit_page_lists_date_columns_for_calendar(admin_client, db, admin_user):
    table, (site, prog, real) = _make_two_dates_table(db, admin_user)

    html = admin_client.get(f"/tables/{table.id}/edit").text

    assert html.count('name="cal_col_ids"') == 2
    assert f'name="cal_col_ids" value="{site.id}"' not in html
