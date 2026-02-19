# PIGE – Backlog et priorités

**Dernière mise à jour** : Février 2026  
**Référence** : `ROADMAP.md` pour le détail des phases et la timeline.

---

## 1. TODOs dans le code (à traiter en priorité)

### Priorité haute – Dialogues manquants (impact UX direct)

| Fichier | Ligne | Description | Action |
|---------|-------|-------------|--------|
| `pige/interfaces/gui/main_window.py` | 184 | Nouveau projet | Brancher ou créer dialogue « New project » |
| `pige/interfaces/gui/main_window.py` | 189 | Nouvelle entrée | Brancher ou créer dialogue « New entry » |
| `pige/interfaces/gui/projects_panel.py` | 251 | Nouveau projet | Ouvrir dialogue new project |
| `pige/interfaces/gui/projects_panel.py` | 261 | Détails projet | Ouvrir détails ou callback |
| `pige/interfaces/gui/entries_panel.py` | 337-338 | Créer entrée | Implémenter CreateEntryDialog (remplacer messagebox) |
| `pige/interfaces/gui/entries_panel.py` | 349-350 | Éditer entrée | Implémenter EditEntryDialog (remplacer messagebox) |
| `pige/interfaces/gui/panels/calendar_panel.py` | 1129 | Éditer task | Implémenter dialogue édition task |
| `pige/interfaces/gui/panels/calendar_panel.py` | 1137 | Créer entry (calendrier) | Implémenter dialogue création entry |
| `pige/interfaces/gui/panels/calendar_panel.py` | 1213 | Créer task (calendrier) | Implémenter dialogue création task |
| `pige/interfaces/gui/panels/work_panel.py` | 1241 | Éditer task | Implémenter dialogue édition task |
| `pige/interfaces/gui/panels/dashboard_panel.py` | 550 | Détail entry (double-clic) | Ouvrir dialogue détail entry |
| `pige/interfaces/gui/panels/dashboard_panel.py` | 576 | Éditer task (double-clic) | Ouvrir dialogue édition task |

### Priorité moyenne – Navigation et cohérence

| Fichier | Ligne | Description | Action |
|---------|-------|-------------|--------|
| `pige/interfaces/gui/main_window.py` | 206 | Navigation sélection | Naviguer vers l’élément sélectionné dans le bon panel |

### Priorité basse – Core / sécurité / données

| Fichier | Ligne | Description | Action |
|---------|-------|-------------|--------|
| `pige/core/models.py` | 102 | Mot de passe HTTP Basic | Chiffrer le mot de passe (actuellement en clair) |
| `pige/core/service.py` | 1941 | `get_pending_items()` | Filtrer aussi les entries avec tags "waiting" ou "blocked" |

---

## 2. Migration GUI modulaire (backlog technique)

Référence : `pige/interfaces/gui/README.md`.

### À faire en premier
- [ ] **Dialogue New Project** – Créer `dialogs/new_project.py` et brancher depuis `main_window` + `projects_panel`.
- [ ] **Dialogue New Entry** – Créer `dialogs/new_entry.py` et brancher depuis `main_window` + `entries_panel` / calendrier.
- [ ] **Dialogue New Task** – Créer `dialogs/new_task.py` et brancher depuis calendrier + work_panel.
- [ ] **CreateEntryDialog / EditEntryDialog** – Implémenter et remplacer les `messagebox.showinfo("TODO", ...)` dans `entries_panel`.
- [ ] **Dialogues édition task** – Unifier et brancher depuis calendar_panel, work_panel, dashboard_panel.

### Ensuite
- [ ] Extraire les autres dialogs (~30 restants) : export, preferences, etc.
- [ ] Panels : finaliser entries, tasks, details (liste + éditeur).
- [ ] Migrer `main_window.py` vers fonctionnalité complète (callbacks, navigation).
- [ ] Mettre à jour `__main__.py` pour utiliser `main_window.py` modulaire.
- [ ] Supprimer le legacy `gui_legacy.py` après migration complète.
- [ ] Tests unitaires pour panels/dialogs.

---

## 3. ROADMAP – Éléments pending (résumé)

Le détail complet est dans **`ROADMAP.md`**. Ci-dessous : résumé des items non cochés par phase.

### Phase 1 (optionnel)
- [ ] **1.7** Validation des dates dans la GUI (1 jour).

### Phase 2 (reportés)
- [ ] Liens entre projets (interface, panneau détails, validation).
- [ ] Filtres combinés et vues personnalisées (sauvegarde, dropdown, dialogue).

### Phase 3 (reportés / optionnels)
- [ ] Drag & drop pour réorganisation (Phase 4+).
- [ ] Intégration recherche dans GUI legacy (déjà fait dans modular).
- [ ] Intégration PaginationControl / IncrementalTreeView dans `gui_legacy.py`.
- [ ] Tests intégration GUI.
- [ ] **3.5** Architecture MVC/MVP (Presenters, vues, tests unitaires).

### Phase 4+
- [ ] Pièces jointes, versioning, sync Git, analytics, templates, thèmes, etc.  
  → Voir `ROADMAP.md` sections Phase 4, 5, 6.

---

## 4. Priorités recommandées (ordre suggéré)

1. **Court terme (valeur utilisateur)**  
   - Implémenter ou brancher les dialogues **New Project**, **New Entry**, **New Task** et **Edit Entry / Edit Task** pour supprimer les messagebox "TODO".  
   - Brancher la **navigation** depuis la sélection (main_window → bon panel).

2. **Moyen terme (migration GUI)**  
   - Créer les dialogs manquants dans `pige/interfaces/gui/dialogs/` et les connecter aux panels existants.  
   - Finaliser les panels entries/tasks/details.

3. **Plus tard (ROADMAP)**  
   - Phase 1 optionnelle : validation dates GUI.  
   - Phase 3.5 : Presenters testables.  
   - Phase 4+ : pièces jointes, versioning, sync, etc.

---

## 5. Références

- **ROADMAP.md** – Phases 1–6, timeline, critères de succès.
- **pige/interfaces/gui/README.md** – Architecture GUI modulaire et statut de migration.
- **CHANGELOG.md** – Historique des livrés.
