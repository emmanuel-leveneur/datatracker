"""
Logique de synchronisation d'une table depuis un webservice externe.
"""
import base64
import json
import logging
from datetime import datetime, timezone

import httpx
from sqlalchemy.orm import Session

from app.models import (
    ActivityLog, CellValue, DataTable, SyncMode, TableRow, TableSync, User,
)

logger = logging.getLogger(__name__)

TIMEOUT = 30


def _build_headers(sync: TableSync) -> dict:
    from app.models import SyncAuthType
    if sync.auth_type == SyncAuthType.BEARER:
        return {"Authorization": f"Bearer {sync.auth_value}"}
    if sync.auth_type == SyncAuthType.API_KEY:
        return {sync.auth_header: sync.auth_value}
    if sync.auth_type == SyncAuthType.BASIC:
        encoded = base64.b64encode(sync.auth_value.encode()).decode()
        return {"Authorization": f"Basic {encoded}"}
    return {}


def _resolve_path(data: dict | list, path: str) -> list:
    """Navigue dans un dict JSON selon un chemin pointé ('data.items')."""
    if not path:
        if isinstance(data, list):
            return data
        raise ValueError("La réponse JSON n'est pas un tableau et aucun chemin n'est configuré.")
    obj = data
    for key in path.split("."):
        if not isinstance(obj, dict) or key not in obj:
            raise ValueError(f"Chemin '{path}' introuvable dans la réponse.")
        obj = obj[key]
    if not isinstance(obj, list):
        raise ValueError(f"Le chemin '{path}' ne pointe pas vers un tableau.")
    return obj


def run_sync(table_id: int, triggered_by: User, db: Session) -> dict:
    """
    Exécute une synchronisation complète pour la table donnée.
    Retourne {"inserted": int, "updated": int, "deleted": int, "errors": list}.
    Lève une exception en cas d'échec réseau ou de config invalide.
    """
    sync: TableSync | None = db.query(TableSync).filter_by(table_id=table_id).first()
    if not sync:
        raise ValueError("Aucune configuration de synchronisation trouvée.")

    table: DataTable | None = db.get(DataTable, table_id)
    if not table:
        raise ValueError("Table introuvable.")

    mapping: dict[str, str] = json.loads(sync.field_mapping or "{}")
    # mapping: {str(col_id): json_field_name}

    headers = _build_headers(sync)
    try:
        resp = httpx.get(sync.url, headers=headers, timeout=TIMEOUT, follow_redirects=True)
        resp.raise_for_status()
    except httpx.HTTPStatusError as e:
        raise ValueError(f"Erreur HTTP {e.response.status_code} : {e.response.text[:200]}")
    except httpx.RequestError as e:
        raise ValueError(f"Erreur réseau : {e}")

    try:
        raw = resp.json()
    except Exception:
        raise ValueError("La réponse n'est pas du JSON valide.")

    records = _resolve_path(raw, sync.response_path)

    col_map = {str(c.id): c for c in table.columns}
    dedup_col = col_map.get(str(sync.dedup_col_id)) if sync.dedup_col_id else None
    mode = SyncMode(sync.sync_mode) if isinstance(sync.sync_mode, str) else sync.sync_mode

    stats = {"inserted": 0, "updated": 0, "deleted": 0, "errors": []}

    def _insert_row(record: dict) -> None:
        row = TableRow(table_id=table_id, created_by_id=triggered_by.id)
        db.add(row)
        db.flush()
        for col_id_str, json_key in mapping.items():
            col = col_map.get(col_id_str)
            if col:
                db.add(CellValue(row_id=row.id, column_id=col.id, value=str(record.get(json_key, ""))))
        stats["inserted"] += 1

    def _find_existing(dedup_val: str) -> TableRow | None:
        if not dedup_col or not dedup_val:
            return None
        cell = (
            db.query(CellValue)
            .join(TableRow, CellValue.row_id == TableRow.id)
            .filter(
                TableRow.table_id == table_id,
                TableRow.deleted_at == None,
                CellValue.column_id == dedup_col.id,
                CellValue.value == dedup_val,
            )
            .first()
        )
        return db.get(TableRow, cell.row_id) if cell else None

    if mode == SyncMode.OVERWRITE:
        # Supprime toutes les lignes actives puis réinsère tout
        existing_rows = db.query(TableRow).filter(
            TableRow.table_id == table_id, TableRow.deleted_at == None,
        ).all()
        for row in existing_rows:
            row.deleted_at = datetime.now(timezone.utc)
        stats["deleted"] = len(existing_rows)
        db.flush()
        for record in records:
            if isinstance(record, dict):
                _insert_row(record)

    elif mode == SyncMode.UPSERT:
        # Met à jour les existants (dedup), insère les nouveaux, supprime les absents
        seen_row_ids: set[int] = set()
        for record in records:
            if not isinstance(record, dict):
                continue
            dedup_json_key = mapping.get(str(dedup_col.id), "") if dedup_col else ""
            dedup_val = str(record.get(dedup_json_key, "")) if dedup_json_key else ""
            existing_row = _find_existing(dedup_val)
            if existing_row:
                for col_id_str, json_key in mapping.items():
                    col = col_map.get(col_id_str)
                    if not col:
                        continue
                    val = str(record.get(json_key, ""))
                    cell = next((cv for cv in existing_row.cell_values if cv.column_id == col.id), None)
                    if cell:
                        cell.value = val
                    else:
                        db.add(CellValue(row_id=existing_row.id, column_id=col.id, value=val))
                seen_row_ids.add(existing_row.id)
                stats["updated"] += 1
            else:
                _insert_row(record)
                seen_row_ids.add(db.query(TableRow).filter_by(table_id=table_id).order_by(TableRow.id.desc()).first().id)
        # Supprime les lignes absentes du WS
        all_active = db.query(TableRow).filter(
            TableRow.table_id == table_id, TableRow.deleted_at == None,
        ).all()
        for row in all_active:
            if row.id not in seen_row_ids:
                row.deleted_at = datetime.now(timezone.utc)
                stats["deleted"] += 1

    elif mode == SyncMode.APPEND_NO_DUP:
        # Insère uniquement les enregistrements dont la clé de dédup est absente
        for record in records:
            if not isinstance(record, dict):
                continue
            dedup_json_key = mapping.get(str(dedup_col.id), "") if dedup_col else ""
            dedup_val = str(record.get(dedup_json_key, "")) if dedup_json_key else ""
            if not _find_existing(dedup_val):
                _insert_row(record)

    elif mode == SyncMode.APPEND_DUP:
        # Insère toujours tout sans aucune vérification
        for record in records:
            if isinstance(record, dict):
                _insert_row(record)

    message = f"{stats['inserted']} insérée(s), {stats['updated']} mise(s) à jour, {stats['deleted']} supprimée(s)"
    db.add(ActivityLog(
        username=triggered_by.email.split("@")[0],
        user_id=triggered_by.id,
        action="sync_table",
        resource_type="table",
        resource_id=table_id,
        resource_name=table.name,
        details=message,
        table_id=table_id,
    ))

    sync.last_sync_at = datetime.now(timezone.utc)
    sync.last_sync_status = "ok"
    sync.last_sync_message = message
    db.commit()

    logger.info(f"[sync] table_id={table_id} — {message}")
    return stats
