# PIGE GUI Architecture

Modular Tkinter GUI for PIGE, launched with `python -m pige gui`
(`pige/interfaces/gui/__init__.py` exports `PigeMainWindow` and `main`).

> The Tkinter GUI is in maintenance mode: it is planned to be retired once the
> web interface is ready (see `BACKLOG.md`, étape 9).

## Structure

```
pige/interfaces/gui/
├── __init__.py              # Exports PigeMainWindow, main
├── main_window.py           # Main window orchestrator
├── pagination.py            # PaginationControl (see PAGINATION.md)
├── tree_diff.py             # Incremental tree updates (see INCREMENTAL_TREE_UPDATE.md)
├── dialogs/
│   ├── about.py, keyboard_shortcuts.py, check_updates.py
│   ├── new_project.py, new_entry.py, new_task.py
│   ├── edit_entry.py, edit_task.py
│   ├── export_dialogs.py    # Project raw/narrative, meeting minutes, weekly, hierarchy
│   ├── followup_tasks.py    # Tasks from ACTION/TODO lines of an entry
│   └── calendar_subscriptions.py
├── panels/
│   ├── dashboard_panel.py, projects_panel.py, entries_panel.py
│   ├── work_panel.py, browse_panel.py, calendar_panel.py, search_panel.py
└── widgets/
    └── autocomplete.py      # AutocompleteEntry
```

The legacy monolith `pige/interfaces/gui_legacy.py` (`PigeApp`) is still importable
but no longer launched by default.

## Remaining work

- Project double-click in `projects_panel.py` does nothing yet (TODO).
- No unit tests for panels/dialogs.
- Panels and dialogs still access `service.storage` directly; to be removed
  (`BACKLOG.md`, étape 3).
- Remove `gui_legacy.py`.

## Design principles

1. Each panel/dialog is self-contained (`ttk.Frame` subclasses for panels).
2. `PigeService` is injected into components.
3. Panels communicate via callbacks, not direct coupling.
4. Dialogs are functions when possible (take parent, return result).
