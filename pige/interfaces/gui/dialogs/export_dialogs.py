"""Export dialogs: project raw/narrative, meeting minutes, weekly summary, hierarchy."""

from __future__ import annotations

import tkinter as tk
from datetime import date, timedelta
from pathlib import Path
from tkinter import ttk, messagebox, filedialog

from pige.core.service import PigeService
from pige.interfaces import gui_helpers


def _open_exported(path: Path) -> None:
    if messagebox.askyesno("Export terminé", "Ouvrir le fichier exporté ?"):
        if not gui_helpers._open_path(path):
            messagebox.showinfo("Export", str(path))


def show_export_project_raw_dialog(
    parent: tk.Widget,
    service: PigeService,
    initial_project_id: str | None = None,
) -> None:
    """Export projet (brut) : entrées + tâches en Markdown sur une période."""
    projects = service.list_projects(status="all")
    projects = [p for p in projects if "calendar-sync" not in (p.tags or [])]
    if not projects:
        messagebox.showwarning("Export", "Aucun projet disponible.")
        return
    dialog = tk.Toplevel(parent)
    dialog.title("Exporter le journal du projet (brut)")
    dialog.grab_set()
    dialog.transient(parent.winfo_toplevel())
    dialog.resizable(False, False)
    dialog.columnconfigure(1, weight=1)

    row = 0
    ttk.Label(dialog, text="Projet").grid(row=row, column=0, sticky=tk.W, padx=6, pady=6)
    project_var = tk.StringVar()
    project_ids = [p.id for p in projects]
    names = [p.name or p.id for p in projects]
    combo = ttk.Combobox(dialog, textvariable=project_var, values=names, width=35, state="readonly")
    combo.grid(row=row, column=1, sticky=tk.EW, padx=6, pady=6)
    if initial_project_id and any(p.id == initial_project_id for p in projects):
        idx = next(i for i, p in enumerate(projects) if p.id == initial_project_id)
        combo.current(idx)
    elif projects:
        combo.current(0)
    row += 1

    ttk.Label(dialog, text="Du (JJ/MM/AAAA, optionnel)").grid(row=row, column=0, sticky=tk.W, padx=6, pady=4)
    from_var = tk.StringVar(value="")
    ttk.Entry(dialog, textvariable=from_var, width=14).grid(row=row, column=1, sticky=tk.W, padx=6, pady=4)
    row += 1
    ttk.Label(dialog, text="Au (JJ/MM/AAAA, optionnel)").grid(row=row, column=0, sticky=tk.W, padx=6, pady=4)
    to_var = tk.StringVar(value="")
    ttk.Entry(dialog, textvariable=to_var, width=14).grid(row=row, column=1, sticky=tk.W, padx=6, pady=4)
    row += 1
    ttk.Label(dialog, text="Laisser vide = toute la période.").grid(row=row, column=0, columnspan=2, sticky=tk.W, padx=6, pady=2)
    row += 1

    redact_var = tk.BooleanVar(value=False)
    ttk.Checkbutton(dialog, text="Masquer le texte des entrées (titres, personnes et tags restent visibles)", variable=redact_var).grid(
        row=row, column=0, columnspan=2, sticky=tk.W, padx=6, pady=4
    )
    row += 1

    ttk.Label(dialog, text="Fichier de sortie (optionnel)").grid(row=row, column=0, sticky=tk.W, padx=6, pady=4)
    out_var = tk.StringVar(value="")
    ttk.Entry(dialog, textvariable=out_var, width=40).grid(row=row, column=1, sticky=tk.EW, padx=6, pady=4)

    def browse() -> None:
        p = filedialog.asksaveasfilename(
            parent=dialog,
            title="Enregistrer l'export",
            defaultextension=".md",
            initialdir=str(service.storage.exports_dir),
        )
        if p:
            out_var.set(p)

    ttk.Button(dialog, text="Parcourir...", command=browse).grid(row=row, column=2, padx=6, pady=4)
    row += 1

    btn_frame = ttk.Frame(dialog)
    btn_frame.grid(row=row, column=0, columnspan=3, sticky=tk.E, padx=6, pady=10)
    ttk.Button(btn_frame, text="Annuler", command=dialog.destroy).pack(side=tk.RIGHT, padx=4)

    def submit() -> None:
        name = project_var.get().strip()
        pid = project_ids[names.index(name)] if name in names else (project_ids[0] if project_ids else None)
        if not pid:
            messagebox.showerror("Export", "Choisissez un projet.")
            return
        from_date = None
        to_date = None
        if from_var.get().strip():
            try:
                from_date = gui_helpers.parse_date_ui(from_var.get())
            except ValueError as e:
                messagebox.showerror("Validation", str(e))
                return
        if to_var.get().strip():
            try:
                to_date = gui_helpers.parse_date_ui(to_var.get())
            except ValueError as e:
                messagebox.showerror("Validation", str(e))
                return
        if from_date and to_date and from_date > to_date:
            messagebox.showerror("Validation", "La date de début doit être avant la date de fin.")
            return
        out_path = Path(out_var.get().strip()) if out_var.get().strip() else None
        try:
            export_path, warnings = service.export_project_raw(pid, from_date, to_date, out_path, redact_bodies=redact_var.get())
        except Exception as e:
            messagebox.showerror("Export", str(e))
            return
        dialog.destroy()
        if warnings:
            messagebox.showwarning("Export", "\n".join(warnings))
        _open_exported(Path(export_path))

    ttk.Button(btn_frame, text="Exporter", command=submit).pack(side=tk.RIGHT)


def show_export_project_narrative_dialog(
    parent: tk.Widget,
    service: PigeService,
    initial_project_id: str | None = None,
) -> None:
    """Export projet (narratif) : résumé, décisions, chronologie, temps."""
    projects = service.list_projects(status="all")
    projects = [p for p in projects if "calendar-sync" not in (p.tags or [])]
    if not projects:
        messagebox.showwarning("Export", "Aucun projet disponible.")
        return
    dialog = tk.Toplevel(parent)
    dialog.title("Exporter le journal du projet (narratif)")
    dialog.grab_set()
    dialog.transient(parent.winfo_toplevel())
    dialog.resizable(False, False)
    dialog.columnconfigure(1, weight=1)

    row = 0
    ttk.Label(dialog, text="Projet").grid(row=row, column=0, sticky=tk.W, padx=6, pady=6)
    project_var = tk.StringVar()
    project_ids = [p.id for p in projects]
    names = [p.name or p.id for p in projects]
    combo = ttk.Combobox(dialog, textvariable=project_var, values=names, width=35, state="readonly")
    combo.grid(row=row, column=1, sticky=tk.EW, padx=6, pady=6)
    if initial_project_id and any(p.id == initial_project_id for p in projects):
        idx = next(i for i, p in enumerate(projects) if p.id == initial_project_id)
        combo.current(idx)
    elif projects:
        combo.current(0)
    row += 1

    ttk.Label(dialog, text="Du (JJ/MM/AAAA, optionnel)").grid(row=row, column=0, sticky=tk.W, padx=6, pady=4)
    from_var = tk.StringVar(value="")
    ttk.Entry(dialog, textvariable=from_var, width=14).grid(row=row, column=1, sticky=tk.W, padx=6, pady=4)
    row += 1
    ttk.Label(dialog, text="Au (JJ/MM/AAAA, optionnel)").grid(row=row, column=0, sticky=tk.W, padx=6, pady=4)
    to_var = tk.StringVar(value="")
    ttk.Entry(dialog, textvariable=to_var, width=14).grid(row=row, column=1, sticky=tk.W, padx=6, pady=4)
    row += 1
    redact_var = tk.BooleanVar(value=False)
    ttk.Checkbutton(dialog, text="Masquer le texte des entrées (titres, personnes et tags restent visibles)", variable=redact_var).grid(
        row=row, column=0, columnspan=2, sticky=tk.W, padx=6, pady=4
    )
    row += 1

    btn_frame = ttk.Frame(dialog)
    btn_frame.grid(row=row, column=0, columnspan=2, sticky=tk.E, padx=6, pady=10)
    ttk.Button(btn_frame, text="Annuler", command=dialog.destroy).pack(side=tk.RIGHT, padx=4)

    def submit() -> None:
        name = project_var.get().strip()
        pid = project_ids[names.index(name)] if name in names else (project_ids[0] if project_ids else None)
        if not pid:
            messagebox.showerror("Export", "Choisissez un projet.")
            return
        from_date = to_date = None
        if from_var.get().strip():
            try:
                from_date = gui_helpers.parse_date_ui(from_var.get())
            except ValueError as e:
                messagebox.showerror("Validation", str(e))
                return
        if to_var.get().strip():
            try:
                to_date = gui_helpers.parse_date_ui(to_var.get())
            except ValueError as e:
                messagebox.showerror("Validation", str(e))
                return
        if from_date and to_date and from_date > to_date:
            messagebox.showerror("Validation", "La date de début doit être avant la date de fin.")
            return
        try:
            export_path = service.export_project_narrative(pid, from_date, to_date, None, redact_bodies=redact_var.get())
        except Exception as e:
            messagebox.showerror("Export", str(e))
            return
        dialog.destroy()
        _open_exported(Path(export_path))

    ttk.Button(btn_frame, text="Exporter", command=submit).pack(side=tk.RIGHT)


def show_export_meeting_minutes_dialog(
    parent: tk.Widget,
    service: PigeService,
    initial_entry_id: str | None = None,
) -> None:
    """Export compte-rendu de réunion à partir d'une entrée type meeting."""
    entries = service.storage.read_entries_meta()
    meetings = [e for e in entries if e.type == "meeting"]
    if not meetings:
        messagebox.showwarning("Export", "Aucune entrée de type réunion.")
        return
    dialog = tk.Toplevel(parent)
    dialog.title("Exporter le compte-rendu de réunion")
    dialog.grab_set()
    dialog.transient(parent.winfo_toplevel())
    dialog.resizable(False, False)
    dialog.columnconfigure(1, weight=1)

    row = 0
    ttk.Label(dialog, text="Entrée réunion").grid(row=row, column=0, sticky=tk.W, padx=6, pady=6)
    meeting_labels = [f"{e.title} ({e.entry_date or 'sans date'})" for e in meetings]
    meeting_ids = [e.id for e in meetings]
    entry_var = tk.StringVar()
    combo = ttk.Combobox(dialog, textvariable=entry_var, values=meeting_labels, width=45, state="readonly")
    combo.grid(row=row, column=1, sticky=tk.EW, padx=6, pady=6)
    if initial_entry_id and initial_entry_id in meeting_ids:
        combo.current(meeting_ids.index(initial_entry_id))
    else:
        combo.current(0)
    row += 1

    include_dec_var = tk.BooleanVar(value=True)
    ttk.Checkbutton(dialog, text="Inclure les décisions", variable=include_dec_var).grid(row=row, column=0, columnspan=2, sticky=tk.W, padx=6, pady=4)
    row += 1
    include_tasks_var = tk.BooleanVar(value=True)
    ttk.Checkbutton(dialog, text="Inclure les tâches", variable=include_tasks_var).grid(row=row, column=0, columnspan=2, sticky=tk.W, padx=6, pady=4)
    row += 1
    ttk.Label(dialog, text="Fenêtre (jours)").grid(row=row, column=0, sticky=tk.W, padx=6, pady=4)
    window_var = tk.StringVar(value="1")
    ttk.Entry(dialog, textvariable=window_var, width=6).grid(row=row, column=1, sticky=tk.W, padx=6, pady=4)
    row += 1
    redact_var = tk.BooleanVar(value=False)
    ttk.Checkbutton(dialog, text="Masquer le texte des entrées (titres, personnes et tags restent visibles)", variable=redact_var).grid(row=row, column=0, columnspan=2, sticky=tk.W, padx=6, pady=4)
    row += 1
    ttk.Label(dialog, text="Fichier de sortie (optionnel)").grid(row=row, column=0, sticky=tk.W, padx=6, pady=4)
    out_var = tk.StringVar(value="")
    ttk.Entry(dialog, textvariable=out_var, width=40).grid(row=row, column=1, sticky=tk.EW, padx=6, pady=4)

    def browse() -> None:
        p = filedialog.asksaveasfilename(
            parent=dialog,
            title="Enregistrer le CR",
            defaultextension=".md",
            initialdir=str(service.storage.exports_dir),
        )
        if p:
            out_var.set(p)

    ttk.Button(dialog, text="Parcourir...", command=browse).grid(row=row, column=2, padx=6, pady=4)
    row += 1

    btn_frame = ttk.Frame(dialog)
    btn_frame.grid(row=row, column=0, columnspan=3, sticky=tk.E, padx=6, pady=10)
    ttk.Button(btn_frame, text="Annuler", command=dialog.destroy).pack(side=tk.RIGHT, padx=4)

    def submit() -> None:
        idx = combo.current()
        if idx < 0:
            messagebox.showerror("Export", "Choisissez une réunion.")
            return
        entry_id = meeting_ids[idx]
        try:
            window_days = int(window_var.get().strip() or "1")
        except ValueError:
            messagebox.showerror("Validation", "Fenêtre doit être un entier.")
            return
        if window_days < 0:
            messagebox.showerror("Validation", "Fenêtre doit être ≥ 0.")
            return
        out_path = out_var.get().strip() or None
        try:
            export_path = service.export_meeting_minutes(
                entry_id,
                out_path,
                include_decisions=include_dec_var.get(),
                include_tasks=include_tasks_var.get(),
                window_days=window_days,
                internal=False,
                redact_bodies=redact_var.get(),
            )
        except ValueError as e:
            messagebox.showerror("Export", str(e))
            return
        dialog.destroy()
        _open_exported(Path(export_path))

    ttk.Button(btn_frame, text="Exporter", command=submit).pack(side=tk.RIGHT)


def show_export_weekly_summary_dialog(
    parent: tk.Widget,
    service: PigeService,
    initial_project_id: str | None = None,
) -> None:
    """Export résumé hebdomadaire (entrées par projet, tâches, optionnel temps)."""
    projects = service.list_projects(status="all")
    projects = [p for p in projects if "calendar-sync" not in (p.tags or [])]
    dialog = tk.Toplevel(parent)
    dialog.title("Exporter le résumé hebdomadaire")
    dialog.grab_set()
    dialog.transient(parent.winfo_toplevel())
    dialog.resizable(False, False)
    dialog.columnconfigure(1, weight=1)

    today = date.today()
    default_end = today
    default_start = today - timedelta(days=6)

    row = 0
    ttk.Label(dialog, text="Du (JJ/MM/AAAA)").grid(row=row, column=0, sticky=tk.W, padx=6, pady=6)
    from_var = tk.StringVar(value=gui_helpers.format_date_ui(default_start))
    ttk.Entry(dialog, textvariable=from_var, width=14).grid(row=row, column=1, sticky=tk.W, padx=6, pady=6)
    row += 1
    ttk.Label(dialog, text="Au (JJ/MM/AAAA)").grid(row=row, column=0, sticky=tk.W, padx=6, pady=6)
    to_var = tk.StringVar(value=gui_helpers.format_date_ui(default_end))
    ttk.Entry(dialog, textvariable=to_var, width=14).grid(row=row, column=1, sticky=tk.W, padx=6, pady=6)
    row += 1
    ttk.Label(dialog, text="Projet (optionnel)").grid(row=row, column=0, sticky=tk.W, padx=6, pady=4)
    project_var = tk.StringVar(value="")
    project_ids: list[str | None] = [None]
    names = ["Tous les projets"]
    names.extend(p.name or p.id for p in projects)
    project_ids.extend(p.id for p in projects)
    combo = ttk.Combobox(dialog, textvariable=project_var, values=names, width=35, state="readonly")
    combo.grid(row=row, column=1, sticky=tk.EW, padx=6, pady=4)
    combo.current(0)
    if initial_project_id and initial_project_id in project_ids:
        combo.current(project_ids.index(initial_project_id))
    row += 1
    include_time_var = tk.BooleanVar(value=False)
    ttk.Checkbutton(dialog, text="Inclure les temps (timelogs)", variable=include_time_var).grid(
        row=row, column=0, columnspan=2, sticky=tk.W, padx=6, pady=4
    )
    row += 1
    include_tasks_var = tk.BooleanVar(value=True)
    ttk.Checkbutton(dialog, text="Inclure les tâches", variable=include_tasks_var).grid(
        row=row, column=0, columnspan=2, sticky=tk.W, padx=6, pady=4
    )
    row += 1
    include_dec_var = tk.BooleanVar(value=True)
    ttk.Checkbutton(dialog, text="Inclure les décisions", variable=include_dec_var).grid(
        row=row, column=0, columnspan=2, sticky=tk.W, padx=6, pady=4
    )
    row += 1
    ttk.Label(dialog, text="Fichier de sortie (optionnel)").grid(row=row, column=0, sticky=tk.W, padx=6, pady=4)
    out_var = tk.StringVar(value="")
    ttk.Entry(dialog, textvariable=out_var, width=40).grid(row=row, column=1, sticky=tk.EW, padx=6, pady=4)

    def browse() -> None:
        p = filedialog.asksaveasfilename(
            parent=dialog,
            title="Enregistrer le résumé",
            defaultextension=".md",
            initialdir=str(service.storage.exports_dir),
        )
        if p:
            out_var.set(p)

    ttk.Button(dialog, text="Parcourir...", command=browse).grid(row=row, column=2, padx=6, pady=4)
    row += 1

    btn_frame = ttk.Frame(dialog)
    btn_frame.grid(row=row, column=0, columnspan=3, sticky=tk.E, padx=6, pady=10)
    ttk.Button(btn_frame, text="Annuler", command=dialog.destroy).pack(side=tk.RIGHT, padx=4)

    def submit() -> None:
        try:
            start = gui_helpers.parse_date_ui(from_var.get())
            end = gui_helpers.parse_date_ui(to_var.get())
        except ValueError as e:
            messagebox.showerror("Validation", str(e))
            return
        if start > end:
            messagebox.showerror("Validation", "La date de début doit être avant la date de fin.")
            return
        idx = combo.current()
        pid = project_ids[idx] if 0 <= idx < len(project_ids) else None
        out_path = out_var.get().strip() or None
        try:
            export_path = service.export_weekly_summary(
                start,
                end,
                pid,
                out_path,
                include_time=include_time_var.get(),
                include_tasks=include_tasks_var.get(),
                include_decisions=include_dec_var.get(),
            )
        except Exception as e:
            messagebox.showerror("Export", str(e))
            return
        dialog.destroy()
        _open_exported(Path(export_path))

    ttk.Button(btn_frame, text="Exporter", command=submit).pack(side=tk.RIGHT)


def show_export_hierarchy_dialog(parent: tk.Widget, service: PigeService) -> None:
    """Export hiérarchie des projets en Markdown."""
    dialog = tk.Toplevel(parent)
    dialog.title("Exporter la hiérarchie des projets")
    dialog.grab_set()
    dialog.transient(parent.winfo_toplevel())
    dialog.resizable(False, False)
    dialog.columnconfigure(1, weight=1)

    row = 0
    include_archived_var = tk.BooleanVar(value=False)
    ttk.Checkbutton(dialog, text="Inclure les projets archivés", variable=include_archived_var).grid(
        row=row, column=0, columnspan=2, sticky=tk.W, padx=6, pady=6
    )
    row += 1
    ttk.Label(dialog, text="Fichier de sortie (optionnel)").grid(row=row, column=0, sticky=tk.W, padx=6, pady=4)
    out_var = tk.StringVar(value="")
    ttk.Entry(dialog, textvariable=out_var, width=40).grid(row=row, column=1, sticky=tk.EW, padx=6, pady=4)

    def browse() -> None:
        p = filedialog.asksaveasfilename(
            parent=dialog,
            title="Enregistrer la hiérarchie",
            defaultextension=".md",
            initialdir=str(service.storage.exports_dir),
        )
        if p:
            out_var.set(p)

    ttk.Button(dialog, text="Parcourir...", command=browse).grid(row=row, column=2, padx=6, pady=4)
    row += 1

    btn_frame = ttk.Frame(dialog)
    btn_frame.grid(row=row, column=0, columnspan=3, sticky=tk.E, padx=6, pady=10)
    ttk.Button(btn_frame, text="Annuler", command=dialog.destroy).pack(side=tk.RIGHT, padx=4)

    def submit() -> None:
        out_path = Path(out_var.get().strip()) if out_var.get().strip() else None
        try:
            export_path = service.export_project_hierarchy(out_path, include_archived=include_archived_var.get())
        except Exception as e:
            messagebox.showerror("Export", str(e))
            return
        dialog.destroy()
        _open_exported(Path(export_path))

    ttk.Button(btn_frame, text="Exporter", command=submit).pack(side=tk.RIGHT)
