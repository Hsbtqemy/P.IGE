"""Edit Task dialog - load task, edit fields, save."""

from __future__ import annotations

import tkinter as tk
from tkinter import messagebox, ttk

from pige.core.models import Task
from pige.core.service import PigeService
from pige.utils import strings

from pige.interfaces.gui_helpers import format_date_ui, parse_date_ui


def _get_task(service: PigeService, task_id: str) -> Task | None:
    for task in service.storage.read_tasks():
        if task.id == task_id:
            return task
    return None


def show_edit_task_dialog(
    parent: tk.Widget,
    service: PigeService,
    task_id: str,
) -> Task | None:
    """Show modal Edit Task dialog. Returns updated task or None if cancelled."""
    task = _get_task(service, task_id)
    if not task:
        messagebox.showerror("Erreur", f"Task {task_id[:8]} introuvable.")
        return None

    dialog = tk.Toplevel(parent)
    dialog.title("Edit Task")
    dialog.grab_set()
    dialog.transient(parent.winfo_toplevel() if hasattr(parent, "winfo_toplevel") else parent)
    dialog.resizable(True, True)
    dialog.columnconfigure(1, weight=1)
    dialog.rowconfigure(4, weight=1)

    ttk.Label(dialog, text="Title").grid(row=0, column=0, sticky=tk.W, padx=6, pady=6)
    title_var = tk.StringVar(value=task.title)
    ttk.Entry(dialog, textvariable=title_var).grid(row=0, column=1, sticky="ew", padx=6, pady=6)

    ttk.Label(dialog, text="Tags").grid(row=1, column=0, sticky=tk.W, padx=6, pady=6)
    tags_var = tk.StringVar(value=", ".join(task.tags))
    ttk.Entry(dialog, textvariable=tags_var).grid(row=1, column=1, sticky="ew", padx=6, pady=6)

    ttk.Label(dialog, text="Due (DD/MM/YYYY)").grid(row=2, column=0, sticky=tk.W, padx=6, pady=6)
    due_var = tk.StringVar(value=format_date_ui(task.due_date))
    ttk.Entry(dialog, textvariable=due_var).grid(row=2, column=1, sticky="ew", padx=6, pady=6)

    ttk.Label(dialog, text="Status").grid(row=3, column=0, sticky=tk.W, padx=6, pady=6)
    status_var = tk.StringVar(value=task.status)
    status_combo = ttk.Combobox(
        dialog,
        textvariable=status_var,
        values=["open", "in_progress", "done"],
        width=14,
        state="readonly",
    )
    status_combo.grid(row=3, column=1, padx=6, pady=6, sticky=tk.W)

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
    if task.note:
        note_text.insert("1.0", task.note)

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
        try:
            updated = service.update_task(
                task_id,
                {"title": title, "tags": tags, "note": note, "due_date": due_date, "status": status_var.get()},
            )
        except ValueError as exc:
            messagebox.showerror("Error", str(exc))
            return
        result = updated
        dialog.destroy()

    ttk.Button(dialog, text="Save", command=submit).grid(row=5, column=0, columnspan=2, pady=10)

    dialog.wait_window()
    return result
