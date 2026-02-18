# Plan d'Action - Phase 3.9: Intégration & Polish

**Objectif**: Intégrer les infrastructures créées en Phase 3 dans la GUI pour valeur utilisateur immédiate

**Durée estimée**: 5-7 jours  
**Priorité**: HAUTE  
**Prérequis**: Phase 3.0-3.4 complétées ✅

---

## Vue d'Ensemble

Phase 3 a créé d'excellentes infrastructures mais elles ne sont pas encore utilisées:
- ✅ FTS5 indexation auto → ❌ Pas d'UI de recherche
- ✅ Pagination widget → ❌ Pas intégré dans GUI
- ✅ Tree diff → ❌ Pas utilisé (full rebuild à chaque fois)

**Phase 3.9 va combler ce gap!**

---

## 🎯 Objectifs de Phase 3.9

1. **Recherche Full-Text fonctionnelle dans GUI**
   - Panneau de recherche visible
   - Résultats instantanés (<50ms)
   - Navigation dans résultats

2. **Pagination pour grandes listes**
   - TreeView projets avec pagination
   - TreeView entrées avec pagination
   - Préférences sauvegardées

3. **Updates GUI fluides**
   - Utiliser tree diff au lieu de full rebuild
   - Éliminer flickering
   - Préserver sélection/scroll

---

## 📋 Tâches Détaillées

### 3.9.1 Intégration FTS5 dans GUI (2-3 jours)

#### Tâche 1.1: Créer panneau de recherche
**Durée**: 3-4h  
**Fichier**: `pige/interfaces/gui/panels/search_panel.py`

**Fonctionnalités**:
- Input text pour requête de recherche
- Bouton "Search" + support Enter key
- Dropdown type: All / Entries / Projects / Tasks
- Status label: "X results found in Yms"

**Code à créer**:
```python
class SearchPanel(ttk.Frame):
    def __init__(self, parent, service, on_result_selected):
        # Search input + button
        # Results TreeView
        # Pagination for results
        pass
    
    def perform_search(self, query: str, search_type: str):
        # Call service.storage._get_search_index()
        # Display results
        pass
```

#### Tâche 1.2: Intégrer SearchPanel dans main_window
**Durée**: 1-2h  
**Fichier**: `pige/interfaces/gui/main_window.py`

**Modifications**:
- Ajouter SearchPanel dans layout (onglet ou panneau latéral)
- Menu: "Search → Find..." (Ctrl+F)
- Callback pour navigation vers résultat

#### Tâche 1.3: Highlighting des résultats
**Durée**: 2-3h  
**Fichier**: `pige/interfaces/gui/widgets/highlighted_text.py`

**Fonctionnalités**:
- Text widget avec highlighting des termes recherchés
- Tag configuration pour couleurs
- Scrolling auto vers premier match

#### Tâche 1.4: Tests
**Durée**: 1-2h  
**Fichier**: `tests/test_search_panel.py`

**Tests à créer**:
- Test SearchPanel création
- Test perform_search avec mock results
- Test navigation dans résultats
- Test types de recherche (entries/projects/tasks)

---

### 3.9.2 Intégration Pagination dans GUI (1-2 jours)

#### Tâche 2.1: Ajouter pagination à ProjectsPanel
**Durée**: 2-3h  
**Fichier**: `pige/interfaces/gui/panels/projects_panel.py`

**Modifications**:
- Import `PaginationControl` depuis `pagination.py`
- Ajouter `self.pagination = PaginationControl(...)` au layout
- Callback `_on_page_change()` pour recharger TreeView
- Utiliser `paginate_items()` pour slice projects list

**Pseudo-code**:
```python
def refresh(self):
    projects = self.service.list_projects()
    self.pagination.set_total_items(len(projects))
    
    # Get current page slice
    start, end = self.pagination.state.start_index, self.pagination.state.end_index
    page_projects = projects[start:end]
    
    # Display only current page
    self._populate_tree(page_projects)
```

#### Tâche 2.2: Ajouter pagination à EntriesPanel (si existe)
**Durée**: 2-3h  
**Fichier**: `pige/interfaces/gui/panels/entries_panel.py` (à créer si nécessaire)

**Fonctionnalités similaires à ProjectsPanel**

#### Tâche 2.3: Intégrer dans GUI legacy
**Durée**: 2-3h  
**Fichier**: `pige/interfaces/gui_legacy.py`

**Modifications**:
- Ajouter PaginationControl aux TreeViews existantes
- Sauvegarder page_size dans prefs
- Restaurer état pagination au démarrage

#### Tâche 2.4: Sauvegarder préférences
**Durée**: 1h  
**Fichier**: `pige/core/storage.py` ou `gui_helpers.py`

**Ajouts**:
- `gui_prefs["pagination"]["projects_page_size"] = 100`
- `gui_prefs["pagination"]["entries_page_size"] = 200`
- Load/save dans `.pige_prefs.json`

---

### 3.9.3 Tree Diff pour Updates Fluides (1 jour)

#### Tâche 3.1: Utiliser IncrementalTreeView dans ProjectsPanel
**Durée**: 2-3h  
**Fichier**: `pige/interfaces/gui/panels/projects_panel.py`

**Modifications**:
```python
from pige.interfaces.gui.tree_diff import IncrementalTreeView, tree_from_items

def __init__(...):
    self.incremental_tree = IncrementalTreeView(self.tree)

def refresh(self):
    projects = self.service.list_projects()
    new_nodes = tree_from_items(
        projects,
        id_func=lambda p: p.id,
        values_func=lambda p: (p.name, p.status, ...)
    )
    
    # Apply diff instead of full rebuild
    self.incremental_tree.apply_diff(new_nodes)
```

#### Tâche 3.2: Utiliser IncrementalTreeView dans GUI legacy
**Durée**: 3-4h  
**Fichier**: `pige/interfaces/gui_legacy.py`

**Modifications**:
- Remplacer `tree.delete(*tree.get_children())` par `apply_diff`
- Tester que sélection/scroll sont préservés
- Benchmarker performance (avant/après)

#### Tâche 3.3: Tests d'intégration
**Durée**: 1-2h  
**Fichier**: `tests/test_gui_integration.py` (nouveau)

**Tests**:
- Test refresh préserve sélection
- Test refresh préserve scroll
- Test pas de flickering (visuel, difficile à automatiser)

---

## 📊 Livrables de Phase 3.9

### Code
- [ ] `pige/interfaces/gui/panels/search_panel.py` (300+ lignes)
- [ ] `pige/interfaces/gui/widgets/highlighted_text.py` (150+ lignes)
- [ ] Modifications: `main_window.py`, `projects_panel.py`, `gui_legacy.py`
- [ ] Tests: `test_search_panel.py`, `test_gui_integration.py`

### Fonctionnalités Utilisateur
- [ ] Menu "Search → Find..." (Ctrl+F)
- [ ] Panneau recherche avec résultats instantanés
- [ ] Pagination fonctionnelle (projets, entrées)
- [ ] Préférences pagination sauvegardées
- [ ] GUI fluide sans flickering

### Documentation
- [ ] `CHANGELOG.md` - Entrée v0.4.1 "Phase 3.9 Polish"
- [ ] `ROADMAP.md` - Section Phase 3.9 complétée
- [ ] `README.md` - Section "Recherche Full-Text"

---

## ⚡ Ordre d'Exécution Recommandé

### Jour 1-2: Recherche FTS5 (haute valeur)
1. Créer `SearchPanel` basique (input + bouton)
2. Connecter à `SearchIndex.search_entries()`
3. Afficher résultats dans TreeView
4. Ajouter à `main_window.py`
5. Menu + raccourci Ctrl+F

### Jour 3: Pagination (impact visible immédiat)
6. Intégrer `PaginationControl` dans `ProjectsPanel`
7. Intégrer dans GUI legacy
8. Sauvegarder préférences

### Jour 4-5: Tree Diff (polish, moins visible mais important)
9. Remplacer rebuilds par `IncrementalTreeView`
10. Tests préservation état
11. Benchmarks performance

### Jour 6-7: Tests & Documentation
12. Tests d'intégration complets
13. Mise à jour CHANGELOG/ROADMAP
14. Session test manuelle complète

---

## ✅ Critères de Succès

### Performance
- [ ] Recherche FTS < 50ms pour 10K entrées
- [ ] Pagination affiche page instantanément (< 10ms)
- [ ] Tree updates préservent scroll/sélection

### Fonctionnalités
- [ ] Recherche full-text accessible via menu
- [ ] Pagination fonctionnelle avec préférences
- [ ] Pas de flickering lors refresh

### Qualité
- [ ] Tous tests passent (180+ tests)
- [ ] Aucune régression fonctionnelle
- [ ] Code coverage maintenu (>85%)

### UX
- [ ] Interface responsive
- [ ] Feedback instantané (search status, pagination)
- [ ] Raccourcis clavier fonctionnels

---

## 🔧 Stack Technique

### Modules Utilisés
- `pige.core.indexing.SearchIndex` - Recherche FTS5
- `pige.interfaces.gui.pagination.PaginationControl` - Widget pagination
- `pige.interfaces.gui.tree_diff.IncrementalTreeView` - Updates incrémentaux

### Nouveaux Modules
- `pige.interfaces.gui.panels.search_panel` - UI recherche
- `pige.interfaces.gui.widgets.highlighted_text` - Highlighting

### Tests
- `pytest` - Framework test
- `unittest.mock` - Mocking pour tests GUI

---

## 📈 Impact Attendu

### Avant Phase 3.9
- ❌ Pas de recherche dans GUI (CLI seulement)
- ❌ Lenteur sur grandes listes (>1000 items)
- ❌ Flickering lors refresh
- ❌ Scroll/sélection perdus

### Après Phase 3.9
- ✅ Recherche instantanée dans GUI (<50ms)
- ✅ Pagination fluide (affichage 10K+ items)
- ✅ Updates incrémentaux sans flickering
- ✅ État UI préservé (scroll, sélection)

**Gain utilisateur**: Application **professionnelle** et **scalable**! 🚀

---

## 🚀 Prochaines Étapes Après 3.9

Une fois Phase 3.9 complétée, on aura une base GUI solide pour:

### Phase 4.1: Attachments
- Drag & drop fichiers
- Affichage inline images
- Métadata attachments

### Phase 4.2: Versioning
- Historique complet entrées
- Restore versions

### Phase 4.3: Sync Git
- Auto-commit/push
- Résolution conflits

---

## Notes Techniques

### Considérations GUI Legacy
- Phase 3.9 touche principalement `gui_legacy.py`
- Migration vers GUI modulaire peut continuer en parallèle
- Pas de breaking changes pour utilisateurs

### Performance
- SearchPanel peut réutiliser `PaginationControl` pour résultats
- Tree diff évite O(n) deletes, devient O(changes)
- FTS5 déjà optimisé (<100ms pour 1K entrées)

### Tests
- Tests GUI nécessitent `tkinter` disponible
- Tests peuvent être marqués `@pytest.mark.gui` si CI sans display
- Focus sur tests logique (Presenters) plutôt que widgets

---

**Date création**: 2026-02-18  
**Phase**: 3.9 Intégration & Polish  
**Priorité**: HAUTE  
**Statut**: PLANIFIÉE
