"""Tests pour l'import automatique de fichiers (CSV / Excel)."""
import io
import json
import pytest

from app.import_utils import (
    detect_encoding, detect_separator,
    infer_column_type, normalize_value,
    parse_csv, parse_excel, sanitize_headers,
    MAX_ROWS,
)
from app.models import ColumnType


# ── Détection encodage ────────────────────────────────────────────────────────

class TestDetectEncoding:
    def test_utf8(self):
        raw = "Nom;Prénom\nAlice;Dupont".encode('utf-8')
        assert detect_encoding(raw).lower() in ('utf-8', 'ascii')

    def test_latin1(self):
        raw = "Nom;Prénom\nAlice;Dupont".encode('latin-1')
        enc = detect_encoding(raw)
        assert enc.lower() in ('iso-8859-1', 'latin-1', 'cp1252', 'windows-1252')


# ── Détection séparateur ──────────────────────────────────────────────────────

class TestDetectSeparator:
    def test_semicolon(self):
        assert detect_separator("Nom;Prénom;Age\nAlice;Dupont;30") == ';'

    def test_comma(self):
        assert detect_separator("Name,First,Age\nAlice,Dupont,30") == ','

    def test_tab(self):
        assert detect_separator("Name\tFirst\tAge\nAlice\tDupont\t30") == '\t'


# ── Parse CSV ─────────────────────────────────────────────────────────────────

class TestParseCSV:
    def test_basic(self):
        raw = "Nom;Age\nAlice;30\nBob;25".encode('utf-8')
        headers, rows, warning = parse_csv(raw)
        assert headers == ['Nom', 'Age']
        assert rows == [['Alice', '30'], ['Bob', '25']]
        assert warning is None

    def test_comma_separator(self):
        raw = "Name,Age\nAlice,30".encode('utf-8')
        headers, rows, _ = parse_csv(raw)
        assert headers == ['Name', 'Age']
        assert rows[0] == ['Alice', '30']

    def test_max_rows(self):
        lines = ["A;B"] + [f"val{i};{i}" for i in range(MAX_ROWS + 50)]
        raw = '\n'.join(lines).encode('utf-8')
        headers, rows, warning = parse_csv(raw)
        assert len(rows) == MAX_ROWS
        assert warning is not None

    def test_skips_empty_rows(self):
        raw = "A;B\nAlice;1\n\n\nBob;2".encode('utf-8')
        _, rows, _ = parse_csv(raw)
        assert len(rows) == 2


# ── Inférence de types ────────────────────────────────────────────────────────

class TestInferColumnType:
    def test_text(self):
        assert infer_column_type(['Alice', 'Bob', 'Charlie']) == ColumnType.TEXT

    def test_integer(self):
        assert infer_column_type(['1', '42', '-7', '100', '0']) == ColumnType.INTEGER

    def test_float(self):
        assert infer_column_type(['3.14', '2.71', '1.0', '0.5']) == ColumnType.FLOAT

    def test_float_french_comma(self):
        assert infer_column_type(['3,14', '2,71', '1,0', '0,5']) == ColumnType.FLOAT

    def test_date_iso(self):
        assert infer_column_type(['2024-01-15', '2023-12-31', '2025-06-01']) == ColumnType.DATE

    def test_date_french(self):
        assert infer_column_type(['15/01/2024', '31/12/2023', '01/06/2025']) == ColumnType.DATE

    def test_boolean_oui_non(self):
        vals = ['oui', 'non', 'oui', 'oui', 'non'] * 4
        assert infer_column_type(vals) == ColumnType.BOOLEAN

    def test_boolean_true_false(self):
        vals = ['true', 'false', 'true', 'false'] * 5
        assert infer_column_type(vals) == ColumnType.BOOLEAN

    def test_email(self):
        vals = ['a@b.com', 'x@y.fr', 'test@example.org'] * 3
        assert infer_column_type(vals) == ColumnType.EMAIL

    def test_select_heuristic(self):
        # 3 valeurs distinctes sur 20 lignes → SELECT
        vals = ['rouge', 'vert', 'bleu'] * 7
        assert infer_column_type(vals) == ColumnType.SELECT

    def test_not_select_if_too_many_distinct(self):
        # 20 valeurs distinctes → pas SELECT
        vals = [f'val_{i}' for i in range(20)]
        assert infer_column_type(vals) != ColumnType.SELECT

    def test_integer_no_leading_zero(self):
        # Valeurs avec zéro initial explicite → TEXT (ex: "007", "01")
        assert infer_column_type(['007', '042', '001']) == ColumnType.TEXT

    def test_empty_column_is_text(self):
        assert infer_column_type(['', '', '']) == ColumnType.TEXT

    def test_mixed_mostly_integer(self):
        # 95% d'entiers → INTEGER
        vals = ['1'] * 19 + ['texte']
        assert infer_column_type(vals) == ColumnType.INTEGER

    def test_mixed_below_threshold_is_text(self):
        # Moins de 95% → TEXT
        vals = ['1'] * 8 + ['texte'] * 2
        assert infer_column_type(vals) == ColumnType.TEXT


# ── Normalisation ─────────────────────────────────────────────────────────────

class TestNormalizeValue:
    def test_boolean_oui(self):
        assert normalize_value('oui', ColumnType.BOOLEAN) == 'true'

    def test_boolean_non(self):
        assert normalize_value('non', ColumnType.BOOLEAN) == 'false'

    def test_date_french_to_iso(self):
        assert normalize_value('15/01/2024', ColumnType.DATE) == '2024-01-15'

    def test_date_iso_unchanged(self):
        assert normalize_value('2024-01-15', ColumnType.DATE) == '2024-01-15'

    def test_float_comma_to_dot(self):
        assert normalize_value('3,14', ColumnType.FLOAT) == '3.14'

    def test_text_unchanged(self):
        assert normalize_value('Hello World', ColumnType.TEXT) == 'Hello World'

    def test_empty_unchanged(self):
        assert normalize_value('', ColumnType.INTEGER) == ''


# ── Nettoyage en-têtes ────────────────────────────────────────────────────────

class TestSanitizeHeaders:
    def test_strips_whitespace(self):
        assert sanitize_headers(['  Nom  ', ' Prénom ']) == ['Nom', 'Prénom']

    def test_deduplicates(self):
        result = sanitize_headers(['Col', 'Col', 'Col'])
        assert result == ['Col', 'Col_2', 'Col_3']

    def test_empty_header_replaced(self):
        result = sanitize_headers(['', 'Nom'])
        assert result[0] == 'Colonne'

    def test_limits_to_max_cols(self):
        from app.import_utils import MAX_COLS
        headers = [f'Col{i}' for i in range(MAX_COLS + 10)]
        assert len(sanitize_headers(headers)) == MAX_COLS


# ── Routes HTTP ───────────────────────────────────────────────────────────────

class TestImportAutoRoutes:
    def test_upload_page_requires_auth(self, client):
        r = client.get('/import-auto/')
        assert r.status_code in (302, 303)

    def test_upload_page_ok(self, admin_client):
        r = admin_client.get('/import-auto/')
        assert r.status_code == 200
        assert 'Importer' in r.text

    def test_analyze_csv(self, admin_client):
        csv_content = b"Nom;Age;Email\nAlice;30;alice@test.com\nBob;25;bob@test.com"
        r = admin_client.post('/import-auto/analyze', files={
            'file': ('test.csv', csv_content, 'text/csv')
        }, data={'sheet_index': '0'})
        assert r.status_code == 200
        assert 'Nom' in r.text
        assert 'Alice' in r.text

    def test_analyze_detects_types(self, admin_client):
        csv_content = b"Nom;Age;Email\nAlice;30;alice@test.com\nBob;25;bob@test.com"
        r = admin_client.post('/import-auto/analyze', files={
            'file': ('test.csv', csv_content, 'text/csv')
        }, data={'sheet_index': '0'})
        assert r.status_code == 200
        # Le type email doit être détecté
        assert 'email' in r.text.lower()

    def test_analyze_file_too_large(self, admin_client):
        big = b'A;B\n' + b'x;y\n' * 1000
        # Simuler un fichier > 10 Mo
        from app.import_utils import MAX_FILE_SIZE
        huge = b'A;B\n' + (b'x' * 100 + b';y\n') * (MAX_FILE_SIZE // 100 + 1)
        r = admin_client.post('/import-auto/analyze', files={
            'file': ('big.csv', huge, 'text/csv')
        }, data={'sheet_index': '0'})
        assert r.status_code == 200
        assert 'limite' in r.text.lower() or 'Mo' in r.text

    def test_confirm_creates_table(self, admin_client, db):
        from app.models import DataTable
        csv_content = b"Produit;Prix;Stock\nChaise;49.99;100\nTable;199.0;20"
        r = admin_client.post('/import-auto/analyze', files={
            'file': ('produits.csv', csv_content, 'text/csv')
        }, data={'sheet_index': '0'})
        assert r.status_code == 200

        # Extraire le payload_json de la réponse
        import re
        match = re.search(r'name="payload_json" value="([^"]+)"', r.text)
        assert match, "payload_json introuvable dans la réponse"
        payload_json = match.group(1).replace('&quot;', '"').replace('&#34;', '"')

        payload = json.loads(payload_json)
        nb_cols = len(payload['headers'])

        r2 = admin_client.post('/import-auto/confirm', data={
            'table_name': 'Produits Test',
            'payload_json': payload_json,
            'col_name': payload['headers'],
            'col_type': payload['col_types'],
        })
        assert r2.status_code in (302, 303)

        table = db.query(DataTable).filter_by(name='Produits Test').first()
        assert table is not None
        assert len(table.columns) == nb_cols
        assert len([r for r in table.rows if r.deleted_at is None]) == 2

    def test_confirm_unique_table_name(self, admin_client, admin_user, db):
        from app.models import DataTable, TableOwner
        # Créer une table existante avec le même nom
        existing = DataTable(name='Import', created_by_id=admin_user.id)
        db.add(existing)
        db.flush()
        db.add(TableOwner(table_id=existing.id, user_id=admin_user.id))
        db.commit()

        payload = json.dumps({
            'headers': ['A'], 'rows': [['val']],
            'col_types': ['text'], 'select_options': [''],
        })
        r = admin_client.post('/import-auto/confirm', data={
            'table_name': 'Import',
            'payload_json': payload,
            'col_name': ['A'],
            'col_type': ['text'],
        })
        assert r.status_code in (302, 303)
        tables = db.query(DataTable).filter(DataTable.name.like('Import%')).all()
        names = [t.name for t in tables]
        assert 'Import (2)' in names
