# Analyse technique PIGE — Revue experte

**Contexte :** PIGE (Python, Tkinter/ttk, stockage JSON/Markdown), cibles macOS + Windows.  
**Principes :** diffs minimaux, usage Tk/ttk sûr multi-versions, GUI → service → stockage.

---

## 1. Carte d’architecture de haut niveau

### 1.1 Modules majeurs

| Module | Rôle | Fichiers clés |
|--------|------|----------------|
| **GUI** | Interface graphique (fenêtre unique, panneaux, dialogs) | `pige/interfaces/gui.py` (~5760 lignes), `gui_constants.py`, `gui_helpers.py` |
| **Service** | Logique métier, validation, orquestration | `pige/core/service.py` (~1160 lignes) |
| **Storage** | Lecture/écriture fichiers, event-sourcing entries | `pige/core/storage.py` (~317 lignes) |
| **Models** | Structures de données (dataclasses) | `pige/core/models.py` (~76 lignes) |
| **Utils** | Dates, IDs, JSON/JSONL, chaînes, people/tags | `pige/utils/{dates,ids,io,strings}.py` |
| **CLI** | Ligne de commande (délégation au service) | `pige/interfaces/cli.py` |

### 1.2 Graphe d’appels / flux de données (texte)

```
[Utilisateur]
     │
     ▼
┌─────────────────────────────────────────────────────────────────┐
│  GUI (PigeApp)                                                   │
│  - PigeApp.__init__ : Storage(data_dir), PigeService(storage)   │
│  - refresh_projects → service.list_projects() + remplissage     │
│    project_tree / entry_tree / task_tree / in_progress_tree      │
│  - _write_entry_content → service.update_entry_content()       │
│  - _save_entry_details → service.update_entry_meta()            │
│  - Timer : _poll_timer() lit storage.read_timer_state()        │
│  - Exports / backup / restore : service.export_* / backup /     │
│    service.restore_data()                                       │
└─────────────────────────────────────────────────────────────────┘
     │
     ▼
┌─────────────────────────────────────────────────────────────────┐
│  PigeService (service.py)                                        │
│  - create_project, update_project, delete_project →              │
│    storage.read_projects() / write_projects()                   │
│  - add_entry → storage.append_entry_event() +                    │
│    storage.write_entry_content()                                │
│  - update_entry_meta / set_entry_context_status →                │
│    storage.append_entry_update() puis read_entries_meta()        │
│  - list_in_progress_threads, search → read_entries_meta(),      │
│    read_tasks(), read_entry_body() (si include_body)            │
│  - time_start/time_stop → read_timer_state, write_timer_state,  │
│    append_timelog()                                              │
│  - export_* : lecture storage + écriture directe fichier MD     │
└─────────────────────────────────────────────────────────────────┘
     │
     ▼
┌─────────────────────────────────────────────────────────────────┐
│  Storage (storage.py)                                            │
│  - projects.json (read/write complets)                           │
│  - entries.jsonl (append events, read → _fold_entry_events)     │
│  - entries/<id>.md (write/read contenu)                          │
│  - tasks.json, timers.json (read/write complets)                │
│  - timelogs.jsonl (append, read ligne à ligne)                  │
└─────────────────────────────────────────────────────────────────┘
     │
     ▼
[Fichiers : projects.json, entries.jsonl, entries/*.md, tasks.json, timers.json, timelogs.jsonl, exports/, .pige_prefs.json]
```

### 1.3 Responsabilités : propres vs mélangées

- **Clair :** Les modèles sont en `models.py` ; le stockage ne fait que I/O et repli d’events ; le service valide et orchestre. La GUI ne contient pas de logique métier (création/update/delete passent par le service).
- **Mélangé / à surveiller :**
  - **GUI** : préférences GUI (`.pige_prefs.json`) sont dans `data_dir` et chargées/sauvegardées par la GUI ; la config globale (data_dir) est dans `~/.config/pige/config.json` ou `%APPDATA%/PIGE/config.json`, gérée par des helpers dans `gui_helpers.py` (`_load_global_config`, `_save_global_config`, `_resolve_data_dir`). Donc deux niveaux de config (globale vs par data_dir). Constantes d’affichage et types dans `gui_constants.py` ; helpers réutilisables (dates, people, chemins, config) dans `gui_helpers.py`.
  - **Service** : les exports (raw, narrative, meeting minutes, weekly summary) écrivent directement dans des fichiers avec `open(..., "w")` au lieu de passer par un module d’IO dédié ; pas d’écriture atomique pour ces exports (contrairement à `safe_write_json`).
  - **Storage** : `write_entry_content` fait un `open(path, "w")` sans `.tmp` + `os.replace` → pas d’écriture atomique pour le contenu des entrées (risque de fichier tronqué en cas de crash pendant l’écriture).

---

## 2. Modèle de données et intégrité du stockage

### 2.1 Artefacts persistés

| Artefact | Fichier(s) | Stratégie d’écriture |
|----------|------------|------------------------|
| Projets | `projects.json` | Overwrite complet (`safe_write_json`) |
| Métadonnées entrées | `entries.jsonl` | Append-only (events: `entry`, `entry_update`, `entry_delete`) |
| Contenu entrées | `entries/<id>.md` | Overwrite direct (non atomique) |
| Tâches | `tasks.json` | Overwrite complet (`safe_write_json`) |
| État timer | `timers.json` | Overwrite complet (`safe_write_json`) |
| Timelogs | `timelogs.jsonl` | Append-only (`append_jsonl`) |
| Exports | `exports/*.md`, `exports/backup_*.zip` | Overwrite direct (non atomique pour MD) |
| Préférences GUI | `.pige_prefs.json` (ou legacy `gui_prefs.json`) | `safe_write_json` (GUI) |
| Config globale | `~/.config/pige/config.json` ou `%APPDATA%/PIGE/config.json` | `.tmp` + `os.replace` (GUI) |

### 2.2 Stratégie de mise à jour, merge, risques de corruption

- **entries.jsonl** : Lecture = `read_jsonl` puis `_fold_entry_events`. Les updates sont des patches ; les deletes retirent l’entrée du state. **Risques :** (1) une ligne JSONL mal formée fait lever `ValueError` dans `read_jsonl` (ligne précisée) ; (2) un event `entry_update` avec `entry_id` inconnu ou patch invalide lève dans `_fold_entry_events` ; (3) pas de compaction → le fichier grossit indéfiniment.
- **Contenu entrées** : `storage.write_entry_content(entry_id, content)` écrit directement dans `entries/<id>.md`. Pas de rename atomique → **risque de corruption partielle** (crash pendant `handle.write(content)`).
- **projects.json / tasks.json / timers.json** : Écriture atomique via `io_utils.safe_write_json`. Clés inconnues : `Project(**item)` et `Task(**payload)` peuvent lever `TypeError` si le JSON contient des champs non prévus par le dataclass ; `read_tasks` normalise partiellement (status, dict(item)) mais pas les champs inconnus ; `TimerState(**data)` idem.
- **timelogs.jsonl** : Append-only ; lecture robuste (seules les clés dans `TIMELOG_KEYS` sont lues, valeurs par défaut pour optionnels).

### 2.3 Schéma, dérive et migration

- **Dérive de schéma :** Ajout de champs optionnels dans les dataclasses (ex. `summary`, `context_status` sur `EntryMeta`) : OK si champs `Optional` ou avec `default`. En revanche, `read_projects`/`read_tasks`/`read_timer_state` ne filtrent pas les clés → fichiers modifiés à la main ou anciens avec champs en trop peuvent casser.
- **Migration explicite :** Aucune. Pas de version de schéma ni de script de migration. Pour ajouter un champ : s’assurer que le code de lecture tolère l’absence (défaut) ou la présence (et idéalement filtrer les clés connues comme pour timelogs).

### 2.4 Recommandations concrètes

- **Validation :** Ajouter une couche de validation au chargement (ex. ensemble de clés autorisées pour Project/Task/TimerState) et ignorer ou logger les clés inconnues au lieu de faire `**item` brut.
- **Sauvegardes :** Déjà en place : backup avant restore, exports dans `exports/`. Recommandation : documenter une fréquence de backup recommandée ; éventuellement proposer un backup automatique avant opérations destructives (delete project/entry) si pas déjà fait côté UX.
- **Compaction / snapshots :** Pour `entries.jsonl`, proposer une fonction “compaction” (optionnelle) : écrire un nouveau JSONL avec uniquement les events `entry` pour l’état courant (snapshot), puis remplacer l’ancien fichier via `safe_write_jsonl` + rename, pour limiter la taille et le temps de repli.
- **Écriture atomique du contenu des entrées :** Faire écrire dans `entries/<id>.md.tmp` puis `os.replace(tmp, path)` dans `storage.write_entry_content` (ou déléguer à un helper du type `safe_write_text(path, content)` dans `pige/utils/io.py`).

---

## 3. Ergononomie GUI et patterns d’interaction

### 3.1 Workflows principaux

- **Création / édition d’entrée :** Nouvelle entrée = menu/dialog (date, type, titre, people, tags, body) → `service.add_entry` → `refresh_entries` + `_load_entry`. Édition = panneau détails (titre, date, people, tags, meeting/decision) → Save → `service.update_entry_meta` ; contenu = éditeur texte → Save / autosave → `service.update_entry_content`.
- **Follow-ups :** “Extract follow-up tasks” (checklist / ACTION/TODO dans le body) → `extract_followup_tasks` → dialog pour sélection → `create_followup_tasks` ; “Tasks from entry” lie la tâche à l’entrée courante.
- **Recherche / filtrage :** Champ recherche (débounce 200 ms) → recherche projet courant ou globale (`search_global_mode_var`, `search_include_body_var`) → `service.search` ; filtres Type, Person, “Show archived”, “Show treated” ; tri colonnes entrées.
- **Exports :** Menu Export → Raw, Narrative, Meeting minutes, Weekly summary ; dialogs pour dates/options puis `service.export_*`.
- **Déplacer une entrée :** Move entry → choix projet + keep tags/people → `service.move_entry`.
- **Timer :** Start/Stop Timer (bouton toolbar) → `service.time_start` / `service.time_stop` ; mise à jour affichage toutes les 1 s via `_poll_timer` (lecture `storage.read_timer_state()`).
- **Tâches :** Liste par projet, filtres statut/recherche/“current entries only” ; ajout/édition/suppression via service ; lien entrée via `linked_entry_id`.

### 3.2 Cohérence UX

- **Discoverabilité :** Les actions principales sont dans la barre d’outils et le menu File/Tools/View ; contexte (projet/entrée/tâche) désactive/active les boutons (ex. timer désactivé sans projet). Manque : raccourcis clavier documentés ou visibles (ils existent via `_bind_shortcuts` mais pas listés dans l’UI).
- **Raccourcis :** À vérifier dans `_bind_shortcuts` (non lu en détail) ; cohérence à garder entre macOS (Command) et Windows (Control).
- **Menus contextuels :** Projet : clic droit → Edit, Delete. Entrées : à confirmer (probablement clic droit ou équivalent).
- **Focus :** Beaucoup de `focus_set()` après ouverture de dialogs ; risque de focus perdu après refresh des trees si la sélection change.

### 3.3 Pièges Tkinter

- **Bindings :** `<<TreeviewSelect>>` déclenche des refresh (ex. `_on_project_select` → refresh entries/tasks). Si le refresh modifie la sélection ou le contenu du tree, attention aux boucles et aux `_suppress_project_select` / `_suppress_entry_select` déjà présents.
- **Treeview :** `refresh_entries` / `refresh_projects` font `tree.delete(*tree.get_children())` puis une série de `tree.insert()`. Coût proportionnel au nombre d’entrées/projets ; pour de très gros volumes, envisager virtualisation ou pagination (non en place).
- **Plateforme :** `_open_path` utilise `os.startfile` (Windows), `open` (macOS), `xdg-open` (Linux). Style ttk (Treeview, etc.) peut rendre différemment selon le thème ; `_configure_tree_stripes` tente d’adapter les couleurs.

### 3.4 Cinq à dix changements UX (rationale, diffs minimaux)

1. **Écriture atomique du contenu des entrées** (stockage) — Éviter corruption en cas de crash pendant la sauvegarde. Fichier : `pige/core/storage.py`, `write_entry_content` : écrire dans `path.tmp` puis `os.replace(tmp, path)` (ou utiliser un `safe_write_text` dans `io.py`).
2. **Afficher les raccourcis dans le menu** — Ex. “Save (Ctrl+S)” dans File. Fichier : `gui.py`, `_build_menu` : ajouter le label avec la séquence dans les `add_command` concernés.
3. **Message clair quand “No entry selected to save”** — Déjà présent ; s’assurer que après suppression d’une entrée ou changement de projet, le statut “No entry” est mis à jour et que le bouton Save est désactivé de façon cohérente (`_update_save_button_state`).
4. **Débounce recherche déjà en place (200 ms)** — Garder ; éventuellement augmenter légèrement si “Include body” est coché (recherche plus lourde) pour limiter les appels pendant la frappe.
5. **Resize des colonnes** — Déjà planifié avec `_schedule_resize` (120 ms) après Configure ; vérifier que sur macOS/Windows les colonnes ne se rétrécissent pas trop au redimensionnement.
6. **Confirmation avant fermeture si entrée dirty** — `_on_close` appelle `_confirm_save_if_dirty` ; s’assurer que le message est explicite (“Unsaved changes in the entry. Save?”) et que Cancel annule bien la fermeture.
7. **Focus après “New Entry”** — Après création, `_load_entry(entry.id)` est appelé ; donner le focus au champ éditeur (ou au panneau entrée) pour enchaîner la rédaction.
8. **Menu contextuel sur la liste des entrées** — Si absent, ajouter clic droit → Open, Edit metadata, Move, Delete, Export meeting minutes (si type meeting), pour symétrie avec le panneau projet.
9. **Désactiver “Start Timer” quand un timer tourne déjà** — Déjà géré : `_poll_timer` met le bouton en “Stop Timer” et le libère ; quand pas de projet, le bouton est disabled. Cohérence OK.
10. **Préférences : sauvegarde différée** — Déjà en place (`_schedule_prefs_save` 250 ms) ; éviter de sauvegarder à chaque frappe dans un champ lié aux prefs.

---

## 4. Couche service : justesse et testabilité

### 4.1 Frontières : ce qui est au service vs GUI vs stockage

- **Service :** Validation des entrées (type, meeting hours, decision_done, context_status), règles métier (un seul timer, projet existant pour tâches/entrées), agrégations (list_in_progress_threads, search avec option include_body), exports (génération du contenu MD). Pas d’affichage ni de chemins utilisateur (sauf utilisation de `storage.exports_dir` pour chemins par défaut).
- **GUI :** Choix des chemins de sauvegarde/export (dialogs), formatage dates UI (DD/MM/YYYY), préférences d’affichage, focus, débounce. Ne doit pas appeler directement le storage sauf pour `read_timer_state` dans `_poll_timer` (pour éviter de passer par le service à chaque seconde) et lecture directe du fichier MD dans `_load_entry` (contournement du service pour afficher le body ; incohérence mineure).
- **Storage :** Uniquement I/O et repli d’events ; pas de validation métier (la validation des patches entry est dans storage `_fold_entry_events` pour les clés autorisées et le type non modifiable).

### 4.2 Code smells

- **Duplication :** Formatage de durée (`_format_duration_hms`), date (`_format_date_ddmmyyyy`), clés de tri entrées (`_entry_local_date`, `_entry_time_label`) répétés dans les exports ; à factoriser si on ajoute d’autres formats d’export.
- **Couplage temporel :** Après `append_entry_update` ou `append_entry_delete`, le service relit `read_entries_meta()` pour retourner l’entrée à jour ; nécessaire car le storage n’expose pas de “get after patch” sans relire.
- **IO cachée :** Les méthodes d’export font `open(out_path, "w")` et `handle.write(content)` directement dans le service ; idéalement, écrire via un module io (ex. `io_utils.safe_write_text` ou équivalent) pour centraliser l’atomique et l’encodage.
- **Validation :** Bien présente pour les entrées/tâches/projets ; les patches entry sont validés dans le service (`_validate_entry_patch`) et dans le storage (clés autorisées, type non modifiable).

### 4.3 Refactors proposés (sans grosse réécriture)

- Introduire `safe_write_text(path, content)` dans `pige/utils/io.py` et l’utiliser dans `storage.write_entry_content` et, à terme, dans les exports (service) pour tout fichier texte.
- Extraire les helpers de formatage d’export (durée, date, libellé temps entrée) dans un module partagé (ex. `pige/utils/formatting.py` ou dans `strings`/`dates`) pour éviter la duplication entre `export_project_raw`, `export_project_narrative`, `export_meeting_minutes`, `export_weekly_summary`.
- Garder la frontière “service ne fait pas de messagebox” ; toutes les erreurs remontent en `ValueError` et sont gérées par la GUI (ou CLI) avec message utilisateur.

---

## 5. Points chauds performance (sans optimisation prématurée)

- **Relecture complète des fichiers :** Chaque `refresh_projects` / `refresh_entries` / `refresh_tasks` déclenche `read_projects()`, `read_entries_meta()` (qui relit tout `entries.jsonl` et replie), `read_tasks()`. Pour de gros volumes, le repli JSONL à chaque rafraîchissement est le coût principal.
- **Recherche avec “Include body” :** `service.search(..., include_body=True)` lit le corps de chaque entrée (`read_entry_body`) pour chaque entrée dont les métadonnées ne matchent pas ; coût linéaire en nombre d’entrées et en taille des MD.
- **Rebuild des trees :** `project_tree.delete(*get_children())` puis N `insert` ; idem pour entry_tree, task_tree, in_progress_tree, upcoming_tree. Pas de mise à jour incrémentale.

Recommandations à faible risque :

- **Cache snapshot entries :** En GUI, après un `refresh_entries`, garder en mémoire la liste des `EntryMeta` (déjà fait via `entries_by_id` / liste affichée) ; éviter de rappeler `read_entries_meta()` plusieurs fois dans la même “transaction” utilisateur (ex. après update_entry_meta, le service relit déjà ; la GUI pourrait réutiliser l’entrée retournée au lieu de refaire un refresh complet si l’affichage le permet).
- **Débounce recherche :** Déjà 200 ms ; pour “Include body”, envisager un délai plus long (ex. 400 ms) ou limiter la recherche au corps aux N dernières entrées du projet (non implémenté).
- **Limiter les refresh en cascade :** Quand une seule entrée change (metadata ou contenu), mettre à jour uniquement la ligne correspondante dans le tree au lieu de refaire tout le tree (plus complexe, à faire seulement si les perfs deviennent un problème).

Plan d’instrumentation léger :

- Ajouter des appels `logging.debug` ou des timers (ex. `time.perf_counter()`) autour de : `storage.read_entries_meta()`, `_fold_entry_events`, `service.search(..., include_body=True)`, et dans `refresh_entries` / `refresh_projects` pour mesurer le temps passé en I/O et en rebuild tree.

---

## 6. Qualité et fiabilité

### 6.1 Gestion d’erreurs

- **Exceptions qui remontent :** Le service lève `ValueError` pour données invalides ou ressource introuvable ; la GUI attrape `ValueError` et affiche `messagebox.showerror("Error", str(exc))`. Plusieurs blocs `except Exception` dans la GUI (ex. chargement config, détection data dir, callbacks) avalent l’erreur sans message utilisateur ni log → en cas de bug, difficile à diagnostiquer.
- **Recommandation :** Remplacer les `except Exception` par des types plus précis où c’est possible ; dans les blocs qui doivent absorber (ex. pour ne pas faire planter l’app), ajouter `logging.exception(...)` ou au minimum `logging.debug(...)`.

### 6.2 Opérations fichier

- **Écriture atomique :** `projects.json`, `tasks.json`, `timers.json`, prefs : oui (`.tmp` + `os.replace`). Contenu entrées (`.md`) et exports : non.
- **Écriture partielle :** Risque pour `entries/<id>.md` et fichiers d’export en cas d’interruption.
- **Chemins cross-platform :** Utilisation de `Path` ; `path.relative_to`, `as_posix()` pour le zip ; pas de concaténation de chaînes pour les chemins. `copy_data_dir_contents` et `restore_backup` utilisent `Path` ; à vérifier sous Windows pour les chemins longs (pas de gestion explicite).

### 6.3 Concurrence

- Pas de threads : tout est synchrone dans le mainloop Tk. Autosave : délai 1200 ms après la dernière modification, puis `_write_entry_content(autosave=True)` ; si l’utilisateur change d’entrée avant la fin du délai, `_cancel_autosave` est appelé et `_loading_entry` évite de déclencher un autosave pendant le chargement. Timer : `_poll_timer` toutes les 1 s lit le disque ; pas de lock. Pas de race identifiée, mais si on ajoutait un thread pour I/O (ex. sauvegarde en arrière-plan), il faudrait ne pas lire `entries_by_id` / `current.entry_id` pendant une écriture.

### 6.4 Améliorations fiabilité concrètes

- Rendre l’écriture du contenu des entrées et des exports atomique (voir section 2).
- Ajouter du logging (niveau DEBUG ou INFO) dans les chemins d’erreur et dans les `except Exception` restants.
- Tester explicitement le comportement sous Windows (chemins, `os.replace`) et macOS (permissions, chemins avec espaces).

---

## 7. Sécurité et confidentialité (pragmatique)

- **Données locales :** Projets, entrées, tâches, timelogs, exports et prefs sont dans `data_dir` (ou config global pour le chemin). Pas de chiffrement ; les exports MD peuvent contenir des notes sensibles.
- **Recommandations :** (1) Documenter que les backups et exports contiennent les données en clair ; (2) option d’export “redacted” (ex. masquer le corps des entrées ou remplacer par “[redacted]”) si besoin de partage ; (3) noms de fichiers d’export déjà assainis (`strings.sanitize_project_name`, `_sanitize_filename_part`) — continuer à éviter les caractères spéciaux et path traversal ; (4) lors de la restauration d’un backup, le backup existant est sauvegardé dans `exports/backup_before_restore_*.zip` — s’assurer que l’utilisateur est informé de l’emplacement.

---

## 8. État de la suite de tests

### 8.1 Tests existants et trous

- **test_storage.py :** Init storage (fichiers créés, timers.json valide). Manque : `read_entries_meta` avec events (entry, update, delete), `_fold_entry_events` avec lignes invalides, `read_tasks` avec champs inconnus, `read_timelogs` avec lignes partielles, `write_entry_content` / `read_entry_body`, `restore_backup` (format reconnu / non reconnu).
- **test_service.py :** Nombreux cas (create/update/delete project, add/update/delete entry, tasks, timer, exports raw, narrative partiel, meeting minutes / weekly non couverts en détail). Manque : `list_in_progress_threads`, `list_in_progress_entries`, `move_entry`, `extract_followup_tasks` / `create_followup_tasks`, `export_project_narrative` (structure complète), `export_weekly_summary`, erreurs de validation (types invalides, meeting hours invalides).
- **test_cli.py :** Export narrative, plage de dates invalide (from > to). Manque : init, project add/list, entry add, time start/stop/today, export raw, export meeting, export weekly, restore.

### 8.2 Proposition de 8–15 tests à haute valeur (service / storage)

1. **storage** : `read_entries_meta` avec un mélange d’events (entry, entry_update, entry_delete) et vérification de l’ordre et du contenu final.
2. **storage** : `read_entries_meta` avec une ligne JSONL invalide → lève avec message contenant le numéro de ligne.
3. **storage** : `read_tasks` avec un objet contenant une clé inconnue → soit ignorer la clé (après refactor), soit documenter le comportement actuel (TypeError si dataclass stricte).
4. **storage** : `write_entry_content` puis `read_entry_body` → contenu identique ; (après atomique) écriture interrompue simulée (fichier .tmp sans replace) → ancien contenu encore lisible.
5. **service** : `list_in_progress_threads` avec entrées et tâches liées → vérifier les comptes et le tri.
6. **service** : `list_in_progress_entries` avec filtres include_created / include_treated.
7. **service** : `move_entry` → entrée dans un autre projet, métadonnées à jour, ancien projet sans l’entrée.
8. **service** : `extract_followup_tasks` avec body contenant `- [ ]` et `ACTION:` → liste de titres attendue.
9. **service** : `create_followup_tasks` → tâches créées avec `linked_entry_id` correct.
10. **service** : `search` avec `include_body=True` → une entrée qui matche seulement dans le body est retournée.
11. **service** : `export_project_narrative` → fichier contient sections Résumé, Décisions, Chronologie, Temps, Annexes.
12. **service** : `export_weekly_summary` avec plage et projet optionnel → structure et totaux cohérents.
13. **service** : `add_entry` avec type invalide → ValueError ; meeting avec start > end → ValueError.
14. **service** : `update_entry_meta` avec entry_date invalide → ValueError.
15. **storage** : `restore_backup` avec zip valide (créé par create_backup) → données restaurées ; avec zip sans marqueurs → ValueError.

Fixture minimale : `TemporaryDirectory`, `Storage(Path(tmp)/"data")`, `service.init_storage()`, puis création de projets/entrées/tâches/timelogs via le service pour les cas multi-entités.

---

## 9. Feuille de route des améliorations

### Priorisation (Must / Should / Could)

**Must (priorité haute)**  
- Rendre l’écriture du contenu des entrées atomique (`storage.write_entry_content` + optional `io.safe_write_text`).
- Ajouter du logging (au moins dans les `except Exception` de la GUI et du storage) pour faciliter le diagnostic.

**Should (priorité moyenne)**  
- Lecture robuste de `projects.json` / `tasks.json` / `timers.json` (filtrer clés connues, défauts pour optionnels).
- Tests ciblés : `_fold_entry_events`, `list_in_progress_threads`, `move_entry`, `extract_followup_tasks`, `export_project_narrative` / `export_weekly_summary`, et un test de restauration backup.
- Écriture atomique des exports (service) via un helper d’écriture texte.

**Could (priorité basse)**  
- Découpage de `gui.py` (panneaux, dialogs, prefs en modules).
- Compaction optionnelle de `entries.jsonl`.
- Option d’export “redacted” pour la confidentialité.
- Raccourcis affichés dans les menus.
- Cache / mise à jour incrémentale des trees si besoin de perfs.

### Top 3 : plans d’implémentation (diffs minimaux)

**1) Écriture atomique du contenu des entrées**

- **Fichiers :** `pige/utils/io.py`, `pige/core/storage.py`.
- **io.py :** Ajouter `def safe_write_text(path: Path, content: str) -> None:` avec `ensure_parent(path)`, `tmp_path = Path(str(path) + ".tmp")`, `open(tmp_path, "w", encoding="utf-8").write(content)`, `os.replace(tmp_path, path)`.
- **storage.py :** Dans `write_entry_content`, au lieu de `with open(path, "w", ...)`, appeler `io_utils.safe_write_text(path, content)` (après `ensure_parent` si nécessaire, ou laisser `ensure_parent` dans `safe_write_text`).
- **Tests :** Dans `test_storage` ou `test_service`, vérifier que après `write_entry_content`, le fichier existe et le contenu lu par `read_entry_body` est correct ; optionnel : simuler un crash (fichier .tmp sans replace) et vérifier que l’ancien contenu est encore lu.
- **Test manuel :** Créer une entrée, modifier le corps, sauvegarder, couper l’app brutalement pendant la sauvegarde (si possible) et rouvrir → l’ancien contenu ou le nouveau doit être cohérent (pas de fichier vide).

**2) Logging dans les blocs except Exception**

- **Fichiers :** `pige/interfaces/gui.py`, éventuellement `pige/core/storage.py`.
- **Ajout :** En tête de `gui.py`, `import logging` et `logger = logging.getLogger(__name__)`. Dans chaque bloc `except Exception:` qui ne remonte pas (ex. `_load_global_config`, `_detect_pige_data_dir`, callbacks de resize/sash), ajouter `logger.exception("...")` ou `logger.debug("...", exc_info=True)` avec un message court décrivant le contexte.
- **Option :** Configurer le niveau de log dans `__main__.py` ou via une variable d’environnement (ex. `PIGE_DEBUG=1` → niveau DEBUG).
- **Test manuel :** Provoquer une erreur (ex. config illisible, data_dir invalide) et vérifier que le log apparaît (console ou fichier selon config).

**3) Lecture robuste de tasks.json (et optionnellement timers.json / projects.json)**

- **Fichier :** `pige/core/storage.py`.
- **Idée :** Comme pour `read_timelogs`, définir `TASK_KEYS = frozenset({"id", "project_id", "title", "status", ...})` et `TASK_REQUIRED_KEYS` ; dans `read_tasks`, pour chaque `item`, construire `payload = {k: item[k] for k in TASK_KEYS if k in item}`, appliquer les défauts (status, tags, note, due_date, done_at, created_at, linked_entry_id), puis `Task(**payload)`.
- **Fichiers à modifier :** `storage.py` uniquement.
- **Tests :** Ajouter un test où `tasks.json` contient un objet avec une clé supplémentaire `"unknown": true` ; vérifier que la tâche est lue correctement et que la clé inconnue est ignorée.
- **Test manuel :** Éditer `tasks.json` à la main pour ajouter une clé, redémarrer l’app → la liste des tâches s’affiche sans erreur.

---

## Top 10 améliorations actionnables (résumé)

1. **Écriture atomique du contenu des entrées** — `io.safe_write_text` + l’utiliser dans `storage.write_entry_content`.
2. **Logging dans les `except Exception`** — Au moins `logger.exception` ou `logger.debug(..., exc_info=True)` dans GUI et storage.
3. **Lecture robuste tasks/timer_state/projects** — Filtrer les clés (comme pour timelogs) pour tolérer schéma évolutif et fichiers modifiés à la main.
4. **Tests : `_fold_entry_events` et entry_update/entry_delete** — Couvrir le repli JSONL et les erreurs de ligne.
5. **Tests : list_in_progress_threads, move_entry, extract_followup_tasks, exports narrative/weekly** — Couvrir les cas métier à forte valeur.
6. **Écriture atomique des exports** — Utiliser `safe_write_text` (ou équivalent) dans les méthodes `export_*` du service.
7. **Afficher les raccourcis dans les menus** — Labels du type “Save (Ctrl+S)” pour discoverabilité.
8. **Menu contextuel sur la liste des entrées** — Clic droit → Open, Edit, Move, Delete, Export meeting (si type meeting).
9. **Compaction optionnelle de entries.jsonl** — Commande ou outil (CLI) qui réécrit un snapshot des entrées courantes pour limiter la taille.
10. **Documenter et/ou option d’export redacted** — Pour partage de rapports sans exposer le détail des notes.

---

*Références de code :*
- Architecture : `pige/__main__.py`, `pige/interfaces/gui.py` (PigeApp.__init__, refresh_*, _write_entry_content), `pige/core/service.py`, `pige/core/storage.py`.
- Données : `pige/core/models.py`, `storage.py` (paths, append_entry_*, read_*, _fold_entry_events), `pige/utils/io.py` (safe_write_json, read_jsonl).
- GUI : `gui.py` (PigeApp, _build_menu, _build_toolbar, _poll_timer, _schedule_autosave, _load_entry, refresh_entries, messagebox) ; `gui_constants.py` (types, colonnes, templates, délais) ; `gui_helpers.py` (config, dates, people, chemins, _open_path).
- Tests : `tests/test_storage.py`, `tests/test_service.py`, `tests/test_cli.py`.
