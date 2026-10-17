# Revue de code — PIGE (Project Integrated Journaling Engine)

**Date :** février 2026 (revue à jour après corrections)  
**Dernière analyse :** 11 février 2026  
**Périmètre :** package `pige/`, `utils/`, `tests/`, `pyproject.toml`, `README.md`

---

## 0. Synthèse de l’analyse actuelle (11/02/2026)

- **État global :** Le projet est cohérent, bien structuré et les 31 tests passent.
- **Points forts confirmés :** Architecture core/interfaces/utils respectée, typage, écriture atomique, validation métier, event-sourcing entries, IDs homogènes (32 hex), lecture timelogs robuste.
- **Points d’attention :** `read_projects` / `read_tasks` / `read_timer_state` restent sensibles aux clés inconnues dans les JSON ; le CLI n’expose pas tous les paramètres d’entrée ; `gui.py` très volumineux (~5900 lignes) ; nombreux `except Exception` sans log.
- **Recommandation :** Aucun correctif urgent ; les améliorations listées en §2 restent optionnelles et à planifier.

---

## 1. Points positifs

### 1.1 Architecture
- **Séparation claire** : `core/` (modèles, service, stockage), `interfaces/` (CLI, GUI), `utils/` (dates, ids, io, strings). La philosophie du README est respectée.
- **CLI sans logique métier** : le CLI délègue au `PigeService` ; les erreurs sont remontées proprement.
- **Stockage ouvert** : JSON/JSONL + Markdown, pas de base propriétaire.

### 1.2 Qualité du code
- **Typage** : usage cohérent de `from __future__ import annotations`, types sur les signatures et dataclasses.
- **Écriture atomique** : `safe_write_json` / `safe_write_jsonl` (fichier `.tmp` + `os.replace`) évitent les fichiers corrompus en cas d’arrêt brutal.
- **Validation** : entrées (type, meeting hours, decision_done), tâches (status, champs), patches d’entrée (clés autorisées) sont validés.
- **Event-sourcing léger** : `entries.jsonl` avec `entry` / `entry_update` / `entry_delete` et repli via `_fold_entry_events` ; historique exploitable.
- **Identifiants homogènes** : projets, entrées et tâches utilisent désormais `ids.new_id()` (32 hex).
- **Règle `ts` / `entry_date`** : si `entry_date` est fourni à `add_entry`, `ts` est fixé au midday de cette date ; sinon à l’heure courante.
- **Lecture timelogs robuste** : `read_timelogs` ne garde que les clés connues (`TIMELOG_KEYS`), ignore les lignes mal formées et assure des valeurs par défaut pour les optionnels.

### 1.3 Tests
- 31 tests (storage, service, CLI) ; tous passent.
- `test_delete_project_removes_associated_data`, `test_export_narrative_succeeds`, `test_add_entry_with_entry_date_midday`, `test_create_task_persists` (format ID 32 chars) couvrent les cas sensibles.

### 1.4 UX / robustesse
- Confirmation avant suppression de projet (GUI).
- Backup automatique avant `restore_backup`.
- Détection de répertoire PIGE (`is_pige_data_dir`, `_detect_pige_data_dir`) pour éviter d’écraser un mauvais dossier.
- README : unittest et pytest documentés pour les tests.

---

## 2. Améliorations possibles (non bloquantes)

### 2.1 Lecture JSON / JSONL et clés inconnues
- **`read_tasks`** : `Task(**payload)` avec `payload = dict(item)` ; des clés inconnues dans `tasks.json` lèveraient `TypeError`.
- **`read_timer_state`** : `TimerState(**data)` ; idem si le JSON a des champs en trop.
- **`read_projects`** : `Project(**item)` ; idem (sauf `links` déjà normalisé).
- **Recommandation** : à terme, appliquer le même principe que pour les timelogs (ensemble de clés autorisées + `setdefault` pour les optionnels) pour tasks, timer_state et projets si on veut tolérer des fichiers modifiés à la main ou des évolutions de schéma.

### 2.2 CLI : paramètres d’entrée non exposés
- Le service `add_entry` accepte `entry_date`, `person`, `group`, `start_time`, `end_time`, `decision_done`, mais le CLI ne propose que `project_id`, `type`, `title`, `tags`, `body`, `--open`.
- **Recommandation** : optionnel ; ajouter par exemple `--entry-date`, `--person`, `--group` (et éventuellement meeting/decision) si on veut créer des entrées complètes depuis le CLI.

### 2.3 Fichier GUI
- `pige/interfaces/gui.py` reste très volumineux (~5900 lignes), ce qui complique la navigation et les tests ciblés.
- **Recommandation** : à moyen terme, découper en modules (ex. panneaux, dialogs, préférences) ou extraire des classes/fenêtres dédiées.

### 2.4 Gestion d’erreurs large
- Plusieurs `except Exception` dans la GUI (et quelques-uns en storage) avalent toute erreur. Pour le débogage, un `logging.exception` (ou au minimum un log) dans ces blocs aiderait ; idéalement, capturer des types d’exceptions plus précis où c’est possible.

### 2.5 Lignes vides dans JSONL
- `read_jsonl` : une ligne vide (`payload == ""`) provoque `json.loads("")` → `JSONDecodeError` et est signalée comme « Corrupt JSONL ». Comportement cohérent ; à documenter si on souhaite un jour ignorer les lignes vides (ex. `if not payload: continue`).

---

## 3. Sécurité et chemins

### 3.1 Restauration de backup
- `restore_backup` extrait le zip dans un répertoire temporaire, puis copie avec `path.relative_to(source_dir)` ; les chemins de destination sont donc dérivés de la structure du backup, pas de saisie utilisateur brute. Pas de path traversal côté copie.
- L’extraction `ZipFile.extractall` peut, selon la version de Python, être sensible à des archives malveillantes (Zip Slip). En contexte local (backup créé par l’app), le risque est limité ; pour des zips d’origine externe, une validation explicite des chemins extraits est recommandée.

### 3.2 Répertoire de données
- `data_dir` vient de `PIGE_DATA_DIR` ou de la config / répertoire courant. Les chemins d’entrées sont construits à partir du modèle (ex. `entry.content_path`). Aucune utilisation directe de saisie utilisateur comme chemin absolu ; pas de path traversal identifié côté GUI/CLI.

---

## 4. Synthèse par fichier

| Fichier / module        | État | Commentaire |
|--------------------------|------|-------------|
| `pige/__main__.py`       | OK   | Point d’entrée clair (gui vs CLI). |
| `pige/core/models.py`    | OK   | Dataclasses bien typées. |
| `pige/core/storage.py`   | OK   | Init, events, backup/restore, `read_timelogs` robuste. |
| `pige/core/service.py`   | OK   | Logique métier, validation, export narratif, delete_project, ts/entry_date, ids pour tâches. |
| `pige/utils/*`           | OK   | dates, ids, io, strings ; io avec ligne vide entre append_jsonl et safe_write_jsonl. |
| `pige/interfaces/cli.py` | OK   | Délégation au service, gestion d’erreurs, pas de logique métier. |
| `pige/interfaces/gui.py` | OK   | Fonctionnel ; très gros fichier, nombreux `except Exception`. |
| `tests/*`                | OK   | 31 tests, dont narrative, delete_project, entry_date, task ID. |
| `README.md`              | OK   | À jour (narrative, pytest). |
| `pyproject.toml`         | OK   | Dépendances vides, Python ≥ 3.11. |

---

## 5. Conclusion

Le projet est **solide et à jour** : les corrections précédentes (IDs tâches, règle ts/entry_date, lecture timelogs, io.py, README) sont en place ; l’architecture reste claire, les données ouvertes, l’écriture atomique et la validation en place. Les points restants sont des **améliorations optionnelles** (robustesse lecture tasks/timer_state/projects, CLI plus riche, découpage GUI, logging dans les `except Exception`). Aucun correctif de sécurité urgent n’a été identifié dans le périmètre revu.

---

## 6. Checklist rapide (analyse 11/02/2026)

| Critère | État |
|--------|------|
| Tests (31) | ✅ Tous passent (pytest) |
| Typage (annotations) | ✅ Cohérent (`__future__ annotations`, dataclasses) |
| Écriture fichiers | ✅ Atomique (`.tmp` + `os.replace`) |
| Validation entrées / patches | ✅ Types, meeting hours, decision_done, tâches |
| Lecture JSON/JSONL tolérante | ⚠️ Timelogs OK ; projects/tasks/timer_state sensibles aux clés en trop |
| CLI vs service | ✅ Délégation nette, pas de logique métier dans le CLI |
| Sécurité chemins / backup | ✅ Pas de path traversal identifié |
| Taille gui.py | ⚠️ ~5900 lignes — découpage recommandé à moyen terme |
| `except Exception` sans log | ⚠️ Nombreux (storage, service, gui) — ajouter `logging.exception` pour le débogage |
