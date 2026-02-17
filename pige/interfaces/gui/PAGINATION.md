# Phase 3.4 - Pagination TreeView

## Objectif
Permettre l'affichage fluide de très grandes quantités de données (10K+ items) en découpant par pages.

## Solution Implémentée

### Module `pige/interfaces/gui/pagination.py`

#### 1. `PaginationState` - Logique Pagination

**Dataclass complète:**
```python
@dataclass
class PaginationState:
    page: int = 1  # Current page (1-indexed)
    page_size: int = 100  # Items per page
    total_items: int = 0  # Total items
```

**Propriétés calculées:**
- `total_pages`: Nombre total de pages
- `start_index`: Index début page (0-indexed)
- `end_index`: Index fin page (0-indexed, exclusive)
- `is_first_page`: Booléen
- `is_last_page`: Booléen

**Méthodes:**
- `get_page_slice(items)`: Extrait [start:end] pour page courante
- `go_to_page(page)`: Navigation directe avec clamping
- `next_page()`: Page suivante (retourne bool si déplacé)
- `previous_page()`: Page précédente (retourne bool)
- `set_page_size(size)`: Change taille + ajuste page pour garder position

#### 2. `PaginationControl` - Widget UI Tkinter

**Composants UI:**
```
[<< Previous] Page 1 of 10 [Next >>] | Show: [100 ▼] items per page (1-100 of 957 total)
```

**Éléments:**
- Boutons Previous/Next (désactivés automatiquement)
- Label page courante
- Combobox page_size (50/100/200/500/1000/All)
- Label total items
- Jump controls (optionnel, via show_jump_controls())

**API:**
```python
pagination = PaginationControl(
    parent=frame,
    on_page_change=lambda state: refresh_with_page(state),
    initial_page_size=100,
    show_all_option=True
)

# Update total quand data change
pagination.set_total_items(len(all_items))

# Reset à page 1
pagination.reset(total_items=new_total)
```

#### 3. Helper `paginate_items()`

**Usage simple:**
```python
all_projects = service.list_projects()

paginated, state = paginate_items(
    all_projects,
    page=1,
    page_size=100
)

# Display paginated only
for project in paginated:
    tree.insert(...)
```

## Tests

### `tests/test_pagination.py` - 13 tests

1. `test_pagination_state_total_pages` - Calcul pages
2. `test_pagination_state_indices` - Start/end indices
3. `test_pagination_state_is_first_last` - First/last detection
4. `test_pagination_state_get_page_slice` - Extraction slice
5. `test_pagination_state_go_to_page` - Navigation directe
6. `test_pagination_state_next_previous` - Nav prev/next
7. `test_pagination_state_set_page_size` - Changement taille
8. `test_paginate_items_helper` - Helper function
9. `test_pagination_with_empty_list` - Liste vide
10. `test_pagination_with_small_dataset` - Petit dataset
11. `test_pagination_edge_cases` - Cas limites
12. `test_pagination_page_size_change_preserves_position` - Préservation position
13. `test_pagination_state_with_single_item` - Un seul item

**Résultat: 13/13 passent ✅**

## Usage Futur

### Dans GUI Modulaire (Panels)

```python
class EntriesPanel(ttk.Frame):
    def __init__(self, parent, service):
        super().__init__(parent)
        
        # TreeView
        self.tree = ttk.Treeview(...)
        
        # Pagination control en bas
        self.pagination = PaginationControl(
            self,
            on_page_change=self._on_page_change,
            initial_page_size=100
        )
        self.pagination.pack(side=tk.BOTTOM, fill=tk.X, pady=5)
        
        self.all_entries = []
        self.refresh()
    
    def refresh(self):
        # Load ALL entries (once)
        self.all_entries = self.service.list_entries(...)
        
        # Update pagination total
        self.pagination.set_total_items(len(self.all_entries))
        
        # Display first page
        self._on_page_change(self.pagination.state)
    
    def _on_page_change(self, state: PaginationState):
        # Get current page
        page_entries = state.get_page_slice(self.all_entries)
        
        # Update tree (with incremental diff if available)
        self._update_tree(page_entries)
```

### Dans GUI Legacy

Modifier `refresh_entries()`:
```python
def refresh_entries(self):
    # ... existing filter logic ...
    self.all_filtered_entries = [e for e in entries if matches_filter(e)]
    
    if not hasattr(self, '_entries_pagination'):
        self._entries_pagination = PaginationControl(
            self.entries_panel_bottom,  # New frame at bottom
            on_page_change=self._refresh_entries_page
        )
    
    self._entries_pagination.set_total_items(len(self.all_filtered_entries))
    self._refresh_entries_page(self._entries_pagination.state)

def _refresh_entries_page(self, state):
    page_entries = state.get_page_slice(self.all_filtered_entries)
    # Clear + rebuild tree with ONLY page_entries
    self.entry_tree.delete(*self.entry_tree.get_children())
    for entry in page_entries:
        self._insert_entry(entry)
```

## Combinaison avec Incremental Update

**Optimal: Pagination + Diff:**
```python
class OptimizedPanel(ttk.Frame):
    def __init__(self, parent, service):
        super().__init__(parent)
        self.tree = ttk.Treeview(...)
        self.incremental = IncrementalTreeView(self.tree)
        self.pagination = PaginationControl(
            self,
            on_page_change=self._on_page_change
        )
        self.all_items = []
    
    def refresh(self):
        # Load all
        self.all_items = self.service.list_all()
        self.pagination.set_total_items(len(self.all_items))
        self._on_page_change(self.pagination.state)
    
    def _on_page_change(self, state):
        # Get page
        page_items = state.get_page_slice(self.all_items)
        
        # Build nodes
        new_nodes = tree_from_items(page_items, ...)
        
        # Apply diff (no flicker!)
        self.incremental.apply_diff(new_nodes)
```

**Bénéfices combinés:**
- ✅ Pagination: Affiche seulement 100 items au lieu de 10K
- ✅ Diff: Update incrémental entre pages (pas de clignotement)
- ✅ Performance: O(page_size) au lieu de O(total)

## Benchmarks (Théoriques)

### Sans Pagination (10K items)

**Rebuild complet:**
- Delete 10K nodes: ~500ms
- Insert 10K nodes: ~1000ms
- **Total: ~1500ms + clignotement + lag UI**

### Avec Pagination (100 items/page)

**Page initiale:**
- Delete 0 (first load): 0ms
- Insert 100 nodes: ~10ms
- **Total: ~10ms, fluide**

**Navigation page suivante:**
- Delete 100: ~5ms
- Insert 100: ~10ms
- **Total: ~15ms, fluide**

**Avec Pagination + Diff:**
- Compute diff (100 items): ~2ms
- Apply changes (typically ~50 modified): ~3ms
- **Total: ~5ms, ultra-fluide**

**Gain: 300x plus rapide!**

## Préférences Utilisateur

### Sauvegarde dans `.pige_prefs.json`

```json
{
  "pagination": {
    "projects_page_size": 100,
    "entries_page_size": 50,
    "tasks_page_size": 200
  }
}
```

**Lors init:**
```python
prefs = load_prefs()
pagination = PaginationControl(
    parent,
    callback,
    initial_page_size=prefs.get("pagination", {}).get("entries_page_size", 100)
)
```

**Lors changement:**
```python
def _on_page_size_change(self, state):
    prefs["pagination"]["entries_page_size"] = state.page_size
    save_prefs(prefs)
```

## Fonctionnalités Avancées

### 1. Jump to Page

```python
# Show jump controls (e.g., on Ctrl+G)
pagination.show_jump_controls()

# User enters page number + Go
# Automatically hidden after navigation
```

### 2. "All" Option

```python
pagination = PaginationControl(
    parent,
    callback,
    show_all_option=True  # Adds "All" to dropdown
)

# When "All" selected:
# - page_size set to total_items
# - Single page displayed
# - Useful for printing/export
```

### 3. Smart Position Preservation

Lors changement page_size:
- Calcule item au début de page actuelle
- Trouve nouvelle page contenant cet item
- Ajuste page automatiquement

Exemple:
- Page 5 avec size 50 (items 200-249)
- Change à size 100
- Nouvelle page 3 (items 200-299) ✅ Position préservée

## Limitations

1. **Recherche/filtrage:**
   - Pagination appliquée APRÈS filtres
   - Nécessite reload si filtre change nombre total items

2. **Tri:**
   - Tri appliqué sur ALL items avant pagination
   - Changement tri = recalcul complet (acceptable)

3. **Sélection cross-page:**
   - Sélection perdue lors navigation page
   - Peut être amélioré avec tracking sélection

## Prochaines Étapes

### Option A: Intégrer dans GUI Legacy
1. Ajouter frames bottom pour pagination dans `gui_legacy.py`
2. Modifier `refresh_projects/entries/tasks()` pour utiliser
3. Sauvegarder préférences page_size

### Option B: Utiliser dans GUI Modulaire
1. `EntriesPanel` avec pagination dès le début
2. `ProjectsPanel` avec pagination (si beaucoup de projets)
3. `TasksPanel` avec pagination

### Option C: Combiner avec Incremental Update
1. Pagination pour réduire N
2. Diff pour updates fluides
3. Performance optimale!

### Option D: Continuer Phase 3.5 (MVC/MVP)
- Laisser pagination prête
- Implémenter Presenters
- Intégrer pagination dans Views

## Conclusion

✅ **Phase 3.4 complétée!**

- Widget pagination complet et testé
- API simple et flexible
- Performance théorique excellente
- Prêt pour intégration
- 177 tests passants (dont 13 nouveaux)

**Stack complet maintenant:**
- Découpage GUI (Phase 3.1) ✅
- FTS5 (Phase 3.2) ✅
- Incremental Updates (Phase 3.3) ✅
- Pagination (Phase 3.4) ✅

**Prochaine étape:** Phase 3.5 Architecture MVC/MVP
