"""Dialog windows for PIGE GUI."""

from __future__ import annotations

from pige.interfaces.gui.dialogs.about import show_about_dialog
from pige.interfaces.gui.dialogs.keyboard_shortcuts import show_keyboard_shortcuts
from pige.interfaces.gui.dialogs.edit_entry import show_edit_entry_dialog
from pige.interfaces.gui.dialogs.edit_task import show_edit_task_dialog
from pige.interfaces.gui.dialogs.new_entry import show_new_entry_dialog
from pige.interfaces.gui.dialogs.new_project import show_new_project_dialog
from pige.interfaces.gui.dialogs.new_task import show_new_task_dialog

__all__ = [
    "show_about_dialog",
    "show_edit_entry_dialog",
    "show_edit_task_dialog",
    "show_keyboard_shortcuts",
    "show_new_entry_dialog",
    "show_new_project_dialog",
    "show_new_task_dialog",
]

