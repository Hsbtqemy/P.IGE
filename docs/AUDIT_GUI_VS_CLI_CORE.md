# Audit : fonctionnalités Core / CLI non exposées dans la nouvelle GUI

> **Note du 2026-10-17** : cet audit est antérieur au serveur (`pige/server/`), à l'interface web et à l'extension Thunderbird. Les 49 accès directs à `service.storage` depuis les interfaces sont suivis dans `BACKLOG.md`, étape 3 (« service assaini »).

Ce document liste ce qui est disponible dans le **core** (service, storage) et la **CLI** mais **pas** (ou pas clairement) dans la nouvelle interface graphique (main_window + panels + dialogs).

---

## 1. Commandes CLI sans équivalent GUI

| Commande CLI | Description | Dans nouvelle GUI ? |
|--------------|-------------|----------------------|
| `pige init` | Initialise le répertoire de données | Implicite au démarrage (init_storage). Pas de menu « Réinitialiser / Recréer les données ». |
| `pige log today` | Affiche les entrées du jour regroupées par projet | **Oui**. Panneau Work → bloc « Journal du jour » (liste + double-clic pour ouvrir). |
| `pige time today` | Affiche les temps enregistrés aujourd’hui par projet | **Oui**. Panneau Work → sous le timer, libellé « Aujourd’hui: Projet: X min ». |
| `pige compact` | Compacte le journal des entrées (supprime l’historique update/delete) | **Oui**. Menu Outils → « Compacter le journal des entrées ». |
| `pige migrate` | Migration schéma (ex. hiérarchie des projets) | **Oui**. Menu Outils → « Migrer les données (hiérarchie projets) ». |
| `pige rebuild-index` | Reconstruit l’index de recherche plein texte | **Oui**. Menu Outils → « Reconstruire l’index de recherche ». |

---

## 2. Méthodes Core (service / storage) sans exposition GUI

### 2.1 Sauvegarde / restauration / maintenance

| Méthode / API | Rôle | CLI | Nouvelle GUI |
|---------------|------|-----|--------------|
| `service.backup_data(out_path)` | Sauvegarde ZIP des données | Non | **Oui**. Menu Fichier → « Sauvegarder les données… ». |
| `service.restore_data(zip_path)` | Restauration depuis un ZIP | Non | **Oui**. Menu Fichier → « Restaurer depuis une sauvegarde… ». |
| `service.compact_entries()` | Compactage du journal d’entrées | Oui (`pige compact`) | **Oui**. Menu Outils → « Compacter le journal des entrées ». |
| `storage.migrate_projects_hierarchy()` | Migration hiérarchie projets | Oui (`pige migrate`) | **Oui**. Menu Outils → « Migrer les données (hiérarchie projets) ». |
| `storage.rebuild_search_index()` | Rebuild index recherche | Oui (`pige rebuild-index`) | **Oui**. Menu Outils → « Reconstruire l’index de recherche ». |
| `service.migrate_data_dir(dest_dir)` | Migration du répertoire de données vers un autre dossier | Non | **Non** (usage plutôt admin / script). |

### 2.2 Journal et temps « du jour »

| Méthode / API | Rôle | CLI | Nouvelle GUI |
|---------------|------|-----|--------------|
| `service.log_today()` | Entrées du jour regroupées par projet | Oui (`pige log today`) | **Oui**. Panneau Work → « Journal du jour ». |
| `service.time_today()` | Temps enregistrés aujourd’hui par projet (totaux) | Oui (`pige time today`) | **Oui**. Panneau Work → « Aujourd’hui: … » sous le timer. |

### 2.3 Tâches de suivi (follow-up)

| Méthode / API | Rôle | CLI | Nouvelle GUI |
|---------------|------|-----|--------------|
| `service.extract_followup_tasks(entry_id)` | Extrait les lignes type « ACTION / TODO » d’une entrée | Non | **Oui**. Panneau Work → éditeur d’entrée → bouton « Créer tâches de suivi ». |
| `service.create_followup_tasks(entry_id, titles)` | Crée des tâches à partir de ces lignes | Non | **Oui**. Idem, dialogue de sélection des lignes puis création. |

### 2.4 Autres APIs core

| Méthode / API | Rôle | Dans nouvelle GUI |
|---------------|------|--------------------|
| `service.list_in_progress_threads(days=14)` | Fils « en cours » (résumé par projet/personnes) | **Non** (pas utilisé dans les panels). |
| `service.get_project_tree()` | Arbre projets (pour export hiérarchie) | Utilisé indirectement par l’export « Hiérarchie des projets ». Pas de vue dédiée. |

---

## 3. Ce qui est bien couvert dans la nouvelle GUI

- **Projets** : création, édition, suppression, déplacement, réordonnancement, hiérarchie (sous-projets via `parent_id` dans le dialogue Nouveau projet).
- **Entrées** : création, édition (méta + contenu), suppression, déplacement vers un autre projet.
- **Tâches** : création, édition, statut fait/à faire, liste par projet (+ sous-projets dans Work).
- **Timer** : start / stop (Work), ajout manuel de temps.
- **Recherche** : recherche plein texte (panneau Search).
- **Export** : projet (brut / narratif), CR réunion, résumé hebdo, hiérarchie des projets (menu Fichier + clic droit sur projet/entrée dans Work).
- **Calendrier** : vues mois/semaine, événements, entrées, tâches, création entrée/tâche à la date.
- **Dashboard** : focus, en cours, à faire, à venir (`get_in_progress_items`, `get_pending_items`, `get_upcoming_items`, `get_focus_suggestions`).

---

## 4. Synthèse des manques (priorisation possible)

1. ~~**Backup / Restore**~~ : **Implémenté** — Menu Fichier → Sauvegarder / Restaurer.
2. ~~**Temps du jour**~~ : **Implémenté** — Panneau Work, sous le timer.
3. ~~**Journal du jour**~~ : **Implémenté** — Panneau Work, bloc « Journal du jour ».
4. ~~**Tâches de suivi**~~ : **Implémenté** — Bouton « Créer tâches de suivi » dans l’éditeur d’entrée.
5. ~~**Maintenance**~~ : **Implémenté** — Menu Outils (Reconstruire index, Migrer, Compacter).
6. **Init / données** : option « Réinitialiser le jeu de données » (avec précaution) si besoin, pour alignement avec `pige init`.

---

*Audit mis à jour après intégration : backup/restore, temps du jour, journal du jour, tâches de suivi, menu Outils, export par clic droit (projet/entrée).*
