"""New Project dialog - extracted from legacy GUI."""

from __future__ import annotations

import tkinter as tk
from tkinter import messagebox, ttk
from typing import Callable

from pige.core.models import Project
from pige.core.service import PigeService
from pige.utils import strings

from pige.interfaces.gui_helpers import join_people_storage, split_people


def _get_people_from_text(widget: tk.Text) -> str | None:
    raw = widget.get("1.0", "end-1c")
    people = split_people(raw)
    value = join_people_storage(people)
    return value or None


def show_new_project_dialog(
    parent: tk.Widget,
    service: PigeService,
    on_created: Callable[[Project], None] | None = None,
) -> Project | None:
    """Show modal New Project dialog. Returns created project or None if cancelled.

    Args:
        parent: Parent window
        service: PigeService instance
        on_created: Optional callback called with the new project after creation
    """
    dialog = tk.Toplevel(parent)
    dialog.title("New Project")
    dialog.grab_set()
    dialog.transient(parent.winfo_toplevel() if hasattr(parent, "winfo_toplevel") else parent)
    dialog.resizable(True, True)

    dialog.columnconfigure(0, weight=0)
    dialog.columnconfigure(1, weight=1)

    ttk.Label(dialog, text="Name").grid(row=0, column=0, sticky="w", padx=6, pady=6)
    name_var = tk.StringVar()
    ttk.Entry(dialog, textvariable=name_var, width=40).grid(
        row=0, column=1, padx=6, pady=6, sticky="ew"
    )

    ttk.Label(dialog, text="Desc").grid(row=1, column=0, sticky="w", padx=6, pady=6)
    desc_var = tk.StringVar()
    ttk.Entry(dialog, textvariable=desc_var, width=40).grid(
        row=1, column=1, padx=6, pady=6, sticky="ew"
    )

    ttk.Label(dialog, text="Tags").grid(row=2, column=0, sticky="w", padx=6, pady=6)
    tags_var = tk.StringVar()
    ttk.Entry(dialog, textvariable=tags_var, width=40).grid(
        row=2, column=1, padx=6, pady=6, sticky="ew"
    )

    ttk.Label(dialog, text="People (one per line)").grid(
        row=3, column=0, sticky="nw", padx=6, pady=6
    )
    person_text = tk.Text(dialog, height=3, wrap="word")
    person_text.grid(row=3, column=1, padx=6, pady=6, sticky="ew")

    ttk.Label(dialog, text="Group").grid(row=4, column=0, sticky="w", padx=6, pady=6)
    group_var = tk.StringVar()
    ttk.Entry(dialog, textvariable=group_var, width=40).grid(
        row=4, column=1, padx=6, pady=6, sticky="ew"
    )

    result: Project | None = None

    def submit() -> None:
        nonlocal result
        name = name_var.get().strip()
        if not name:
            messagebox.showerror("Validation", "Project name is required")
            return
        tags = strings.parse_tags(tags_var.get())
        try:
            project = service.create_project(
                name,
                desc_var.get().strip() or None,
                tags,
                _get_people_from_text(person_text),
                group_var.get().strip() or None,
            )
        except ValueError as exc:
            messagebox.showerror("Error", str(exc))
            return
        result = project
        dialog.destroy()
        if on_created:
            on_created(project)

    ttk.Button(dialog, text="Create", command=submit).grid(
        row=5, column=0, columnspan=2, pady=10
    )

    dialog.wait_window()
    return result
