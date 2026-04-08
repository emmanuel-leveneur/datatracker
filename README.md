# DataTracker

> Application web de gestion de tables de données dynamiques avec contrôle d'accès granulaire, traçabilité complète, alertes conditionnelles et commentaires collaboratifs.

---

## Sommaire

1. [Présentation](#présentation)
2. [Stack technique](#stack-technique)
3. [Architecture applicative](#architecture-applicative)
4. [Modèle de données](#modèle-de-données)
5. [Routers et routes](#routers-et-routes)
6. [Couche dépendances (dependencies.py)](#couche-dépendances)
7. [Gestion des sessions et authentification](#gestion-des-sessions-et-authentification)
8. [Sécurité et permissions](#sécurité-et-permissions)
9. [Traçabilité et journaux](#traçabilité-et-journaux)
10. [Système d'alertes](#système-dalertes)
11. [Commentaires par ligne](#commentaires-par-ligne)
12. [Import automatique CSV/Excel](#import-automatique-csvexcel)
13. [Rendu frontend](#rendu-frontend)
14. [Structure des fichiers](#structure-des-fichiers)
15. [Installation et lancement](#installation-et-lancement)
16. [Tests](#tests)
17. [Conventions de développement](#conventions-de-développement)

---

## Présentation

DataTracker permet à des utilisateurs de créer leurs propres tables de données structurées, d'y saisir des enregistrements, de les partager avec des droits fins, et de consulter l'historique complet de chaque modification.

Cas d'usage typiques : suivi d'inventaire, gestion de contacts, tableaux de bord internes, collecte de données collaboratives.

---

## Stack technique

| Couche | Technologie | Version |
|---|---|---|
| Framework web | FastAPI | 0.115 |
| ORM / base de données | SQLAlchemy (synchrone) + SQLite | 2.0 / SQLite 3 |
| Templating | Jinja2 | 3.1 |
| CSS | Tailwind CSS | CDN |
| Interactions dynamiques | HTMX | 1.9.12 |
| Tableaux interactifs | DataTables + Buttons plugin | 1.13.8 / 2.4.2 |
| Icônes | Lucide | CDN (latest) |
| Authentification | itsdangerous (cookie signé) + bcrypt | — |
| Export Excel | openpyxl | — |
| Import CSV/Excel | chardet + openpyxl | — |
| Tâches planifiées | APScheduler | 3.10 |
| Tests | pytest + FastAPI TestClient | — |

**Pas de build step frontend.** Pas de framework JS. Tout est rendu côté serveur (SSR) avec des enrichissements HTMX ponctuels pour les mises à jour partielles de page.

---

## Architecture applicative

```
┌──────────────────────────────────────────────────────────────────┐
│                          Navigateur                              │
│   Tailwind CSS · HTMX 1.9 · DataTables · Lucide · localStorage  │
└───────────────────────────┬──────────────────────────────────────┘
                            │ HTTP (GET / POST form / HTMX fetch)
┌───────────────────────────▼──────────────────────────────────────┐
│                         FastAPI                                  │
│                                                                  │
│  /auth/*           Authentification (login, register, logout)    │
│  /tables/*         CRUD tables, colonnes, lignes, corbeille      │
│  /tables/{id}/     Permissions, export, traçabilité, alertes,    │
│                    commentaires, import                          │
│  /import-auto/*    Import automatique CSV / Excel                │
│  /notifications    Centre de notifications                       │
│  /admin/*          Administration utilisateurs + journaux        │
│  /permissions/*    Cascade permissions colonnes de relation      │
│                                                                  │
│  app/dependencies.py — dépendances transversales :              │
│    get_current_user · can_access_table · is_table_owner          │
│    get_visible_columns · is_column_readonly · require_admin      │
└───────────────────────────┬──────────────────────────────────────┘
                            │ SQLAlchemy ORM (synchrone)
┌───────────────────────────▼──────────────────────────────────────┐
│                         SQLite                                   │
│   datatracker.db — migrations auto au démarrage (_run_migrations)│
└──────────────────────────────────────────────────────────────────┘

Tâche planifiée (APScheduler)
  → Nettoyage orphelins à 3h00 : DELETE rows sans CellValue
```

### Flux d'une requête type

1. Le navigateur envoie une requête (formulaire POST classique ou HTMX partiel).
2. FastAPI résout les dépendances : cookie → `user_id` → objet `User` → vérification d'accès à la table.
3. Le router effectue l'opération DB, appelle `log_action()` **avant** `db.commit()`.
4. La réponse est :
   - un **redirect** (actions POST classiques, ex. création de ligne),
   - un **template HTML complet** (GET de pages),
   - un **fragment HTML** (réponse HTMX, ex. rechargement du tableau).
5. Pour les mises à jour partielles multiples, HTMX OOB swaps (`hx-swap-oob="true"`) permettent de mettre à jour simultanément plusieurs zones de la page (ex. badge compteur commentaires + liste de commentaires).

---

## Modèle de données

Le schéma repose sur un modèle **EAV** (Entity–Attribute–Value) pour les données dynamiques, combiné à des entités dédiées pour les fonctionnalités transversales.

```
User
 ├── DataTable (created_by_id)
 │    ├── TableColumn (name, col_type, order, required, select_options,
 │    │                related_table_id, related_display_col_id, related_value_col_id)
 │    ├── TableRow (created_by_id, created_at, updated_at, deleted_at)
 │    │    ├── CellValue (column_id, value: Text)       ← données EAV
 │    │    └── RowComment (user_id, content, created_at, edited_at)
 │    ├── TablePermission (user_id, level: READ|WRITE)
 │    ├── TableOwner (user_id)                          ← co-propriétaires
 │    └── Alert (name, scope, conditions JSON, actions JSON, is_active)
 │         ├── AlertState (row_id, is_triggered, last_triggered_at)
 │         └── AlertNotification (user_id, message, is_read, ...)
 │
 ├── ColumnPermission (column_id, hidden, readonly)
 ├── TableFavorite (table_id)
 └── ActivityLog (action, resource_type, resource_name, details, table_id, username)
```

### Types de colonnes (`ColumnType`)

| Valeur | Description | Comportement spécial |
|---|---|---|
| `text` | Texte libre | — |
| `integer` | Entier | Validation numérique |
| `float` | Décimal | Validation numérique |
| `date` | Date (ISO 8601) | Affichage JJ/MM/AAAA, widget date |
| `datetime` | Date + heure | Affichage JJ/MM/AAAA HH:MM, widget datetime-local |
| `boolean` | Oui / Non | Affichage pastille colorée |
| `email` | Adresse email | Lien `mailto:` cliquable |
| `select` | Liste déroulante | Options séparées par virgule dans `select_options` |
| `relation` | Référence à une autre table | Autocomplete HTMX, colonne affichée ≠ colonne stockée |

### Relation entre tables (`RELATION`)

- `related_table_id` : table cible (pas de FK physique — survit à la suppression de la table cible)
- `related_display_col_id` : colonne affichée dans l'autocomplete
- `related_value_col_id` : colonne dont la valeur est stockée dans la cellule (si `NULL` → stocke l'ID de ligne)

Pour les grands volumes, l'autocomplete utilise HTMX (`/tables/{id}/rows/autocomplete?q=...`) pour charger les suggestions à la demande.

### Soft-delete

`DataTable.deleted_at` et `TableRow.deleted_at` permettent la mise en corbeille sans suppression physique immédiate. Toutes les requêtes actives filtrent `.deleted_at == None`. La suppression définitive est une action explicite depuis la corbeille.

### Dénormalisation de l'historique

`ActivityLog.username` et `AlertNotification.table_name` / `alert_name` sont stockés dénormalisés : ils restent lisibles même si l'utilisateur ou la ressource est supprimé(e).

### Migrations

Les colonnes ajoutées après la création initiale sont gérées par `_run_migrations()` dans `app/database.py` : lecture du `PRAGMA table_info` SQLite, exécution conditionnelle des `ALTER TABLE`. Idempotent à chaque redémarrage.

---

## Routers et routes

### `app/routers/auth.py` — `/auth`

| Méthode | Route | Description |
|---|---|---|
| GET | `/auth/login` | Page de connexion |
| POST | `/auth/login` | Authentification → cookie signé |
| GET | `/auth/register` | Page d'inscription |
| POST | `/auth/register` | Création de compte (premier compte = admin) |
| GET | `/auth/logout` | Suppression du cookie → redirect login |

### `app/routers/tables.py` — `/tables`

| Méthode | Route | Description |
|---|---|---|
| GET | `/tables/` | Liste des tables (favoris, partagées, toutes) |
| GET | `/tables/create` | Formulaire de création |
| POST | `/tables/create` | Création table + colonnes |
| GET | `/tables/{id}` | Vue détail avec tableau HTMX |
| GET | `/tables/{id}/edit` | Formulaire de modification schéma |
| POST | `/tables/{id}/edit` | Mise à jour schéma (colonnes add/rename/delete) |
| POST | `/tables/{id}/trash` | Mise en corbeille de la table |
| GET | `/tables/trash` | Corbeille des tables |
| POST | `/tables/{id}/restore` | Restauration depuis corbeille |
| POST | `/tables/{id}/delete` | Suppression définitive |
| POST | `/tables/{id}/favorite` | Toggle favori |
| GET | `/tables/{id}/rows/autocomplete` | Autocomplete HTMX pour colonnes RELATION |

### `app/routers/data.py` — `/tables/{id}`

| Méthode | Route | Description |
|---|---|---|
| GET | `/tables/{id}/rows` | Fragment HTMX : tableau paginé + filtres |
| GET | `/tables/{id}/rows/{row_id}/edit` | Formulaire d'édition de ligne (HTMX) |
| POST | `/tables/{id}/rows` | Création d'une ligne |
| POST | `/tables/{id}/rows/{row_id}/update` | Mise à jour d'une ligne |
| POST | `/tables/{id}/rows/{row_id}/delete` | Mise en corbeille ligne |
| GET | `/tables/{id}/rows/trash` | Corbeille des lignes |
| POST | `/tables/{id}/rows/{row_id}/restore` | Restauration ligne |
| POST | `/tables/{id}/rows/{row_id}/delete-permanent` | Suppression définitive ligne |
| POST | `/tables/{id}/import` | Import CSV (mapping colonne, insensible casse) |

### `app/routers/permissions.py` — `/tables/{id}`

| Méthode | Route | Description |
|---|---|---|
| GET | `/tables/{id}/permissions` | Page gestion des permissions |
| POST | `/tables/{id}/permissions/bulk` | Mise à jour en masse table + colonne |
| GET | `/permissions/confirm-relation` | Page confirmation cascade RELATION |
| POST | `/permissions/confirm-relation` | Application des accès en cascade |

### `app/routers/alerts.py` — `/tables/{id}`

| Méthode | Route | Description |
|---|---|---|
| GET | `/tables/{id}/alerts/panel` | Fragment HTMX : panneau alertes |
| POST | `/tables/{id}/alerts` | Création d'une alerte |
| POST | `/tables/{id}/alerts/{alert_id}/toggle` | Activation/désactivation |
| GET | `/tables/{id}/alerts/{alert_id}/edit` | Formulaire d'édition |
| POST | `/tables/{id}/alerts/{alert_id}/edit` | Mise à jour alerte |
| POST | `/tables/{id}/alerts/{alert_id}/delete` | Suppression alerte |
| POST | `/api/notifications/mark-read/{notif_id}` | Marquer notification lue |
| GET | `/api/notifications/count` | Badge compteur (HTMX polling 30s) |

### `app/routers/comments.py` — `/tables/{id}/rows/{row_id}`

| Méthode | Route | Description |
|---|---|---|
| GET | `/tables/{id}/rows/{row_id}/comments/panel` | Fragment HTMX : panneau commentaires |
| POST | `/tables/{id}/rows/{row_id}/comments` | Ajout commentaire |
| POST | `/tables/{id}/rows/{row_id}/comments/{c_id}/edit` | Modification commentaire |
| POST | `/tables/{id}/rows/{row_id}/comments/{c_id}/delete` | Suppression commentaire |

### `app/routers/export.py`

| Méthode | Route | Description |
|---|---|---|
| GET | `/tables/{id}/export/excel` | Export Excel stylisé (colonnes visibles) |

### `app/routers/tracabilite.py`

| Méthode | Route | Description |
|---|---|---|
| GET | `/tables/{id}/tracabilite` | Journal filtré par table |

### `app/routers/import_auto.py` — `/import-auto`

| Méthode | Route | Description |
|---|---|---|
| GET | `/import-auto/upload` | Page upload CSV/Excel |
| POST | `/import-auto/analyze` | Analyse + preview colonnes détectées |
| POST | `/import-auto/confirm` | Création table + import données |

### `app/routers/admin.py` — `/admin`

| Méthode | Route | Description |
|---|---|---|
| GET | `/admin/users` | Liste des utilisateurs |
| POST | `/admin/users/{id}/toggle-admin` | Basculer rôle admin |
| POST | `/admin/users/{id}/delete` | Supprimer utilisateur |
| GET | `/admin/users/{id}/permissions` | Permissions d'un utilisateur (vue globale) |
| POST | `/admin/users/{id}/permissions` | Mise à jour permissions par utilisateur |

### `app/routers/logs.py` — `/admin`

| Méthode | Route | Description |
|---|---|---|
| GET | `/admin/logs` | Journal global des 1000 dernières actions |

---

## Couche dépendances

`app/dependencies.py` centralise les vérifications d'accès utilisées comme dépendances FastAPI :

| Dépendance | Rôle |
|---|---|
| `get_current_user` | Lit le cookie signé → retourne `User` ou redirect 303 vers login |
| `get_current_user_optional` | Idem sans lever d'exception (routes publiques) |
| `require_admin` | Vérifie `user.is_admin` → 403 sinon |
| `get_table_or_404` | Charge `DataTable` par `table_id` → 404 si absent |
| `is_table_owner` | Vérifie la présence dans `TableOwner` (co-propriétaires) |
| `can_access_table` | Admin OU co-owner OU `TablePermission` existante (optionnellement WRITE) |
| `get_visible_columns` | Filtre les colonnes selon `ColumnPermission.hidden` |
| `is_column_readonly` | Consulte `ColumnPermission.readonly` pour l'utilisateur |

---

## Gestion des sessions et authentification

- Cookie de session : `dt_session`, signé via `itsdangerous.URLSafeTimedSerializer` avec `SECRET_KEY` (7 jours d'expiration).
- Mots de passe : hachés avec `bcrypt` (12 rounds).
- Premier utilisateur inscrit : promu admin automatiquement.
- Pas de token JWT. Pas d'OAuth. Authentification exclusivement par email + mot de passe.

---

## Sécurité et permissions

### Hiérarchie des rôles

| Rôle | Périmètre | Obtention |
|---|---|---|
| **Administrateur** | Toutes les tables, tous les utilisateurs, tous les journaux | Premier inscrit ou promotion admin |
| **Co-propriétaire** | Contrôle total sur la table (schéma, permissions, alertes, corbeille) | Ajout via page permissions |
| **WRITE** | Lecture + ajout/modification/corbeille des lignes | Attribution par propriétaire/admin |
| **READ** | Lecture des données, commentaires, traçabilité | Attribution par propriétaire/admin |

### Permissions par colonne (`ColumnPermission`)

Pour chaque couple `(colonne, utilisateur)` :
- `hidden = true` : colonne invisible dans la vue tableau et dans l'export Excel
- `readonly = true` : valeur visible mais champ désactivé dans le formulaire de saisie ; icône 🔒 dans l'en-tête

Ces permissions sont gérables depuis deux interfaces :
- `/tables/{id}/permissions` — par le propriétaire/co-propriétaire de la table
- `/admin/users/{id}/permissions` — par un administrateur, vue consolidée par utilisateur

### Cascade d'accès sur les colonnes RELATION

Lors d'un partage d'une table contenant des colonnes de type `RELATION`, le système détecte si les nouveaux bénéficiaires n'ont pas accès aux tables référencées. Si le grantor (celui qui partage) est lui-même propriétaire des tables liées, une page de confirmation propose d'octroyer automatiquement un accès READ.

### Notification email lors d'un partage

Lorsqu'un utilisateur reçoit un accès à une table (niveau READ ou WRITE), un email lui est automatiquement envoyé. Il indique le nom de la table, le niveau d'accès accordé et l'identité de la personne ayant effectué le partage. L'email inclut un lien direct vers la table. L'envoi est également déclenché pour les accès READ accordés en cascade sur les tables de relation. Si `SMTP_HOST` n'est pas configuré, l'envoi est silencieusement ignoré.

### Visibilité des tables RELATION dans le schéma

Lors de la création/modification d'une colonne RELATION, le sélecteur de table cible ne propose que les tables accessibles (au minimum en lecture) par l'utilisateur courant.

---

## Traçabilité et journaux

### Journal global (`/admin/logs`)

Réservé aux administrateurs. Affiche les **1 000 dernières actions** toutes tables confondues avec : timestamp, acteur, type d'action, ressource, détail diff.

### Traçabilité par table (`/tables/{id}/tracabilite`)

Accessible à tout utilisateur ayant accès à la table. Filtrée sur `ActivityLog.table_id`.

### Actions tracées

| Action | Déclencheur | Ressource |
|---|---|---|
| `register` | Inscription | `user` |
| `login` | Connexion | `user` |
| `create_table` | Création table | `table` |
| `edit_table` | Modification schéma | `table` |
| `trash_table` | Mise en corbeille table | `table` |
| `restore_table` | Restauration table | `table` |
| `delete_table` | Suppression définitive table | `table` |
| `create_row` | Ajout ligne | `row` |
| `update_row` | Modification ligne | `row` |
| `trash_row` | Mise en corbeille ligne | `row` |
| `restore_row` | Restauration ligne | `row` |
| `delete_row` | Suppression définitive ligne | `row` |
| `import_csv` | Import CSV | `table` |
| `create_comment` | Ajout commentaire | `comment` |
| `edit_comment` | Modification commentaire | `comment` |
| `delete_comment` | Suppression commentaire | `comment` |
| `update_permissions` | Modification permissions table | `permission` |
| `update_user_permissions` | Permissions vue admin utilisateur | `permission` |
| `add_owner` | Ajout co-propriétaire | `permission` |
| `remove_owner` | Retrait co-propriétaire | `permission` |
| `toggle_admin` | Modification rôle admin | `user` |
| `delete_user` | Suppression utilisateur | `user` |

### Format du champ `details`

- **Modification table** : diff ligne par ligne — `Nom : "Avant" → "Après"`
- **Modification ligne** : diff par colonne — `"Col" : "avant" → "après"`
- **Permissions** : diff par utilisateur — `Accès "alice" : "none" → "write"`
- **Lignes (create/trash/restore/delete)** : `Ligne #42 avec Col1 -> Val1, Col2 -> Val2`

---

## Système d'alertes

Les alertes surveillent les données d'une table et déclenchent des actions visuelles ou des notifications en cas de condition vérifiée.

### Modèle d'une alerte

- **Conditions** (jusqu'à 5) : `{col_id, operator, value, logic (AND/OR), value_type (literal|column)}`
  - Opérateurs : `eq`, `neq`, `gt`, `gte`, `lt`, `lte`, `contains`, `not_contains`, `is_empty`, `is_not_empty`
  - `value_type = column` : comparaison colonne-à-colonne sur la même ligne
- **Actions** :
  - `notify_inapp` : notification dans le centre de notifications (cloche navbar)
  - `notify_email` : envoi d'un email aux destinataires concernés (nécessite une configuration SMTP dans `.env`)
  - `highlight.enabled` : surbrillance de la ligne ou des cellules concernées
  - `highlight.mode` : `row` (toute la ligne) ou `cells` (cellules impliquées)
  - `highlight.color` : couleur hexadécimale (ex. `#fbbf24`)
- **Portée** :
  - `private` : visible uniquement par le créateur
  - `global` : visible par tous les utilisateurs ayant accès à la table (réservé aux propriétaires/admins)

### Évaluation

- Réévaluée à chaque **création ou modification de ligne** (`evaluate_alerts_for_row()` dans `app/alerts.py`)
- Réévaluée immédiatement à la **création d'une alerte** sur toutes les lignes existantes
- L'état courant est persisté dans `AlertState` (déclenché ou non, horodatage)
- L'indicateur 🔔 (bell-ring) est affiché dans la colonne alerte du tableau si la ligne déclenche une alerte avec notification non lue

### Notifications

- Stockées dans `AlertNotification` (dénormalisées : nom alerte + nom table)
- Centre de notifications : `/notifications`
- Badge de comptage dans la navbar : rechargement HTMX toutes les 30 secondes
- Marquage individuel ou global comme lu

---

## Commentaires par ligne

Chaque ligne de données peut recevoir des commentaires collaboratifs.

### Caractéristiques

- Accessibles à **tous les utilisateurs** ayant un accès READ ou WRITE sur la table
- Visibles dans un panneau latéral glissant, chargé via HTMX
- Création, modification et suppression tracées dans le journal d'activité
- L'édition d'un commentaire est réservée à son auteur ; la suppression est ouverte à l'auteur, au propriétaire de la table et aux admins
- Un résumé de la ligne (3 premières valeurs non vides) est affiché en tête du panneau

### Indicateur visuel

- Bouton dans la colonne Actions de chaque ligne :
  - Icône discrète grise si aucun commentaire
  - Pill badge bleu avec compteur si ≥ 1 commentaire
- Le badge est mis à jour en temps réel via HTMX OOB swap après chaque ajout/suppression

### Timestamps relatifs

Les horodatages des commentaires sont affichés de façon relative : « à l'instant », « il y a 5 min », « il y a 2h », « hier », « il y a 3 jours » ou date complète pour les anciens.

---

## Import automatique CSV/Excel

Flux en deux étapes :

1. **Upload + analyse** (`POST /import-auto/analyze`) :
   - Accepte CSV (encodage détecté automatiquement via `chardet`) et Excel (`.xlsx`, `.xls`)
   - Détection automatique du type de chaque colonne par heuristiques sur l'échantillon de données
   - Limites : 5 000 lignes max, 50 colonnes max, 5 Mo max
   - Affiche une page de preview avec les 5 premières lignes et les types suggérés, modifiables

2. **Confirmation** (`POST /import-auto/confirm`) :
   - Crée la table avec le nom déduit du nom de fichier (avec suffixe si conflit)
   - Crée les colonnes dans l'ordre détecté
   - Insère toutes les lignes via `INSERT bulk` optimisé
   - Normalise les valeurs (dates ISO 8601, booléens, nombres)

### Heuristiques de détection de type

| Type détecté | Critères |
|---|---|
| `boolean` | Valeurs parmi oui/non/true/false/1/0 (insensible casse) |
| `integer` | 100 % de valeurs entières |
| `float` | 100 % de valeurs numériques (dont au moins un décimal) |
| `date` | Formats `DD/MM/YYYY`, `YYYY-MM-DD`, `MM/DD/YYYY` |
| `email` | Présence du caractère `@` |
| `text` | Cas par défaut |

---

## Rendu frontend

### HTMX

- Rechargement partiel du tableau (lignes + pagination) sur filtre, recherche, pagination
- Panneau de commentaires chargé à la demande (lazy)
- Panneau d'alertes chargé à la demande
- Formulaire d'ajout/édition de ligne injecté dans `#row-form-area` sans rechargement
- OOB swaps pour mises à jour simultanées (badge commentaire, liste commentaires)
- Autocomplete relation via polling HTMX sur saisie

### DataTables

- Tri, filtres par colonne (ligne de filtres `<tr>` dédiée dans le `<thead>`)
- Boutons export : Copier, CSV, Excel, PDF, Imprimer
- Bouton de visibilité des colonnes (Colvis) avec persistance via `localStorage`
- Indicateur de colonnes masquées dans la barre d'outils
- Colvis configuré avec callback `columnText` pour lire les titres depuis la première ligne du `<thead>` (contournement thead multi-lignes)
- Filtres par colonne désactivés pour la colonne Actions (non exportable — classe `dt-no-export`)

### Colonne Actions sticky

La colonne Actions est fixée à droite (`position: sticky; right: 0`) avec une ombre gauche via pseudo-élément `::before` pour signaler le défilement horizontal.

### Lucide Icons

Icônes vectorielles SVG injectées via `lucide.createIcons()` au chargement initial et après chaque swap HTMX.

---

## Structure des fichiers

```
datatracker/
├── app/
│   ├── main.py              # Création FastAPI, lifespan, include_router, handlers 403/404
│   ├── models.py            # Tous les modèles SQLAlchemy (User, DataTable, TableColumn,
│   │                        #   TableRow, CellValue, TablePermission, ColumnPermission,
│   │                        #   TableOwner, TableFavorite, Alert, AlertState,
│   │                        #   AlertNotification, ActivityLog, RowComment)
│   ├── database.py          # Engine SQLite, get_db(), create_tables(), _run_migrations()
│   ├── auth.py              # bcrypt, sessions itsdangerous (encode/decode cookie)
│   ├── activity.py          # log_action() — helper transversal
│   ├── alerts.py            # evaluate_alerts_for_row(), get_alert_row_data()
│   ├── email_utils.py       # send_alert_email(), send_share_notification_email()
│   │                        #   — envoi SMTP synchrone (smtplib)
│   ├── import_utils.py      # parse_csv(), parse_excel(), infer_column_type(),
│   │                        #   normalize_value(), sanitize_headers()
│   ├── dependencies.py      # get_current_user, can_access_table, get_visible_columns…
│   ├── config.py            # Settings (DATABASE_URL, SECRET_KEY via env)
│   ├── scheduler.py         # APScheduler — nettoyage orphelins à 3h
│   └── routers/
│       ├── auth.py          # /auth/login · /auth/register · /auth/logout
│       ├── tables.py        # /tables/ · /tables/create · /tables/{id} · corbeille
│       │                    #   · favoris · autocomplete relation
│       ├── data.py          # /tables/{id}/rows/* · import CSV · pagination · filtres
│       ├── export.py        # /tables/{id}/export/excel
│       ├── permissions.py   # /tables/{id}/permissions/bulk · confirm-relation
│       ├── alerts.py        # /tables/{id}/alerts/* · /notifications · badge API
│       ├── comments.py      # /tables/{id}/rows/{id}/comments/* · filtres Jinja2
│       ├── import_auto.py   # /import-auto/upload · analyze · confirm
│       ├── admin.py         # /admin/users · /admin/users/{id}/permissions
│       ├── logs.py          # /admin/logs — ACTION_LABELS, RESOURCE_LABELS
│       └── tracabilite.py   # /tables/{id}/tracabilite
│
├── app/templates/
│   ├── base.html            # Layout, navbar, CDN (Tailwind, HTMX, DataTables, Lucide)
│   │                        #   DT_LANG_FR, DT_BUTTONS, dtColFilters(), col-sticky-right CSS
│   ├── auth/                # login.html · register.html
│   ├── tables/              # list · detail · create · edit · import · tracabilite
│   ├── partials/            # table_rows.html · row_form.html (fragments HTMX)
│   │                        #   notif_badge.html
│   ├── comments/            # panel.html · _list.html · _comment.html
│   ├── alerts/              # panel.html · edit_form.html
│   ├── import_auto/         # upload.html · preview.html
│   ├── notifications/       # index.html
│   ├── permissions/         # manage.html · confirm_relation.html
│   ├── admin/               # users.html · user_permissions.html · logs.html
│   └── errors/              # 403.html · 404.html
│
├── tests/
│   ├── conftest.py          # Fixtures : DB in-memory (StaticPool), admin_client,
│   │                        #   user_client, reset schema entre tests
│   ├── helpers.py           # make_table() — création rapide table + colonnes
│   ├── test_auth.py
│   ├── test_tables.py
│   ├── test_data.py
│   ├── test_permissions.py
│   ├── test_admin.py
│   ├── test_logs.py
│   └── test_tracabilite.py
│
├── requirements.txt
├── pytest.ini
└── CLAUDE.md                # Instructions pour Claude Code
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

### Variables d'environnement (optionnelles)

| Variable | Défaut | Description |
|---|---|---|
| `DATABASE_URL` | `sqlite:///./datatracker.db` | URL de connexion SQLAlchemy |
| `SECRET_KEY` | Valeur codée en dur dans `app/auth.py` | Clé de signature des cookies — **à changer en production** |
| `SMTP_HOST` | *(vide)* | Hôte SMTP — si vide, les notifications email sont désactivées |
| `SMTP_PORT` | `587` | Port SMTP |
| `SMTP_USER` | *(vide)* | Identifiant SMTP |
| `SMTP_PASSWORD` | *(vide)* | Mot de passe SMTP |
| `SMTP_FROM` | *(vide)* | Adresse expéditeur (si vide, utilise `SMTP_USER`) |
| `SMTP_USE_TLS` | `true` | Activer STARTTLS |

---

## Tests

```bash
# Tous les tests
pytest

# Un fichier
pytest tests/test_tables.py

# Un test précis avec sortie verbeuse
pytest tests/test_data.py::test_create_row_as_owner -v
```

Les tests utilisent une base SQLite **en mémoire** (`StaticPool`). Chaque test part d'un schéma vierge (`create_all` / `drop_all` via fixture `autouse`).

Couverture actuelle : **209 tests**, tous verts.

---

## Conventions de développement

### Ajouter une fonctionnalité

1. **Modèle** : ajouter le modèle ou la colonne dans `app/models.py`. Si c'est une nouvelle colonne sur une table existante, ajouter la migration dans `_run_migrations()`.
2. **Router** : créer ou modifier le router dans `app/routers/`. Appeler `log_action()` **avant** `db.commit()` pour les actions importantes.
3. **Template** : créer ou modifier le template Jinja2. Utiliser `{% block scripts %}` pour le JS spécifique à la page.
4. **Tests** : couvrir les cas nominaux et les cas d'erreur (403, 404, contraintes).

### Patterns à respecter

- Les dépendances FastAPI (`get_current_user`, `can_access_table`, etc.) sont dans `app/dependencies.py` — ne pas dupliquer ces vérifications dans les routes.
- Les icônes utilisent Lucide (`<i data-lucide="nom">`) — `lucide.createIcons()` est appelé automatiquement au chargement et après chaque swap HTMX.
- Les tables HTML interactives utilisent DataTables avec `DT_LANG_FR`, `DT_BUTTONS` et `dtColFilters()` définis dans `base.html`.
- Le soft-delete se fait via `deleted_at = datetime.utcnow()`. Les queries doivent filtrer `.deleted_at == None` pour les vues actives.
- Les fragments HTMX (partials) sont dans `app/templates/partials/`. Ils reçoivent un contexte construit par une fonction `_xxx_template_ctx()` partagée entre la vue complète et la vue HTMX pour garantir la cohérence des données.
- Pour les OOB swaps HTMX : injecter `ctx["_oob_xxx"]` **avant** de créer le `TemplateResponse` (Starlette rend le template à la construction, pas au retour).
- Pas de FK physique sur `table_id` dans `ActivityLog`, `Alert`, `AlertNotification` et `AlertState` — ces entités doivent survivre à la suppression de la table ou de la ligne cible.
