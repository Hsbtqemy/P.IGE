"""Dialog to create follow-up tasks from ACTION/TODO lines in an entry."""

from __future__ import annotations

import tkinter as tk
from tkinter import messagebox, ttk
from typing import TYPE_CHECKING, Callable

if TYPE_CHECKING:
    from pige.core.service import PigeService


def show_followup_tasks_dialog(
    parent: tk.Widget,
    service: "PigeService",
    entry_id: str,
    on_created: Callable[[int], None] | None = None,
) -> None:
    """
    Show dialog to select extracted ACTION/TODO lines and create tasks.
    on_created(created_count) is called after tasks are created (for refresh).
    """
    try:
        titles = service.extract_followup_tasks(entry_id)
    except ValueError as e:
        messagebox.showerror("Erreur", str(e), parent=parent)
        return
    if not titles:
        messagebox.showinfo(
            "Tâches de suivi",
            "Aucune ligne ACTION: ou TODO: ou case à cocher vide trouvée dans cette entrée.",
            parent=parent,
        )
        return

    dialog = tk.Toplevel(parent)
    dialog.title("Créer des tâches de suivi")
    dialog.transient(parent)
    dialog.grab_set()
    dialog.geometry("500x350")

    main = ttk.Frame(dialog, padding=10)
    main.pack(fill=tk.BOTH, expand=True)

    ttk.Label(main, text="Cochez les lignes à transformer en tâches :").pack(anchor=tk.W)
    list_frame = ttk.Frame(main)
    list_frame.pack(fill=tk.BOTH, expand=True, pady=5)
    scroll = ttk.Scrollbar(list_frame)
    scroll.pack(side=tk.RIGHT, fill=tk.Y)
    lb = tk.Listbox(
        list_frame,
        selectmode=tk.EXTENDED,
        height=12,
        font=("TkDefaultFont", 10),
        yscrollcommand=scroll.set,
    )
    lb.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
    scroll.config(command=lb.yview)
    for t in titles:
        lb.insert(tk.END, t)
    # Select all by default
    lb.selection_set(0, tk.END)

    def submit() -> None:
        sel = lb.curselection()
        if not sel:
            messagebox.showwarning("Attention", "Sélectionnez au moins une ligne.", parent=dialog)
            return
        selected = [titles[i] for i in sel]
        try:
            created = service.create_followup_tasks(entry_id, selected)
            dialog.destroy()
            messagebox.showinfo("Succès", f"{len(created)} tâche(s) créée(s).", parent=parent)
            if on_created:
                on_created(len(created))
        except Exception as e:
            messagebox.showerror("Erreur", f"Impossible de créer les tâches :\n{e}", parent=dialog)

    btn_frame = ttk.Frame(main)
    btn_frame.pack(fill=tk.X, pady=10)
    ttk.Button(btn_frame, text="Créer les tâches", command=submit).pack(side=tk.LEFT, padx=5)
    ttk.Button(btn_frame, text="Annuler", command=dialog.destroy).pack(side=tk.LEFT)
    dialog.wait_window()
