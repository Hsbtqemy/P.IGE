# Phase 3.3 - Mise à Jour Incrémentale TreeView

## Objectif
Éliminer le clignotement des TreeViews en implémentant des mises à jour incrémentales basées sur des diffs, au lieu de reconstruire entièrement l'arbre à chaque rafraîchissement.

## Problème Actuel

Dans `gui_legacy.py`, la méthode `refresh_projects()` (et similaires) fait:
```python
self.project_tree.delete(*self.project_tree.get_children())  # ❌ Supprime tout
# ... puis reconstruit tout
```

**Conséquences:**
- ❌ Clignotement visible
- ❌ Perte de sélection/scroll
- ❌ Performance O(n) même pour 1 changement
- ❌ Mauvaise UX

## Solution Implémentée

### Module `pige/interfaces/gui/tree_diff.py`

#### 1. Data Structures

**`TreeNode[T]`** - Représente un nœud:
```python
@dataclass
class TreeNode(Generic[T]):
    id: str
    parent_id: str | None
    values: tuple[Any, ...]  # Values displayed in columns
    data: T  # Original data object
    tags: tuple[str, ...] = ()
    open: bool = False  # Expand/collapse state
```

**`TreeDiff`** - Représente les changements:
```python
@dataclass
class TreeDiff:
    added: list[TreeNode]  # New nodes
    removed: list[str]  # IDs to remove
    modified: list[tuple[str, tuple]]  # (id, new_values)
    reordered: list[tuple[str, int]]  # (id, new_index)
    expand_changed: list[tuple[str, bool]]  # (id, new_open)
```

#### 2. Core Functions

**`compute_tree_diff(old, new) -> TreeDiff`**
- Compare deux états tree
- Détecte: ajouts, suppressions, modifications, réordres
- Complexité: O(n)

**`tree_from_items(items, getters...) -> dict[str, TreeNode]`**
- Helper pour construire nodes depuis data items
- Prend fonctions d'extraction (id, parent, values, tags, open)

#### 3. Helper Class: `IncrementalTreeView`

**API:**
```python
tree_view = IncrementalTreeView(tkinter_treeview)

# Capture état initial
tree_view.snapshot_state()

# Plus tard, après modifications data
tree_view.apply_diff(
    new_nodes,
    preserve_selection=True,
    preserve_scroll=True
)
```

**Fonctionnement `apply_diff()`:**
1. Compute diff vs snapshot
2. Save selection & scroll
3. Remove nodes (bottom-up)
4. Modify existing (update values in-place)
5. Add new nodes (parents first)
6. Update expand/collapse states
7. Restore selection & scroll

**Avantages:**
- ✅ Pas de clignotement (update in-place)
- ✅ Préserve sélection
- ✅ Préserve scroll position
- ✅ Performance O(changes) au lieu de O(n)

## Tests

### `tests/test_tree_diff.py` - 10 tests

1. `test_compute_diff_no_changes` - Arbres identiques
2. `test_compute_diff_added_nodes` - Nodes ajoutés
3. `test_compute_diff_removed_nodes` - Nodes supprimés
4. `test_compute_diff_modified_values` - Values modifiées
5. `test_compute_diff_expand_state_changed` - Expand/collapse
6. `test_compute_diff_mixed_changes` - Multiples types
7. `test_tree_from_items` - Construction depuis items
8. `test_tree_from_items_with_tags` - Avec tags
9. `test_compute_diff_reorder_detection` - Détection réordre
10. `test_diff_with_hierarchy` - Hiérarchie parent-enfant

**Résultat: 10/10 passent ✅**

## Usage Futur

### Dans GUI Legacy

Remplacer:
```python
def refresh_projects(self):
    self.project_tree.delete(*self.project_tree.get_children())  # ❌
    # ... rebuild all
```

Par:
```python
def refresh_projects(self):
    projects = self.service.list_projects(...)
    
    new_nodes = tree_from_items(
        projects,
        id_getter=lambda p: p.id,
        parent_getter=lambda p: p.parent_id,
        values_getter=self._format_project_values,
        tags_getter=lambda p: ("even",) if depth % 2 == 0 else ("odd",),
        open_getter=lambda p: p.id in self.expanded_projects
    )
    
    self._incremental_tree.apply_diff(new_nodes)  # ✅
```

### Dans GUI Modulaire

Le `ProjectsPanel` peut utiliser `IncrementalTreeView` directement:
```python
class ProjectsPanel(ttk.Frame):
    def __init__(self, parent, service):
        super().__init__(parent)
        self.tree = ttk.Treeview(...)
        self._incremental = IncrementalTreeView(self.tree)
        self._incremental.snapshot_state()
    
    def refresh(self):
        # Build new state
        new_nodes = tree_from_items(...)
        # Apply diff
        self._incremental.apply_diff(new_nodes)
```

## Benchmarks (Théoriques)

### Scénario: 1000 projets, 1 modifié

**Avant (rebuild complet):**
- Delete 1000 nodes: ~50ms
- Insert 1000 nodes: ~100ms
- **Total: ~150ms + clignotement**

**Après (diff incrémental):**
- Compute diff: ~5ms (O(n) scan)
- Apply 1 modification: ~0.1ms (update values)
- **Total: ~5ms, pas de clignotement**

**Gain: 30x plus rapide!**

### Scénario: 10 000 entrées, 10 modifiées

**Avant:** ~1500ms + clignotement  
**Après:** ~50ms, pas de clignotement  
**Gain: 30x**

## Limitations Actuelles

1. **Réordonnancement non implémenté**
   - Détecté mais pas appliqué (nécessite delete+reinsert en Tkinter)
   - Peut être ajouté si besoin (avec stratégie pour éviter clignotement)

2. **Non intégré dans GUI**
   - Infrastructure prête
   - Intégration dans `gui_legacy.py` ou panels modulaires à faire

3. **Pas de tests performance réels**
   - Tests unitaires logique uniquement
   - Benchmarks sur vrais data à faire

## Prochaines Étapes

### Option A: Intégrer dans GUI Legacy
1. Modifier `refresh_projects()` pour utiliser diff
2. Modifier `refresh_entries()` pour utiliser diff
3. Modifier `refresh_tasks()` pour utiliser diff
4. Benchmarker avec 10K+ entrées

### Option B: Utiliser dans GUI Modulaire
1. `ProjectsPanel` utilise `IncrementalTreeView`
2. Créer `EntriesPanel` avec diff dès le début
3. Créer `TasksPanel` avec diff dès le début

### Option C: Continuer Phase 3.4 (Pagination)
- Laisser infrastructure diff prête
- Implémenter pagination d'abord
- Combiner diff + pagination après

## Conclusion

✅ **Phase 3.3 complétée!**

- Infrastructure diff complète et testée
- API simple et élégante
- Gains performance majeurs anticipés
- Prêt pour intégration
- 164 tests passants (dont 10 nouveaux)

**Prochaine étape:** Phase 3.4 Pagination ou intégration diff dans GUI existant.
