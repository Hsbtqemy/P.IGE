"""Edit Entry dialog - load entry, edit meta and body, save."""

from __future__ import annotations

import tkinter as tk
from tkinter import messagebox, ttk

from pige.core.models import EntryMeta
from pige.core.service import PigeService
from pige.utils import strings

from pige.interfaces import gui_constants
from pige.interfaces.gui_helpers import (
    format_date_ui,
    join_people_storage,
    parse_date_ui,
    split_people,
)
from pige.interfaces.gui_constants import (
    DISPLAY_ENTRY_TYPES,
    TYPE_INTERNAL_TO_DISPLAY,
)

TYPE_DISPLAY_TO_INTERNAL = gui_constants.TYPE_DISPLAY_TO_INTERNAL


def _internal_entry_type(display_value: str) -> str:
    return TYPE_DISPLAY_TO_INTERNAL.get(display_value, display_value)


def _get_people_from_text(widget: tk.Text) -> str | None:
    raw = widget.get("1.0", "end-1c")
    people = split_people(raw)
    value = join_people_storage(people)
    return value or None


def _collect_known_tags(service: PigeService) -> list[str]:
    tags: set[str] = set()
    for project in service.storage.read_projects():
        for tag in project.tags:
            cleaned = tag.strip()
            if cleaned:
                tags.add(cleaned)
    for entry in service.storage.read_entries_meta():
        for tag in entry.tags:
            cleaned = tag.strip()
            if cleaned:
                tags.add(cleaned)
    return sorted(tags)


def _add_tags_from_list(listbox: tk.Listbox, tags_var: tk.StringVar) -> None:
    selections = listbox.curselection()
    if not selections:
        return
    existing = strings.parse_tags(tags_var.get())
    existing_set = set(existing)
    for index in selections:
        tag = listbox.get(index)
        if tag not in existing_set:
            existing.append(tag)
            existing_set.add(tag)
    tags_var.set(", ".join(existing))


def show_edit_entry_dialog(
    parent: tk.Widget,
    service: PigeService,
    entry_id: str,
) -> EntryMeta | None:
    """Show modal Edit Entry dialog. Returns updated entry or None if cancelled.

    Args:
        parent: Parent window
        service: PigeService instance
        entry_id: Entry ID to edit
    """
    entry = service.storage.get_entry(entry_id)
    if not entry:
        messagebox.showerror("Erreur", f"Entry {entry_id[:8]} introuvable.")
        return None

    body = service.storage.read_entry_body(entry)
    date_str = format_date_ui(entry.entry_date) if entry.entry_date else ""

    dialog = tk.Toplevel(parent)
    dialog.title("Edit Entry")
    dialog.grab_set()
    dialog.transient(parent.winfo_toplevel() if hasattr(parent, "winfo_toplevel") else parent)
    dialog.resizable(True, True)
    dialog.columnconfigure(1, weight=1)
    dialog.rowconfigure(7, weight=1)
    dialog.rowconfigure(11, weight=1)

    ttk.Label(dialog, text="Date (DD/MM/YYYY)").grid(
        row=0, column=0, sticky=tk.W, padx=6, pady=6
    )
    date_var = tk.StringVar(value=date_str)
    ttk.Entry(dialog, textvariable=date_var, width=18).grid(
        row=0, column=1, padx=6, pady=6, sticky=tk.W
    )

    ttk.Label(dialog, text="Type").grid(row=1, column=0, sticky=tk.W, padx=6, pady=6)
    type_var = tk.StringVar(value=TYPE_INTERNAL_TO_DISPLAY.get(entry.type, entry.type))
    type_box = ttk.Combobox(
        dialog,
        textvariable=type_var,
        values=list(DISPLAY_ENTRY_TYPES),
        width=14,
        state="readonly",
    )
    type_box.grid(row=1, column=1, padx=6, pady=6, sticky=tk.W)

    ttk.Label(dialog, text="Title").grid(row=2, column=0, sticky=tk.W, padx=6, pady=6)
    title_var = tk.StringVar(value=entry.title or "")
    ttk.Entry(dialog, textvariable=title_var, width=40).grid(
        row=2, column=1, padx=6, pady=6, sticky="ew"
    )

    ttk.Label(dialog, text="People (one per line)").grid(
        row=3, column=0, sticky=tk.NW, padx=6, pady=6
    )
    person_text = tk.Text(dialog, height=3, wrap="word")
    person_text.grid(row=3, column=1, padx=6, pady=6, sticky="ew")
    if entry.person:
        person_text.insert("1.0", entry.person)

    ttk.Label(dialog, text="Group").grid(row=4, column=0, sticky=tk.W, padx=6, pady=6)
    group_var = tk.StringVar(value=entry.group or "")
    ttk.Entry(dialog, textvariable=group_var, width=40).grid(
        row=4, column=1, padx=6, pady=6, sticky="ew"
    )

    ttk.Label(dialog, text="Tags").grid(row=5, column=0, sticky=tk.W, padx=6, pady=6)
    tags_var = tk.StringVar(value=", ".join(entry.tags) if entry.tags else "")
    ttk.Entry(dialog, textvariable=tags_var, width=40).grid(
        row=5, column=1, padx=6, pady=6, sticky="ew"
    )

    ttk.Label(dialog, text="Priorité (1=haute, 5=basse)").grid(row=6, column=0, sticky=tk.W, padx=6, pady=6)
    entry_priority = getattr(entry, "priority", 3)
    if not isinstance(entry_priority, int) or not (1 <= entry_priority <= 5):
        entry_priority = 3
    priority_var = tk.IntVar(value=entry_priority)
    priority_spin = ttk.Spinbox(dialog, from_=1, to=5, width=5, textvariable=priority_var)
    priority_spin.grid(row=6, column=1, padx=6, pady=6, sticky=tk.W)

    ttk.Label(dialog, text="Known tags").grid(row=7, column=0, sticky=tk.NW, padx=6, pady=6)
    tag_frame = ttk.Frame(dialog)
    tag_frame.grid(row=7, column=1, padx=6, pady=6, sticky="nsew")
    tag_frame.columnconfigure(0, weight=1)
    tag_frame.rowconfigure(0, weight=1)
    tag_list = tk.Listbox(tag_frame, selectmode=tk.MULTIPLE, height=5)
    tag_scroll = ttk.Scrollbar(tag_frame, orient=tk.VERTICAL, command=tag_list.yview)
    tag_list.configure(yscrollcommand=tag_scroll.set)
    for tag in _collect_known_tags(service):
        tag_list.insert(tk.END, tag)
    tag_list.grid(row=0, column=0, padx=4, pady=4, sticky="nsew")
    tag_scroll.grid(row=0, column=1, sticky="ns", padx=(0, 4), pady=4)
    ttk.Button(
        tag_frame,
        text="Add selected",
        command=lambda: _add_tags_from_list(tag_list, tags_var),
    ).grid(row=1, column=0, columnspan=2, padx=4, pady=4, sticky=tk.W)

    start_label = ttk.Label(dialog, text="Start (HH:MM)")
    start_label.grid(row=8, column=0, sticky=tk.W, padx=6, pady=6)
    start_var = tk.StringVar(value=entry.start_time or "")
    start_entry = ttk.Entry(dialog, textvariable=start_var, width=12)
    start_entry.grid(row=8, column=1, padx=6, pady=6, sticky=tk.W)
    if entry.type != "meeting":
        start_label.grid_remove()
        start_entry.grid_remove()

    end_label = ttk.Label(dialog, text="End (HH:MM)")
    end_label.grid(row=9, column=0, sticky=tk.W, padx=6, pady=6)
    end_var = tk.StringVar(value=entry.end_time or "")
    end_entry = ttk.Entry(dialog, textvariable=end_var, width=12)
    end_entry.grid(row=9, column=1, padx=6, pady=6, sticky=tk.W)
    if entry.type != "meeting":
        end_label.grid_remove()
        end_entry.grid_remove()

    decision_label = ttk.Label(dialog, text="Applied/Done")
    decision_label.grid(row=10, column=0, sticky=tk.W, padx=6, pady=6)
    decision_var = tk.BooleanVar(value=bool(entry.decision_done))
    decision_check = ttk.Checkbutton(dialog, variable=decision_var)
    decision_check.grid(row=10, column=1, padx=6, pady=6, sticky=tk.W)
    if entry.type != "decision":
        decision_label.grid_remove()
        decision_check.grid_remove()

    ttk.Label(dialog, text="Body").grid(row=11, column=0, sticky=tk.NW, padx=6, pady=6)
    body_frame = ttk.Frame(dialog)
    body_frame.grid(row=11, column=1, padx=6, pady=6, sticky="nsew")
    body_frame.columnconfigure(0, weight=1)
    body_frame.rowconfigure(0, weight=1)
    body_text = tk.Text(body_frame, width=50, height=8, wrap="word")
    body_scroll = ttk.Scrollbar(body_frame, orient=tk.VERTICAL, command=body_text.yview)
    body_text.configure(yscrollcommand=body_scroll.set)
    body_text.grid(row=0, column=0, sticky="nsew")
    body_scroll.grid(row=0, column=1, sticky="ns")
    body_text.insert("1.0", body)

    result: EntryMeta | None = None

    def submit() -> None:
        nonlocal result
        title = title_var.get().strip()
        if not title:
            messagebox.showerror("Validation", "Entry title is required")
            return
        date_text = date_var.get().strip()
        parsed_date = None
        if date_text:
            try:
                parsed_date = parse_date_ui(date_text)
            except ValueError:
                messagebox.showerror(
                    "Validation",
                    f"Invalid date {date_text}. Expected DD/MM/YYYY (or YYYY-MM-DD)",
                )
                return
        tags = strings.parse_tags(tags_var.get())
        new_body = body_text.get("1.0", "end-1c")
        try:
            prio = priority_var.get()
        except tk.TclError:
            prio = 3
        if not (1 <= prio <= 5):
            prio = 3
        try:
            service.update_entry_meta(
                entry_id,
                title=title,
                tags=tags,
                entry_date=parsed_date,
                person=_get_people_from_text(person_text),
                group=group_var.get().strip() or None,
                start_time=(start_var.get().strip() or None) if entry.type == "meeting" else None,
                end_time=(end_var.get().strip() or None) if entry.type == "meeting" else None,
                decision_done=decision_var.get() if entry.type == "decision" else None,
                priority=prio,
            )
            if new_body != body:
                service.update_entry_content(entry_id, new_body)
        except ValueError as exc:
            messagebox.showerror("Error", str(exc))
            return
        updated = service.storage.get_entry(entry_id)
        result = updated
        dialog.destroy()

    ttk.Button(dialog, text="Save", command=submit).grid(
        row=12, column=0, columnspan=2, pady=10
    )

    dialog.wait_window()
    return result
