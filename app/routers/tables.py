from fastapi import APIRouter, Depends, Form, HTTPException, Query, Request, status
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import delete as sa_delete, select
from sqlalchemy.orm import Session, subqueryload
from app.activity import log_action
from app.database import get_db
from app.dependencies import can_access_table, get_current_user, get_table_or_404, is_table_owner
from app.import_utils import infer_column_type, normalize_value, MAX_ROWS
from app.models import (
    CellValue, ColumnType, DataTable, SyncAuthType, TableColumn,
    TableFavorite, TableOwner, TablePermission, TableRow, TableSync, User,
)

router = APIRouter(prefix="/tables", tags=["tables"])
templates = Jinja2Templates(directory="app/templates")

COLUMN_TYPES = [e.value for e in ColumnType]


@router.get("/", response_class=HTMLResponse)
def list_tables(request: Request, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    if user.is_admin:
        tables = db.query(DataTable).filter(DataTable.deleted_at == None).order_by(DataTable.created_at.desc()).all()
        trashed_tables = db.query(DataTable).filter(DataTable.deleted_at != None).order_by(DataTable.deleted_at.desc()).all()
    else:
        owned_ids = [r[0] for r in db.query(TableOwner.table_id).filter_by(user_id=user.id).all()]
        owned = db.query(DataTable).filter(DataTable.id.in_(owned_ids), DataTable.deleted_at == None).all()
        shared_ids = [r[0] for r in db.query(TablePermission.table_id).filter_by(user_id=user.id).all()]
        shared = db.query(DataTable).filter(DataTable.id.in_(shared_ids), DataTable.deleted_at == None).all()
        seen = {t.id for t in owned}
        tables = owned + [t for t in shared if t.id not in seen]
        trashed_tables = db.query(DataTable).filter(
            DataTable.id.in_(owned_ids), DataTable.deleted_at != None
        ).order_by(DataTable.deleted_at.desc()).all()

    favorite_ids = {
        f.table_id for f in db.query(TableFavorite).filter_by(user_id=user.id).all()
    }
    favorites = [t for t in tables if t.id in favorite_ids]

    if user.is_admin:
        admin_owned_ids = {r[0] for r in db.query(TableOwner.table_id).filter_by(user_id=user.id).all()}
        owner_table_ids = admin_owned_ids
    else:
        owner_table_ids = set(owned_ids)

    # Nombre d'utilisateurs ayant une permission explicite sur chaque table
    shared_counts = {t.id: len(t.permissions) for t in tables}

    # Niveau d'accès de l'utilisateur sur les tables dont il n'est pas propriétaire
    user_perm_levels: dict[int, str] = {}
    for t in tables:
        if t.id not in owner_table_ids:
            tp = next((p for p in t.permissions if p.user_id == user.id), None)
            if tp:
                user_perm_levels[t.id] = tp.level.value

    # Nom du premier propriétaire de chaque table (pour les tables partagées)
    table_owner_names: dict[int, str] = {}
    for t in tables:
        if t.id not in owner_table_ids and t.co_owners:
            owner_obj = t.co_owners[0]
            if owner_obj.user:
                table_owner_names[t.id] = owner_obj.user.email.split("@")[0]

    return templates.TemplateResponse(
        request, "tables/list.html",
        {
            "user": user,
            "tables": tables,
            "favorites": favorites,
            "favorite_ids": favorite_ids,
            "trashed_tables": trashed_tables,
            "owner_table_ids": owner_table_ids,
            "shared_counts": shared_counts,
            "user_perm_levels": user_perm_levels,
            "table_owner_names": table_owner_names,
        },
    )


@router.post("/{table_id}/favorite")
def toggle_favorite(
    table_id: int,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    table = db.get(DataTable, table_id)
    if not table:
        raise HTTPException(status_code=404)
    fav = db.query(TableFavorite).filter_by(user_id=user.id, table_id=table_id).first()
    if fav:
        db.delete(fav)
    else:
        db.add(TableFavorite(user_id=user.id, table_id=table_id))
    db.commit()
    return RedirectResponse(url="/tables/", status_code=status.HTTP_303_SEE_OTHER)


def _all_tables_json(db: Session, user: User, exclude_id: int | None = None) -> str:
    """Sérialise les tables accessibles par l'utilisateur (min. lecture) avec leurs colonnes."""
    import json
    tables = db.query(DataTable).filter(DataTable.deleted_at == None).all()
    return json.dumps([
        {
            "id": t.id,
            "name": t.name,
            "columns": [
                {"id": c.id, "name": c.name}
                for c in sorted(t.columns, key=lambda c: c.order)
                if c.col_type.value != "relation"  # évite les relations circulaires
            ],
        }
        for t in tables
        if t.id != exclude_id and can_access_table(t, user, db)
    ])


@router.get("/create", response_class=HTMLResponse)
def create_table_page(request: Request, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    return templates.TemplateResponse(
        request, "tables/create.html",
        {"user": user, "column_types": COLUMN_TYPES, "all_tables_json": _all_tables_json(db, user)},
    )


@router.post("/create")
def create_table(
    request: Request,
    name: str = Form(...),
    description: str = Form(""),
    col_names: list[str] = Form(default=[]),
    col_types: list[str] = Form(default=[]),
    col_required: list[str] = Form(default=[]),
    col_personal_data: list[str] = Form(default=[]),
    col_options: list[str] = Form(default=[]),
    col_related_table_ids: list[str] = Form(default=[]),
    col_related_display_col_ids: list[str] = Form(default=[]),
    col_related_value_col_ids: list[str] = Form(default=[]),
    dpo_declared: str = Form(default=""),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    table = DataTable(name=name, description=description, created_by_id=user.id,
                      dpo_declared=bool(dpo_declared))
    db.add(table)
    db.flush()
    db.add(TableOwner(table_id=table.id, user_id=user.id))

    required_set = set(col_required)
    personal_data_set = set(col_personal_data)
    for i, (cname, ctype) in enumerate(zip(col_names, col_types)):
        cname = cname.strip()
        if not cname:
            continue
        options = col_options[i] if i < len(col_options) else ""
        rel_table_id = None
        rel_display_col_id = None
        rel_value_col_id = None
        if ctype == "relation":
            try:
                rel_table_id = int(col_related_table_ids[i]) if i < len(col_related_table_ids) and col_related_table_ids[i] else None
                rel_display_col_id = int(col_related_display_col_ids[i]) if i < len(col_related_display_col_ids) and col_related_display_col_ids[i] else None
                rel_value_col_id = int(col_related_value_col_ids[i]) if i < len(col_related_value_col_ids) and col_related_value_col_ids[i] else None
            except (ValueError, IndexError):
                pass
        col = TableColumn(
            table_id=table.id,
            name=cname,
            col_type=ColumnType(ctype),
            order=i,
            required=(str(i) in required_set),
            is_personal_data=(str(i) in personal_data_set),
            select_options=options,
            related_table_id=rel_table_id,
            related_display_col_id=rel_display_col_id,
            related_value_col_id=rel_value_col_id,
        )
        db.add(col)
    log_action(db, user, "create_table", "table",
               resource_id=table.id, resource_name=table.name,
               details=f"{len(col_names)} colonne(s)", table_id=table.id)
    db.commit()
    return RedirectResponse(url=f"/tables/{table.id}", status_code=status.HTTP_303_SEE_OTHER)


PAGE_SIZE = 25  # taille de page par défaut
ALLOWED_PAGE_SIZES = [25, 50, 100, 250, 500]


# ── Wizard : créer une table depuis un webservice ──────────────────────────

_WS_AUTH_TYPES = [e.value for e in SyncAuthType]
_WS_PREVIEW_ROWS = 5


def _ws_detect_fields(url, auth_type, auth_value, auth_header, response_path):
    import httpx
    import types
    from app.sync_service import _build_headers, _resolve_path
    from app.models import SyncAuthType as SAT
    tmp = types.SimpleNamespace(
        auth_type=SAT(auth_type) if auth_type in _WS_AUTH_TYPES else SAT.NONE,
        auth_value=auth_value,
        auth_header=auth_header or "X-API-Key",
    )
    headers = _build_headers(tmp)
    try:
        resp = httpx.get(url, headers=headers, timeout=30, follow_redirects=True)
        resp.raise_for_status()
    except httpx.HTTPStatusError as e:
        raise ValueError(f"Erreur HTTP {e.response.status_code} — {e.response.text[:200]}")
    except httpx.RequestError as e:
        raise ValueError(f"Erreur réseau : {e}")
    try:
        raw = resp.json()
    except Exception:
        raise ValueError("La réponse n'est pas du JSON valide.")
    records = _resolve_path(raw, response_path)
    if not records:
        raise ValueError("Le tableau retourné est vide.")
    first = records[0]
    if not isinstance(first, dict):
        raise ValueError("Les enregistrements ne sont pas des objets JSON (dict attendu).")
    detected_cols = []
    for key in first.keys():
        sample = [str(r.get(key, "")) for r in records[:50] if r.get(key) is not None]
        detected_cols.append({"json_key": key, "name": key, "type": infer_column_type(sample, col_name=key).value})
    return records, detected_cols


@router.get("/create-from-webservice", response_class=HTMLResponse)
def create_from_webservice_page(request: Request, user: User = Depends(get_current_user)):
    return templates.TemplateResponse(
        request, "tables/create_from_webservice.html", {"auth_types": _WS_AUTH_TYPES},
    )


@router.post("/create-from-webservice/detect", response_class=HTMLResponse)
def detect_webservice(
    request: Request,
    user: User = Depends(get_current_user),
    url: str = Form(...),
    auth_type: str = Form("none"),
    auth_value: str = Form(""),
    auth_header: str = Form("X-API-Key"),
    response_path: str = Form(""),
):
    try:
        records, detected_cols = _ws_detect_fields(url, auth_type, auth_value, auth_header, response_path)
    except ValueError as e:
        return templates.TemplateResponse(
            request, "partials/webservice_detect_preview.html", {"error": str(e)},
        )
    return templates.TemplateResponse(
        request, "partials/webservice_detect_preview.html",
        {
            "detected_cols": detected_cols,
            "preview": records[:_WS_PREVIEW_ROWS],
            "total_records": len(records),
            "column_types": COLUMN_TYPES,
            "auth_types": _WS_AUTH_TYPES,
            "url": url, "auth_type": auth_type, "auth_value": auth_value,
            "auth_header": auth_header, "response_path": response_path,
        },
    )


@router.post("/create-from-webservice/confirm")
def confirm_webservice_table(
    request: Request,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
    table_name: str = Form(...),
    url: str = Form(...),
    auth_type: str = Form("none"),
    auth_value: str = Form(""),
    auth_header: str = Form("X-API-Key"),
    response_path: str = Form(""),
    sync_interval_minutes: int = Form(60),
    is_auto: str = Form(""),
    dedup_col_json_key: str = Form(""),
    col_json_keys: list[str] = Form(default=[]),
    col_names: list[str] = Form(default=[]),
    col_types: list[str] = Form(default=[]),
):
    try:
        records, _ = _ws_detect_fields(url, auth_type, auth_value, auth_header, response_path)
    except ValueError as e:
        return templates.TemplateResponse(
            request, "partials/webservice_detect_preview.html",
            {"error": f"Erreur lors de la récupération des données : {e}"},
        )
    final_cols = []
    for json_key, col_name, col_type_str in zip(col_json_keys, col_names, col_types):
        name = col_name.strip()
        if not name:
            continue
        try:
            ct = ColumnType(col_type_str)
        except ValueError:
            ct = ColumnType.TEXT
        final_cols.append({"json_key": json_key, "name": name, "type": ct})
    if not final_cols:
        return templates.TemplateResponse(
            request, "partials/webservice_detect_preview.html",
            {"error": "Aucune colonne sélectionnée."},
        )
    table = DataTable(name=table_name.strip() or "Table webservice", created_by_id=user.id)
    db.add(table)
    db.flush()
    db.add(TableOwner(table_id=table.id, user_id=user.id))
    col_objects = []
    for order, col_def in enumerate(final_cols):
        tc = TableColumn(table_id=table.id, name=col_def["name"], col_type=col_def["type"], order=order)
        db.add(tc)
        col_objects.append(tc)
    db.flush()
    field_mapping = {str(tc.id): col_def["json_key"] for tc, col_def in zip(col_objects, final_cols)}
    dedup_col_id = None
    if dedup_col_json_key:
        for tc, col_def in zip(col_objects, final_cols):
            if col_def["json_key"] == dedup_col_json_key:
                dedup_col_id = tc.id
                break
    for record in records[:MAX_ROWS]:
        if not isinstance(record, dict):
            continue
        row = TableRow(table_id=table.id, created_by_id=user.id)
        db.add(row)
        db.flush()
        for tc, col_def in zip(col_objects, final_cols):
            val = normalize_value(str(record.get(col_def["json_key"], "")), col_def["type"])
            db.add(CellValue(row_id=row.id, column_id=tc.id, value=val))
    import json as _json
    db.add(TableSync(
        table_id=table.id, url=url.strip(),
        auth_type=SyncAuthType(auth_type) if auth_type in _WS_AUTH_TYPES else SyncAuthType.NONE,
        auth_value=auth_value.strip(), auth_header=auth_header.strip() or "X-API-Key",
        response_path=response_path.strip(), field_mapping=_json.dumps(field_mapping),
        dedup_col_id=dedup_col_id, is_auto=bool(is_auto),
        sync_interval_minutes=max(1, sync_interval_minutes),
    ))
    log_action(db, user, "create_from_webservice", "table",
               resource_id=table.id, resource_name=table.name,
               details=f"{len(records[:MAX_ROWS])} ligne(s), {len(final_cols)} colonne(s) depuis {url}",
               table_id=table.id)
    db.commit()
    return RedirectResponse(url=f"/tables/{table.id}", status_code=303)


@router.get("/{table_id}", response_class=HTMLResponse)
def table_detail(
    request: Request,
    page: int = Query(1, ge=1),
    q: str = Query(""),
    page_size: int = Query(PAGE_SIZE),
    table: DataTable = Depends(get_table_or_404),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    if table.deleted_at is not None:
        raise HTTPException(status_code=404)
    if not can_access_table(table, user, db):
        raise HTTPException(status_code=403, detail="Accès refusé")
    from app.dependencies import get_visible_columns
    from app.models import TableRow

    visible_cols = get_visible_columns(table, user, db)
    visible_col_ids = {c.id for c in visible_cols}

    # Filtres par colonne depuis les query params (?col_123=val)
    col_filters = {k[7:]: v for k, v in request.query_params.items() if k.startswith("filter_") and v}

    base = db.query(TableRow).filter(
        TableRow.table_id == table.id, TableRow.deleted_at == None
    )
    if q:
        from app.models import CellValue as CV
        matching_subq = db.query(CV.row_id).filter(
            CV.value.ilike(f"%{q}%"),
            CV.column_id.in_(visible_col_ids),
        ).distinct().subquery()
        base = base.filter(TableRow.id.in_(matching_subq))
    for col_id_str, filter_val in col_filters.items():
        if not filter_val.strip():
            continue
        try:
            col_id = int(col_id_str)
        except ValueError:
            continue
        if col_id not in visible_col_ids:
            continue
        from app.models import CellValue as CV
        col_subq = db.query(CV.row_id).filter(
            CV.column_id == col_id,
            CV.value.ilike(f"%{filter_val}%"),
        ).distinct().subquery()
        base = base.filter(TableRow.id.in_(col_subq))

    page_size = page_size if page_size in ALLOWED_PAGE_SIZES else PAGE_SIZE
    total_count: int = base.count()
    total_pages = max(1, (total_count + page_size - 1) // page_size)
    page = min(max(1, page), total_pages)

    rows = base.options(
        subqueryload(TableRow.cell_values)
    ).order_by(TableRow.created_at.desc()).limit(page_size).offset((page - 1) * page_size).all()

    rows_data = [
        {"row": row, "cells": {cv.column_id: cv.value for cv in row.cell_values if cv.column_id in visible_col_ids}}
        for row in rows
    ]

    trashed_rows = db.query(TableRow).options(
        subqueryload(TableRow.cell_values)
    ).filter(
        TableRow.table_id == table.id, TableRow.deleted_at != None
    ).order_by(TableRow.deleted_at.desc()).all()
    trashed_rows_data = [
        {"row": row, "cells": {cv.column_id: cv.value for cv in row.cell_values if cv.column_id in visible_col_ids}}
        for row in trashed_rows
    ]

    lat_col = next((c for c in visible_cols if c.col_type == ColumnType.LATITUDE), None)
    lon_col = next((c for c in visible_cols if c.col_type == ColumnType.LONGITUDE), None)

    is_owner = is_table_owner(table, user, db)
    can_write = can_access_table(table, user, db, require_write=True)

    from app.dependencies import is_column_readonly
    from app.alerts import get_alert_row_data
    from app.routers.data import _resolve_relation_labels
    from app.models import RowComment
    from sqlalchemy import func as _func
    col_readonly = {col.id: is_column_readonly(col, user, db) for col in visible_cols}

    row_ids = [r.id for r in rows]
    comment_counts: dict[int, int] = {}
    if row_ids:
        _counts = db.query(RowComment.row_id, _func.count(RowComment.id)).filter(
            RowComment.row_id.in_(row_ids)
        ).group_by(RowComment.row_id).all()
        comment_counts = dict(_counts)

    table_sync = db.query(TableSync).filter_by(table_id=table.id).first()

    return templates.TemplateResponse(
        request, "tables/detail.html",
        {
            "user": user,
            "table": table,
            "columns": visible_cols,
            "rows_data": rows_data,
            "trashed_rows_data": trashed_rows_data,
            "is_owner": is_owner,
            "can_write": can_write,
            "col_readonly": col_readonly,
            "column_types": COLUMN_TYPES,
            "alerted_rows": get_alert_row_data(db, table.id, user.id),
            "relation_labels": _resolve_relation_labels(db, visible_cols),
            "page": page,
            "total_pages": total_pages,
            "total_count": total_count,
            "page_size": page_size,
            "allowed_page_sizes": ALLOWED_PAGE_SIZES,
            "q": q,
            "col_filters": col_filters,
            "comment_counts": comment_counts,
            "lat_col": lat_col,
            "lon_col": lon_col,
            "table_sync": table_sync,
        },
    )


@router.get("/{table_id}/geojson")
def table_geojson(
    request: Request,
    q: str = Query(""),
    table: DataTable = Depends(get_table_or_404),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    if not can_access_table(table, user, db):
        raise HTTPException(status_code=403)

    from app.dependencies import get_visible_columns
    visible_cols = get_visible_columns(table, user, db)
    lat_col = next((c for c in visible_cols if c.col_type == ColumnType.LATITUDE), None)
    lon_col = next((c for c in visible_cols if c.col_type == ColumnType.LONGITUDE), None)

    if not lat_col or not lon_col:
        return {"type": "FeatureCollection", "features": []}

    visible_col_ids = {c.id for c in visible_cols}
    other_cols = [c for c in visible_cols if c.col_type not in (ColumnType.LATITUDE, ColumnType.LONGITUDE)]

    col_filters = {k[7:]: v for k, v in request.query_params.items() if k.startswith("filter_") and v}

    base = db.query(TableRow).filter(
        TableRow.table_id == table.id,
        TableRow.deleted_at == None,
    )
    if q:
        matching_subq = db.query(CellValue.row_id).filter(
            CellValue.value.ilike(f"%{q}%"),
            CellValue.column_id.in_(visible_col_ids),
        ).distinct().subquery()
        base = base.filter(TableRow.id.in_(matching_subq))
    for col_id_str, filter_val in col_filters.items():
        if not filter_val.strip():
            continue
        try:
            col_id = int(col_id_str)
        except ValueError:
            continue
        if col_id not in visible_col_ids:
            continue
        col_subq = db.query(CellValue.row_id).filter(
            CellValue.column_id == col_id,
            CellValue.value.ilike(f"%{filter_val}%"),
        ).distinct().subquery()
        base = base.filter(TableRow.id.in_(col_subq))

    rows = base.options(subqueryload(TableRow.cell_values)).all()

    features = []
    for row in rows:
        cells = {cv.column_id: cv.value for cv in row.cell_values if cv.column_id in visible_col_ids}
        try:
            lat = float(cells.get(lat_col.id) or "")
            lon = float(cells.get(lon_col.id) or "")
        except ValueError:
            continue
        props = {"row_id": row.id}
        for col in other_cols:
            props[col.name] = cells.get(col.id, "")
        features.append({
            "type": "Feature",
            "geometry": {"type": "Point", "coordinates": [lon, lat]},
            "properties": props,
        })

    return {"type": "FeatureCollection", "features": features}


@router.get("/{table_id}/edit", response_class=HTMLResponse)
def edit_table_page(
    request: Request,
    table: DataTable = Depends(get_table_or_404),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    if table.deleted_at is not None:
        raise HTTPException(status_code=404)
    if not is_table_owner(table, user, db) and not user.is_admin:
        raise HTTPException(status_code=403, detail="Accès refusé")
    return templates.TemplateResponse(
        request, "tables/edit.html",
        {
            "user": user,
            "table": table,
            "column_types": COLUMN_TYPES,
            "all_tables_json": _all_tables_json(db, user, exclude_id=table.id),
        },
    )


@router.post("/{table_id}/edit")
def edit_table(
    request: Request,
    table_id: int,
    name: str = Form(...),
    description: str = Form(""),
    col_ids: list[str] = Form(default=[]),
    col_names: list[str] = Form(default=[]),
    col_types: list[str] = Form(default=[]),
    col_required: list[str] = Form(default=[]),
    col_personal_data: list[str] = Form(default=[]),
    col_options: list[str] = Form(default=[]),
    col_related_table_ids: list[str] = Form(default=[]),
    col_related_display_col_ids: list[str] = Form(default=[]),
    col_related_value_col_ids: list[str] = Form(default=[]),
    rgpd_finalite: str = Form(""),
    rgpd_base_legale: str = Form(""),
    rgpd_duree_conservation: str = Form(""),
    rgpd_responsable: str = Form(""),
    rgpd_destinataires: str = Form(""),
    rgpd_hors_ue: str = Form(""),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    table = db.get(DataTable, table_id)
    if not table:
        raise HTTPException(status_code=404)
    if not is_table_owner(table, user, db) and not user.is_admin:
        raise HTTPException(status_code=403)

    # ── Capture de l'état avant modification ──────────────────────────────
    old_name = table.name
    old_description = table.description or ""
    old_cols = {col.id: {"name": col.name, "type": col.col_type.value} for col in table.columns}

    table.name = name
    table.description = description
    table.rgpd_finalite = rgpd_finalite
    table.rgpd_base_legale = rgpd_base_legale
    table.rgpd_duree_conservation = rgpd_duree_conservation
    table.rgpd_responsable = rgpd_responsable
    table.rgpd_destinataires = rgpd_destinataires
    table.rgpd_hors_ue = bool(rgpd_hors_ue)

    existing_ids = {str(c.id) for c in table.columns}
    submitted_ids = set(col_ids)

    # Delete removed columns
    for col in list(table.columns):
        if str(col.id) not in submitted_ids:
            db.delete(col)

    required_set = set(col_required)
    personal_data_set = set(col_personal_data)
    for i, (cid, cname, ctype) in enumerate(zip(col_ids, col_names, col_types)):
        cname = cname.strip()
        if not cname:
            continue
        options = col_options[i] if i < len(col_options) else ""
        rel_table_id = None
        rel_display_col_id = None
        rel_value_col_id = None
        if ctype == "relation":
            try:
                rel_table_id = int(col_related_table_ids[i]) if i < len(col_related_table_ids) and col_related_table_ids[i] else None
                rel_display_col_id = int(col_related_display_col_ids[i]) if i < len(col_related_display_col_ids) and col_related_display_col_ids[i] else None
                rel_value_col_id = int(col_related_value_col_ids[i]) if i < len(col_related_value_col_ids) and col_related_value_col_ids[i] else None
            except (ValueError, IndexError):
                pass
        if cid and cid in existing_ids:
            col = db.get(TableColumn, int(cid))
            if col:
                col.name = cname
                col.col_type = ColumnType(ctype)
                col.order = i
                col.required = (str(i) in required_set)
                col.is_personal_data = (str(i) in personal_data_set)
                col.select_options = options
                col.related_table_id = rel_table_id
                col.related_display_col_id = rel_display_col_id
                col.related_value_col_id = rel_value_col_id
        else:
            col = TableColumn(
                table_id=table.id,
                name=cname,
                col_type=ColumnType(ctype),
                order=i,
                required=(str(i) in required_set),
                is_personal_data=(str(i) in personal_data_set),
                select_options=options,
                related_table_id=rel_table_id,
                related_display_col_id=rel_display_col_id,
                related_value_col_id=rel_value_col_id,
            )
            db.add(col)

    # ── Construction du diff avant/après ──────────────────────────────────
    diff = []
    if old_name != name:
        diff.append(f'Nom : "{old_name}" → "{name}"')
    if old_description != (description or ""):
        diff.append(f'Description : "{old_description}" → "{description or ""}"')
    for col_id, old in old_cols.items():
        if str(col_id) not in submitted_ids:
            diff.append(f'Colonne supprimée : "{old["name"]}" ({old["type"]})')
    for i, (cid, cname, ctype) in enumerate(zip(col_ids, col_names, col_types)):
        cname = cname.strip()
        if not cname:
            continue
        if cid and cid in existing_ids:
            old = old_cols.get(int(cid))
            if old:
                if old["name"] != cname:
                    diff.append(f'Colonne : "{old["name"]}" → "{cname}"')
                if old["type"] != ctype:
                    diff.append(f'Type "{cname}" : {old["type"]} → {ctype}')
        else:
            diff.append(f'Colonne ajoutée : "{cname}" ({ctype})')

    log_action(db, user, "edit_table", "table",
               resource_id=table.id, resource_name=name, table_id=table.id,
               details="\n".join(diff) if diff else "Aucune modification")
    db.commit()
    return RedirectResponse(url=f"/tables/{table_id}", status_code=status.HTTP_303_SEE_OTHER)


@router.post("/{table_id}/delete")
def trash_table(
    table_id: int,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    from datetime import datetime
    table = db.get(DataTable, table_id)
    if not table:
        raise HTTPException(status_code=404)
    if not is_table_owner(table, user, db) and not user.is_admin:
        raise HTTPException(status_code=403)
    table.deleted_at = datetime.utcnow()
    log_action(db, user, "trash_table", "table",
               resource_id=table.id, resource_name=table.name, table_id=table.id)
    db.commit()
    return RedirectResponse(url="/tables/", status_code=status.HTTP_303_SEE_OTHER)


@router.post("/{table_id}/restore")
def restore_table(
    table_id: int,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    table = db.get(DataTable, table_id)
    if not table:
        raise HTTPException(status_code=404)
    if not is_table_owner(table, user, db) and not user.is_admin:
        raise HTTPException(status_code=403)
    table.deleted_at = None
    log_action(db, user, "restore_table", "table",
               resource_id=table.id, resource_name=table.name, table_id=table.id)
    db.commit()
    return RedirectResponse(url="/tables/", status_code=status.HTTP_303_SEE_OTHER)


@router.post("/{table_id}/delete-permanent")
def delete_table_permanent(
    table_id: int,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    table = db.get(DataTable, table_id)
    if not table:
        raise HTTPException(status_code=404)
    if not is_table_owner(table, user, db) and not user.is_admin:
        raise HTTPException(status_code=403)
    if table.deleted_at is None:
        raise HTTPException(status_code=400, detail="La table doit d'abord être mise à la corbeille")
    log_action(db, user, "delete_table", "table",
               resource_id=table.id, resource_name=table.name, table_id=table.id)

    # Suppression en masse via SQL pour éviter N DELETE ORM sur les cellules et lignes.
    # Les IDs sont matérialisés en Python pour éviter les sous-requêtes temporaires SQLite
    # qui causent des erreurs I/O sur filesystem Windows/WSL.
    row_ids = [r[0] for r in db.execute(select(TableRow.id).where(TableRow.table_id == table.id)).fetchall()]
    if row_ids:
        _CHUNK = 500
        for i in range(0, len(row_ids), _CHUNK):
            db.execute(sa_delete(CellValue).where(CellValue.row_id.in_(row_ids[i:i + _CHUNK])))
    db.execute(sa_delete(TableRow).where(TableRow.table_id == table.id))

    db.delete(table)  # supprime colonnes, permissions, owners via cascade ORM (peu nombreux)
    db.commit()
    return RedirectResponse(url="/tables/", status_code=status.HTTP_303_SEE_OTHER)
