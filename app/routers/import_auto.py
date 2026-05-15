"""
Router pour la création automatique de table depuis un fichier CSV ou Excel.
Flux en deux étapes :
  1. POST /import-auto/analyze  → analyse le fichier, retourne la page de preview
  2. POST /import-auto/confirm  → crée la table, les colonnes, insère les lignes
"""
import json
import os

from fastapi import APIRouter, Depends, File, Form, Request, UploadFile
from fastapi.responses import HTMLResponse, RedirectResponse, StreamingResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import insert as sa_insert
from sqlalchemy.orm import Session

from app.activity import log_action
from app.database import get_db
from app.dependencies import get_current_user
from app.import_utils import (
    MAX_FILE_SIZE, MAX_ROWS, MAX_COLS,
    infer_column_type, normalize_value,
    parse_csv, parse_excel, sanitize_headers,
)
from app.models import CellValue, ColumnType, DataTable, TableColumn, TableOwner, TableRow, User

router = APIRouter(prefix="/import-auto", tags=["import-auto"])
templates = Jinja2Templates(directory="app/templates")

COLUMN_TYPES = [e.value for e in ColumnType]
PREVIEW_ROWS = 5  # nombre de lignes affichées dans la preview


# ── Helpers ────────────────────────────────────────────────────────────────────

def _unique_table_name(db: Session, base_name: str) -> str:
    """Retourne un nom de table unique en ajoutant un suffixe si nécessaire."""
    name = base_name
    suffix = 2
    while db.query(DataTable).filter_by(name=name, deleted_at=None).first():
        name = f"{base_name} ({suffix})"
        suffix += 1
    return name


def _col_type_label(col_type: ColumnType) -> str:
    labels = {
        ColumnType.TEXT: "Texte",
        ColumnType.INTEGER: "Entier",
        ColumnType.FLOAT: "Décimal",
        ColumnType.DATE: "Date",
        ColumnType.DATETIME: "Date+Heure",
        ColumnType.BOOLEAN: "Oui/Non",
        ColumnType.EMAIL: "Email",
        ColumnType.SELECT: "Liste",
        ColumnType.LATITUDE: "Latitude",
        ColumnType.LONGITUDE: "Longitude",
    }
    return labels.get(col_type, col_type.value)


# ── Page d'upload ──────────────────────────────────────────────────────────────

@router.get("/", response_class=HTMLResponse)
def upload_page(
    request: Request,
    user: User = Depends(get_current_user),
):
    return templates.TemplateResponse(request, "import_auto/upload.html", {"user": user})


# ── Étape 1 : analyse ─────────────────────────────────────────────────────────

@router.post("/analyze", response_class=HTMLResponse)
async def analyze_file(
    request: Request,
    file: UploadFile = File(...),
    sheet_index: int = Form(0),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    raw = await file.read()

    # Taille
    if len(raw) > MAX_FILE_SIZE:
        return templates.TemplateResponse(request, "import_auto/upload.html", {
            "user": user,
            "error": f"Le fichier dépasse la limite de {MAX_FILE_SIZE // 1024 // 1024} Mo.",
        })

    # Détection format
    filename = file.filename or "import"
    ext = os.path.splitext(filename)[1].lower()
    sheet_names: list[str] = []
    warning: str | None = None

    if ext in (".xlsx", ".xls", ".xlsm"):
        try:
            headers, rows, sheet_names, warning = parse_excel(raw, sheet_index)
        except Exception as e:
            return templates.TemplateResponse(request, "import_auto/upload.html", {
                "user": user,
                "error": f"Impossible de lire le fichier Excel : {e}",
            })
    else:
        try:
            headers, rows, warning = parse_csv(raw)
        except Exception as e:
            return templates.TemplateResponse(request, "import_auto/upload.html", {
                "user": user,
                "error": f"Impossible de lire le fichier CSV : {e}",
            })

    if not headers:
        return templates.TemplateResponse(request, "import_auto/upload.html", {
            "user": user,
            "error": "Le fichier est vide ou ne contient pas d'en-tête.",
        })

    # Nettoyage en-têtes, limite colonnes
    headers = sanitize_headers(headers)
    nb_cols = len(headers)
    if nb_cols > MAX_COLS:
        headers = headers[:MAX_COLS]
        warning = (warning or "") + f" Les colonnes ont été limitées à {MAX_COLS}."

    # Aligner les lignes sur le nombre de colonnes
    rows = [
        row[:nb_cols] + [''] * max(0, nb_cols - len(row))
        for row in rows
    ]

    # Inférence des types
    col_types: list[ColumnType] = []
    select_options: list[str] = []  # options pour les colonnes SELECT
    for i, col_name in enumerate(headers):
        col_values = [row[i] for row in rows]
        ct = infer_column_type(col_values, col_name=col_name)
        col_types.append(ct)
        if ct == ColumnType.SELECT:
            opts = sorted(set(v.strip() for v in col_values if v.strip()))
            select_options.append(','.join(opts))
        else:
            select_options.append('')

    # Nom de table par défaut = nom du fichier sans extension
    default_name = _unique_table_name(db, os.path.splitext(filename)[0].strip() or "Import")

    # Données brutes encodées pour la confirmation (JSON + base64 pour sécurité)
    payload = json.dumps({
        "headers": headers,
        "rows": rows,
        "col_types": [ct.value for ct in col_types],
        "select_options": select_options,
    })

    return templates.TemplateResponse(request, "import_auto/preview.html", {
        "user": user,
        "filename": filename,
        "default_name": default_name,
        "headers": headers,
        "col_types": col_types,
        "col_type_labels": [_col_type_label(ct) for ct in col_types],
        "select_options": select_options,
        "all_types": COLUMN_TYPES,
        "preview_rows": rows[:PREVIEW_ROWS],
        "total_rows": len(rows),
        "warning": warning,
        "sheet_names": sheet_names,
        "sheet_index": sheet_index,
        "payload_json": payload,
        "is_excel": bool(sheet_names),
    })


# ── Étape 2 : confirmation & création ─────────────────────────────────────────

@router.post("/confirm", response_class=HTMLResponse)
async def confirm_import(
    request: Request,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    form = await request.form()

    table_name = str(form.get("table_name", "")).strip() or "Import"
    table_name = _unique_table_name(db, table_name)
    payload_json = str(form.get("payload_json", "{}"))

    try:
        payload = json.loads(payload_json)
    except json.JSONDecodeError:
        return RedirectResponse(url="/import-auto/", status_code=303)

    headers: list[str] = payload.get("headers", [])
    rows: list[list[str]] = payload.get("rows", [])
    stored_types: list[str] = payload.get("col_types", [])
    stored_options: list[str] = payload.get("select_options", [])

    if not headers:
        return RedirectResponse(url="/import-auto/", status_code=303)

    # Récupérer les overrides de type et de nom saisis par l'utilisateur
    col_names_override = form.getlist("col_name")
    col_types_override = form.getlist("col_type")
    col_ignore = set(form.getlist("col_ignore"))  # indices en string

    # Construire la liste finale des colonnes à créer
    final_cols: list[dict] = []
    for i, header in enumerate(headers):
        if str(i) in col_ignore:
            continue
        name = col_names_override[i].strip() if i < len(col_names_override) else header
        type_val = col_types_override[i] if i < len(col_types_override) else stored_types[i] if i < len(stored_types) else "text"
        try:
            ct = ColumnType(type_val)
        except ValueError:
            ct = ColumnType.TEXT
        opts = stored_options[i] if i < len(stored_options) else ''
        final_cols.append({"orig_index": i, "name": name or header, "type": ct, "options": opts})

    if not final_cols:
        return RedirectResponse(url="/import-auto/", status_code=303)

    # Créer la table
    table = DataTable(name=table_name, created_by_id=user.id)
    db.add(table)
    db.flush()

    # Propriétaire
    db.add(TableOwner(table_id=table.id, user_id=user.id))

    # Créer les colonnes
    col_objects: list[TableColumn] = []
    for order, col_def in enumerate(final_cols):
        tc = TableColumn(
            table_id=table.id,
            name=col_def["name"],
            col_type=col_def["type"],
            order=order,
            required=False,
            select_options=col_def["options"] if col_def["type"] == ColumnType.SELECT else "",
        )
        db.add(tc)
        col_objects.append(tc)
    db.flush()

    # Insérer les lignes
    row_objects: list[tuple[TableRow, list[str]]] = []
    for row_data in rows[:MAX_ROWS]:
        row = TableRow(table_id=table.id, created_by_id=user.id)
        db.add(row)
        row_objects.append((row, row_data))

    db.flush()  # un seul flush pour obtenir tous les IDs

    cell_dicts: list[dict] = []
    for row, row_data in row_objects:
        for col_obj, col_def in zip(col_objects, final_cols):
            raw_val = row_data[col_def["orig_index"]] if col_def["orig_index"] < len(row_data) else ''
            cell_dicts.append({
                "row_id": row.id,
                "column_id": col_obj.id,
                "value": normalize_value(raw_val, col_def["type"]),
            })

    # Insertion par lots pour éviter les erreurs I/O SQLite sur filesystem Windows/WSL
    _CHUNK = 500
    for i in range(0, len(cell_dicts), _CHUNK):
        db.execute(sa_insert(CellValue), cell_dicts[i:i + _CHUNK])
    nb_inserted = len(row_objects)

    log_action(
        db, user,
        action="import_auto",
        resource_type="table",
        resource_id=table.id,
        resource_name=table_name,
        details=f"{nb_inserted} ligne(s), {len(final_cols)} colonne(s) importées depuis fichier",
        table_id=table.id,
    )

    db.commit()

    return RedirectResponse(url=f"/tables/{table.id}", status_code=303)


# ── Étape 2 (SSE) : confirmation avec progression temps réel ──────────────────

@router.post("/confirm-stream")
async def confirm_import_stream(
    request: Request,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Même logique que /confirm mais envoie des événements SSE pour la progression."""
    form = await request.form()

    table_name = str(form.get("table_name", "")).strip() or "Import"
    table_name = _unique_table_name(db, table_name)
    payload_json = str(form.get("payload_json", "{}"))

    try:
        payload = json.loads(payload_json)
    except json.JSONDecodeError:
        return RedirectResponse(url="/import-auto/", status_code=303)

    headers: list[str] = payload.get("headers", [])
    rows: list[list[str]] = payload.get("rows", [])
    stored_types: list[str] = payload.get("col_types", [])
    stored_options: list[str] = payload.get("select_options", [])

    if not headers:
        return RedirectResponse(url="/import-auto/", status_code=303)

    col_names_override = form.getlist("col_name")
    col_types_override = form.getlist("col_type")
    col_ignore = set(form.getlist("col_ignore"))

    final_cols: list[dict] = []
    for i, header in enumerate(headers):
        if str(i) in col_ignore:
            continue
        name = col_names_override[i].strip() if i < len(col_names_override) else header
        type_val = col_types_override[i] if i < len(col_types_override) else stored_types[i] if i < len(stored_types) else "text"
        try:
            ct = ColumnType(type_val)
        except ValueError:
            ct = ColumnType.TEXT
        opts = stored_options[i] if i < len(stored_options) else ''
        final_cols.append({"orig_index": i, "name": name or header, "type": ct, "options": opts})

    if not final_cols:
        return RedirectResponse(url="/import-auto/", status_code=303)

    def _evt(data: dict) -> str:
        return f"data: {json.dumps(data)}\n\n"

    async def generate():
        try:
            yield _evt({"progress": 5, "message": "Création de la table…"})

            table = DataTable(name=table_name, created_by_id=user.id)
            db.add(table)
            db.flush()
            db.add(TableOwner(table_id=table.id, user_id=user.id))

            yield _evt({"progress": 15, "message": "Création des colonnes…"})

            col_objects: list[TableColumn] = []
            for order, col_def in enumerate(final_cols):
                tc = TableColumn(
                    table_id=table.id,
                    name=col_def["name"],
                    col_type=col_def["type"],
                    order=order,
                    required=False,
                    select_options=col_def["options"] if col_def["type"] == ColumnType.SELECT else "",
                )
                db.add(tc)
                col_objects.append(tc)
            db.flush()

            total_rows = len(rows[:MAX_ROWS])
            yield _evt({"progress": 20, "message": f"Insertion de {total_rows:,} lignes…"})

            row_objects: list[tuple] = []
            for row_data in rows[:MAX_ROWS]:
                row = TableRow(table_id=table.id, created_by_id=user.id)
                db.add(row)
                row_objects.append((row, row_data))
            db.flush()

            cell_dicts: list[dict] = []
            for row, row_data in row_objects:
                for col_obj, col_def in zip(col_objects, final_cols):
                    raw_val = row_data[col_def["orig_index"]] if col_def["orig_index"] < len(row_data) else ''
                    cell_dicts.append({
                        "row_id": row.id,
                        "column_id": col_obj.id,
                        "value": normalize_value(raw_val, col_def["type"]),
                    })

            _CHUNK = 500
            nb_cols = max(len(final_cols), 1)
            total_cells = len(cell_dicts)

            if total_cells == 0:
                yield _evt({"progress": 95, "message": "Finalisation…"})
            else:
                for i in range(0, total_cells, _CHUNK):
                    db.execute(sa_insert(CellValue), cell_dicts[i:i + _CHUNK])
                    done_cells = min(i + _CHUNK, total_cells)
                    done_rows = done_cells // nb_cols
                    progress = 25 + int(done_cells / total_cells * 70)
                    yield _evt({
                        "progress": min(progress, 95),
                        "message": f"{done_rows:,} / {total_rows:,} lignes importées…",
                    })

            log_action(
                db, user,
                action="import_auto",
                resource_type="table",
                resource_id=table.id,
                resource_name=table_name,
                details=f"{total_rows} ligne(s), {len(final_cols)} colonne(s) importées depuis fichier",
                table_id=table.id,
            )
            db.commit()

            yield _evt({"progress": 100, "done": True, "redirect": f"/tables/{table.id}"})

        except Exception as e:
            try:
                db.rollback()
            except Exception:
                pass
            yield _evt({"error": str(e)})

    return StreamingResponse(generate(), media_type="text/event-stream")
