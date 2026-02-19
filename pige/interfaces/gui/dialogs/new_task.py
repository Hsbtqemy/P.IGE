"""New Task dialog - extracted from legacy GUI."""

from __future__ import annotations

from datetime import date
import tkinter as tk
from tkinter import messagebox, ttk

from pige.core.models import Task
from pige.core.service import PigeService
from pige.utils import strings

from pige.interfaces.gui_helpers import format_date_ui, parse_date_ui


def show_new_task_dialog(
    parent: tk.Widget,
    service: PigeService,
    project_id: str,
    *,
    initial_title: str = "",
    initial_tags: list[str] | None = None,
    initial_due_date: date | str | None = None,
    linked_entry_id: str | None = None,
    show_link_entry_check: bool = False,
) -> Task | None:
    """Show modal New Task dialog. Returns created task or None if cancelled.

    Args:
        parent: Parent window
        service: PigeService instance
        project_id: Project ID (required)
        initial_title: Optional initial title (e.g. "Follow-up: ...")
        initial_tags: Optional initial tags
        initial_due_date: Optional initial due date
        linked_entry_id: If set and show_link_entry_check, pre-check "Link to entry"
        show_link_entry_check: Whether to show "Link to current entry" checkbox
    """
    service._ensure_project_exists(project_id)

    due_str = ""
    if initial_due_date is not None:
        if isinstance(initial_due_date, date):
            due_str = format_date_ui(initial_due_date)
        else:
            due_str = str(initial_due_date)
    tags_str = ", ".join(initial_tags) if initial_tags else ""

    dialog = tk.Toplevel(parent)
    dialog.title("Add Task")
    dialog.grab_set()
    dialog.transient(parent.winfo_toplevel() if hasattr(parent, "winfo_toplevel") else parent)
    dialog.resizable(True, True)
    dialog.columnconfigure(1, weight=1)
    dialog.rowconfigure(4, weight=1)

    ttk.Label(dialog, text="Title").grid(row=0, column=0, sticky=tk.W, padx=6, pady=6)
    title_var = tk.StringVar(value=initial_title)
    ttk.Entry(dialog, textvariable=title_var).grid(
        row=0, column=1, sticky="ew", padx=6, pady=6
    )

    ttk.Label(dialog, text="Tags").grid(row=1, column=0, sticky=tk.W, padx=6, pady=6)
    tags_var = tk.StringVar(value=tags_str)
    ttk.Entry(dialog, textvariable=tags_var).grid(
        row=1, column=1, sticky="ew", padx=6, pady=6
    )

    ttk.Label(dialog, text="Due (DD/MM/YYYY)").grid(row=2, column=0, sticky=tk.W, padx=6, pady=6)
    due_var = tk.StringVar(value=due_str)
    ttk.Entry(dialog, textvariable=due_var).grid(
        row=2, column=1, sticky="ew", padx=6, pady=6
    )

    link_var = tk.BooleanVar(value=bool(linked_entry_id))
    if show_link_entry_check:
        ttk.Checkbutton(
            dialog, text="Link to current entry", variable=link_var
        ).grid(row=3, column=0, columnspan=2, sticky=tk.W, padx=6, pady=6)

    ttk.Label(dialog, text="Note").grid(row=4, column=0, sticky=tk.NW, padx=6, pady=6)
    note_frame = ttk.Frame(dialog)
    note_frame.grid(row=4, column=1, sticky="nsew", padx=6, pady=6)
    note_frame.columnconfigure(0, weight=1)
    note_frame.rowconfigure(0, weight=1)
    note_text = tk.Text(note_frame, height=4, wrap="word")
    note_scroll = ttk.Scrollbar(note_frame, orient=tk.VERTICAL, command=note_text.yview)
    note_text.configure(yscrollcommand=note_scroll.set)
    note_text.grid(row=0, column=0, sticky="nsew")
    note_scroll.grid(row=0, column=1, sticky="ns")

    result: Task | None = None

    def submit() -> None:
        nonlocal result
        title = title_var.get().strip()
        if not title:
            messagebox.showerror("Validation", "Task title is required")
            return
        tags = strings.parse_tags(tags_var.get())
        note = note_text.get("1.0", "end-1c").strip() or None
        due_text = due_var.get().strip()
        due_date = None
        if due_text:
            try:
                due_date = parse_date_ui(due_text).isoformat()
            except ValueError:
                messagebox.showerror(
                    "Validation",
                    "Due date must be DD/MM/YYYY (or YYYY-MM-DD)",
                )
                return
        effective_linked = linked_entry_id if (show_link_entry_check and link_var.get()) else None
        try:
            task = service.create_task(
                project_id,
                title,
                tags,
                note,
                effective_linked,
                due_date,
            )
        except ValueError as exc:
            messagebox.showerror("Error", str(exc))
            return
        result = task
        dialog.destroy()

    ttk.Button(dialog, text="Create", command=submit).grid(
        row=5, column=0, columnspan=2, pady=10
    )

    dialog.wait_window()
    return result
