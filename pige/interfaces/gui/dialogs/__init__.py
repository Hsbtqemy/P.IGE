"""Dialog windows for PIGE GUI."""

from __future__ import annotations

from pige.interfaces.gui.dialogs.about import show_about_dialog
from pige.interfaces.gui.dialogs.check_updates import show_check_updates_dialog
from pige.interfaces.gui.dialogs.keyboard_shortcuts import show_keyboard_shortcuts
from pige.interfaces.gui.dialogs.edit_entry import show_edit_entry_dialog
from pige.interfaces.gui.dialogs.edit_task import show_edit_task_dialog
from pige.interfaces.gui.dialogs.export_dialogs import (
    show_export_hierarchy_dialog,
    show_export_meeting_minutes_dialog,
    show_export_project_narrative_dialog,
    show_export_project_raw_dialog,
    show_export_weekly_summary_dialog,
)
from pige.interfaces.gui.dialogs.followup_tasks import show_followup_tasks_dialog
from pige.interfaces.gui.dialogs.new_entry import show_new_entry_dialog
from pige.interfaces.gui.dialogs.new_project import show_new_project_dialog
from pige.interfaces.gui.dialogs.new_task import show_new_task_dialog

__all__ = [
    "show_about_dialog",
    "show_check_updates_dialog",
    "show_edit_entry_dialog",
    "show_followup_tasks_dialog",
    "show_edit_task_dialog",
    "show_export_hierarchy_dialog",
    "show_export_meeting_minutes_dialog",
    "show_export_project_narrative_dialog",
    "show_export_project_raw_dialog",
    "show_export_weekly_summary_dialog",
    "show_keyboard_shortcuts",
    "show_new_entry_dialog",
    "show_new_project_dialog",
    "show_new_task_dialog",
]

