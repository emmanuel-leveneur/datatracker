"""
Chiffre une base SQLite existante avec SQLCipher (AES-256).

Usage :
    python scripts/encrypt_db.py --db ~/datatracker.db --key <votre_clé>

Le fichier original est conservé sous <db>.bak avant d'être remplacé.
"""

import argparse
import shutil
import sys
from pathlib import Path


def main():
    parser = argparse.ArgumentParser(description="Chiffre une base SQLite avec SQLCipher.")
    parser.add_argument("--db", required=True, help="Chemin vers le fichier .db existant")
    parser.add_argument("--key", required=True, help="Clé de chiffrement (conserver précieusement)")
    args = parser.parse_args()

    db_path = Path(args.db).expanduser().resolve()
    if not db_path.exists():
        print(f"Erreur : fichier introuvable : {db_path}", file=sys.stderr)
        sys.exit(1)

    try:
        import sqlcipher3
    except ImportError:
        print("Erreur : sqlcipher3 n'est pas installé.", file=sys.stderr)
        print("  sudo apt-get install libsqlcipher-dev && pip install sqlcipher3", file=sys.stderr)
        sys.exit(1)

    backup_path = db_path.with_suffix(".db.bak")
    print(f"Sauvegarde : {db_path} → {backup_path}")
    shutil.copy2(db_path, backup_path)

    tmp_path = db_path.with_suffix(".db.enc_tmp")
    tmp_path.unlink(missing_ok=True)
    try:
        # Ouvrir la base en clair avec sqlcipher3 (sans PRAGMA key = mode plaintext),
        # puis ATTACH la cible chiffrée et utiliser sqlcipher_export.
        safe_key = args.key.replace("'", "''")
        safe_tmp = str(tmp_path).replace("'", "''")
        conn = sqlcipher3.connect(str(db_path))
        conn.execute(f"ATTACH DATABASE '{safe_tmp}' AS encrypted KEY '{safe_key}'")
        conn.execute("SELECT sqlcipher_export('encrypted')")
        conn.execute("DETACH DATABASE encrypted")
        conn.close()
    except Exception as exc:
        tmp_path.unlink(missing_ok=True)
        print(f"Erreur pendant le chiffrement : {exc}", file=sys.stderr)
        sys.exit(1)

    tmp_path.replace(db_path)
    print(f"Base chiffrée avec succès : {db_path}")
    print(f"Sauvegarde conservée       : {backup_path}")
    print()
    print("Ajoutez dans votre .env :")
    print(f"  DB_ENCRYPTION_KEY={args.key}")


if __name__ == "__main__":
    main()
