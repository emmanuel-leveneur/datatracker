import json
from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session

from app.database import get_db
from app.dependencies import get_current_user, get_table_or_404, is_table_owner
from app.import_utils import infer_column_type
from app.models import DataTable, SyncAuthType, SyncMode, TableSync, User
from app.sync_service import _build_headers, _resolve_path, run_sync
import httpx

router = APIRouter(prefix="/tables", tags=["sync"])
templates = Jinja2Templates(directory="app/templates")

AUTH_TYPES = [e.value for e in SyncAuthType]
SYNC_MODES = [e.value for e in SyncMode]


@router.get("/{table_id}/sync/panel", response_class=HTMLResponse)
def sync_panel(
    request: Request,
    table: DataTable = Depends(get_table_or_404),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    if not is_table_owner(table, user, db):
        raise HTTPException(status_code=403)
    sync = db.query(TableSync).filter_by(table_id=table.id).first()
    mapping = json.loads(sync.field_mapping) if sync else {}
    return templates.TemplateResponse(
        request, "partials/sync_panel.html",
        {
            "table": table,
            "sync": sync,
            "mapping": mapping,
            "auth_types": AUTH_TYPES,
            "sync_modes": SYNC_MODES,
            "can_write": True,
        },
    )


@router.post("/{table_id}/sync/config", response_class=HTMLResponse)
def save_sync_config(
    request: Request,
    table: DataTable = Depends(get_table_or_404),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
    url: str = Form(...),
    auth_type: str = Form("none"),
    auth_value: str = Form(""),
    auth_header: str = Form("X-API-Key"),
    response_path: str = Form(""),
    sync_interval_minutes: int = Form(60),
    dedup_col_id: str = Form(""),
    sync_mode: str = Form("overwrite"),
    col_ids: list[str] = Form(default=[]),
    json_keys: list[str] = Form(default=[]),
):
    if not is_table_owner(table, user, db):
        raise HTTPException(status_code=403)
    if auth_type not in AUTH_TYPES:
        auth_type = "none"
    if sync_mode not in SYNC_MODES:
        sync_mode = "overwrite"

    field_mapping = {
        cid: jkey
        for cid, jkey in zip(col_ids, json_keys)
        if cid and jkey.strip()
    }

    sync = db.query(TableSync).filter_by(table_id=table.id).first()
    if sync is None:
        sync = TableSync(table_id=table.id)
        db.add(sync)

    sync.url = url.strip()
    sync.auth_type = SyncAuthType(auth_type)
    sync.auth_value = auth_value.strip()
    sync.auth_header = auth_header.strip() or "X-API-Key"
    sync.response_path = response_path.strip()
    sync.field_mapping = json.dumps(field_mapping)
    sync.sync_interval_minutes = max(1, sync_interval_minutes)
    sync.dedup_col_id = int(dedup_col_id) if dedup_col_id.strip().isdigit() else None
    sync.sync_mode = SyncMode(sync_mode)
    db.commit()
    db.refresh(sync)

    mapping = json.loads(sync.field_mapping)
    return templates.TemplateResponse(
        request, "partials/sync_panel.html",
        {
            "table": table,
            "sync": sync,
            "mapping": mapping,
            "auth_types": AUTH_TYPES,
            "sync_modes": SYNC_MODES,
            "can_write": True,
            "success_msg": "Configuration sauvegardée.",
        },
    )


@router.post("/{table_id}/sync/run", response_class=HTMLResponse)
def run_sync_now(
    request: Request,
    table: DataTable = Depends(get_table_or_404),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    if not is_table_owner(table, user, db):
        raise HTTPException(status_code=403)
    try:
        stats = run_sync(table.id, user, db)
        msg = f"Synchronisation réussie — {stats['inserted']} insérée(s), {stats['updated']} mise(s) à jour, {stats['deleted']} supprimée(s)."
        status = "ok"
    except Exception as e:
        msg = str(e)
        status = "error"
        sync = db.query(TableSync).filter_by(table_id=table.id).first()
        if sync:
            from datetime import datetime, timezone
            sync.last_sync_at = datetime.now(timezone.utc)
            sync.last_sync_status = "error"
            sync.last_sync_message = msg
            db.commit()

    sync = db.query(TableSync).filter_by(table_id=table.id).first()
    mapping = json.loads(sync.field_mapping) if sync else {}
    return templates.TemplateResponse(
        request, "partials/sync_panel.html",
        {
            "table": table,
            "sync": sync,
            "mapping": mapping,
            "auth_types": AUTH_TYPES,
            "sync_modes": SYNC_MODES,
            "can_write": True,
            "run_status": status,
            "run_msg": msg,
        },
    )


@router.post("/{table_id}/sync/toggle", response_class=HTMLResponse)
def toggle_auto_sync(
    request: Request,
    table: DataTable = Depends(get_table_or_404),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    if not is_table_owner(table, user, db):
        raise HTTPException(status_code=403)
    sync = db.query(TableSync).filter_by(table_id=table.id).first()
    if not sync:
        raise HTTPException(status_code=404)
    sync.is_auto = not sync.is_auto
    db.commit()
    db.refresh(sync)

    mapping = json.loads(sync.field_mapping)
    return templates.TemplateResponse(
        request, "partials/sync_panel.html",
        {
            "table": table,
            "sync": sync,
            "mapping": mapping,
            "auth_types": AUTH_TYPES,
            "sync_modes": SYNC_MODES,
            "can_write": True,
            "success_msg": f"Synchronisation automatique {'activée' if sync.is_auto else 'désactivée'}.",
        },
    )


@router.post("/{table_id}/sync/delete", response_class=HTMLResponse)
def delete_sync_config(
    request: Request,
    table: DataTable = Depends(get_table_or_404),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    if not is_table_owner(table, user, db):
        raise HTTPException(status_code=403)
    sync = db.query(TableSync).filter_by(table_id=table.id).first()
    if sync:
        db.delete(sync)
        db.commit()
    return templates.TemplateResponse(
        request, "partials/sync_panel.html",
        {
            "table": table,
            "sync": None,
            "mapping": {},
            "auth_types": AUTH_TYPES,
            "sync_modes": SYNC_MODES,
            "can_write": True,
            "success_msg": "Configuration supprimée.",
        },
    )


# ── Helpers partagés avec le wizard de création ────────────────────────────

PREVIEW_ROWS = 5


def _detect_fields(url: str, auth_type: str, auth_value: str, auth_header: str, response_path: str):
    """
    Fetch le webservice et retourne (records, detected_cols).
    detected_cols = [{"json_key": str, "name": str, "type": str}]
    Lève ValueError en cas d'erreur.
    """
    import types
    from app.models import SyncAuthType as SAT
    tmp_sync = types.SimpleNamespace(
        auth_type=SAT(auth_type) if auth_type in AUTH_TYPES else SAT.NONE,
        auth_value=auth_value,
        auth_header=auth_header or "X-API-Key",
    )
    headers = _build_headers(tmp_sync)

    try:
        resp = httpx.get(url, headers=headers, timeout=TIMEOUT, follow_redirects=True)
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

    # Détecte les champs depuis le premier enregistrement
    first = records[0]
    if not isinstance(first, dict):
        raise ValueError("Les enregistrements ne sont pas des objets JSON (dict attendu).")

    detected_cols = []
    for key in first.keys():
        # Collecte jusqu'à 50 valeurs pour inférer le type
        sample = [str(r.get(key, "")) for r in records[:50] if r.get(key) is not None]
        col_type = infer_column_type(sample, col_name=key).value
        detected_cols.append({"json_key": key, "name": key, "type": col_type})

    return records, detected_cols


