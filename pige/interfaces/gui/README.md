# PIGE GUI Architecture

This directory contains the modular GUI implementation for PIGE.

## Structure

```
pige/interfaces/gui/
├── __init__.py              # Package exports
├── main_window.py           # Main window orchestrator (<500 lines)
├── dialogs/                 # Dialog windows
│   ├── __init__.py
│   ├── about.py             # About dialog ✓
│   ├── keyboard_shortcuts.py # Shortcuts help ✓
│   ├── new_project.py       # TODO: New project dialog
│   ├── new_entry.py         # TODO: New entry dialog
│   ├── new_task.py          # TODO: New task dialog
│   ├── export_dialogs.py    # Export: projet brut/narratif, CR réunion, résumé hebdo, hiérarchie ✓
│   ├── followup_tasks.py    # Créer tâches de suivi depuis ACTION/TODO d'une entrée ✓
│   ├── preferences.py       # TODO: Preferences dialog
│   └── ...                  # Other dialogs
├── panels/                  # Main UI panels
│   ├── __init__.py
│   ├── projects_panel.py    # Projects TreeView ✓ (example)
│   ├── entries_panel.py     # TODO: Entries list
│   ├── tasks_panel.py       # TODO: Tasks list
│   └── details_panel.py     # TODO: Entry/Project details editor
└── widgets/                 # Reusable components
    ├── __init__.py
    ├── autocomplete.py      # Autocomplete entry widget ✓
    └── ...                  # Future widgets
```

## Migration Status

### ✓ Completed
- Created directory structure
- Moved `AutocompleteEntry` widget to `gui/widgets/`
- Created `about.py` and `keyboard_shortcuts.py` dialogs
- Created example `projects_panel.py`
- Created skeleton `main_window.py`
- **Menu Fichier** : Sauvegarder / Restaurer les données (backup ZIP)
- **Menu Outils** : Reconstruire l’index, Migrer les données, Compacter le journal
- **Panneau Work** : Temps du jour (sous le timer), Journal du jour (entrées du jour), bouton « Créer tâches de suivi »
- **Export** : dialogs projet (brut/narratif), CR réunion, résumé hebdo, hiérarchie ; menu Fichier → Exporter… + clic droit sur projet/entrée dans Work

### 🔄 In Progress
- **Legacy monolith**: `pige/interfaces/gui.py` (6122 lines) still exists
- Extraction of remaining dialogs and panels

### 📋 TODO
- Extract remaining dialogs (~30 dialogs)
- Extract remaining panels (entries, tasks, details)
- Migrate `main_window.py` to full functionality
- Update `__main__.py` to use `main_window.py`
- Remove legacy `gui.py` after complete migration
- Add unit tests for panels/dialogs

## Design Principles

1. **Separation of Concerns**: Each panel/dialog is self-contained
2. **Dependency Injection**: Services (PigeService) passed to components
3. **Event-driven**: Panels communicate via callbacks, not direct coupling
4. **Testability**: Components can be tested independently
5. **Incremental Migration**: Old `gui.py` remains functional during transition

## Usage

### Current (Legacy)
```python
from pige.interfaces.gui import PigeApp
app = PigeApp(data_dir)
app.mainloop()
```

### Target (Modular)
```python
from pige.interfaces.gui.main_window import PigeMainWindow
app = PigeMainWindow(data_dir)
app.mainloop()
```

## Notes

- The legacy `gui.py` will remain functional until full migration
- New features should be implemented in the modular structure
- Dialogs should be pure functions when possible (take parent, return result)
- Panels should be self-contained `ttk.Frame` subclasses
