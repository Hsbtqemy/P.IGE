"""New Entry dialog - extracted from legacy GUI."""

from __future__ import annotations

from datetime import date, datetime
import tkinter as tk
from tkinter import messagebox, ttk
from pathlib import Path
from pige.core.models import EntryMeta
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
    ENTRY_BODY_TEMPLATES,
    TYPE_INTERNAL_TO_DISPLAY,
)

from pige.core.service import PigeService


def _internal_entry_type(display_value: str) -> str:
    return gui_constants.TYPE_DISPLAY_TO_INTERNAL.get(display_value, display_value)


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


def show_new_entry_dialog(
    parent: tk.Widget,
    service: PigeService,
    project_id: str,
    *,
    initial_date: date | str | None = None,
    prefill_people: list[str] | None = None,
) -> tuple[EntryMeta, Path] | None:
    """Show modal New Entry dialog. Returns (entry, content_path) or None if cancelled.

    Args:
        parent: Parent window
        service: PigeService instance
        project_id: Project ID (required)
        initial_date: Optional initial date (date or ISO string)
        prefill_people: Optional list of people to prefill
    """
    project = service._get_project(project_id)
    today_label = datetime.now().astimezone().date()
    if initial_date is not None:
        if isinstance(initial_date, date):
            date_value = initial_date
        else:
            try:
                date_value = parse_date_ui(str(initial_date))
            except ValueError:
                date_value = today_label
    else:
        date_value = today_label
    date_str = format_date_ui(date_value)

    dialog = tk.Toplevel(parent)
    dialog.title("New Entry")
    dialog.grab_set()
    dialog.transient(parent.winfo_toplevel() if hasattr(parent, "winfo_toplevel") else parent)
    dialog.resizable(True, True)
    dialog.columnconfigure(1, weight=1)
    dialog.rowconfigure(6, weight=1)
    dialog.rowconfigure(10, weight=1)

    ttk.Label(dialog, text="Date (DD/MM/YYYY)").grid(
        row=0, column=0, sticky=tk.W, padx=6, pady=6
    )
    date_var = tk.StringVar(value=date_str)
    ttk.Entry(dialog, textvariable=date_var, width=18).grid(
        row=0, column=1, padx=6, pady=6, sticky=tk.W
    )

    ttk.Label(dialog, text="Type").grid(row=1, column=0, sticky=tk.W, padx=6, pady=6)
    type_var = tk.StringVar(value=TYPE_INTERNAL_TO_DISPLAY["note"])
    type_box = ttk.Combobox(
        dialog,
        textvariable=type_var,
        values=list(DISPLAY_ENTRY_TYPES),
        width=14,
    )
    type_box.state(["readonly"])
    type_box.grid(row=1, column=1, padx=6, pady=6, sticky=tk.W)

    ttk.Label(dialog, text="Title").grid(row=2, column=0, sticky=tk.W, padx=6, pady=6)
    title_var = tk.StringVar()
    ttk.Entry(dialog, textvariable=title_var, width=40).grid(
        row=2, column=1, padx=6, pady=6, sticky="ew"
    )

    ttk.Label(dialog, text="People (one per line)").grid(
        row=3, column=0, sticky=tk.NW, padx=6, pady=6
    )
    person_text = tk.Text(dialog, height=3, wrap="word")
    person_text.grid(row=3, column=1, padx=6, pady=6, sticky="ew")
    if prefill_people:
        person_text.insert("1.0", join_people_storage(prefill_people))
    elif project.person:
        person_text.insert("1.0", project.person)

    ttk.Label(dialog, text="Group").grid(row=4, column=0, sticky=tk.W, padx=6, pady=6)
    group_var = tk.StringVar(value=project.group or "")
    ttk.Entry(dialog, textvariable=group_var, width=40).grid(
        row=4, column=1, padx=6, pady=6, sticky="ew"
    )

    ttk.Label(dialog, text="Tags").grid(row=5, column=0, sticky=tk.W, padx=6, pady=6)
    tags_var = tk.StringVar()
    ttk.Entry(dialog, textvariable=tags_var, width=40).grid(
        row=5, column=1, padx=6, pady=6, sticky="ew"
    )

    ttk.Label(dialog, text="Known tags").grid(row=6, column=0, sticky=tk.NW, padx=6, pady=6)
    tag_frame = ttk.Frame(dialog)
    tag_frame.grid(row=6, column=1, padx=6, pady=6, sticky="nsew")
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
    start_label.grid(row=7, column=0, sticky=tk.W, padx=6, pady=6)
    start_var = tk.StringVar()
    start_entry = ttk.Entry(dialog, textvariable=start_var, width=12)
    start_entry.grid(row=7, column=1, padx=6, pady=6, sticky=tk.W)

    end_label = ttk.Label(dialog, text="End (HH:MM)")
    end_label.grid(row=8, column=0, sticky=tk.W, padx=6, pady=6)
    end_var = tk.StringVar()
    end_entry = ttk.Entry(dialog, textvariable=end_var, width=12)
    end_entry.grid(row=8, column=1, padx=6, pady=6, sticky=tk.W)

    decision_label = ttk.Label(dialog, text="Applied/Done")
    decision_label.grid(row=9, column=0, sticky=tk.W, padx=6, pady=6)
    decision_var = tk.BooleanVar(value=False)
    decision_check = ttk.Checkbutton(dialog, variable=decision_var)
    decision_check.grid(row=9, column=1, padx=6, pady=6, sticky=tk.W)

    ttk.Label(dialog, text="Body").grid(row=10, column=0, sticky=tk.NW, padx=6, pady=6)
    body_frame = ttk.Frame(dialog)
    body_frame.grid(row=10, column=1, padx=6, pady=6, sticky="nsew")
    body_frame.columnconfigure(0, weight=1)
    body_frame.rowconfigure(0, weight=1)
    body_text = tk.Text(body_frame, width=50, height=8, wrap="word")
    body_scroll = ttk.Scrollbar(body_frame, orient=tk.VERTICAL, command=body_text.yview)
    body_text.configure(yscrollcommand=body_scroll.set)
    body_text.grid(row=0, column=0, sticky="nsew")
    body_scroll.grid(row=0, column=1, sticky="ns")

    def render_body_template(entry_type: str) -> str:
        template = ENTRY_BODY_TEMPLATES.get(entry_type, "")
        people_inline = ", ".join(split_people(person_text.get("1.0", "end-1c")))
        values = {
            "date": date_var.get().strip(),
            "title": title_var.get().strip(),
            "project": project.name,
            "person": people_inline,
            "group": group_var.get().strip(),
            "tags": tags_var.get().strip(),
            "start": start_var.get().strip(),
            "end": end_var.get().strip(),
        }
        return template.format(**values)

    def maybe_insert_template(entry_type: str) -> None:
        current_body = body_text.get("1.0", "end-1c")
        if current_body.strip():
            return
        body_text.delete("1.0", tk.END)
        body_text.insert("1.0", render_body_template(entry_type))

    def toggle_fields(_event: object | None = None) -> None:
        entry_type = _internal_entry_type(type_var.get())
        if entry_type == "meeting":
            start_label.grid()
            start_entry.grid()
            end_label.grid()
            end_entry.grid()
        else:
            start_var.set("")
            end_var.set("")
            start_label.grid_remove()
            start_entry.grid_remove()
            end_label.grid_remove()
            end_entry.grid_remove()
        if entry_type == "decision":
            decision_label.grid()
            decision_check.grid()
        else:
            decision_var.set(False)
            decision_label.grid_remove()
            decision_check.grid_remove()
        maybe_insert_template(entry_type)

    result: tuple[EntryMeta, Path] | None = None

    def submit() -> None:
        nonlocal result
        title = title_var.get().strip()
        if not title:
            messagebox.showerror("Validation", "Entry title is required")
            return
        date_text = date_var.get().strip()
        entry_date = None
        if date_text:
            try:
                entry_date = parse_date_ui(date_text)
            except ValueError:
                messagebox.showerror(
                    "Validation",
                    f"Invalid date {date_text}. Expected DD/MM/YYYY (or YYYY-MM-DD)",
                )
                return
        tags = strings.parse_tags(tags_var.get())
        raw_body = body_text.get("1.0", "end-1c")
        entry_type = _internal_entry_type(type_var.get())
        body = raw_body if raw_body.strip() else render_body_template(entry_type)
        try:
            entry, content_path = service.add_entry(
                project_id,
                entry_type,
                title,
                tags,
                body,
                entry_date=entry_date,
                person=_get_people_from_text(person_text),
                group=group_var.get().strip() or None,
                start_time=(start_var.get().strip() or None) if entry_type == "meeting" else None,
                end_time=(end_var.get().strip() or None) if entry_type == "meeting" else None,
                decision_done=decision_var.get() if entry_type == "decision" else None,
            )
        except ValueError as exc:
            messagebox.showerror("Error", str(exc))
            return
        result = (entry, content_path)
        dialog.destroy()

    type_box.bind("<<ComboboxSelected>>", toggle_fields)
    toggle_fields()

    ttk.Button(dialog, text="Create", command=submit).grid(
        row=11, column=0, columnspan=2, pady=10
    )

    dialog.wait_window()
    return result
