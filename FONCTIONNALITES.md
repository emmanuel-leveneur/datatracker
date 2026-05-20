# DataTracker — Catalogue des fonctionnalités

> Document exhaustif listant l'ensemble des fonctionnalités de l'application, organisé par domaine fonctionnel.

---

## Sommaire

1. [Authentification et comptes](#1-authentification-et-comptes)
2. [Gestion des tables](#2-gestion-des-tables)
3. [Types de colonnes](#3-types-de-colonnes)
4. [Saisie et gestion des données](#4-saisie-et-gestion-des-données)
5. [Recherche et filtrage](#5-recherche-et-filtrage)
6. [Favoris](#6-favoris)
7. [Corbeille](#7-corbeille)
8. [Partage et permissions](#8-partage-et-permissions)
9. [Système d'alertes](#9-système-dalertes)
10. [Commentaires par ligne](#10-commentaires-par-ligne)
11. [Notifications](#11-notifications)
12. [Import automatique CSV / Excel](#12-import-automatique-csv--excel)
13. [Export Excel](#13-export-excel)
14. [Synchronisation webservice](#14-synchronisation-webservice)
15. [Visualisation cartographique](#15-visualisation-cartographique)
16. [Traçabilité](#16-traçabilité)
17. [Administration](#17-administration)
18. [Configuration](#18-configuration)
19. [Interface utilisateur](#19-interface-utilisateur)

---

## 1. Authentification et comptes

| Fonctionnalité | Description |
|---|---|
| Inscription | Création d'un compte avec email unique, nom d'utilisateur, mot de passe |
| Confirmation d'email | Lien de confirmation envoyé par email ; compte inactif tant qu'il n'est pas vérifié ; si SMTP absent, le compte est validé directement |
| Connexion | Email + mot de passe → session cookie signée (7 jours) |
| Déconnexion | Suppression du cookie de session, redirect vers login |
| Mot de passe oublié | Demande par email → token UUID à usage unique (30 min) → formulaire de réinitialisation → connexion avec nouveau mot de passe |
| Sécurité du reset | Réponse identique qu'il existe ou non un compte (évite l'énumération d'emails) ; token invalidé dès usage ; anciens tokens écrasés à chaque nouvelle demande |
| Admin automatique | Le premier utilisateur inscrit devient automatiquement administrateur |
| Hachage sécurisé | Mots de passe stockés avec bcrypt |
| Protection des routes | Toutes les pages (hors login/register/forgot) requièrent une session valide |
| Redirect intelligente | Accès non authentifié → redirect vers login (HTTP 303) |

---

## 2. Gestion des tables

### Création

| Fonctionnalité | Description |
|---|---|
| Page unifiée "Nouvelle table" | 3 onglets JS (sans rechargement) : Manuellement, Depuis un fichier, Depuis un webservice |
| Création manuelle | Nom, description, définition des colonnes, déclaration RGPD/DPO |
| Création depuis un fichier | Onglet intégré : upload CSV/Excel → navigation vers la page d'analyse existante |
| Création depuis un webservice | Onglet intégré : URL + authentification → détection automatique des champs → mapping → création table + sync configurée |
| Mémo d'onglet | L'onglet actif est mémorisé dans le hash URL (`#fichier`, `#webservice`) |

### Modification de schéma

| Fonctionnalité | Description |
|---|---|
| Ajout de colonnes | Ajout à une table existante avec type et options |
| Renommage de colonne | Modification du nom sans perte de données |
| Suppression de colonne | Suppression physique avec cascade sur `CellValue` et `ColumnPermission` |
| Réordonnancement | Les colonnes sont ordonnées par le champ `order` |
| Colonne obligatoire | Marquage d'une colonne comme requise (`required = true`) |
| Options de sélection | Pour le type `select` : liste d'options séparées par des virgules |

### Liste des tables

| Fonctionnalité | Description |
|---|---|
| Mes tables | Section listant les tables dont l'utilisateur est propriétaire |
| Tables partagées | Section listant les tables auxquelles l'utilisateur a été invité |
| Favoris | Section "Mes favoris" affichée en haut si au moins un favori |
| Nombre de lignes | Affiché sous le nom de chaque table |
| Indicateur de partage | Nombre d'utilisateurs avec qui la table est partagée (vue propriétaire) |
| Niveau d'accès | Badge "Lecture" ou "Lecture / Écriture" pour les tables partagées |
| Nom du propriétaire | Affiché pour les tables dont l'utilisateur n'est pas propriétaire |
| Recherche | Filtrage côté client (JS) sur nom et description |

### Vue détail d'une table

| Fonctionnalité | Description |
|---|---|
| Tableau interactif | DataTables avec tri, pagination, filtres |
| Barre d'outils | Boutons : Ajouter, Importer CSV, Export Excel, Alertes, Paramètres, Synchro (si table webservice) |
| Formulaire d'ajout inline | Formulaire HTMX injecté sans rechargement de page |
| Entête avec verrou | Indicateur 🔒 sur les colonnes en lecture seule pour l'utilisateur |

---

## 3. Types de colonnes

| Type | Saisie | Affichage |
|---|---|---|
| `text` | Champ texte libre | Texte brut |
| `integer` | Champ numérique entier | Nombre |
| `float` | Champ numérique décimal | Nombre |
| `date` | Widget `<input type="date">` | JJ/MM/AAAA |
| `datetime` | Widget `<input type="datetime-local">` | JJ/MM/AAAA HH:MM |
| `boolean` | Case à cocher | Pastille verte "Oui" / grise "Non" |
| `email` | Champ email avec validation | Lien `mailto:` cliquable |
| `select` | Liste déroulante | Valeur sélectionnée |
| `relation` | Autocomplete vers une autre table | Valeur de la colonne référencée |
| `latitude` | Champ numérique décimal | Nombre — utilisé par la carte |
| `longitude` | Champ numérique décimal | Nombre — utilisé par la carte |

### Détail du type `relation`

| Fonctionnalité | Description |
|---|---|
| Sélection de la table cible | Parmi les tables accessibles en lecture par l'utilisateur |
| Colonne d'affichage | Colonne montrée dans l'autocomplete (peut différer de la valeur stockée) |
| Colonne de valeur stockée | Colonne dont la valeur est enregistrée dans la cellule (ou ID de ligne si non précisé) |
| Autocomplete HTMX | Suggestions chargées dynamiquement sur saisie |
| Libellé résolu | À l'affichage, la valeur est résolue via `relation_labels` pour montrer un texte lisible |
| Référence manquante | Si la ligne liée a été supprimée : affichage `[ref. manquante]` en italique gris |

---

## 4. Saisie et gestion des données

### Lignes

| Fonctionnalité | Description |
|---|---|
| Ajout de ligne | Formulaire HTMX — injection dans la page sans rechargement |
| Modification de ligne | Formulaire HTMX chargé à la demande dans `#row-form-area` |
| Mise en corbeille | La ligne est masquée (soft delete : `deleted_at` non nul) |
| Suppression définitive | Depuis la corbeille uniquement |
| Restauration | Depuis la corbeille de la table |
| Historique de ligne | Modal affichant toutes les modifications chronologiques d'une ligne (qui, quand, quoi) |
| Auteur tracé | `created_by_id` enregistré à la création |
| Horodatage | `created_at` automatique |

### Import CSV (dans une table existante)

| Fonctionnalité | Description |
|---|---|
| Upload CSV | Fichier CSV UTF-8 ou Latin-1 |
| Mapping par nom | Les colonnes du CSV sont mappées par nom (insensible à la casse) |
| Colonnes non reconnues | Ignorées silencieusement |
| Colonnes manquantes | Laissées vides |
| Traçabilité | Action `import_csv` enregistrée dans `ActivityLog` |

---

## 5. Recherche et filtrage

| Fonctionnalité | Description |
|---|---|
| Recherche globale | Champ de recherche sur toutes les colonnes visibles (via sous-requête SQL `ILIKE`) |
| Filtres par colonne | Ligne de filtres sous les en-têtes de colonnes, déclenchement HTMX avec délai 350ms |
| Filtres combinables | Recherche globale et filtres par colonnes fonctionnent simultanément |
| Persistance des filtres | Les valeurs de filtre sont incluses via `hx-include` |
| Recherche insensible à la casse | Opérateur `ILIKE` SQLAlchemy |
| Recherche dans la liste | Filtrage côté client (JS) sur nom et description dans la liste des tables |

---

## 6. Favoris

| Fonctionnalité | Description |
|---|---|
| Marquage favori | Clic sur l'étoile → bascule favori/non favori (HTMX) |
| Section "Mes favoris" | Affichée en haut de la liste des tables si au moins un favori |
| Persistance | Stocké en base dans `TableFavorite` (unique par utilisateur + table) |

---

## 7. Corbeille

### Corbeille des tables

| Fonctionnalité | Description |
|---|---|
| Mise en corbeille | La table disparaît de la liste principale (`deleted_at` renseigné) |
| Vue corbeille | `/tables/trash` — liste des tables supprimées avec date |
| Restauration | Remet `deleted_at = NULL`, la table réapparaît |
| Suppression définitive | Suppression physique de la table + toutes ses données (cascade) |

### Corbeille des lignes

| Fonctionnalité | Description |
|---|---|
| Mise en corbeille | La ligne disparaît du tableau principal |
| Vue corbeille lignes | Accordéon en bas de la vue table |
| Restauration | La ligne réapparaît dans le tableau |
| Suppression définitive | Suppression physique de la ligne + CellValues + commentaires |
| Vider la corbeille | Bouton "Vider" avec confirmation — supprime définitivement toutes les lignes à la corbeille en une action |

---

## 8. Partage et permissions

### Niveaux d'accès à la table

| Niveau | Droits |
|---|---|
| **Co-propriétaire** (`TableOwner`) | Tout : schéma, permissions, alertes globales, corbeille, paramètres, synchro |
| **WRITE** (`TablePermission`) | Ajout/modification/corbeille des lignes, commentaires, consultation traçabilité |
| **READ** (`TablePermission`) | Lecture des données, commentaires, consultation traçabilité |

### Gestion des permissions par table

| Fonctionnalité | Description |
|---|---|
| Interface bulk | Tableau croisé utilisateurs × colonnes avec cases à cocher |
| Gestion co-propriétaires | Ajout/retrait de co-propriétaires depuis la page permissions |
| Permissions par colonne | Par colonne : `hidden` (masquée) ou `readonly` (lecture seule) |
| Application en masse | Un seul POST met à jour tous les accès en une transaction |
| Traçabilité | Diff des changements enregistré dans `ActivityLog` |

### Cascade d'accès sur les relations

| Fonctionnalité | Description |
|---|---|
| Détection automatique | Après partage, détecte si les nouveaux bénéficiaires manquent d'accès aux tables liées |
| Page de confirmation | Propose de donner un accès READ sur chaque table liée manquante |
| Conditions | Seules les tables liées dont le grantor est propriétaire sont proposées |
| Opt-in | L'utilisateur peut ignorer certaines propositions via les cases à cocher |

### Notification de partage par email

| Fonctionnalité | Description |
|---|---|
| Email automatique | Lors d'un nouveau partage, l'utilisateur concerné reçoit un email de notification |
| Contenu de l'email | Nom de la table, niveau d'accès accordé, nom de l'auteur du partage |
| Lien direct | Bouton "Voir le tableau" pointant directement sur la table partagée |
| Cascade relations | L'email est également envoyé pour les accès READ accordés automatiquement sur les tables de relation |
| Conditionnel SMTP | L'envoi est silencieusement ignoré si `SMTP_HOST` n'est pas configuré |

### Vue admin des permissions

| Fonctionnalité | Description |
|---|---|
| Vue par utilisateur | `/admin/users/{id}/permissions` — toutes les tables accessibles par un utilisateur |
| Modification globale | Mise à jour des accès table + colonne en une transaction depuis la vue admin |

---

## 9. Système d'alertes

### Création et configuration

| Fonctionnalité | Description |
|---|---|
| Nom de l'alerte | Libellé libre |
| Portée | Trois niveaux : `Privée` (soi uniquement), `Globale` (tous les accédants), `Personnalisée` (destinataires choisis) — global et personnalisée réservés aux propriétaires/admins |
| Portée personnalisée | Sélection des destinataires parmi les utilisateurs ayant accès à la table via un tag input avec autocomplete (badges supprimables, pré-rempli à l'édition) |
| Jusqu'à 5 conditions | Combinaison avec opérateurs logiques AND/OR |
| Opérateurs de comparaison | `=`, `≠`, `>`, `≥`, `<`, `≤`, `contient`, `ne contient pas`, `est vide`, `n'est pas vide` |
| Comparaison littérale | Valeur de référence saisie manuellement |
| Comparaison colonne-à-colonne | La valeur de référence est une autre colonne de la même ligne |
| Activation/désactivation | Toggle sans supprimer la configuration |
| Modification | Formulaire pré-rempli avec la configuration existante |
| Suppression | Suppression alerte + états + notifications + destinataires associés |

### Actions déclenchées

| Action | Description |
|---|---|
| Notification in-app | Génère une `AlertNotification` pour chaque utilisateur concerné selon la portée |
| Notification email | Envoie un email avec le nom de l'alerte, le nom de la table et la fiche de la ligne déclenchante (valeurs mises en évidence) |
| Surbrillance ligne | Colorisation de toute la ligne avec la couleur choisie |
| Surbrillance cellules | Colorisation uniquement des cellules impliquées dans la condition |

### Portée des notifications et de la surbrillance

| Portée | Notifications | Surbrillance |
|---|---|---|
| **Privée** | Créateur uniquement | Créateur uniquement |
| **Globale** | Tous les utilisateurs ayant accès à la table | Tous les utilisateurs ayant accès à la table |
| **Personnalisée** | Destinataires explicites ∩ utilisateurs ayant encore accès | Destinataires explicites uniquement (portée stricte) |

### Évaluation

| Fonctionnalité | Description |
|---|---|
| Évaluation à la modification | Déclenchée à chaque `create_row` et `update_row` — notifications envoyées si passage False → True |
| Réévaluation temporelle | Cron quotidien (8h) pour les conditions basées sur des dates relatives (aujourd'hui, hier…) |
| Évaluation initiale silencieuse | À la création, modification ou toggle d'une alerte, les lignes existantes sont évaluées pour les couleurs uniquement — aucune notification rétroactive |
| Anti-spam amorcé | Les lignes déjà en état `True` à la création de l'alerte ne déclencheront pas de notification lors de la prochaine modification live |
| Persistance d'état | `AlertState` stocke si l'alerte est actuellement déclenchée sur chaque ligne |
| Sécurité destinataires | Un destinataire personnalisé ayant perdu son accès à la table ne reçoit plus les notifications |
| Indicateur visuel | Icône 🔔 dans la colonne alerte du tableau si ligne déclenchée avec notification non lue |

---

## 10. Commentaires par ligne

| Fonctionnalité | Description |
|---|---|
| Accès | Tout utilisateur READ ou WRITE sur la table peut commenter |
| Panneau latéral | Chargé via HTMX, panneau glissant à droite de l'écran |
| Résumé de ligne | Les 3 premières valeurs non vides sont affichées en en-tête du panneau |
| Ajout commentaire | Textarea + Ctrl+↵ pour envoyer |
| Modification | Réservée à l'auteur, inline dans le panneau |
| Suppression | Auteur, co-propriétaire de table ou admin |
| Indication de modification | Libellé "(modifié)" affiché si le commentaire a été édité |
| Avatar | Initiale du nom d'utilisateur sur fond coloré (couleur déterministe par nom) |
| Timestamp relatif | "à l'instant", "il y a Xmin", "il y a Xh", "hier", "il y a X jours" |
| Indicateur sur la ligne | Pill badge bleu avec compteur si ≥ 1 commentaire, icône discrète sinon |
| Mise à jour temps réel | Le badge est mis à jour via HTMX OOB swap après chaque commentaire |
| Traçabilité | Création, modification et suppression tracées dans `ActivityLog` |

---

## 11. Notifications

| Fonctionnalité | Description |
|---|---|
| Centre de notifications | `/notifications` — liste de toutes les notifications |
| Badge navbar | Cloche avec compteur des notifications non lues, rechargé toutes les 30s (HTMX) |
| Contenu | Nom de l'alerte, nom de la table, message descriptif, lien vers la table |
| Marquage individuel | Marquer une notification comme lue |
| Marquage global | Tout marquer comme lu en un clic |
| Persistance | Stocké en base, dénormalisé (survit à la suppression de la table ou de l'alerte) |

---

## 12. Import automatique CSV / Excel

### Upload et analyse

| Fonctionnalité | Description |
|---|---|
| Formats supportés | CSV (tout séparateur, tout encodage), Excel `.xlsx`, `.xls`, `.xlsm` |
| Détection d'encodage | `chardet` pour les CSV (UTF-8, Latin-1, etc.) |
| Limites | 10 000 lignes, 50 colonnes, 10 Mo |
| Détection automatique des types | Boolean, integer, float, date, datetime, email, text |
| Nettoyage des en-têtes | Suppression des caractères spéciaux, dédoublonnage |
| Zone de glisser-déposer | Drag & drop sur la zone d'upload |
| Page de preview | 5 premières lignes + types suggérés modifiables avant import |
| Modification des types | L'utilisateur peut ajuster chaque type avant confirmation |

### Transformations avant import

| Fonctionnalité | Description |
|---|---|
| Éclater une colonne | Séparation d'une colonne texte en deux colonnes selon un délimiteur |
| Nettoyer les espaces | Suppression des espaces en début/fin de valeur |

### Confirmation et création

| Fonctionnalité | Description |
|---|---|
| Nom de table | Déduit du nom de fichier, suffixe numérique si conflit |
| Création des colonnes | Dans l'ordre détecté |
| Insertion optimisée | Bulk INSERT par lots de 500 lignes |
| Normalisation des valeurs | Dates en ISO 8601, booléens normalisés (true/false), nombres sans espaces |
| Traçabilité | Action `import_csv` enregistrée |

---

## 13. Export Excel

| Fonctionnalité | Description |
|---|---|
| Format | `.xlsx` via `openpyxl` |
| Colonnes exportées | Uniquement les colonnes visibles pour l'utilisateur (respecte `ColumnPermission.hidden`) |
| En-têtes stylisées | Fond coloré, police en gras |
| Colonnes exclues | La colonne Actions (`dt-no-export`) est exclue automatiquement |
| Nom du fichier | `{nom_table}.xlsx` |

---

## 14. Synchronisation webservice

### Configuration

| Fonctionnalité | Description |
|---|---|
| URL | URL HTTP/HTTPS du webservice |
| Authentification | `Aucune`, `Bearer token`, `API Key (header)`, `Basic Auth (user:pass)` |
| Chemin de réponse | Chemin pointé (`data`, `results.items`) pour naviguer dans un JSON imbriqué |
| Mapping champs | Association colonnes de la table ↔ clés JSON du webservice |
| Clé de déduplication | Colonne servant d'identifiant unique pour les modes upsert/ajout sans doublon |
| Intervalle | Fréquence de la synchronisation automatique (en minutes) |

### Modes de synchronisation

| Mode | Comportement |
|---|---|
| **Écrasement total** | Supprime toutes les lignes existantes puis réinsère les données du webservice |
| **Mise à jour (upsert)** | Met à jour les lignes existantes (via clé de dédup), insère les nouvelles, supprime les absentes |
| **Ajout sans doublon** | Insère uniquement les enregistrements dont la clé de dédup est absente — lignes existantes non modifiées |
| **Ajout avec doublon** | Insère toujours toutes les lignes sans vérification — accumulation pure (logs, relevés horodatés…) |

### Déclenchement

| Fonctionnalité | Description |
|---|---|
| Synchronisation manuelle | Bouton "Lancer une synchronisation" avec confirmation selon le mode |
| Synchronisation automatique | Toggle activable, vérification toutes les minutes par le scheduler |
| Bouton Synchro | Visible uniquement sur les tables créées depuis un webservice |

### Suivi

| Fonctionnalité | Description |
|---|---|
| Statut dernière sync | Date, statut (ok/erreur), message de résultat |
| Statistiques | Nombre de lignes insérées, mises à jour, supprimées |
| Traçabilité | Action `sync_table` enregistrée dans le journal |

---

## 15. Visualisation cartographique

| Fonctionnalité | Description |
|---|---|
| Activation | Disponible si la table possède au moins une colonne `latitude` et une colonne `longitude` |
| Panneau carte | Carte Leaflet / OpenStreetMap intégrée dans la vue de la table |
| Marqueurs | Un marqueur par ligne avec coordonnées valides |
| Labels permanents | Étiquettes affichées en permanence sur chaque marqueur |
| Info-bulle | Clic sur un marqueur affiche les valeurs de la ligne |
| Filtrage | Les filtres actifs sur le tableau sont appliqués à la carte |
| Export GeoJSON | Endpoint `/tables/{id}/geojson` retournant les données filtrées au format GeoJSON |

---

## 16. Traçabilité

### Journal global (admin)

| Fonctionnalité | Description |
|---|---|
| Accès | Administrateurs uniquement |
| URL | `/admin/logs` |
| Volume | 1 000 dernières actions |
| Données | Timestamp, acteur (préfixe email), action, ressource, détails diff |
| Libellés lisibles | Chaque action et type de ressource est traduit en français |

### Journal par table

| Fonctionnalité | Description |
|---|---|
| Accès | Tout utilisateur avec accès READ ou WRITE sur la table |
| URL | `/tables/{id}/tracabilite` |
| Filtrage | Sur `ActivityLog.table_id` uniquement |
| Persistance | L'historique survit à la suppression de la table (`table_id` sans FK physique) |

### Historique de ligne

| Fonctionnalité | Description |
|---|---|
| Accès | Via le bouton historique sur chaque ligne |
| Affichage | Modal listant toutes les modifications de la ligne avec acteur, date, et diff des valeurs |

### Actions tracées

Authentification (`register`, `login`, `reset_password`), création/modification/suppression/corbeille/restauration de table, gestion de schéma, ajout/modification/suppression/corbeille/restauration de ligne, import CSV, synchronisation webservice (`sync_table`), ajout/modification/suppression de commentaire, gestion des permissions et co-propriétaires, vidage de corbeille (`empty_trash`), administration des utilisateurs.

### Format des détails

- **Lignes** : diff complet par colonne `"Champ" : "ancienne valeur" → "nouvelle valeur"`
- **Permissions** : diff `Accès "utilisateur" : "none" → "write"`
- **Tables** : diff champ par champ du schéma
- **Commentaires** : libellé de la ligne concernée
- **Synchro** : statistiques insérées/mises à jour/supprimées

---

## 17. Administration

### Gestion des utilisateurs

| Fonctionnalité | Description |
|---|---|
| Liste des utilisateurs | Email, nom, rôle, date d'inscription |
| Promotion admin | Toggle admin/non-admin (sauf pour soi-même) |
| Suppression | Suppression physique de l'utilisateur (avec avertissement) |
| Vue permissions | Toutes les tables accessibles par un utilisateur, avec niveaux et permissions colonnes |

### Journaux

| Fonctionnalité | Description |
|---|---|
| Journal global | 1 000 dernières actions toutes tables confondues |
| Filtrage visuel | Tableau DataTables avec filtres par colonne |
| Export | CSV, Excel, PDF depuis DataTables |

---

## 18. Configuration

| Variable | Description |
|---|---|
| `DATABASE_URL` | URL de connexion SQLAlchemy (SQLite par défaut) |
| `SECRET_KEY` | Clé de signature des cookies de session |
| `DB_ENCRYPTION_KEY` | Clé de chiffrement SQLCipher — laisser vide pour SQLite non chiffré |
| `APP_URL` | URL publique de l'application (utilisée dans les liens des emails) |
| `ORG_NAME` | Nom de l'organisation affiché dans le footer et les mentions RGPD (optionnel) |
| `DPO_EMAIL` | Email du DPO pré-rempli dans le lien "Envoyer un email au DPO" (optionnel) |
| `SMTP_HOST` | Serveur SMTP — si vide, les emails ne sont pas envoyés |
| `SMTP_PORT` | Port SMTP (défaut : 587) |
| `SMTP_USER` | Identifiant SMTP |
| `SMTP_PASSWORD` | Mot de passe SMTP |
| `SMTP_FROM` | Adresse expéditeur |
| `SMTP_USE_TLS` | Activer STARTTLS (défaut : true) |

### Comportement si SMTP non configuré

- Emails de confirmation, reset, partage et alertes silencieusement ignorés
- Liens de confirmation et de reset affichés dans les logs serveur (mode développement)
- Comptes créés directement vérifiés (sans étape email)

### Tâches planifiées (scheduler)

| Tâche | Fréquence | Description |
|---|---|---|
| Nettoyage des lignes orphelines | Quotidien — 3h | Supprime les `TableRow` sans aucune `CellValue` |
| Réévaluation des alertes temporelles | Quotidien — 8h | Réévalue les alertes dont les conditions dépendent de dates relatives |
| Synchronisations automatiques | Toutes les minutes | Exécute les syncs `is_auto=True` dont l'intervalle est échu |

---

## 19. Interface utilisateur

### Navigation

| Fonctionnalité | Description |
|---|---|
| Navbar fixe | Logo + liens principaux + badge notifications + bouton déconnexion |
| Affichage utilisateur | Préfixe email (avant `@`) + badge "Admin" si applicable |
| Messages flash | Confirmation ou erreur affichés en haut de page, fermables |
| Pages d'erreur | 403 (accès refusé) et 404 (non trouvé) personnalisées |

### Tableau de données

| Fonctionnalité | Description |
|---|---|
| Colonne alerte | Icône 🔔 si la ligne déclenche une alerte avec notification non lue |
| Indicateur lecture seule | Icône 🔒 dans l'en-tête de colonne |
| Colonne commentaires | Pill badge bleu avec compteur ou icône discrète |
| Colonne Actions sticky | Fixée à droite lors du défilement horizontal, avec ombre signalant le scroll |
| Pagination | Boutons numérotés avec ellipses pour les grandes tables, rechargement HTMX |
| Taille de page | 25 / 50 / 100 / 250 / 500 lignes par page |
| Filtres par colonne | Inputs dans une ligne dédiée sous les en-têtes, déclenchement différé 350ms |
| Tri | Par clic sur les en-têtes (DataTables) |

### Visibilité des colonnes (Colvis)

| Fonctionnalité | Description |
|---|---|
| Bouton Colonnes | Affiche/masque des colonnes à la volée |
| Noms corrects | Callback spécifique pour lire les titres depuis la première ligne du `<thead>` |
| Persistance localStorage | La configuration est sauvegardée par table dans `localStorage` |
| Clé de persistance | `colvis_{table_id}` — résistante aux rechargements de page |
| Indicateur de masquage | Badge ambré "N colonne(s) masquée(s)" dans la barre d'outils si applicable |

### Accessibilité et ergonomie

| Fonctionnalité | Description |
|---|---|
| Confirmations | Boîtes de dialogue natif (`hx-confirm`) pour les actions destructives |
| Raccourcis clavier | Ctrl+↵ pour soumettre les formulaires de commentaire, Échap pour fermer les panneaux |
| Auto-scroll | Le panneau de commentaires défile automatiquement vers le bas à l'ouverture et après ajout |
| Focus automatique | Le textarea commentaire est focusé à l'ouverture du panneau |
| Avatars colorés | Initiale de l'utilisateur sur fond de couleur déterministe (stable entre sessions) |
| Design responsive | Tailwind CSS responsive, scroll horizontal sur les grandes tables |
| Transitions | Animations CSS sur les panneaux latéraux et les hover d'icônes |

### Fuseaux horaires

| Fonctionnalité | Description |
|---|---|
| Stockage UTC | Toutes les dates sont stockées en UTC en base de données |
| Affichage UTC+4 | Toutes les dates affichées dans l'interface sont converties en heure de La Réunion (UTC+4, sans changement d'heure) via le filtre Jinja2 `dt_reunion` |
