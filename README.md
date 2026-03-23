# DataTracker

> Application web de gestion de tables de données dynamiques avec contrôle d'accès granulaire, traçabilité complète et corbeille.

---

## Sommaire

1. [Présentation](#présentation)
2. [Stack technique](#stack-technique)
3. [Architecture](#architecture)
4. [Modèle de données](#modèle-de-données)
5. [Fonctionnalités](#fonctionnalités)
6. [Sécurité et permissions](#sécurité-et-permissions)
7. [Traçabilité et journaux](#traçabilité-et-journaux)
8. [Structure des fichiers](#structure-des-fichiers)
9. [Installation et lancement](#installation-et-lancement)
10. [Tests](#tests)
11. [Conventions de développement](#conventions-de-développement)

---

## Présentation

DataTracker permet à des utilisateurs de créer leurs propres tables de données structurées, d'y saisir des enregistrements, de les partager avec des droits fins, et de consulter l'historique complet de chaque modification.

Cas d'usage typiques : suivi d'inventaire, gestion de contacts, tableaux de bord internes, collecte de données collaboratives.

---

## Stack technique

| Couche | Technologie |
|---|---|
| Framework web | FastAPI 0.115 |
| ORM / base de données | SQLAlchemy 2.0 + SQLite |
| Templating | Jinja2 3.1 |
| CSS | Tailwind CSS (CDN) |
| Interactions dynamiques | HTMX 1.9 |
| Tableaux interactifs | DataTables 1.13.8 + Buttons 2.4.2 |
| Icônes | Lucide (CDN) |
| Authentification | Cookie signé itsdangerous (7 jours) + bcrypt |
| Export | openpyxl (Excel) |
| Tâches planifiées | APScheduler 3.10 |
| Tests | pytest + FastAPI TestClient + SQLite in-memory |

Pas de build step frontend. Pas de framework JS. Tout est rendu côté serveur (SSR) avec des enrichissements HTMX ponctuels.

---

## Architecture

```
┌─────────────────────────────────────────────────────┐
│                     Navigateur                      │
│          Tailwind CSS · HTMX · DataTables · Lucide  │
└────────────────────┬────────────────────────────────┘
                     │ HTTP
┌────────────────────▼────────────────────────────────┐
│                    FastAPI                          │
│                                                     │
│  /auth          /tables         /admin              │
│  /tables/{id}   /tables/{id}/   /admin/logs         │
│  /rows          tracabilite     /admin/users        │
│                                                     │
│  Dépendances transversales (app/dependencies.py) :  │
│  get_current_user · can_access_table                │
│  get_visible_columns · is_column_readonly           │
└────────────────────┬────────────────────────────────┘
                     │ SQLAlchemy ORM (sync)
┌────────────────────▼────────────────────────────────┐
│                   SQLite                            │
│   datatracker.db  (migrations auto au démarrage)   │
└─────────────────────────────────────────────────────┘
```

### Flux d'une requête type

1. Le navigateur envoie une requête (formulaire POST ou HTMX).
2. FastAPI résout les dépendances : session → utilisateur → vérification d'accès.
3. Le router effectue l'opération DB, appelle `log_action()` avant `db.commit()`.
4. La réponse est soit un redirect (actions POST), soit un template HTML rendu, soit un fragment HTML (HTMX).

---

## Modèle de données

Le schéma repose sur un modèle **EAV** (Entity–Attribute–Value) pour les données dynamiques.

```
User
 ├── DataTable (created_by_id)
 │    ├── TableColumn (name, col_type, order, required, select_options)
 │    ├── TableRow (created_by_id, deleted_at)
 │    │    └── CellValue (column_id, value: Text)
 │    └── TablePermission (user_id, level: READ|WRITE)
 │
 ├── ColumnPermission (column_id, hidden, readonly)
 ├── TableFavorite (table_id)
 └── ActivityLog (action, resource_type, resource_name, details, table_id)
```

### Types de colonnes

`text` · `integer` · `float` · `date` · `boolean` · `email` · `select`

### Soft-delete

`DataTable.deleted_at` et `TableRow.deleted_at` permettent la mise en corbeille sans suppression physique immédiate. La suppression définitive est une action explicite depuis la corbeille.

### Migrations

Les colonnes ajoutées après la création initiale sont gérées par `_run_migrations()` dans `app/database.py` : lecture du `PRAGMA table_info` SQLite, exécution conditionnelle des `ALTER TABLE`. Idempotent au redémarrage.

---

## Fonctionnalités

### Gestion des tables

- Création de tables avec colonnes typées, ordre personnalisable, champ obligatoire
- Modification de schéma (ajout, renommage, suppression de colonnes)
- Export Excel stylisé (colonnes visibles uniquement, respects des permissions)
- Import CSV (mapping par nom de colonne, insensible à la casse)
- Corbeille : mise en corbeille → restauration ou suppression définitive

### Gestion des lignes

- Saisie via formulaire HTMX (pas de rechargement de page)
- Modification inline
- Mise en corbeille avec restauration possible
- Affichage booléen, lien mailto pour les emails

### Favoris

- Chaque utilisateur peut marquer des tables en favori (étoile)
- Section "Mes favoris" affichée en haut de la liste
- Recherche en temps réel sur nom et description (filtrage côté client)

### Authentification

- Inscription avec email unique + nom d'utilisateur
- **Connexion par email + mot de passe**
- Le premier utilisateur inscrit devient automatiquement administrateur
- Sessions cookie signées (itsdangerous, expiration 7 jours)
- Affichage du préfixe email (avant `@`) dans l'interface

---

## Sécurité et permissions

### Niveaux d'accès

| Rôle | Périmètre |
|---|---|
| **Administrateur** | Voit et gère toutes les tables, tous les utilisateurs, tous les journaux |
| **Propriétaire** | Contrôle total sur ses tables (schéma, permissions, corbeille) |
| **READ** | Lecture des données, consultation de la traçabilité |
| **WRITE** | Lecture + ajout/modification/corbeille des lignes |

### Permissions par colonne (`ColumnPermission`)

Pour chaque couple (colonne, utilisateur) :
- `hidden` : la colonne n'est pas visible dans la vue ni dans l'export
- `readonly` : la valeur est visible mais non modifiable

Ces permissions sont gérées depuis deux interfaces :
- `/tables/{id}/permissions` — par le propriétaire de la table
- `/admin/users/{id}/permissions` — par un administrateur, vue par utilisateur

---

## Traçabilité et journaux

### Journal d'activité (`/admin/logs`)

Réservé aux administrateurs. Affiche les 1 000 dernières actions toutes tables confondues.

### Traçabilité par table (`/tables/{id}/tracabilite`)

Accessible à tout utilisateur ayant accès à la table. Filtre sur `ActivityLog.table_id`.

### Actions tracées

| Action | Déclencheur |
|---|---|
| `register` / `login` | Auth |
| `create_table` / `edit_table` | Schéma de table |
| `trash_table` / `restore_table` / `delete_table` | Corbeille table |
| `create_row` / `update_row` | Données |
| `trash_row` / `restore_row` / `delete_row` | Corbeille lignes |
| `import_csv` | Import |
| `update_permissions` / `update_user_permissions` | Permissions |
| `toggle_admin` / `delete_user` | Admin utilisateurs |

### Format du champ `details`

- **Modification de table** : diff ligne par ligne — `Nom : "Avant" → "Après"`
- **Modification de ligne** : diff par colonne — `"Col" : "avant" → "après"`
- **Permissions** : diff par utilisateur — `Accès "alice" : "none" → "write"`
- **Lignes (create/trash/restore/delete)** : `Ligne #42 avec Col1 -> Val1, Col2 -> Val2 créée le JJ/MM/AAAA HH:MM`

Le champ `username` stocke le **préfixe email** de l'acteur (partie avant `@`). Il est dénormalisé : il reste lisible même si l'utilisateur est supprimé.

---

## Structure des fichiers

```
datatracker/
├── app/
│   ├── main.py              # Création FastAPI, lifespan, include_router, handlers 403/404
│   ├── models.py            # Tous les modèles SQLAlchemy
│   ├── database.py          # Engine SQLite, get_db(), create_tables(), _run_migrations()
│   ├── auth.py              # bcrypt, sessions itsdangerous
│   ├── activity.py          # log_action() — helper transversal
│   ├── dependencies.py      # get_current_user, can_access_table, get_visible_columns…
│   ├── scheduler.py         # APScheduler — nettoyage orphelins à 3h
│   └── routers/
│       ├── auth.py          # /auth/login · /auth/register · /auth/logout
│       ├── tables.py        # /tables/ · /tables/create · /tables/{id} · corbeille
│       ├── data.py          # /tables/{id}/rows/* · import CSV
│       ├── export.py        # /tables/{id}/export/excel
│       ├── permissions.py   # /tables/{id}/permissions/bulk
│       ├── admin.py         # /admin/users · /admin/users/{id}/permissions
│       ├── logs.py          # /admin/logs — ACTION_LABELS, RESOURCE_LABELS
│       └── tracabilite.py   # /tables/{id}/tracabilite
│
├── app/templates/
│   ├── base.html            # Layout, navbar, CDN (Tailwind, HTMX, DataTables, Lucide)
│   ├── auth/                # login.html · register.html
│   ├── tables/              # list · detail · create · edit · import · tracabilite
│   ├── partials/            # table_rows.html · row_form.html (fragments HTMX)
│   ├── permissions/         # manage.html
│   ├── admin/               # users · user_permissions · logs
│   └── errors/              # 403 · 404
│
├── tests/
│   ├── conftest.py          # Fixtures : DB in-memory, admin_client, user_client
│   ├── helpers.py           # make_table()
│   ├── test_auth.py
│   ├── test_tables.py
│   ├── test_data.py
│   ├── test_permissions.py
│   ├── test_admin.py
│   ├── test_logs.py
│   └── test_tracabilite.py
│
├── requirements.txt
└── pytest.ini
```

---

## Installation et lancement

### Prérequis

- Python 3.11+

### Installation

```bash
python3 -m venv venv
source venv/bin/activate        # Linux/macOS
# ou : venv\Scripts\activate    # Windows

pip install -r requirements.txt
```

### Lancement en développement

```bash
uvicorn app.main:app --reload
```

L'application est accessible sur `http://localhost:8000`.

La base de données `datatracker.db` est créée automatiquement au premier démarrage. Le premier utilisateur inscrit obtient le rôle administrateur.

### Variables d'environnement

Aucune configuration obligatoire. La clé de signature des sessions est définie dans `app/auth.py` (`SECRET_KEY`) — à remplacer par une valeur secrète en production.

---

## Tests

```bash
# Tous les tests
pytest

# Un fichier
pytest tests/test_tables.py

# Un test précis
pytest tests/test_data.py::test_create_row_as_owner -v
```

Les tests utilisent une base SQLite **en mémoire** (StaticPool). Chaque test part d'un schéma vierge (`create_all` / `drop_all` via fixture `autouse`).

Couverture actuelle : **101 tests**, tous verts.

---

## Conventions de développement

### Ajouter une fonctionnalité

1. **Modèle** : ajouter le modèle ou la colonne dans `app/models.py`. Si c'est une nouvelle colonne sur une table existante, ajouter la migration dans `_run_migrations()`.
2. **Router** : créer ou modifier le router dans `app/routers/`. Appeler `log_action()` avant chaque `db.commit()` pour les actions importantes.
3. **Template** : créer ou modifier le template Jinja2. Utiliser `{% block scripts %}` pour le JS spécifique à la page.
4. **Tests** : couvrir les cas nominaux et les cas d'erreur (403, 404, contraintes).

### Patterns à respecter

- Les dépendances FastAPI (`get_current_user`, `can_access_table`, etc.) sont dans `app/dependencies.py` — ne pas dupliquer ces vérifications dans les routes.
- Les icônes utilisent Lucide (`<i data-lucide="nom">`) — `lucide.createIcons()` est appelé automatiquement au chargement et après chaque swap HTMX.
- Les tables HTML interactives utilisent DataTables avec `DT_LANG_FR`, `DT_BUTTONS` et `dtColFilters()` définis dans `base.html`.
- Le soft-delete se fait via `deleted_at = datetime.utcnow()`. Les queries doivent filtrer `deleted_at == None` pour les vues actives.
