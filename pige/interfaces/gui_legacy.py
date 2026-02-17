from __future__ import annotations

import json
import logging
import os
import re
import subprocess
import sys
import webbrowser
import tkinter as tk
import tkinter.font as tkfont
from datetime import date, datetime, timedelta, timezone
from dataclasses import dataclass
from pathlib import Path
from tkinter import filedialog, messagebox, simpledialog, ttk

from pige.core.models import EntryMeta, Project, Task
from pige.core.service import PigeService, normalize_context_status
from pige.core.storage import Storage
from pige.utils import dates, io as io_utils, strings

from pige.interfaces import gui_constants
from pige.interfaces import gui_helpers
from pige.interfaces.gui.widgets import AutocompleteEntry

logger = logging.getLogger(__name__)

# Re-export constants and helpers so existing code can use the same names
VALID_ENTRY_TYPES = gui_constants.VALID_ENTRY_TYPES
TYPE_INTERNAL_TO_DISPLAY = gui_constants.TYPE_INTERNAL_TO_DISPLAY
TYPE_DISPLAY_TO_INTERNAL = gui_constants.TYPE_DISPLAY_TO_INTERNAL
DISPLAY_ENTRY_TYPES = gui_constants.DISPLAY_ENTRY_TYPES
AVAILABLE_ENTRY_COLUMNS = gui_constants.AVAILABLE_ENTRY_COLUMNS
AVAILABLE_PROJECT_COLUMNS = gui_constants.AVAILABLE_PROJECT_COLUMNS
DEFAULT_PROJECT_DISPLAYCOLUMNS = gui_constants.DEFAULT_PROJECT_DISPLAYCOLUMNS
DEFAULT_ENTRY_DISPLAYCOLUMNS = gui_constants.DEFAULT_ENTRY_DISPLAYCOLUMNS
ENTRY_COLUMN_LABELS = gui_constants.ENTRY_COLUMN_LABELS
UPCOMING_RANGE_LABELS = gui_constants.UPCOMING_RANGE_LABELS
UPCOMING_RANGE_DAYS = gui_constants.UPCOMING_RANGE_DAYS
ENTRY_BODY_TEMPLATES = gui_constants.ENTRY_BODY_TEMPLATES
AUTOSAVE_DELAY_MS = gui_constants.AUTOSAVE_DELAY_MS
TOOLBAR_LAYOUT_DEBOUNCE_MS = gui_constants.TOOLBAR_LAYOUT_DEBOUNCE_MS
TOOLBAR_COMPACT_WIDTH = gui_constants.TOOLBAR_COMPACT_WIDTH
TOOLBAR_EXPAND_WIDTH = gui_constants.TOOLBAR_EXPAND_WIDTH

_menu_accel = gui_helpers._menu_accel
_display_entry_type = gui_helpers._display_entry_type
_internal_entry_type = gui_helpers._internal_entry_type
format_date_ui = gui_helpers.format_date_ui
parse_date_ui = gui_helpers.parse_date_ui
split_people = gui_helpers.split_people
join_people_storage = gui_helpers.join_people_storage
format_people_inline = gui_helpers.format_people_inline
_resolve_data_dir = gui_helpers._resolve_data_dir
_load_global_config = gui_helpers._load_global_config
_save_global_config = gui_helpers._save_global_config
_is_dir_empty = gui_helpers._is_dir_empty
_is_subpath = gui_helpers._is_subpath
_count_entry_files = gui_helpers._count_entry_files
_detect_pige_data_dir = gui_helpers._detect_pige_data_dir
_safe_write_text = gui_helpers._safe_write_text
_open_path = gui_helpers._open_path


@dataclass
class _SelectionState:
    project_id: str | None = None
    entry_id: str | None = None


class PigeApp(tk.Tk):
    def __init__(self, data_dir: Path) -> None:
        super().__init__()
        self.title("PIGE")
        self.geometry("1200x700")

        self.storage = Storage(data_dir)
        self.service = PigeService(self.storage)
        self.service.init_storage()

        self.prefs_path = self.storage.data_dir / ".pige_prefs.json"
        self.legacy_prefs_path = self.storage.data_dir / "gui_prefs.json"
        self.gui_prefs = self._load_gui_prefs()
        self.project_column_defs = {
            "name": {
                "header": "Name",
                "label": "Name",
                "width": 180,
                "stretch": True,
                "anchor": tk.W,
            },
            "people": {
                "header": "People",
                "label": "People",
                "width": 160,
                "stretch": False,
                "anchor": tk.W,
            },
            "tasks_open": {
                "header": "Tasks",
                "label": "Tasks",
                "width": 60,
                "stretch": False,
                "anchor": tk.CENTER,
            },
            "status": {
                "header": "Status",
                "label": "Status",
                "width": 40,
                "stretch": False,
                "anchor": tk.CENTER,
            },
        }
        project_display_pref = self.gui_prefs.get("project_displaycolumns")
        if project_display_pref is None:
            project_display_pref = self.gui_prefs.get("projects_columns")
        self.project_displaycolumns = self._validate_project_displaycolumns(
            project_display_pref
        )
        entry_display_pref = self.gui_prefs.get("entry_displaycolumns")
        if entry_display_pref is None:
            entry_display_pref = self.gui_prefs.get("entry_columns_order")
        self.entry_displaycolumns = self._validate_entry_displaycolumns(
            entry_display_pref
        )
        sort_col = self.gui_prefs.get("project_sort_col")
        if sort_col == "today":
            sort_col = "people"
        sort_dir = self.gui_prefs.get("project_sort_dir")
        if sort_col not in self.project_column_defs:
            sort_col = None
        if sort_dir not in ("asc", "desc"):
            sort_dir = None
        if not sort_col or not sort_dir:
            sort_col = None
            sort_dir = None
        self.project_sort_col: str | None = sort_col
        self.project_sort_dir: str | None = sort_dir

        self.projects_by_id: dict[str, Project] = {}
        self.entries_by_id: dict[str, EntryMeta] = {}
        self.tasks_by_id: dict[str, Task] = {}
        self.current_task_id: str | None = None
        self.current = _SelectionState()
        self.current_entry_path: Path | None = None
        self.dirty = False
        self._autosave_after_id: str | None = None
        self._autosave_in_progress = False
        self._save_state = "none"
        self._loading_entry = False
        self._suppress_project_select = False
        self._suppress_entry_select = False
        self.create_activity_var = tk.BooleanVar(
            value=bool(self.gui_prefs.get("create_activity_on_stop", False))
        )
        self.show_archived_var = tk.BooleanVar(
            value=bool(self.gui_prefs.get("show_archived", False))
        )
        self.show_treated_var = tk.BooleanVar(value=False)
        self.project_editing = False
        self.project_dirty = False
        self._project_detail_updating = False
        self.project_detail_snapshot: Project | None = None
        self.project_name_var = tk.StringVar(value="")
        self.project_person_var = tk.StringVar(value="")
        self.project_group_var = tk.StringVar(value="")
        self.project_tags_var = tk.StringVar(value="")
        self.project_status_var = tk.BooleanVar(value=False)
        self.project_today_var = tk.StringVar(value="-")
        self.project_entry_count_var = tk.StringVar(value="-")
        self._resize_after_id: str | None = None
        self._prefs_after_id: str | None = None
        self._poll_after_id: str | None = None
        self._toolbar_after_id: str | None = None
        self._search_after_id: str | None = None
        self._toolbar_compact: bool | None = None
        self._root_sash_initialized = False
        self._bottom_sash_initialized = False
        self._focus_active = False
        self._focus_root_sash: int | None = None
        self._focus_main_sashes: tuple[int, int] | None = None
        self.focus_var = tk.BooleanVar(value=False)
        self._closing = False
        self.details_visible_var = tk.BooleanVar(value=True)
        self.entry_search_var = tk.StringVar(
            value=str(self.gui_prefs.get("search_query", ""))
        )
        self.entry_type_filter_var = tk.StringVar(value="All")
        self.entry_person_filter_var = tk.StringVar(value="All")
        self.search_global_mode_var = tk.BooleanVar(value=False)
        self.search_include_body_var = tk.BooleanVar(value=False)
        self.entry_editing = False
        self.entry_dirty = False
        self._entry_detail_updating = False
        self.entry_detail_snapshot: EntryMeta | None = None
        self.entry_sort_col = "date"
        self.entry_sort_desc = False
        self.entry_title_var = tk.StringVar(value="")
        self.entry_type_var = tk.StringVar(value="-")
        self.entry_date_var = tk.StringVar(value="")
        self.entry_person_var = tk.StringVar(value="")
        self.entry_group_var = tk.StringVar(value="")
        self.entry_tags_var = tk.StringVar(value="")
        self.entry_start_var = tk.StringVar(value="")
        self.entry_end_var = tk.StringVar(value="")
        self.entry_decision_var = tk.BooleanVar(value=False)
        self.editor_title_var = tk.StringVar(value="No entry selected")
        self.editor_font: tkfont.Font | None = None
        self.editor_font_default_size = 11
        self.timer_elapsed_var = tk.StringVar(value="00:00:00")
        self.timer_tracking_var = tk.StringVar(value="Tracking: Idle")
        self.save_status_var = tk.StringVar(value="No entry")
        self.stats_timer_state_var = tk.StringVar(value="Idle")
        self.stats_timer_elapsed_var = tk.StringVar(value="00:00:00")
        self.stats_today_project_var = tk.StringVar(value="-")
        self.stats_today_all_var = tk.StringVar(value="-")
        self.stats_selected_project_var = tk.StringVar(value="-")
        self.stats_data_dir_var = tk.StringVar(value=str(self.storage.data_dir))
        self.task_search_var = tk.StringVar(value="")
        self.task_status_filter_var = tk.StringVar(value="All")
        self.task_current_entries_only_var = tk.BooleanVar(value=False)
        self.task_created_var = tk.StringVar(value="-")
        self.task_done_var = tk.StringVar(value="-")
        self._global_search_cache_query = ""
        self._global_search_cache_include_body = False
        self._global_search_cache_projects: list[Project] = []
        self._global_search_cache_entries: list[EntryMeta] = []
        self.in_progress_show_created_var = tk.BooleanVar(value=False)
        self.in_progress_show_treated_var = tk.BooleanVar(value=False)
        self.in_progress_entries_by_id: dict[str, EntryMeta] = {}
        self.in_progress_sort_col: str | None = None
        self.in_progress_sort_dir: str | None = None
        self.in_progress_column_labels = {
            "project": "Project",
            "people": "People",
            "date": "Date",
            "type": "Type",
            "title": "Title",
            "open_actions": "Open actions",
        }
        self.upcoming_range_var = tk.StringVar(value=UPCOMING_RANGE_LABELS[0])
        self.upcoming_include_overdue_var = tk.BooleanVar(value=True)
        self.upcoming_tasks_by_id: dict[str, Task] = {}

        self._build_ui()
        self._bind_shortcuts()
        self.refresh_projects()
        self._poll_timer()

    def _build_ui(self) -> None:
        self._configure_styles()
        self._build_menu()
        self._build_toolbar()
        self._build_main_layout()
        self._set_project_editing(False)
        self._set_entry_editing(False)
        self.bind("<Configure>", self._on_window_configure)
        self._schedule_resize()
        self.protocol("WM_DELETE_WINDOW", self._on_close)

    def _build_main_layout(self) -> None:
        self.root_paned = ttk.PanedWindow(self, orient=tk.VERTICAL)
        self.root_paned.pack(fill=tk.BOTH, expand=True, padx=8, pady=8)

        self.main_container = ttk.Frame(self.root_paned)
        self.bottom_container = ttk.Frame(self.root_paned)
        self.root_paned.add(self.main_container, weight=3)
        self.root_paned.add(self.bottom_container, weight=1)

        self._build_main_panes(parent=self.main_container)
        self._build_bottom_panel(parent=self.bottom_container)
        self.after(80, self._init_root_sash)

    def _configure_styles(self) -> None:
        style = ttk.Style(self)
        style.configure("Treeview", rowheight=28)
        style.configure("TNotebook.Tab", padding=(10, 4))
        style.configure("Airy.TFrame", padding=6)

    def _parse_color_to_rgb(self, color: str) -> tuple[int, int, int] | None:
        if not color:
            return None
        if color.startswith("#"):
            hex_value = color[1:]
            if len(hex_value) == 3:
                try:
                    r = int(hex_value[0] * 2, 16)
                    g = int(hex_value[1] * 2, 16)
                    b = int(hex_value[2] * 2, 16)
                    return (r, g, b)
                except ValueError:
                    return None
            if len(hex_value) == 6:
                try:
                    r = int(hex_value[0:2], 16)
                    g = int(hex_value[2:4], 16)
                    b = int(hex_value[4:6], 16)
                    return (r, g, b)
                except ValueError:
                    return None
        try:
            r, g, b = self.winfo_rgb(color)
        except tk.TclError:
            return None
        return (r // 256, g // 256, b // 256)

    def _is_dark(self, rgb: tuple[int, int, int]) -> bool:
        r, g, b = rgb
        luminance = (0.2126 * r + 0.7152 * g + 0.0722 * b) / 255
        return luminance < 0.5

    def _mix_rgb(
        self, base: tuple[int, int, int], target: tuple[int, int, int], ratio: float
    ) -> tuple[int, int, int]:
        ratio = max(0.0, min(1.0, ratio))
        return tuple(
            int(base[i] * (1 - ratio) + target[i] * ratio) for i in range(3)
        )

    def _rgb_to_hex(self, rgb: tuple[int, int, int]) -> str:
        return f"#{rgb[0]:02x}{rgb[1]:02x}{rgb[2]:02x}"

    def _configure_tree_stripes(self, tree: ttk.Treeview) -> None:
        style = ttk.Style(self)
        base = style.lookup("Treeview", "background")
        if not base:
            base = style.lookup("TTreeview", "background")
        if not base:
            base = style.lookup(".", "background")
        if not base:
            base = self.cget("background")
        if not base:
            base = "#ffffff"
        base_rgb = self._parse_color_to_rgb(base)
        if base_rgb is None:
            base_rgb = (255, 255, 255)

        if self._is_dark(base_rgb):
            even_rgb = base_rgb
            odd_rgb = self._mix_rgb(base_rgb, (255, 255, 255), 0.08)
            if odd_rgb == even_rgb:
                odd_rgb = self._mix_rgb(base_rgb, (255, 255, 255), 0.12)
        else:
            even_rgb = base_rgb
            odd_rgb = self._mix_rgb(base_rgb, (0, 0, 0), 0.06)
            if odd_rgb == even_rgb:
                odd_rgb = self._mix_rgb(base_rgb, (0, 0, 0), 0.1)

        tree.tag_configure("even", background=self._rgb_to_hex(even_rgb))
        tree.tag_configure("odd", background=self._rgb_to_hex(odd_rgb))

    def _build_menu(self) -> None:
        menubar = tk.Menu(self)
        file_menu = tk.Menu(menubar, tearoff=0)
        file_menu.add_command(
            label="New Project", 
            command=self._new_project,
            accelerator=_menu_accel("N")
        )
        file_menu.add_command(
            label="New Entry", 
            command=self._new_entry,
            accelerator=_menu_accel("E")
        )
        file_menu.add_separator()
        file_menu.add_command(
            label="Save",
            command=self._save_entry,
            accelerator=_menu_accel("S"),
        )
        file_menu.add_command(label="Export Raw", command=self._export_raw)
        file_menu.add_separator()
        file_menu.add_command(label="Backup...", command=self._backup_data_dialog)
        file_menu.add_command(label="Restore...", command=self._restore_data_dialog)
        file_menu.add_separator()
        file_menu.add_command(
            label="Quit",
            command=self._on_close,
            accelerator=_menu_accel("Q"),
        )
        menubar.add_cascade(label="File", menu=file_menu)

        tools_menu = tk.Menu(menubar, tearoff=0)
        tools_menu.add_command(label="Data Directory...", command=self._select_data_dir)
        tools_menu.add_command(label="Open Data Folder", command=self._open_data_folder)
        tools_menu.add_command(label="Open Externally", command=self._open_current)
        tools_menu.add_command(label="Add manual time...", command=self._add_manual_time_dialog)
        tools_menu.add_separator()
        tools_menu.add_command(
            label="Compact entries log...",
            command=self._compact_entries_dialog,
        )
        tools_menu.add_separator()
        tools_menu.add_command(label="Restart", command=self._restart_app)
        menubar.add_cascade(label="Tools", menu=tools_menu)

        view_menu = tk.Menu(menubar, tearoff=0)
        view_menu.add_checkbutton(
            label="Show Details Panel",
            variable=self.details_visible_var,
            command=self._toggle_details_panel,
        )
        view_menu.add_checkbutton(
            label="Focus Mode",
            variable=self.focus_var,
            command=self._on_focus_toggle,
            accelerator="F9",
        )
        view_menu.add_command(label="Project Columns...", command=self._edit_project_columns)
        view_menu.add_command(
            label="Arrange Entry Columns...", command=self._edit_entry_columns
        )
        menubar.add_cascade(label="View", menu=view_menu)

        help_menu = tk.Menu(menubar, tearoff=0)
        help_menu.add_command(
            label="Keyboard Shortcuts...",
            command=self._show_keyboard_shortcuts,
            accelerator="F1"
        )
        help_menu.add_separator()
        help_menu.add_command(label="About PIGE", command=self._show_about_dialog)
        menubar.add_cascade(label="Help", menu=help_menu)

        self.config(menu=menubar)

    def _build_toolbar(self) -> None:
        self.toolbar = ttk.Frame(self)
        self.toolbar.pack(side=tk.TOP, fill=tk.X, padx=6, pady=4)

        self.new_project_button = ttk.Button(
            self.toolbar, text="New Project", command=self._new_project
        )
        self.new_entry_button = ttk.Button(
            self.toolbar, text="New Entry", command=self._new_entry
        )
        self.export_button = ttk.Button(
            self.toolbar, text="Export", command=self._show_export_menu
        )
        self.refresh_button = ttk.Button(
            self.toolbar, text="Refresh", command=self.refresh_projects
        )
        self.focus_button = ttk.Button(
            self.toolbar, text="Focus", command=self._toggle_focus
        )
        self.timer_button = ttk.Button(
            self.toolbar, text="Start Timer", command=self._toggle_timer
        )
        self.timer_tracking_label = ttk.Label(
            self.toolbar, textvariable=self.timer_tracking_var
        )
        self.save_status_label = ttk.Label(
            self.toolbar, textvariable=self.save_status_var
        )
        self.toolbar_spacer = ttk.Frame(self.toolbar)
        self.quit_button = ttk.Button(self.toolbar, text="Quit", command=self._on_close)
        if not self.current.project_id:
            self.timer_button.state(["disabled"])

        self.export_menu = tk.Menu(self, tearoff=0)
        self.export_menu.add_command(label="Project (Raw)", command=self._export_raw)
        self.export_menu.add_command(
            label="Project (Raw, redacted)",
            command=lambda: self._export_raw(redact_bodies=True),
        )
        self.export_menu.add_command(
            label="Project (Narrative)...", command=self._export_narrative_dialog
        )
        self.export_menu.add_command(
            label="Meeting minutes...", command=self._export_meeting_minutes_dialog
        )
        self.export_menu.add_command(
            label="Weekly summary...", command=self._export_weekly_summary_dialog
        )

        self._layout_toolbar(False)
        self._schedule_toolbar_layout()

    def _layout_toolbar(self, compact: bool) -> None:
        for widget in (
            self.new_project_button,
            self.new_entry_button,
            self.export_button,
            self.refresh_button,
            self.focus_button,
            self.timer_button,
            self.timer_tracking_label,
            self.save_status_label,
            self.toolbar_spacer,
            self.quit_button,
        ):
            widget.grid_forget()

        for idx in range(10):
            self.toolbar.columnconfigure(idx, weight=0)
        self.toolbar.rowconfigure(0, weight=0)
        self.toolbar.rowconfigure(1, weight=0)

        if compact:
            self.new_project_button.grid(row=0, column=0, padx=4, pady=2)
            self.new_entry_button.grid(row=0, column=1, padx=4, pady=2)
            self.export_button.grid(row=0, column=2, padx=4, pady=2)
            self.refresh_button.grid(row=0, column=3, padx=4, pady=2)
            self.timer_button.grid(row=0, column=4, padx=4, pady=2)
            self.toolbar_spacer.grid(row=0, column=5, sticky="ew")
            self.quit_button.grid(row=0, column=6, padx=4, pady=2, sticky=tk.E)
            self.toolbar.columnconfigure(5, weight=1)

            self.focus_button.grid(row=1, column=0, padx=4, pady=(0, 2), sticky=tk.W)
            self.timer_tracking_label.grid(
                row=1, column=1, padx=4, pady=(0, 2), sticky=tk.W
            )
            self.save_status_label.grid(
                row=1, column=2, padx=4, pady=(0, 2), sticky=tk.W
            )
        else:
            self.new_project_button.grid(row=0, column=0, padx=4, pady=2)
            self.new_entry_button.grid(row=0, column=1, padx=4, pady=2)
            self.export_button.grid(row=0, column=2, padx=4, pady=2)
            self.refresh_button.grid(row=0, column=3, padx=4, pady=2)
            self.timer_button.grid(row=0, column=4, padx=4, pady=2)
            self.focus_button.grid(row=0, column=5, padx=4, pady=2)
            self.timer_tracking_label.grid(row=0, column=6, padx=4, pady=2, sticky=tk.W)
            self.save_status_label.grid(row=0, column=7, padx=4, pady=2, sticky=tk.W)
            self.toolbar_spacer.grid(row=0, column=8, sticky="ew")
            self.quit_button.grid(row=0, column=9, padx=4, pady=2, sticky=tk.E)
            self.toolbar.columnconfigure(8, weight=1)

    def _schedule_toolbar_layout(self) -> None:
        if self._toolbar_after_id:
            self.after_cancel(self._toolbar_after_id)
        self._toolbar_after_id = self.after(
            TOOLBAR_LAYOUT_DEBOUNCE_MS, self._update_toolbar_layout
        )

    def _update_toolbar_layout(self) -> None:
        self._toolbar_after_id = None
        width = self.winfo_width()
        if width <= 1:
            self._schedule_toolbar_layout()
            return
        if self._toolbar_compact is None:
            self._toolbar_compact = width <= TOOLBAR_COMPACT_WIDTH
            self._layout_toolbar(self._toolbar_compact)
            return
        if self._toolbar_compact and width >= TOOLBAR_EXPAND_WIDTH:
            self._toolbar_compact = False
            self._layout_toolbar(False)
        elif not self._toolbar_compact and width <= TOOLBAR_COMPACT_WIDTH:
            self._toolbar_compact = True
            self._layout_toolbar(True)

    def _build_main_panes(self, parent: tk.Widget) -> None:
        self.paned = ttk.PanedWindow(parent, orient=tk.HORIZONTAL)
        self.paned.pack(fill=tk.BOTH, expand=True)

        self.project_frame = ttk.Frame(self.paned, style="Airy.TFrame")
        self.entry_frame = ttk.Frame(self.paned, style="Airy.TFrame")
        self.editor_frame = ttk.Frame(self.paned, style="Airy.TFrame")

        self.paned.add(self.project_frame, weight=1)
        self.paned.add(self.entry_frame, weight=2)
        self.paned.add(self.editor_frame, weight=3)

        self._build_projects_panel()
        self._build_entries_panel()
        self._build_editor_panel()

    def _build_projects_panel(self) -> None:
        self.project_tree = ttk.Treeview(self.project_frame, show="headings")
        self._apply_project_columns(self.project_displaycolumns)
        self._configure_tree_stripes(self.project_tree)
        project_scroll = ttk.Scrollbar(
            self.project_frame, orient=tk.VERTICAL, command=self.project_tree.yview
        )
        self.project_tree.configure(yscrollcommand=project_scroll.set)
        self.project_tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        project_scroll.pack(side=tk.RIGHT, fill=tk.Y)
        self.project_tree.bind("<<TreeviewSelect>>", self._on_project_select)
        self.project_tree.bind("<<TreeviewOpen>>", self._on_project_expand)
        self.project_tree.bind("<<TreeviewClose>>", self._on_project_collapse)
        self.project_context_menu = tk.Menu(self, tearoff=0)
        self.project_context_menu.add_command(
            label="New Entry in Project", command=self._new_entry
        )
        self.project_context_menu.add_separator()
        self.project_context_menu.add_command(
            label="Edit", command=self._edit_project_details
        )
        self.project_context_menu.add_command(
            label="Copy Project ID", command=self._copy_project_id
        )
        self.project_context_menu.add_separator()
        self.project_context_menu.add_command(
            label="Delete", command=self._delete_project
        )
        for sequence in ("<Button-3>", "<Button-2>", "<Control-Button-1>"):
            self.project_tree.bind(sequence, self._show_project_context_menu)

    def _build_entries_panel(self) -> None:
        filter_frame = ttk.Frame(self.entry_frame, style="Airy.TFrame")
        filter_frame.pack(side=tk.TOP, fill=tk.X, padx=4, pady=4)
        filter_frame.columnconfigure(0, weight=1)
        row_primary = ttk.Frame(filter_frame, style="Airy.TFrame")
        row_secondary = ttk.Frame(filter_frame, style="Airy.TFrame")
        row_primary.grid(row=0, column=0, sticky="ew", pady=(0, 2))
        row_secondary.grid(row=1, column=0, sticky="ew")

        ttk.Label(row_primary, text="Search").grid(row=0, column=0, sticky="w")
        self.entry_search_entry = ttk.Entry(
            row_primary, textvariable=self.entry_search_var
        )
        self.entry_search_entry.grid(row=0, column=1, sticky="ew", padx=4)
        row_primary.columnconfigure(1, weight=1)
        self.entry_search_entry.bind("<Return>", lambda _e: self._apply_entry_search())
        self.entry_search_var.trace_add("write", self._on_entry_search_change)
        self.entry_global_check = ttk.Checkbutton(
            row_primary,
            text="Global",
            variable=self.search_global_mode_var,
            command=self._apply_entry_search,
        )
        self.entry_global_check.grid(row=0, column=2, sticky="w", padx=(4, 0))
        self.entry_body_check = ttk.Checkbutton(
            row_primary,
            text="Include body",
            variable=self.search_include_body_var,
            command=self._apply_entry_search,
        )
        self.entry_body_check.grid(row=0, column=3, sticky="w", padx=4)

        self.show_archived_check = ttk.Checkbutton(
            row_secondary,
            text="Show archived",
            variable=self.show_archived_var,
            command=self._on_project_filter_change,
        )
        self.show_archived_check.grid(row=0, column=0, sticky="w")
        self.show_treated_check = ttk.Checkbutton(
            row_secondary,
            text="Show treated",
            variable=self.show_treated_var,
            command=self.refresh_entries,
        )
        self.show_treated_check.grid(row=0, column=1, sticky="w", padx=(8, 0))
        ttk.Label(row_secondary, text="Type").grid(
            row=0, column=2, sticky="w", padx=(8, 0)
        )
        self.entry_type_filter = ttk.Combobox(
            row_secondary,
            textvariable=self.entry_type_filter_var,
            values=("All", *DISPLAY_ENTRY_TYPES),
            state="readonly",
            width=12,
        )
        self.entry_type_filter.grid(row=0, column=3, sticky="w", padx=4)
        self.entry_type_filter.bind("<<ComboboxSelected>>", lambda _e: self.refresh_entries())
        ttk.Label(row_secondary, text="Person").grid(
            row=0, column=4, sticky="w", padx=(8, 0)
        )
        self.entry_person_filter = ttk.Combobox(
            row_secondary,
            textvariable=self.entry_person_filter_var,
            values=("All",),
            state="readonly",
            width=16,
        )
        self.entry_person_filter.grid(row=0, column=5, sticky="w", padx=4)
        self.entry_person_filter.bind(
            "<<ComboboxSelected>>", lambda _e: self.refresh_entries()
        )

        self.entry_tree = ttk.Treeview(
            self.entry_frame,
            columns=("date", "time", "type", "context", "done", "title", "people", "tags"),
            show="headings",
        )
        self.entry_tree.heading(
            "date", text="Date", command=lambda c="date": self._on_entry_sort(c)
        )
        self.entry_tree.heading(
            "time", text="Time", command=lambda c="time": self._on_entry_sort(c)
        )
        self.entry_tree.heading(
            "type", text="Type", command=lambda c="type": self._on_entry_sort(c)
        )
        self.entry_tree.heading(
            "context", text="Context", command=lambda c="context": self._on_entry_sort(c)
        )
        self.entry_tree.heading(
            "done", text="Done", command=lambda c="done": self._on_entry_sort(c)
        )
        self.entry_tree.heading(
            "title", text="Title", command=lambda c="title": self._on_entry_sort(c)
        )
        self.entry_tree.heading(
            "people", text="People", command=lambda c="people": self._on_entry_sort(c)
        )
        self.entry_tree.heading(
            "tags", text="Tags", command=lambda c="tags": self._on_entry_sort(c)
        )

        self._apply_entry_columns(self.entry_displaycolumns)

        self.entry_tree.column("date", width=120, anchor=tk.W, stretch=False)
        self.entry_tree.column("time", width=110, anchor=tk.W, stretch=False)
        self.entry_tree.column("type", width=100, anchor=tk.W, stretch=False)
        self.entry_tree.column("context", width=80, anchor=tk.W, stretch=False)
        self.entry_tree.column("done", width=50, anchor=tk.W, stretch=False)
        self.entry_tree.column("title", width=220, anchor=tk.W)
        self.entry_tree.column("people", width=160, anchor=tk.W)
        self.entry_tree.column("tags", width=140, anchor=tk.W)
        self._configure_tree_stripes(self.entry_tree)

        entry_scroll = ttk.Scrollbar(
            self.entry_frame, orient=tk.VERTICAL, command=self.entry_tree.yview
        )
        self.entry_tree.configure(yscrollcommand=entry_scroll.set)
        self.entry_tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        entry_scroll.pack(side=tk.RIGHT, fill=tk.Y)
        self.entry_tree.bind("<<TreeviewSelect>>", self._on_entry_select)
        self.entry_tree.bind("<Double-1>", self._on_entry_double_click)
        self.entry_context_menu = tk.Menu(self, tearoff=0)
        self.entry_context_menu.add_command(
            label="Open",
            command=self._entry_context_open,
        )
        self.entry_context_menu.add_command(label="Edit", command=self._edit_entry_details)
        self.entry_context_menu.add_command(label="Delete", command=self._delete_entry)
        self.entry_context_menu.add_command(
            label="Export meeting minutes...",
            command=self._export_meeting_minutes_from_context,
        )
        self.entry_context_menu.add_command(
            label="Mark as Actual",
            command=lambda: self._set_entry_context_status("actual"),
        )
        self.entry_context_menu.add_command(
            label="Mark as Treated",
            command=lambda: self._set_entry_context_status("treated"),
        )
        self.entry_context_menu.add_command(
            label="Mark as Created",
            command=lambda: self._set_entry_context_status("created"),
        )
        self.entry_context_menu.add_command(
            label="Create follow-up tasks...", command=self._create_followup_tasks_dialog
        )
        self.entry_context_menu.add_separator()
        self.entry_context_menu.add_command(
            label="Copy Entry ID", command=self._copy_entry_id
        )
        self.entry_context_menu.add_command(
            label="Move to project...", command=self._move_entry_dialog
        )
        for sequence in ("<Button-3>", "<Button-2>", "<Control-Button-1>"):
            self.entry_tree.bind(sequence, self._show_entry_context_menu)

    def _build_editor_panel(self) -> None:
        header_frame = ttk.Frame(self.editor_frame, style="Airy.TFrame")
        header_frame.pack(side=tk.TOP, fill=tk.X, padx=6, pady=(6, 2))
        ttk.Label(
            header_frame, textvariable=self.editor_title_var, anchor=tk.W
        ).pack(side=tk.LEFT, fill=tk.X, expand=True)
        zoom_frame = ttk.Frame(header_frame)
        zoom_frame.pack(side=tk.RIGHT)
        ttk.Button(zoom_frame, text="A-", command=lambda: self._zoom_editor(-1)).pack(
            side=tk.LEFT, padx=2
        )
        ttk.Button(zoom_frame, text="A+", command=lambda: self._zoom_editor(1)).pack(
            side=tk.LEFT, padx=2
        )
        ttk.Button(
            zoom_frame, text="[ ]", command=self._editor_insert_checklist_item
        ).pack(side=tk.LEFT, padx=2)
        ttk.Button(zoom_frame, text="Reset", command=self._reset_editor_zoom).pack(
            side=tk.LEFT, padx=2
        )

        editor_area = ttk.Frame(self.editor_frame)
        editor_area.pack(side=tk.TOP, fill=tk.BOTH, expand=True, padx=6, pady=6)

        self.editor_text = tk.Text(editor_area, wrap="word", undo=True)
        self._init_editor_font()

        editor_scroll = ttk.Scrollbar(
            editor_area, orient=tk.VERTICAL, command=self.editor_text.yview
        )
        self.editor_text.configure(yscrollcommand=editor_scroll.set)

        self.editor_text.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        editor_scroll.pack(side=tk.RIGHT, fill=tk.Y)
        self.editor_text.bind("<<Modified>>", self._on_text_modified)
        self.editor_text.bind("<Return>", self._editor_on_return)
        self.editor_text.bind("<Tab>", self._editor_on_tab)
        self.editor_text.bind("<Shift-Tab>", self._editor_on_shift_tab)
        self.editor_text.bind("<ISO_Left_Tab>", self._editor_on_shift_tab)
        self.editor_text.bind("<Control-Shift-X>", self._editor_toggle_checkbox)
        self.editor_text.bind("<Command-Shift-X>", self._editor_toggle_checkbox)
        self.editor_context_menu = tk.Menu(self, tearoff=0)
        self.editor_context_menu.add_command(
            label="Insert checklist item", command=self._editor_insert_checklist_item
        )
        self.editor_context_menu.add_command(
            label="Create tasks from selection...",
            command=self._editor_create_tasks_from_selection,
        )
        for sequence in ("<Button-3>", "<Button-2>", "<Control-Button-1>"):
            self.editor_text.bind(sequence, self._show_editor_context_menu)


    def _init_root_sash(self) -> None:
        if self._root_sash_initialized or not hasattr(self, "root_paned"):
            return
        self.update_idletasks()
        total = self.root_paned.winfo_height()
        if total <= 0:
            self.after(80, self._init_root_sash)
            return
        tabs_req = self._max_reqheight(
            (
                getattr(self, "project_tab", None),
                getattr(self, "entry_tab", None),
                getattr(self, "stats_tab", None),
                getattr(self, "in_progress_tab", None),
                getattr(self, "upcoming_tab", None),
            )
        )
        footer_req = self._max_reqheight(
            (
                getattr(self, "project_footer", None),
                getattr(self, "entry_footer", None),
                getattr(self, "stats_footer", None),
                getattr(self, "upcoming_footer", None),
                getattr(self, "action_bar", None),
            )
        )
        fallback = 360
        padding = 24
        bottom_min = max(fallback, tabs_req + footer_req + padding)
        max_sash = max(0, total - 2)
        top_min = min(200, max_sash)
        desired = total - bottom_min
        desired = max(top_min, min(desired, max_sash))
        try:
            self.root_paned.sashpos(0, desired)
            self._root_sash_initialized = True
        except Exception:
            logger.exception("Exception caught in GUI operation")
            self.after(80, self._init_root_sash)

    def _init_bottom_sash(self) -> None:
        if self._bottom_sash_initialized or not hasattr(self, "bottom_paned"):
            return
        total = self.bottom_paned.winfo_width()
        if total <= 0:
            self.after(80, self._init_bottom_sash)
            return
        try:
            self.bottom_paned.sashpos(0, int(total * 0.65))
        except Exception:
            logger.exception("Exception caught in GUI operation")
            pass
        self._bottom_sash_initialized = True
        self._clamp_bottom_sash()

    def _clamp_bottom_sash(self) -> None:
        if not hasattr(self, "bottom_paned"):
            return
        total = self.bottom_paned.winfo_width()
        if total <= 0:
            return
        min_details = 380
        min_tasks = 300
        try:
            pos = int(self.bottom_paned.sashpos(0))
            pos = max(min_details, min(pos, total - min_tasks))
            self.bottom_paned.sashpos(0, pos)
        except Exception:
            logger.exception("Exception caught in GUI operation")
            return

    def _max_reqheight(self, widgets: tuple[tk.Widget | None, ...]) -> int:
        max_req = 0
        for widget in widgets:
            req = self._safe_reqheight(widget, 0)
            if req > max_req:
                max_req = req
        return max_req

    def _safe_reqheight(self, widget: tk.Widget | None, fallback: int = 0) -> int:
        if widget is None:
            return fallback
        try:
            req = int(widget.winfo_reqheight())
        except Exception:
            logger.exception("Exception caught in GUI operation")
            return fallback
        return req if req > 1 else fallback

    def _build_bottom_panel(self, parent: tk.Widget) -> None:
        self.bottom_frame = ttk.Frame(parent)
        self.bottom_frame.pack(fill=tk.BOTH, expand=True)

        self.bottom_paned = ttk.PanedWindow(self.bottom_frame, orient=tk.HORIZONTAL)
        self.bottom_paned.pack(fill=tk.BOTH, expand=True)

        self.details_container = ttk.Frame(self.bottom_paned)
        self.tasks_container = ttk.Frame(self.bottom_paned)
        self.bottom_paned.add(self.details_container, weight=2)
        self.bottom_paned.add(self.tasks_container, weight=1)
        self.bottom_paned.bind(
            "<ButtonRelease-1>", lambda _e: self._clamp_bottom_sash()
        )
        self.bottom_paned.bind("<Configure>", lambda _e: self._clamp_bottom_sash())

        self.details_container.columnconfigure(0, weight=1)
        self.details_container.rowconfigure(0, weight=1)
        self.details_container.rowconfigure(1, weight=0)

        self.details_notebook = ttk.Notebook(self.details_container)
        self.details_notebook.grid(
            row=0, column=0, sticky="nsew", padx=8, pady=(0, 6)
        )

        self.project_tab = ttk.Frame(self.details_notebook, style="Airy.TFrame")
        self.entry_tab = ttk.Frame(self.details_notebook, style="Airy.TFrame")
        self.stats_tab = ttk.Frame(self.details_notebook, style="Airy.TFrame")
        self.in_progress_tab = ttk.Frame(self.details_notebook, style="Airy.TFrame")
        self.upcoming_tab = ttk.Frame(self.details_notebook, style="Airy.TFrame")

        self.details_notebook.add(self.project_tab, text="Project")
        self.details_notebook.add(self.entry_tab, text="Entry")
        self.details_notebook.add(self.stats_tab, text="Stats")
        self.details_notebook.add(self.in_progress_tab, text="In progress")
        self.details_notebook.add(self.upcoming_tab, text="Upcoming")

        self._build_project_tab()
        self._build_entry_tab()
        self._build_stats_tab()
        self._build_in_progress_tab()
        self._build_upcoming_tab()

        self._build_action_bar(parent=self.details_container)
        self.action_bar.grid(row=1, column=0, sticky="ew", padx=8, pady=6)
        self.details_notebook.bind("<<NotebookTabChanged>>", self._on_details_tab_changed)
        self._on_details_tab_changed(None)
        self._build_tasks_panel(self.tasks_container)
        self.after(80, self._init_bottom_sash)

    def _build_project_tab(self) -> None:
        self.project_tab.columnconfigure(1, weight=1)
        self.project_tab.columnconfigure(3, weight=1)

        ttk.Label(self.project_tab, text="Name").grid(
            row=0, column=0, sticky=tk.W, padx=6, pady=4
        )
        self.project_name_entry = ttk.Entry(
            self.project_tab, textvariable=self.project_name_var
        )
        self.project_name_entry.grid(row=0, column=1, sticky="ew", padx=6, pady=4)

        self.project_status_check = ttk.Checkbutton(
            self.project_tab,
            text="Archived / Finished",
            variable=self.project_status_var,
            command=self._on_project_detail_modified,
        )
        self.project_status_check.grid(
            row=0, column=2, columnspan=2, sticky=tk.W, padx=6, pady=4
        )

        ttk.Label(self.project_tab, text="Desc").grid(
            row=1, column=0, sticky=tk.NW, padx=6, pady=4
        )
        self.project_desc_text = tk.Text(self.project_tab, height=3, wrap="word")
        self.project_desc_text.grid(
            row=1, column=1, columnspan=3, sticky="nsew", padx=6, pady=4
        )
        self.project_desc_text.bind("<<Modified>>", self._on_project_desc_modified)

        ttk.Label(self.project_tab, text="People (one per line)").grid(
            row=2, column=0, sticky=tk.NW, padx=6, pady=4
        )
        self.project_people_text = tk.Text(self.project_tab, height=3, wrap="word")
        self.project_people_text.grid(
            row=2, column=1, sticky="nsew", padx=6, pady=4
        )
        self.project_people_text.bind("<<Modified>>", self._on_project_people_modified)

        ttk.Label(self.project_tab, text="Group").grid(
            row=2, column=2, sticky=tk.W, padx=6, pady=4
        )
        self.project_group_entry = ttk.Entry(
            self.project_tab, textvariable=self.project_group_var
        )
        self.project_group_entry.grid(row=2, column=3, sticky="ew", padx=6, pady=4)

        ttk.Label(self.project_tab, text="Tags").grid(
            row=3, column=0, sticky=tk.W, padx=6, pady=4
        )
        self.project_tags_entry = AutocompleteEntry(
            self.project_tab,
            get_suggestions=self._get_all_tags,
            textvariable=self.project_tags_var
        )
        self.project_tags_entry.grid(
            row=3, column=1, columnspan=3, sticky="ew", padx=6, pady=4
        )

        ttk.Label(self.project_tab, text="Links (one per line)").grid(
            row=4, column=0, sticky=tk.NW, padx=6, pady=4
        )
        self.project_links_frame = ttk.Frame(self.project_tab)
        self.project_links_frame.grid(
            row=4, column=1, columnspan=3, sticky="nsew", padx=6, pady=4
        )
        self.project_links_frame.columnconfigure(0, weight=1)
        self.project_links_frame.rowconfigure(0, weight=1)
        self.project_links_text = tk.Text(self.project_links_frame, height=3, wrap="word")
        self.project_links_text.grid(row=0, column=0, sticky="nsew")
        self.project_links_text.bind("<<Modified>>", self._on_project_links_modified)

        self.project_links_buttons = ttk.Frame(self.project_links_frame)
        self.project_links_buttons.grid(row=0, column=1, sticky="ns", padx=(6, 0))
        self.project_links_open_button = ttk.Button(
            self.project_links_buttons, text="Open", command=self._open_project_link
        )
        self.project_links_open_button.pack(fill=tk.X, pady=(0, 4))
        self.project_links_copy_button = ttk.Button(
            self.project_links_buttons, text="Copy", command=self._copy_project_link
        )
        self.project_links_copy_button.pack(fill=tk.X)

        ttk.Label(self.project_tab, text="Today").grid(
            row=5, column=0, sticky=tk.W, padx=6, pady=4
        )
        ttk.Label(self.project_tab, textvariable=self.project_today_var).grid(
            row=5, column=1, sticky=tk.W, padx=6, pady=4
        )
        ttk.Label(self.project_tab, text="Entries").grid(
            row=5, column=2, sticky=tk.W, padx=6, pady=4
        )
        ttk.Label(self.project_tab, textvariable=self.project_entry_count_var).grid(
            row=5, column=3, sticky=tk.W, padx=6, pady=4
        )

    def _build_entry_tab(self) -> None:
        self.entry_tab.columnconfigure(1, weight=1)
        self.entry_tab.columnconfigure(3, weight=1)

        ttk.Label(self.entry_tab, text="Title").grid(
            row=0, column=0, sticky=tk.W, padx=6, pady=4
        )
        self.entry_title_entry = ttk.Entry(self.entry_tab, textvariable=self.entry_title_var)
        self.entry_title_entry.grid(row=0, column=1, sticky="ew", padx=6, pady=4)

        ttk.Label(self.entry_tab, text="Type").grid(
            row=0, column=2, sticky=tk.W, padx=6, pady=4
        )
        ttk.Label(self.entry_tab, textvariable=self.entry_type_var).grid(
            row=0, column=3, sticky=tk.W, padx=6, pady=4
        )

        ttk.Label(self.entry_tab, text="Date (DD/MM/YYYY)").grid(
            row=1, column=0, sticky=tk.W, padx=6, pady=4
        )
        self.entry_date_entry = ttk.Entry(self.entry_tab, textvariable=self.entry_date_var)
        self.entry_date_entry.grid(row=1, column=1, sticky="ew", padx=6, pady=4)

        ttk.Label(self.entry_tab, text="People (one per line)").grid(
            row=1, column=2, sticky=tk.NW, padx=6, pady=4
        )
        self.entry_people_text = tk.Text(self.entry_tab, height=3, wrap="word")
        self.entry_people_text.grid(row=1, column=3, sticky="nsew", padx=6, pady=4)
        self.entry_people_text.bind("<<Modified>>", self._on_entry_people_modified)

        ttk.Label(self.entry_tab, text="Group").grid(
            row=2, column=0, sticky=tk.W, padx=6, pady=4
        )
        self.entry_group_entry = ttk.Entry(self.entry_tab, textvariable=self.entry_group_var)
        self.entry_group_entry.grid(row=2, column=1, sticky="ew", padx=6, pady=4)

        ttk.Label(self.entry_tab, text="Tags").grid(
            row=2, column=2, sticky=tk.W, padx=6, pady=4
        )
        self.entry_tags_entry = AutocompleteEntry(
            self.entry_tab,
            get_suggestions=self._get_all_tags,
            textvariable=self.entry_tags_var
        )
        self.entry_tags_entry.grid(row=2, column=3, sticky="ew", padx=6, pady=4)

        self.entry_meeting_label = ttk.Label(self.entry_tab, text="Meeting")
        self.entry_meeting_label.grid(row=3, column=0, sticky=tk.W, padx=6, pady=4)
        self.entry_meeting_frame = ttk.Frame(self.entry_tab)
        self.entry_meeting_frame.grid(
            row=3, column=1, columnspan=3, sticky=tk.W, padx=6, pady=4
        )
        ttk.Label(self.entry_meeting_frame, text="Start").pack(side=tk.LEFT)
        self.entry_start_entry = ttk.Entry(
            self.entry_meeting_frame, textvariable=self.entry_start_var, width=8
        )
        self.entry_start_entry.pack(side=tk.LEFT, padx=(4, 8))
        ttk.Label(self.entry_meeting_frame, text="End").pack(side=tk.LEFT)
        self.entry_end_entry = ttk.Entry(
            self.entry_meeting_frame, textvariable=self.entry_end_var, width=8
        )
        self.entry_end_entry.pack(side=tk.LEFT, padx=4)

        self.entry_decision_label = ttk.Label(self.entry_tab, text="Decision")
        self.entry_decision_label.grid(row=4, column=0, sticky=tk.W, padx=6, pady=4)
        self.entry_decision_check = ttk.Checkbutton(
            self.entry_tab,
            text="Applied/Done",
            variable=self.entry_decision_var,
            command=self._on_entry_decision_toggle,
        )
        self.entry_decision_check.grid(row=4, column=1, sticky=tk.W, padx=6, pady=4)

        self.entry_title_var.trace_add("write", self._on_entry_detail_modified)
        self.entry_date_var.trace_add("write", self._on_entry_detail_modified)
        self.entry_group_var.trace_add("write", self._on_entry_detail_modified)
        self.entry_tags_var.trace_add("write", self._on_entry_detail_modified)
        self.entry_start_var.trace_add("write", self._on_entry_detail_modified)
        self.entry_end_var.trace_add("write", self._on_entry_detail_modified)

    def _build_tasks_panel(self, parent: ttk.Frame) -> None:
        parent.columnconfigure(0, weight=1)
        parent.rowconfigure(0, weight=1)

        self.tasks_empty_label = ttk.Label(
            parent, text="Select a project to view tasks."
        )
        self.tasks_empty_label.grid(row=0, column=0, sticky="w", padx=8, pady=8)

        self.tasks_content_frame = ttk.Frame(parent, style="Airy.TFrame")
        self.tasks_content_frame.grid(row=0, column=0, sticky="nsew")
        self.tasks_content_frame.columnconfigure(0, weight=1)
        self.tasks_content_frame.rowconfigure(1, weight=1)

        filter_frame = ttk.Frame(self.tasks_content_frame)
        filter_frame.grid(row=0, column=0, sticky="ew", padx=4, pady=4)
        ttk.Label(filter_frame, text="Search").pack(side=tk.LEFT)
        self.task_search_entry = ttk.Entry(
            filter_frame, textvariable=self.task_search_var
        )
        self.task_search_entry.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=4)
        ttk.Label(filter_frame, text="Status").pack(side=tk.LEFT, padx=(8, 0))
        self.task_status_filter = ttk.Combobox(
            filter_frame,
            textvariable=self.task_status_filter_var,
            values=("All", "Open", "In Progress", "Done"),
            state="readonly",
            width=12,
        )
        self.task_status_filter.pack(side=tk.LEFT, padx=4)
        self.task_current_entries_check = ttk.Checkbutton(
            filter_frame,
            text="Current entries only",
            variable=self.task_current_entries_only_var,
            command=self.refresh_tasks,
        )
        self.task_current_entries_check.pack(side=tk.LEFT, padx=(8, 0))
        self.task_status_filter.bind("<<ComboboxSelected>>", lambda _e: self.refresh_tasks())
        self.task_search_var.trace_add("write", lambda *_a: self.refresh_tasks())

        tree_frame = ttk.Frame(self.tasks_content_frame)
        tree_frame.grid(row=1, column=0, sticky="nsew", padx=4, pady=4)
        tree_frame.columnconfigure(0, weight=1)
        tree_frame.rowconfigure(0, weight=1)
        self.task_tree = ttk.Treeview(
            tree_frame,
            columns=("done", "title", "due", "tags", "source"),
            show="headings",
        )
        self.task_tree.heading("done", text="Done")
        self.task_tree.heading("title", text="Title")
        self.task_tree.heading("due", text="Due")
        self.task_tree.heading("tags", text="Tags")
        self.task_tree.heading("source", text="Source")
        self.task_tree.column("done", width=50, anchor=tk.CENTER, stretch=False)
        self.task_tree.column("title", width=240, anchor=tk.W, stretch=True)
        self.task_tree.column("due", width=100, anchor=tk.W, stretch=False)
        self.task_tree.column("tags", width=160, anchor=tk.W, stretch=True)
        self.task_tree.column("source", width=90, anchor=tk.W, stretch=False)
        self._configure_tree_stripes(self.task_tree)

        task_scroll = ttk.Scrollbar(
            tree_frame, orient=tk.VERTICAL, command=self.task_tree.yview
        )
        self.task_tree.configure(yscrollcommand=task_scroll.set)
        self.task_tree.grid(row=0, column=0, sticky="nsew")
        task_scroll.grid(row=0, column=1, sticky="ns")
        self.task_tree.bind("<<TreeviewSelect>>", self._on_task_select)
        self.task_tree.bind("<Double-1>", lambda _e: self._toggle_task_done())
        self.task_context_menu = tk.Menu(self, tearoff=0)
        self.task_context_menu.add_command(
            label="Mark Open", command=lambda: self._set_task_status("open")
        )
        self.task_context_menu.add_command(
            label="Mark In Progress", command=lambda: self._set_task_status("in_progress")
        )
        self.task_context_menu.add_command(
            label="Mark Done", command=lambda: self._set_task_status("done")
        )
        for sequence in ("<Button-3>", "<Button-2>", "<Control-Button-1>"):
            self.task_tree.bind(sequence, self._show_task_context_menu)

        bottom_frame = ttk.Frame(self.tasks_content_frame)
        bottom_frame.grid(row=2, column=0, sticky="ew", padx=4, pady=4)
        bottom_frame.columnconfigure(1, weight=1)

        details_frame = ttk.Frame(bottom_frame)
        details_frame.grid(row=0, column=0, columnspan=2, sticky="ew")
        details_frame.columnconfigure(1, weight=1)

        ttk.Label(details_frame, text="Note").grid(
            row=0, column=0, sticky=tk.NW, padx=4, pady=2
        )
        self.task_note_text = tk.Text(details_frame, height=3, wrap="word")
        self.task_note_text.grid(
            row=0, column=1, columnspan=3, sticky="nsew", padx=4, pady=2
        )
        self.task_note_text.configure(state="disabled")

        ttk.Label(details_frame, text="Created").grid(
            row=1, column=0, sticky=tk.W, padx=4, pady=2
        )
        ttk.Label(details_frame, textvariable=self.task_created_var).grid(
            row=1, column=1, sticky=tk.W, padx=4, pady=2
        )
        ttk.Label(details_frame, text="Done").grid(
            row=1, column=2, sticky=tk.W, padx=4, pady=2
        )
        ttk.Label(details_frame, textvariable=self.task_done_var).grid(
            row=1, column=3, sticky=tk.W, padx=4, pady=2
        )

        button_frame = ttk.Frame(bottom_frame)
        button_frame.grid(row=1, column=0, columnspan=2, sticky="w", pady=4)
        self.task_add_button = ttk.Button(
            button_frame, text="Add", command=self._add_task_dialog
        )
        self.task_edit_button = ttk.Button(
            button_frame, text="Edit", command=self._edit_task_dialog
        )
        self.task_delete_button = ttk.Button(
            button_frame, text="Delete", command=self._delete_task
        )
        self.task_from_entry_button = ttk.Button(
            button_frame,
            text="Create from Entry",
            command=lambda: self._add_task_dialog(from_entry=True),
        )
        self.task_add_button.pack(side=tk.LEFT, padx=(0, 6))
        self.task_edit_button.pack(side=tk.LEFT, padx=(0, 6))
        self.task_delete_button.pack(side=tk.LEFT, padx=(0, 6))
        self.task_from_entry_button.pack(side=tk.LEFT)

    def _build_stats_tab(self) -> None:
        self.stats_tab.columnconfigure(1, weight=1)

        ttk.Label(self.stats_tab, text="Timer").grid(
            row=0, column=0, sticky=tk.W, padx=6, pady=4
        )
        ttk.Label(self.stats_tab, textvariable=self.stats_timer_state_var).grid(
            row=0, column=1, sticky=tk.W, padx=6, pady=4
        )
        ttk.Label(self.stats_tab, text="Elapsed").grid(
            row=1, column=0, sticky=tk.W, padx=6, pady=4
        )
        ttk.Label(self.stats_tab, textvariable=self.stats_timer_elapsed_var).grid(
            row=1, column=1, sticky=tk.W, padx=6, pady=4
        )
        ttk.Label(self.stats_tab, text="Today (selected)").grid(
            row=2, column=0, sticky=tk.W, padx=6, pady=4
        )
        ttk.Label(self.stats_tab, textvariable=self.stats_today_project_var).grid(
            row=2, column=1, sticky=tk.W, padx=6, pady=4
        )
        ttk.Label(self.stats_tab, text="Today (all projects)").grid(
            row=3, column=0, sticky=tk.W, padx=6, pady=4
        )
        ttk.Label(self.stats_tab, textvariable=self.stats_today_all_var).grid(
            row=3, column=1, sticky=tk.W, padx=6, pady=4
        )
        ttk.Label(self.stats_tab, text="Selected project").grid(
            row=4, column=0, sticky=tk.W, padx=6, pady=4
        )
        ttk.Label(self.stats_tab, textvariable=self.stats_selected_project_var).grid(
            row=4, column=1, sticky=tk.W, padx=6, pady=4
        )
        ttk.Label(self.stats_tab, text="Data dir").grid(
            row=5, column=0, sticky=tk.W, padx=6, pady=4
        )
        ttk.Label(self.stats_tab, textvariable=self.stats_data_dir_var).grid(
            row=5, column=1, sticky=tk.W, padx=6, pady=4
        )

    def _build_in_progress_tab(self) -> None:
        self.in_progress_tab.columnconfigure(0, weight=1)
        self.in_progress_tab.rowconfigure(1, weight=1)

        filter_frame = ttk.Frame(self.in_progress_tab)
        filter_frame.grid(row=0, column=0, sticky="ew", padx=6, pady=4)
        ttk.Checkbutton(
            filter_frame,
            text="Show Created",
            variable=self.in_progress_show_created_var,
            command=self.refresh_in_progress,
        ).pack(side=tk.LEFT, padx=(0, 8))
        ttk.Checkbutton(
            filter_frame,
            text="Show Treated",
            variable=self.in_progress_show_treated_var,
            command=self.refresh_in_progress,
        ).pack(side=tk.LEFT, padx=(0, 8))
        ttk.Button(filter_frame, text="Refresh", command=self.refresh_in_progress).pack(
            side=tk.LEFT
        )

        tree_frame = ttk.Frame(self.in_progress_tab)
        tree_frame.grid(row=1, column=0, sticky="nsew", padx=6, pady=4)
        tree_frame.columnconfigure(0, weight=1)
        tree_frame.rowconfigure(0, weight=1)

        self.in_progress_tree = ttk.Treeview(
            tree_frame,
            columns=("project", "people", "date", "type", "title", "open_actions"),
            show="headings",
        )
        for col in self.in_progress_tree["columns"]:
            label = self.in_progress_column_labels.get(col, col)
            self.in_progress_tree.heading(
                col, text=label, command=lambda c=col: self._toggle_in_progress_sort(c)
            )
        self.in_progress_tree.column("project", width=160, anchor=tk.W, stretch=False)
        self.in_progress_tree.column("people", width=160, anchor=tk.W, stretch=False)
        self.in_progress_tree.column("date", width=110, anchor=tk.W, stretch=False)
        self.in_progress_tree.column("type", width=90, anchor=tk.W, stretch=False)
        self.in_progress_tree.column("title", width=320, anchor=tk.W, stretch=True)
        self.in_progress_tree.column("open_actions", width=90, anchor=tk.CENTER, stretch=False)
        self._configure_tree_stripes(self.in_progress_tree)

        in_progress_scroll = ttk.Scrollbar(
            tree_frame, orient=tk.VERTICAL, command=self.in_progress_tree.yview
        )
        self.in_progress_tree.configure(yscrollcommand=in_progress_scroll.set)
        self.in_progress_tree.grid(row=0, column=0, sticky="nsew")
        in_progress_scroll.grid(row=0, column=1, sticky="ns")
        self.in_progress_tree.bind("<Double-1>", self._on_in_progress_open)

        self.in_progress_context_menu = tk.Menu(self, tearoff=0)
        self.in_progress_context_menu.add_command(
            label="Open entry", command=self._open_selected_in_progress
        )
        self.in_progress_context_menu.add_command(
            label="Mark as Actual",
            command=lambda: self._set_in_progress_entry_context_status("actual"),
        )
        self.in_progress_context_menu.add_command(
            label="Mark as Treated",
            command=lambda: self._set_in_progress_entry_context_status("treated"),
        )
        self.in_progress_context_menu.add_command(
            label="Mark as Created",
            command=lambda: self._set_in_progress_entry_context_status("created"),
        )
        for sequence in ("<Button-3>", "<Button-2>", "<Control-Button-1>"):
            self.in_progress_tree.bind(sequence, self._show_in_progress_context_menu)

    def _build_upcoming_tab(self) -> None:
        self.upcoming_tab.columnconfigure(0, weight=1)
        self.upcoming_tab.rowconfigure(1, weight=1)

        filter_frame = ttk.Frame(self.upcoming_tab)
        filter_frame.grid(row=0, column=0, sticky="ew", padx=6, pady=4)
        ttk.Label(filter_frame, text="Range").pack(side=tk.LEFT)
        self.upcoming_range_combo = ttk.Combobox(
            filter_frame,
            textvariable=self.upcoming_range_var,
            values=UPCOMING_RANGE_LABELS,
            state="readonly",
            width=14,
        )
        self.upcoming_range_combo.pack(side=tk.LEFT, padx=(4, 8))
        self.upcoming_range_combo.bind(
            "<<ComboboxSelected>>", lambda _e: self.refresh_upcoming()
        )
        self.upcoming_overdue_check = ttk.Checkbutton(
            filter_frame,
            text="Include overdue",
            variable=self.upcoming_include_overdue_var,
            command=self.refresh_upcoming,
        )
        self.upcoming_overdue_check.pack(side=tk.LEFT)

        tree_frame = ttk.Frame(self.upcoming_tab)
        tree_frame.grid(row=1, column=0, sticky="nsew", padx=6, pady=4)
        tree_frame.columnconfigure(0, weight=1)
        tree_frame.rowconfigure(0, weight=1)

        self.upcoming_tree = ttk.Treeview(
            tree_frame,
            columns=("due", "project", "task"),
            show="headings",
        )
        self.upcoming_tree.heading("due", text="Due")
        self.upcoming_tree.heading("project", text="Project")
        self.upcoming_tree.heading("task", text="Task")
        self.upcoming_tree.column("due", width=100, anchor=tk.W, stretch=False)
        self.upcoming_tree.column("project", width=160, anchor=tk.W, stretch=False)
        self.upcoming_tree.column("task", width=260, anchor=tk.W, stretch=True)
        self._configure_tree_stripes(self.upcoming_tree)

        upcoming_scroll = ttk.Scrollbar(
            tree_frame, orient=tk.VERTICAL, command=self.upcoming_tree.yview
        )
        self.upcoming_tree.configure(yscrollcommand=upcoming_scroll.set)
        self.upcoming_tree.grid(row=0, column=0, sticky="nsew")
        upcoming_scroll.grid(row=0, column=1, sticky="ns")
        self.upcoming_tree.bind("<Double-1>", self._on_upcoming_open)

    def _build_action_bar(self, parent: tk.Widget) -> None:
        self.details_footer = ttk.Frame(parent)
        self.action_bar = self.details_footer
        self.action_bar.columnconfigure(0, weight=1)

        self.status_var = tk.StringVar(value="Ready")

        self.project_footer = ttk.Frame(self.action_bar)
        self.entry_footer = ttk.Frame(self.action_bar)
        self.stats_footer = ttk.Frame(self.action_bar)
        self.upcoming_footer = ttk.Frame(self.action_bar)

        self.project_footer.grid(row=0, column=0, sticky="ew")
        self.entry_footer.grid(row=0, column=0, sticky="ew")
        self.stats_footer.grid(row=0, column=0, sticky="ew")
        self.upcoming_footer.grid(row=0, column=0, sticky="ew")
        self.entry_footer.grid_remove()
        self.stats_footer.grid_remove()
        self.upcoming_footer.grid_remove()

        self.project_edit_save_button = ttk.Button(
            self.project_footer, text="Edit", command=self._on_project_edit_save
        )
        self.project_cancel_button = ttk.Button(
            self.project_footer, text="Cancel", command=self._cancel_project_details
        )
        self.project_edit_save_button.pack(side=tk.LEFT, padx=(0, 6))
        self.project_cancel_button.pack(side=tk.LEFT, padx=(0, 12))

        ttk.Separator(self.project_footer, orient=tk.VERTICAL).pack(
            side=tk.LEFT, fill=tk.Y, padx=6
        )

        self.project_done_button = ttk.Button(
            self.project_footer, text="Archive", command=self._mark_project_done
        )
        self.project_delete_button = ttk.Button(
            self.project_footer, text="Delete", command=self._delete_project
        )
        self.project_done_button.pack(side=tk.LEFT, padx=(0, 6))
        self.project_delete_button.pack(side=tk.LEFT)

        self.entry_edit_save_button = ttk.Button(
            self.entry_footer, text="Edit", command=self._on_entry_edit_save
        )
        self.entry_cancel_button = ttk.Button(
            self.entry_footer, text="Cancel", command=self._cancel_entry_details
        )
        self.entry_delete_button = ttk.Button(
            self.entry_footer, text="Delete", command=self._delete_entry
        )
        self.entry_edit_save_button.pack(side=tk.LEFT, padx=(0, 6))
        self.entry_cancel_button.pack(side=tk.LEFT, padx=(0, 6))
        self.entry_delete_button.pack(side=tk.LEFT)

        self.activity_check = ttk.Checkbutton(
            self.stats_footer,
            text="Create Activity on stop",
            variable=self.create_activity_var,
            command=self._save_activity_pref,
        )
        self.activity_check.pack(side=tk.LEFT, padx=6, pady=2)

    def _on_details_tab_changed(self, _event: tk.Event | None) -> None:
        selected = self.details_notebook.select()
        if selected == str(self.project_tab):
            self.project_footer.grid()
            self.entry_footer.grid_remove()
            self.stats_footer.grid_remove()
            self.upcoming_footer.grid_remove()
        elif selected == str(self.entry_tab):
            self.project_footer.grid_remove()
            self.entry_footer.grid()
            self.stats_footer.grid_remove()
            self.upcoming_footer.grid_remove()
        elif selected == str(self.stats_tab):
            self.project_footer.grid_remove()
            self.entry_footer.grid_remove()
            self.stats_footer.grid()
            self.upcoming_footer.grid_remove()
        elif selected == str(self.in_progress_tab):
            self.project_footer.grid_remove()
            self.entry_footer.grid_remove()
            self.stats_footer.grid_remove()
            self.upcoming_footer.grid_remove()
            self.refresh_in_progress()
        elif selected == str(self.upcoming_tab):
            self.project_footer.grid_remove()
            self.entry_footer.grid_remove()
            self.stats_footer.grid_remove()
            self.upcoming_footer.grid()
            self.refresh_upcoming()
        else:
            self.project_footer.grid_remove()
            self.entry_footer.grid_remove()
            self.stats_footer.grid_remove()
            self.upcoming_footer.grid_remove()

    def _toggle_details_panel(self) -> None:
        if self.details_visible_var.get():
            if not self.details_notebook.winfo_ismapped():
                self.details_notebook.grid()
            if not self.action_bar.winfo_ismapped():
                self.action_bar.grid()
            self._on_details_tab_changed(None)
        else:
            if self.details_notebook.winfo_ismapped():
                self.details_notebook.grid_remove()
            if self.action_bar.winfo_ismapped():
                self.action_bar.grid_remove()
        self._schedule_resize()

    def _on_focus_toggle(self) -> None:
        self._apply_focus_mode()

    def _toggle_focus(self) -> None:
        self.focus_var.set(not self.focus_var.get())
        self._apply_focus_mode()

    def _apply_focus_mode(self) -> None:
        enable = bool(self.focus_var.get())
        self.after(80, lambda: self._apply_focus_mode_now(enable))

    def _apply_focus_mode_now(self, enable: bool) -> None:
        if enable == self._focus_active:
            return
        if not hasattr(self, "root_paned") or not hasattr(self, "paned"):
            return

        if enable:
            self._focus_root_sash = self._get_sashpos(self.root_paned, 0)
            self._focus_main_sashes = self._get_main_sash_positions()
            total_h = self.root_paned.winfo_height()
            if total_h > 0:
                try:
                    self.root_paned.sashpos(0, max(0, total_h - 2))
                except Exception:
                    logger.exception("Exception caught in GUI operation")
                    pass
            self._shrink_main_panes()
            self._focus_active = True
        else:
            if self._focus_root_sash is not None:
                try:
                    self.root_paned.sashpos(0, self._focus_root_sash)
                except Exception:
                    logger.exception("Exception caught in GUI operation")
                    pass
            if self._focus_main_sashes is not None:
                self._restore_main_sash_positions(self._focus_main_sashes)
            self._focus_active = False
        self._update_focus_button()

    def _get_sashpos(self, paned: ttk.PanedWindow, index: int) -> int | None:
        try:
            return int(paned.sashpos(index))
        except Exception:
            logger.exception("Exception caught in GUI operation")
            return None

    def _get_main_sash_positions(self) -> tuple[int, int] | None:
        try:
            panes = self.paned.panes()
            if len(panes) < 3:
                return None
            first = int(self.paned.sashpos(0))
            second = int(self.paned.sashpos(1))
            return (first, second)
        except Exception:
            logger.exception("Exception caught in GUI operation")
            return None

    def _restore_main_sash_positions(self, positions: tuple[int, int]) -> None:
        try:
            self.paned.sashpos(0, positions[0])
            self.paned.sashpos(1, positions[1])
        except Exception:
            logger.exception("Exception caught in GUI operation")
            pass

    def _shrink_main_panes(self) -> None:
        try:
            if len(self.paned.panes()) < 3:
                return
        except Exception:
            logger.exception("Exception caught in GUI operation")
            return
        total_w = self.paned.winfo_width()
        if total_w <= 1:
            return
        project_width = 160
        entry_width = 280
        min_editor = 320
        if total_w < project_width + entry_width + min_editor:
            available = max(0, total_w - min_editor)
            project_width = max(80, int(available * 0.4))
            entry_width = max(120, available - project_width)
        try:
            self.paned.sashpos(0, project_width)
            self.paned.sashpos(1, project_width + entry_width)
        except Exception:
            logger.exception("Exception caught in GUI operation")
            pass

    def _update_focus_button(self) -> None:
        if hasattr(self, "focus_button"):
            label = "Exit Focus" if self._focus_active else "Focus"
            self.focus_button.configure(text=label)

    def _bind_shortcuts(self) -> None:
        self.bind_all("<Control-s>", self._on_ctrl_s_save)
        self.bind_all("<Command-s>", self._on_cmd_s_save)
        self.bind_all("<Control-q>", self._on_quit_shortcut)
        self.bind_all("<Command-q>", self._on_quit_shortcut)
        self.bind_all("<Control-n>", self._on_new_project_shortcut)
        self.bind_all("<Command-n>", self._on_new_project_shortcut)
        self.bind_all("<Control-e>", self._on_new_entry_shortcut)
        self.bind_all("<Command-e>", self._on_new_entry_shortcut)
        self.bind_all("<F1>", self._on_help_shortcut)
        for sequence in ("<Delete>", "<BackSpace>", "<KP_Delete>"):
            self.bind_all(sequence, self._on_delete_key, add="+")
        self._bind_editor_zoom_shortcuts()

    def _on_ctrl_s_save(self, event: tk.Event) -> str | None:
        if not self._is_ctrl_s_event(event):
            return None
        if not self._is_main_window_event(event):
            return "break"
        if not self.current.entry_id:
            return "break"
        self._save_entry()
        return "break"

    def _on_cmd_s_save(self, event: tk.Event) -> str | None:
        if not self._is_main_window_event(event):
            return "break"
        if not self.current.entry_id:
            return "break"
        self._save_entry()
        return "break"

    def _on_quit_shortcut(self, event: tk.Event) -> str:
        if self._is_main_window_event(event):
            self._on_close()
        return "break"

    def _on_new_project_shortcut(self, event: tk.Event) -> str:
        if self._is_main_window_event(event):
            self._new_project()
        return "break"

    def _on_new_entry_shortcut(self, event: tk.Event) -> str:
        if self._is_main_window_event(event):
            self._new_entry()
        return "break"

    def _on_help_shortcut(self, event: tk.Event) -> str:
        self._show_keyboard_shortcuts()
        return "break"

    def _is_main_window_event(self, event: tk.Event) -> bool:
        try:
            return event.widget.winfo_toplevel() is self
        except Exception:
            logger.exception("Exception caught in GUI operation")
            return False

    def _is_ctrl_s_event(self, event: tk.Event) -> bool:
        char = getattr(event, "char", "") or ""
        keysym = getattr(event, "keysym", "") or ""
        state = getattr(event, "state", 0) or 0
        if char:
            return char == "\x13"
        if keysym and keysym.lower() != "s":
            return False
        return bool(state & 0x4)

    def _is_cmd_s_event(self, event: tk.Event) -> bool:
        char = getattr(event, "char", "") or ""
        keysym = getattr(event, "keysym", "") or ""
        state = getattr(event, "state", 0) or 0
        if char == "\x13":
            return True
        if keysym and keysym.lower() != "s":
            return False
        if char and char.lower() != "s":
            return False
        return bool(state)

    def _on_delete_key(self, _event: tk.Event) -> str | None:
        widget = self.focus_get()
        if widget is None:
            return None
        if isinstance(widget, (tk.Entry, ttk.Entry, tk.Text)):
            return None

        def is_child(target: tk.Widget, parent: tk.Widget) -> bool:
            current: tk.Widget | None = target
            while current is not None:
                if current is parent:
                    return True
                current = current.master
            return False

        if is_child(widget, self.entry_tree):
            if self.entry_tree.selection():
                self._delete_entry()
                return "break"
            return None
        if is_child(widget, self.project_tree):
            if self.project_tree.selection():
                self._delete_project()
                return "break"
            return None
        return None

    def _init_editor_font(self) -> None:
        base_font = tkfont.nametofont("TkFixedFont")
        default_size = int(base_font.cget("size"))
        if default_size < 0:
            default_size = abs(default_size)
        if default_size <= 0:
            default_size = 11
        self.editor_font_default_size = default_size
        size = self.gui_prefs.get("editor_font_size", default_size)
        try:
            size = int(size)
        except (TypeError, ValueError):
            size = default_size
        size = max(10, min(22, size))
        self.editor_font = base_font.copy()
        self.editor_font.configure(size=size)
        self.editor_text.configure(font=self.editor_font)

    def _set_editor_font_size(self, size: int) -> None:
        if not self.editor_font:
            return
        size = max(10, min(22, int(size)))
        current = int(self.editor_font.cget("size"))
        if current < 0:
            current = abs(current)
        if size == current:
            return
        self.editor_font.configure(size=size)
        self.gui_prefs["editor_font_size"] = size
        self._schedule_prefs_save()

    def _zoom_editor(self, delta: int) -> None:
        if not self.editor_font:
            return
        current = int(self.editor_font.cget("size"))
        if current < 0:
            current = abs(current)
        self._set_editor_font_size(current + delta)

    def _reset_editor_zoom(self) -> None:
        self._set_editor_font_size(self.editor_font_default_size)

    def _bind_editor_zoom_shortcuts(self) -> None:
        for sequence in (
            "<Control-plus>",
            "<Control-equal>",
            "<Control-KP_Add>",
            "<Control-KP_Equal>",
        ):
            self.bind_all(sequence, lambda _event: self._zoom_editor(1))
        for sequence in ("<Control-minus>", "<Control-KP_Subtract>"):
            self.bind_all(sequence, lambda _event: self._zoom_editor(-1))
        for sequence in ("<Control-0>", "<Control-KP_0>"):
            self.bind_all(sequence, lambda _event: self._reset_editor_zoom())
        for sequence in (
            "<Command-plus>",
            "<Command-equal>",
            "<Command-KP_Add>",
            "<Command-KP_Equal>",
        ):
            self.bind_all(sequence, lambda _event: self._zoom_editor(1))
        for sequence in ("<Command-minus>", "<Command-KP_Subtract>"):
            self.bind_all(sequence, lambda _event: self._zoom_editor(-1))
        for sequence in ("<Command-0>", "<Command-KP_0>"):
            self.bind_all(sequence, lambda _event: self._reset_editor_zoom())
        self.bind_all("<F9>", lambda _event: self._toggle_focus())

    def _set_status(self, message: str) -> None:
        self.status_var.set(message)

    def _set_save_state(self, state: str) -> None:
        labels = {
            "saved": "Saved ✓",
            "unsaved": "Unsaved •",
            "saving": "Saving…",
            "error": "Save failed",
            "none": "No entry",
        }
        self._save_state = state
        self.save_status_var.set(labels.get(state, state))

    def _update_save_button_state(self) -> None:
        if not self.current.entry_id:
            self._set_save_state("none")
            return
        if self._save_state == "saving":
            return
        if self._save_state == "error" and self.dirty:
            return
        if self.dirty:
            self._set_save_state("unsaved")
        else:
            self._set_save_state("saved")

    def _cancel_autosave(self) -> None:
        if self._autosave_after_id:
            self.after_cancel(self._autosave_after_id)
            self._autosave_after_id = None

    def _schedule_autosave(self) -> None:
        if not self.current.entry_id:
            return
        self._cancel_autosave()
        self._autosave_after_id = self.after(AUTOSAVE_DELAY_MS, self._autosave_entry)

    def _autosave_entry(self) -> None:
        self._autosave_after_id = None
        if self._autosave_in_progress:
            self._schedule_autosave()
            return
        if not self.dirty or not self.current.entry_id:
            return
        self._autosave_in_progress = True
        saved = self._write_entry_content(autosave=True, show_error=False)
        self._autosave_in_progress = False
        if not saved:
            return
        self._update_save_button_state()

    def _write_entry_content(self, *, autosave: bool, show_error: bool) -> bool:
        if not self.current.entry_id:
            if show_error:
                messagebox.showerror("No entry", "No entry selected to save.")
            return False
        self._set_save_state("saving")
        content = self.editor_text.get("1.0", "end-1c")
        try:
            path = self.service.update_entry_content(self.current.entry_id, content)
        except (OSError, ValueError) as exc:
            if show_error:
                messagebox.showerror("Save failed", str(exc))
            else:
                self._set_status(f"Autosave failed: {exc}")
            self._set_save_state("error")
            return False
        self.current_entry_path = path
        self.editor_text.edit_modified(False)
        self.dirty = False
        self._set_save_state("saved")
        self._set_status("Entry autosaved" if autosave else "Entry saved")
        return True

    def _flush_autosave_now(self) -> bool:
        if not self.dirty or not self.current.entry_id:
            return True
        self._cancel_autosave()
        return self._write_entry_content(autosave=True, show_error=False)

    def _on_window_configure(self, event: tk.Event) -> None:
        if event.widget is self:
            self._schedule_resize()
            self._schedule_toolbar_layout()

    def _schedule_resize(self) -> None:
        if self._resize_after_id:
            self.after_cancel(self._resize_after_id)
        self._resize_after_id = self.after(120, self._resize_columns)

    def _resize_columns(self) -> None:
        self._resize_after_id = None
        self._resize_project_columns()
        self._resize_entry_columns()
        self._resize_task_columns()

    def _resize_project_columns(self) -> None:
        tree = self.project_tree
        total_width = tree.winfo_width()
        if total_width <= 1:
            return
        scrollbar_width = 18
        columns = set(tree["displaycolumns"])
        fixed = 0
        if "people" in columns:
            tree.column("people", width=160, stretch=False, anchor=tk.W)
            fixed += 160
        if "tasks_open" in columns:
            tree.column("tasks_open", width=60, stretch=False, anchor=tk.CENTER)
            fixed += 60
        if "status" in columns:
            tree.column("status", width=36, stretch=False, anchor=tk.CENTER)
            fixed += 36
        available = max(0, total_width - fixed - scrollbar_width)
        min_name = 180
        if "name" in columns:
            tree.column("name", width=max(min_name, available), stretch=True, anchor=tk.W)

    def _resize_entry_columns(self) -> None:
        tree = self.entry_tree
        total_width = tree.winfo_width()
        if total_width <= 1:
            return
        scrollbar_width = 18
        columns = set(tree["displaycolumns"])
        fixed = 0
        fixed_defs = {
            "date": 100,
            "time": 110,
            "type": 100,
            "context": 80,
            "done": 50,
        }
        for col, width in fixed_defs.items():
            if col not in columns:
                continue
            tree.column(col, width=width, stretch=False, anchor=tk.W)
            fixed += width
        if "tags" in columns:
            tags_width = 140
            tree.column("tags", width=tags_width, stretch=True, anchor=tk.W)
            fixed += tags_width
        available = max(0, total_width - fixed - scrollbar_width)
        min_title = 220
        min_people = 120
        if "title" in columns and "people" in columns:
            title_width = max(min_title, int(available * 0.7))
            people_width = max(min_people, available - title_width)
            if title_width + people_width > available:
                people_width = max(min_people, available - title_width)
                title_width = max(min_title, available - people_width)
            tree.column("title", width=title_width, stretch=True, anchor=tk.W)
            tree.column("people", width=people_width, stretch=True, anchor=tk.W)
        elif "title" in columns:
            tree.column("title", width=max(min_title, available), stretch=True, anchor=tk.W)
        elif "people" in columns:
            tree.column("people", width=max(min_people, available), stretch=True, anchor=tk.W)

    def _resize_task_columns(self) -> None:
        if not hasattr(self, "task_tree"):
            return
        tree = self.task_tree
        total_width = tree.winfo_width()
        if total_width <= 1:
            return
        scrollbar_width = 18
        fixed = 0
        fixed_defs = {
            "done": 50,
            "due": 100,
            "source": 90,
        }
        for col, width in fixed_defs.items():
            anchor = tk.CENTER if col == "done" else tk.W
            tree.column(col, width=width, stretch=False, anchor=anchor)
            fixed += width
        available = max(0, total_width - fixed - scrollbar_width)
        min_title = 200
        min_tags = 120
        title_width = max(min_title, int(available * 0.6))
        tags_width = max(min_tags, available - title_width)
        if title_width + tags_width > available:
            tags_width = max(min_tags, available - title_width)
            title_width = max(min_title, available - tags_width)
        tree.column("title", width=title_width, stretch=True, anchor=tk.W)
        tree.column("tags", width=tags_width, stretch=True, anchor=tk.W)

    def _format_duration(self, seconds: int) -> str:
        total = max(0, int(seconds))
        hours = total // 3600
        minutes = (total % 3600) // 60
        secs = total % 60
        return f"{hours:02d}:{minutes:02d}:{secs:02d}"

    def _parse_manual_duration(self, value: str) -> int:
        cleaned = (value or "").strip()
        if not cleaned:
            raise ValueError("Duration is required")
        if ":" in cleaned:
            parts = cleaned.split(":")
            if len(parts) != 2:
                raise ValueError("Duration must be HH:MM")
            try:
                hours = int(parts[0])
                minutes = int(parts[1])
            except ValueError as exc:
                raise ValueError("Duration must be HH:MM") from exc
            if hours < 0 or minutes < 0 or minutes >= 60:
                raise ValueError("Duration must be HH:MM")
            return hours * 3600 + minutes * 60
        if cleaned.isdigit():
            minutes = int(cleaned)
            return minutes * 60
        raise ValueError("Duration must be HH:MM or minutes")

    def _load_gui_prefs(self) -> dict[str, object]:
        try:
            if self.prefs_path.exists():
                return io_utils.read_json(self.prefs_path, default={})
            if self.legacy_prefs_path.exists():
                return io_utils.read_json(self.legacy_prefs_path, default={})
            return {}
        except Exception:
            logger.exception("Failed to load GUI prefs from %s", self.prefs_path)
            return {}

    def _save_gui_prefs(self) -> None:
        try:
            io_utils.safe_write_json(self.prefs_path, self.gui_prefs)
        except OSError:
            pass

    def _validate_project_displaycolumns(self, value: object) -> list[str]:
        if not isinstance(value, list):
            return list(DEFAULT_PROJECT_DISPLAYCOLUMNS)
        cleaned: list[str] = []
        for item in value:
            if item == "today":
                item = "people"
            if item in AVAILABLE_PROJECT_COLUMNS and item not in cleaned:
                cleaned.append(item)
        if not cleaned:
            return list(DEFAULT_PROJECT_DISPLAYCOLUMNS)
        return cleaned

    def _validate_entry_displaycolumns(self, value: object) -> list[str]:
        if not isinstance(value, list):
            return list(DEFAULT_ENTRY_DISPLAYCOLUMNS)
        cleaned: list[str] = []
        for item in value:
            if item in AVAILABLE_ENTRY_COLUMNS and item not in cleaned:
                cleaned.append(item)
        if not cleaned:
            return list(DEFAULT_ENTRY_DISPLAYCOLUMNS)
        return cleaned

    def _apply_project_columns(self, displaycolumns: list[str]) -> None:
        self.project_tree["columns"] = tuple(AVAILABLE_PROJECT_COLUMNS)
        for col in AVAILABLE_PROJECT_COLUMNS:
            col_def = self.project_column_defs[col]
            self.project_tree.heading(
                col,
                text=col_def["header"],
                command=lambda c=col: self._toggle_project_sort(c),
            )
            self.project_tree.column(
                col,
                width=col_def["width"],
                stretch=col_def["stretch"],
                anchor=col_def["anchor"],
            )
        cols = [col for col in displaycolumns if col in AVAILABLE_PROJECT_COLUMNS]
        if not cols:
            cols = list(DEFAULT_PROJECT_DISPLAYCOLUMNS)
        self.project_tree["displaycolumns"] = tuple(cols)
        self._update_project_sort_headers()

    def _apply_entry_columns(self, displaycolumns: list[str]) -> None:
        cols = list(displaycolumns) if displaycolumns else list(DEFAULT_ENTRY_DISPLAYCOLUMNS)
        self.entry_tree["displaycolumns"] = tuple(cols)

    def _toggle_project_sort(self, col_id: str) -> None:
        if col_id not in self.project_column_defs:
            return
        if self.project_sort_col != col_id:
            self.project_sort_col = col_id
            self.project_sort_dir = "asc"
        elif self.project_sort_dir == "asc":
            self.project_sort_dir = "desc"
        else:
            self.project_sort_col = None
            self.project_sort_dir = None
        self.gui_prefs["project_sort_col"] = self.project_sort_col
        self.gui_prefs["project_sort_dir"] = self.project_sort_dir
        self._schedule_prefs_save()
        self.refresh_projects()

    def _update_project_sort_headers(self) -> None:
        columns = list(self.project_tree["columns"])
        active_col = self.project_sort_col if self.project_sort_col in columns else None
        active_dir = self.project_sort_dir if active_col else None
        arrow = "↓" if active_dir == "desc" else "↑"
        for col in columns:
            col_def = self.project_column_defs[col]
            label = col_def["header"]
            if col == active_col:
                label = f"{label} {arrow}"
            self.project_tree.heading(col, text=label)

    def _edit_project_columns(self) -> None:
        dialog = tk.Toplevel(self)
        dialog.title("Project Columns")
        dialog.transient(self)
        dialog.grab_set()
        dialog.resizable(False, False)

        displaycolumns = list(self.project_displaycolumns)
        order: list[str] = []
        listbox = tk.Listbox(
            dialog, height=len(AVAILABLE_PROJECT_COLUMNS), width=24
        )
        listbox.grid(row=0, column=0, rowspan=5, padx=8, pady=8)

        def build_order() -> list[str]:
            merged = list(displaycolumns)
            for col in AVAILABLE_PROJECT_COLUMNS:
                if col not in merged:
                    merged.append(col)
            return merged

        def refresh_list(selected: str | None = None) -> None:
            listbox.delete(0, tk.END)
            order[:] = build_order()
            for col in order:
                label = self.project_column_defs[col]["label"]
                marker = "[x]" if col in displaycolumns else "[ ]"
                listbox.insert(tk.END, f"{marker} {label}")
            if selected and selected in order:
                listbox.selection_set(order.index(selected))
            elif order:
                listbox.selection_set(0)

        def move(delta: int) -> None:
            selection = listbox.curselection()
            if not selection:
                return
            col = order[selection[0]]
            if col not in displaycolumns:
                return
            index = displaycolumns.index(col)
            new_index = index + delta
            if new_index < 0 or new_index >= len(displaycolumns):
                return
            displaycolumns[index], displaycolumns[new_index] = (
                displaycolumns[new_index],
                displaycolumns[index],
            )
            refresh_list(selected=col)

        def toggle() -> None:
            selection = listbox.curselection()
            if not selection:
                return
            col = order[selection[0]]
            if col in displaycolumns:
                if len(displaycolumns) == 1:
                    messagebox.showinfo(
                        "Keep one column",
                        "At least one column must remain visible.",
                    )
                    return
                displaycolumns.remove(col)
            else:
                displaycolumns.append(col)
            refresh_list(selected=col)

        def reset() -> None:
            displaycolumns[:] = list(DEFAULT_PROJECT_DISPLAYCOLUMNS)
            refresh_list()

        def apply_changes() -> None:
            self.project_displaycolumns = list(displaycolumns)
            self.gui_prefs["project_displaycolumns"] = list(displaycolumns)
            self._save_gui_prefs()
            self._apply_project_columns(self.project_displaycolumns)
            self.refresh_projects()
            dialog.destroy()

        refresh_list()

        ttk.Button(dialog, text="Up", command=lambda: move(-1)).grid(
            row=0, column=1, padx=6, pady=4
        )
        ttk.Button(dialog, text="Down", command=lambda: move(1)).grid(
            row=1, column=1, padx=6, pady=4
        )
        ttk.Button(dialog, text="Toggle", command=toggle).grid(
            row=2, column=1, padx=6, pady=4
        )
        ttk.Button(dialog, text="Reset", command=reset).grid(
            row=3, column=1, padx=6, pady=4
        )

        button_frame = ttk.Frame(dialog)
        button_frame.grid(row=4, column=1, padx=6, pady=4, sticky="e")
        ttk.Button(button_frame, text="OK", command=apply_changes).pack(
            side=tk.LEFT, padx=(0, 6)
        )
        ttk.Button(button_frame, text="Cancel", command=dialog.destroy).pack(
            side=tk.LEFT
        )

    def _edit_entry_columns(self) -> None:
        dialog = tk.Toplevel(self)
        dialog.title("Arrange Entry Columns")
        dialog.transient(self)
        dialog.grab_set()
        dialog.resizable(False, False)

        displaycolumns = list(self.entry_displaycolumns)
        order: list[str] = []
        listbox = tk.Listbox(
            dialog, height=len(AVAILABLE_ENTRY_COLUMNS), width=24
        )
        listbox.grid(row=0, column=0, rowspan=5, padx=8, pady=8)

        def build_order() -> list[str]:
            merged = list(displaycolumns)
            for col in AVAILABLE_ENTRY_COLUMNS:
                if col not in merged:
                    merged.append(col)
            return merged

        def refresh_list(selected: str | None = None) -> None:
            listbox.delete(0, tk.END)
            order[:] = build_order()
            for col in order:
                label = ENTRY_COLUMN_LABELS.get(col, col)
                marker = "[x]" if col in displaycolumns else "[ ]"
                listbox.insert(tk.END, f"{marker} {label}")
            if selected and selected in order:
                listbox.selection_set(order.index(selected))
            elif order:
                listbox.selection_set(0)

        def move(delta: int) -> None:
            selection = listbox.curselection()
            if not selection:
                return
            col = order[selection[0]]
            if col not in displaycolumns:
                return
            index = displaycolumns.index(col)
            new_index = index + delta
            if new_index < 0 or new_index >= len(displaycolumns):
                return
            displaycolumns[index], displaycolumns[new_index] = (
                displaycolumns[new_index],
                displaycolumns[index],
            )
            refresh_list(selected=col)

        def toggle() -> None:
            selection = listbox.curselection()
            if not selection:
                return
            col = order[selection[0]]
            if col in displaycolumns:
                if len(displaycolumns) == 1:
                    messagebox.showinfo(
                        "Keep one column",
                        "At least one column must remain visible.",
                    )
                    return
                displaycolumns.remove(col)
            else:
                displaycolumns.append(col)
            refresh_list(selected=col)

        def reset() -> None:
            displaycolumns[:] = list(DEFAULT_ENTRY_DISPLAYCOLUMNS)
            refresh_list()

        def apply_changes() -> None:
            self.entry_displaycolumns = list(displaycolumns)
            self.gui_prefs["entry_displaycolumns"] = list(displaycolumns)
            self._save_gui_prefs()
            self._apply_entry_columns(self.entry_displaycolumns)
            self.refresh_entries(select_entry_id=self.current.entry_id)
            dialog.destroy()

        refresh_list()

        ttk.Button(dialog, text="Up", command=lambda: move(-1)).grid(
            row=0, column=1, padx=6, pady=4
        )
        ttk.Button(dialog, text="Down", command=lambda: move(1)).grid(
            row=1, column=1, padx=6, pady=4
        )
        ttk.Button(dialog, text="Toggle", command=toggle).grid(
            row=2, column=1, padx=6, pady=4
        )
        ttk.Button(dialog, text="Reset", command=reset).grid(
            row=3, column=1, padx=6, pady=4
        )

        button_frame = ttk.Frame(dialog)
        button_frame.grid(row=4, column=1, padx=6, pady=4, sticky="e")
        ttk.Button(button_frame, text="OK", command=apply_changes).pack(
            side=tk.LEFT, padx=(0, 6)
        )
        ttk.Button(button_frame, text="Cancel", command=dialog.destroy).pack(
            side=tk.LEFT
        )

    def _save_activity_pref(self) -> None:
        self.gui_prefs["create_activity_on_stop"] = bool(self.create_activity_var.get())
        self._schedule_prefs_save()

    def _schedule_prefs_save(self) -> None:
        if self._prefs_after_id:
            self.after_cancel(self._prefs_after_id)
        self._prefs_after_id = self.after(250, self._save_gui_prefs_debounced)

    def _save_gui_prefs_debounced(self) -> None:
        self._prefs_after_id = None
        self._save_gui_prefs()

    def _on_project_search_change(self, *_args: object) -> None:
        self.gui_prefs["search_query"] = self.entry_search_var.get()
        self._schedule_prefs_save()

    def _on_project_filter_change(self) -> None:
        self.gui_prefs["show_archived"] = bool(self.show_archived_var.get())
        self._schedule_prefs_save()
        self.refresh_projects()

    def _project_matches_query(self, project: Project, query: str) -> bool:
        if not query:
            return True
        haystack = " ".join(
            [
                project.name,
                project.description or "",
                project.person or "",
                project.group or "",
                " ".join(project.tags),
            ]
        ).lower()
        return query in haystack

    def _on_project_detail_modified(self, *_args: object) -> None:
        if self._project_detail_updating or not self.project_editing:
            return
        self.project_dirty = True

    def _on_project_desc_modified(self, _event: tk.Event) -> None:
        if self._project_detail_updating or not self.project_editing:
            self.project_desc_text.edit_modified(False)
            return
        if self.project_desc_text.edit_modified():
            self.project_dirty = True
            self.project_desc_text.edit_modified(False)

    def _on_project_people_modified(self, _event: tk.Event) -> None:
        if self._project_detail_updating or not self.project_editing:
            self.project_people_text.edit_modified(False)
            return
        if self.project_people_text.edit_modified():
            self.project_dirty = True
            self.project_people_text.edit_modified(False)

    def _on_project_links_modified(self, _event: tk.Event) -> None:
        if self._project_detail_updating or not self.project_editing:
            self.project_links_text.edit_modified(False)
            return
        if self.project_links_text.edit_modified():
            self.project_dirty = True
            self.project_links_text.edit_modified(False)

    def _get_project_links(self) -> list[str]:
        raw = self.project_links_text.get("1.0", tk.END)
        return [line.strip() for line in raw.splitlines() if line.strip()]

    def _get_people_text_value(self, widget: tk.Text) -> str | None:
        raw = widget.get("1.0", "end-1c")
        people = split_people(raw)
        value = join_people_storage(people)
        return value or None

    def _get_selected_project_link(self) -> str | None:
        try:
            selection = self.project_links_text.get(tk.SEL_FIRST, tk.SEL_LAST)
        except tk.TclError:
            return None
        lines = [line.strip() for line in selection.splitlines() if line.strip()]
        return lines[0] if lines else None

    def _open_project_link(self) -> None:
        if not self.current.project_id:
            self._set_status("No project selected")
            return
        link = self._get_selected_project_link()
        if not link:
            links = self._get_project_links()
            link = links[0] if links else None
        if not link:
            self._set_status("No links to open")
            return
        try:
            opened = webbrowser.open(link)
        except Exception:
            logger.exception("Exception caught in GUI operation")
            opened = False
        if not opened:
            self._set_status("Failed to open link")
            return
        self._set_status("Opened link")

    def _copy_project_link(self) -> None:
        if not self.current.project_id:
            self._set_status("No project selected")
            return
        link = self._get_selected_project_link()
        if not link:
            self._set_status("Select a link to copy")
            return
        try:
            self.clipboard_clear()
            self.clipboard_append(link)
        except Exception:
            logger.exception("Exception caught in GUI operation")
            self._set_status("Failed to copy link")
            return
        self._set_status("Link copied")

    def _set_project_fields_state(self, enabled: bool) -> None:
        state = "normal" if enabled else "disabled"
        for widget in (
            self.project_name_entry,
            self.project_group_entry,
            self.project_tags_entry,
        ):
            widget.configure(state=state)
        self.project_desc_text.configure(state=state)
        self.project_people_text.configure(state=state)
        self.project_links_text.configure(state=state)
        if enabled:
            self.project_status_check.state(["!disabled"])
        else:
            self.project_status_check.state(["disabled"])

    def _set_project_editing(self, editing: bool) -> None:
        self.project_editing = editing
        self.project_dirty = False
        self._set_project_fields_state(editing)
        if editing:
            self.project_edit_save_button.configure(text="Save")
            self.project_edit_save_button.state(["!disabled"])
            self.project_cancel_button.state(["!disabled"])
            if not self.project_cancel_button.winfo_ismapped():
                self.project_cancel_button.pack(side=tk.LEFT, padx=(0, 12))
            self.project_done_button.state(["disabled"])
            self.project_delete_button.state(["disabled"])
        else:
            self.project_edit_save_button.configure(text="Edit")
            self.project_edit_save_button.state(["!disabled"])
            self.project_cancel_button.state(["disabled"])
            if self.project_cancel_button.winfo_ismapped():
                self.project_cancel_button.pack_forget()
            self.project_done_button.state(["!disabled"])
            self.project_delete_button.state(["!disabled"])

    def _load_project_details(self, project: Project | None) -> None:
        self._project_detail_updating = True
        try:
            if not project:
                self.project_detail_snapshot = None
                self.project_name_var.set("")
                self.project_group_var.set("")
                self.project_tags_var.set("")
                self.project_status_var.set(False)
                self.project_desc_text.configure(state="normal")
                self.project_desc_text.delete("1.0", tk.END)
                self.project_desc_text.edit_modified(False)
                self.project_desc_text.configure(state="disabled")
                self.project_people_text.configure(state="normal")
                self.project_people_text.delete("1.0", tk.END)
                self.project_people_text.edit_modified(False)
                self.project_people_text.configure(state="disabled")
                self.project_links_text.configure(state="normal")
                self.project_links_text.delete("1.0", tk.END)
                self.project_links_text.edit_modified(False)
                self.project_links_text.configure(state="disabled")
                self.project_links_open_button.state(["disabled"])
                self.project_links_copy_button.state(["disabled"])
                self.project_today_var.set("-")
                self.project_entry_count_var.set("-")
                self._set_project_editing(False)
                return
            self.project_detail_snapshot = project
            self.project_name_var.set(project.name)
            self.project_group_var.set(project.group or "")
            self.project_tags_var.set(", ".join(project.tags))
            self.project_status_var.set(project.status == "archived")
            self.project_desc_text.configure(state="normal")
            self.project_desc_text.delete("1.0", tk.END)
            if project.description:
                self.project_desc_text.insert("1.0", project.description)
            self.project_desc_text.edit_modified(False)
            self.project_people_text.configure(state="normal")
            self.project_people_text.delete("1.0", tk.END)
            if project.person:
                people_text = join_people_storage(split_people(project.person))
                if people_text:
                    self.project_people_text.insert("1.0", people_text)
            self.project_people_text.edit_modified(False)
            self.project_links_text.configure(state="normal")
            self.project_links_text.delete("1.0", tk.END)
            if project.links:
                self.project_links_text.insert("1.0", "\n".join(project.links))
            self.project_links_text.edit_modified(False)
            self.project_links_open_button.state(["!disabled"])
            self.project_links_copy_button.state(["!disabled"])
        finally:
            self._project_detail_updating = False
        self._set_project_editing(False)
        self._update_project_details_stats()

    def _edit_project_details(self) -> None:
        if not self.current.project_id:
            messagebox.showerror("No project", "Select a project first.")
            return
        self._set_project_editing(True)
        self.project_name_entry.focus_set()

    def _on_project_edit_save(self) -> None:
        if not self.project_editing:
            self._edit_project_details()
            return
        if self._save_project_details():
            self._set_project_editing(False)

    def _save_project_details(self) -> bool:
        if not self.current.project_id:
            messagebox.showerror("No project", "Select a project first.")
            return False
        name = self.project_name_var.get().strip()
        if not name:
            messagebox.showerror("Validation", "Project name is required")
            return False
        desc = self.project_desc_text.get("1.0", tk.END).strip() or None
        tags = strings.parse_tags(self.project_tags_var.get())
        status = "archived" if self.project_status_var.get() else "active"
        person = self._get_people_text_value(self.project_people_text)
        group = self.project_group_var.get().strip() or None
        links = self.project_links_text.get("1.0", tk.END)
        try:
            updated = self.service.update_project(
                self.current.project_id,
                name=name,
                description=desc,
                tags=tags,
                person=person,
                group=group,
                status=status,
                links=links,
            )
        except ValueError as exc:
            messagebox.showerror("Error", str(exc))
            return False
        self.refresh_projects()
        self._set_status("Project saved")
        return True

    def _mark_project_done(self) -> None:
        if not self.current.project_id:
            messagebox.showerror("No project", "Select a project first.")
            return
        if self.project_editing and self.project_dirty:
            if not self._confirm_project_dirty():
                return
        name = self.project_name_var.get().strip()
        if not name:
            messagebox.showerror("Validation", "Project name is required")
            return
        desc = self.project_desc_text.get("1.0", tk.END).strip() or None
        tags = strings.parse_tags(self.project_tags_var.get())
        person = self._get_people_text_value(self.project_people_text)
        group = self.project_group_var.get().strip() or None
        links = self.project_links_text.get("1.0", tk.END)
        try:
            self.service.update_project(
                self.current.project_id,
                name=name,
                description=desc,
                tags=tags,
                person=person,
                group=group,
                status="archived",
                links=links,
            )
        except ValueError as exc:
            messagebox.showerror("Error", str(exc))
            return
        self.project_status_var.set(True)
        self.refresh_projects()
        self._set_status("Project archived")

    def _delete_project(self) -> None:
        """Supprime définitivement un projet avec confirmation stricte."""
        if not self.current.project_id:
            messagebox.showerror("No project", "Select a project first.")
            return
    
        project = self.projects_by_id.get(self.current.project_id)
        if not project:
            messagebox.showerror("Error", "Project not found.")
            return
    
        # Compter les entrées et tâches pour informer l'utilisateur
        entry_count = len([e for e in self.entries_by_id.values() 
                           if e.project_id == self.current.project_id])
        task_count = len([t for t in self.service.storage.read_tasks() 
                             if t.project_id == self.current.project_id])
    
        # Confirmation : informer de ce qui sera supprimé
        warning_message = (
            f"Delete project '{project.name}'?\n\n"
            f"This will PERMANENTLY delete:\n"
            f"- The project\n"
            f"- {entry_count} entries\n"
            f"- {task_count} tasks\n\n"
            f"This action CANNOT be undone!"
        )
        if not messagebox.askyesno("Delete Project", warning_message):
            return
    
        # Effectuer la suppression
        try:
            self.service.delete_project(self.current.project_id)
        except ValueError as exc:
            messagebox.showerror("Error", str(exc))
            return
    
        # Réinitialiser la sélection et rafraîchir
        self.current.project_id = None
        self.current.entry_id = None
        self.current_entry_path = None
        self._clear_editor()
        self.refresh_projects()
        self._set_status(f"Project '{project.name}' deleted permanently")
        messagebox.showinfo("Deleted", f"Project '{project.name}' has been deleted.")    

    def _cancel_project_details(self) -> None:
        if self.project_detail_snapshot:
            self._load_project_details(self.project_detail_snapshot)
        else:
            self._load_project_details(None)

    def _confirm_project_dirty(self) -> bool:
        if not self.project_dirty:
            return True
        result = messagebox.askyesnocancel(
            "Save changes?", "Save changes to the current project?"
        )
        if result is None:
            return False
        if result:
            return self._save_project_details()
        if self.project_detail_snapshot:
            self._load_project_details(self.project_detail_snapshot)
        else:
            self._load_project_details(None)
        return True

    def _update_project_details_stats(self) -> None:
        if not self.current.project_id:
            self.project_today_var.set("-")
            self.project_entry_count_var.set("-")
            self.stats_selected_project_var.set("-")
            return
        totals = self.service.time_today()
        seconds = totals.get(self.current.project_id, 0)
        self.project_today_var.set(self._format_duration(seconds))
        entry_count = len(self.entries_by_id)
        self.project_entry_count_var.set(str(entry_count))
        project = self.projects_by_id.get(self.current.project_id)
        self.stats_selected_project_var.set(project.name if project else "-")

    # Plan: add editor key bindings for Markdown lists, indentation, and checkbox toggles.
    def _editor_in_code_fence(self, line_start: str) -> bool:
        content = self.editor_text.get("1.0", line_start)
        if not content:
            return False
        fences = 0
        for line in content.splitlines():
            if line.strip().startswith("```"):
                fences += 1
        return fences % 2 == 1

    def _editor_on_return(self, _event: tk.Event) -> str | None:
        if self.editor_text.tag_ranges("sel"):
            return None
        insert = self.editor_text.index("insert")
        line_start = self.editor_text.index("insert linestart")
        line_end = self.editor_text.index("insert lineend")
        if insert != line_end:
            return None
        if self._editor_in_code_fence(line_start):
            return None
        line = self.editor_text.get(line_start, line_end)

        checklist = re.match(r"^([ \t]*)([-*+]) \[(?: |x|X)\] (.*)$", line)
        if checklist:
            indent, marker, rest = checklist.groups()
            prefix = f"{indent}{marker} [ ] "
            if not rest.strip():
                self.editor_text.delete(line_start, f"{line_start}+{len(prefix)}c")
                self.editor_text.mark_set("insert", line_end)
                self.editor_text.insert("insert", "\n")
                return "break"
            self.editor_text.insert("insert", f"\n{prefix}")
            return "break"

        ordered = re.match(r"^([ \t]*)(\d+)\. (.*)$", line)
        if ordered:
            indent, number, rest = ordered.groups()
            prefix_len = len(indent) + len(number) + 2
            if not rest.strip():
                self.editor_text.delete(line_start, f"{line_start}+{prefix_len}c")
                self.editor_text.mark_set("insert", line_end)
                self.editor_text.insert("insert", "\n")
                return "break"
            next_number = int(number) + 1
            self.editor_text.insert("insert", f"\n{indent}{next_number}. ")
            return "break"

        bullet = re.match(r"^([ \t]*)([-*+]) (.*)$", line)
        if bullet:
            indent, marker, rest = bullet.groups()
            prefix_len = len(indent) + 2
            if not rest.strip():
                self.editor_text.delete(line_start, f"{line_start}+{prefix_len}c")
                self.editor_text.mark_set("insert", line_end)
                self.editor_text.insert("insert", "\n")
                return "break"
            self.editor_text.insert("insert", f"\n{indent}{marker} ")
            return "break"

        return None

    def _editor_on_tab(self, _event: tk.Event) -> str:
        sel = self.editor_text.tag_ranges("sel")
        if sel:
            start = self.editor_text.index("sel.first")
            end = self.editor_text.index("sel.last")
        else:
            start = self.editor_text.index("insert linestart")
            end = self.editor_text.index("insert lineend")
        start_line = int(start.split(".")[0])
        end_line = int(end.split(".")[0])
        if sel:
            end_col = int(end.split(".")[1])
            if end_col == 0 and end_line > start_line:
                end_line -= 1
        for line in range(start_line, end_line + 1):
            self.editor_text.insert(f"{line}.0", "  ")
        if sel:
            self.editor_text.tag_remove("sel", "1.0", "end")
            self.editor_text.tag_add("sel", f"{start_line}.0", f"{end_line}.end")
        return "break"

    def _editor_on_shift_tab(self, _event: tk.Event) -> str:
        sel = self.editor_text.tag_ranges("sel")
        if sel:
            start = self.editor_text.index("sel.first")
            end = self.editor_text.index("sel.last")
        else:
            start = self.editor_text.index("insert linestart")
            end = self.editor_text.index("insert lineend")
        start_line = int(start.split(".")[0])
        end_line = int(end.split(".")[0])
        if sel:
            end_col = int(end.split(".")[1])
            if end_col == 0 and end_line > start_line:
                end_line -= 1
        for line in range(start_line, end_line + 1):
            first = self.editor_text.get(f"{line}.0", f"{line}.1")
            if first == "\t":
                self.editor_text.delete(f"{line}.0", f"{line}.1")
                continue
            if first == " ":
                second = self.editor_text.get(f"{line}.1", f"{line}.2")
                if second == " ":
                    self.editor_text.delete(f"{line}.0", f"{line}.2")
                else:
                    self.editor_text.delete(f"{line}.0", f"{line}.1")
        if sel:
            self.editor_text.tag_remove("sel", "1.0", "end")
            self.editor_text.tag_add("sel", f"{start_line}.0", f"{end_line}.end")
        return "break"

    def _editor_toggle_checkbox(self, _event: tk.Event) -> str | None:
        line_start = self.editor_text.index("insert linestart")
        line_end = self.editor_text.index("insert lineend")
        line = self.editor_text.get(line_start, line_end)
        match = re.search(r"- \[( |x|X)\] ", line)
        if not match:
            return None
        start_offset = match.start()
        value = match.group(1)
        new_value = "x" if value == " " else " "
        marker_start = f"{line_start}+{start_offset + 3}c"
        marker_end = f"{line_start}+{start_offset + 4}c"
        self.editor_text.delete(marker_start, marker_end)
        self.editor_text.insert(marker_start, new_value)
        return "break"

    def _editor_insert_checklist_item(self) -> None:
        text = self.editor_text
        sel = text.tag_ranges("sel")
        if sel:
            start = text.index("sel.first")
            end = text.index("sel.last")
            start_line = int(start.split(".")[0])
            end_line = int(end.split(".")[0])
            end_col = int(end.split(".")[1])
            if end_col == 0 and end_line > start_line:
                end_line -= 1
            for line_num in range(start_line, end_line + 1):
                line_start = f"{line_num}.0"
                line_end = f"{line_num}.end"
                line_text = text.get(line_start, line_end)
                indent_match = re.match(r"^([ \t]*)", line_text)
                indent = indent_match.group(1) if indent_match else ""
                if line_text.strip():
                    insert_at = f"{line_start}+{len(indent)}c"
                    text.insert(insert_at, "- [ ] ")
                else:
                    text.delete(line_start, line_end)
                    text.insert(line_start, f"{indent}- [ ] ")
            return

        insert = text.index("insert")
        line_start = text.index("insert linestart")
        line_end = text.index("insert lineend")
        line_text = text.get(line_start, line_end)
        indent_match = re.match(r"^([ \t]*)", line_text)
        indent = indent_match.group(1) if indent_match else ""

        if insert != line_end:
            text.insert(insert, "\n")
            line_start = text.index("insert linestart")
            line_end = text.index("insert lineend")
            line_text = text.get(line_start, line_end)
            current_indent_match = re.match(r"^([ \t]*)", line_text)
            current_indent = current_indent_match.group(1) if current_indent_match else ""
            if current_indent != indent:
                text.delete(line_start, f"{line_start}+{len(current_indent)}c")
                text.insert(line_start, indent)

        insert_at = f"{line_start}+{len(indent)}c"
        text.insert(insert_at, "- [ ] ")
        text.mark_set("insert", f"{insert_at}+{len('- [ ] ')}c")

    def _editor_create_tasks_from_selection(self) -> None:
        if not self.editor_text.tag_ranges("sel"):
            messagebox.showinfo("No selection", "Select one or more lines first.")
            return
        entry = self._get_selected_entry_for_export()
        if not entry:
            messagebox.showerror("No entry", "Select an entry first.")
            return
        selected_text = self.editor_text.get("sel.first", "sel.last")
        titles = self._extract_task_titles_from_text(selected_text)
        if not titles:
            messagebox.showinfo(
                "No tasks found", "No task titles were found in the selection."
            )
            return
        self._open_task_bulk_create_dialog(entry, titles)

    def _on_text_modified(self, _event: tk.Event) -> None:
        if self._loading_entry:
            self.editor_text.edit_modified(False)
            return
        if self.editor_text.edit_modified():
            self.editor_text.edit_modified(False)
            if not self.current.entry_id:
                return
            self.dirty = True
            self._set_status("Unsaved changes")
            self._set_save_state("unsaved")
            self._schedule_autosave()

    def _confirm_save_if_dirty(self) -> bool:
        if not self.dirty:
            return True
        if self._flush_autosave_now():
            return True
        result = messagebox.askyesnocancel(
            "Save changes?", "Save changes to the current entry?"
        )
        if result is None:
            return False
        if result:
            return self._save_entry()
        return True

    def _on_project_select(self, _event: tk.Event) -> None:
        if self._suppress_project_select:
            return
        selection = self.project_tree.selection()
        if not selection:
            return
        project_id = selection[0]
        if project_id == self.current.project_id:
            return
        if not self._confirm_project_dirty():
            self._restore_project_selection()
            return
        if not self._confirm_entry_detail_dirty():
            self._restore_project_selection()
            return
        if not self._confirm_save_if_dirty():
            self._restore_project_selection()
            return
        self.current.project_id = project_id
        self.current.entry_id = None
        self.current_entry_path = None
        self._clear_editor()
        self.refresh_entries()
        self.refresh_tasks()
        self._update_time_today()

    def _on_project_expand(self, event: tk.Event) -> None:
        """Handle project expand event - save state to prefs."""
        try:
            item_id = self.project_tree.focus()
            if item_id:
                expanded = set(self.gui_prefs.get("expanded_projects", []))
                expanded.add(item_id)
                self.gui_prefs["expanded_projects"] = list(expanded)
                self._save_gui_prefs()
        except Exception:
            logger.exception("Failed to save expand state")

    def _on_project_collapse(self, event: tk.Event) -> None:
        """Handle project collapse event - save state to prefs."""
        try:
            item_id = self.project_tree.focus()
            if item_id:
                expanded = set(self.gui_prefs.get("expanded_projects", []))
                expanded.discard(item_id)
                self.gui_prefs["expanded_projects"] = list(expanded)
                self._save_gui_prefs()
        except Exception:
            logger.exception("Failed to save collapse state")
        self._load_project_details(self.projects_by_id.get(project_id))

    def _restore_project_selection(self) -> None:
        self._suppress_project_select = True
        try:
            self.project_tree.selection_remove(self.project_tree.selection())
            if self.current.project_id:
                self.project_tree.selection_set(self.current.project_id)
        finally:
            self._suppress_project_select = False

    def _on_entry_select(self, _event: tk.Event) -> None:
        if self._suppress_entry_select:
            return
        selection = self.entry_tree.selection()
        if not selection:
            return
        entry_id = selection[0]
        if entry_id == self.current.entry_id:
            return
        if not self._confirm_entry_detail_dirty():
            self._restore_entry_selection()
            return
        if not self._confirm_save_if_dirty():
            self._restore_entry_selection()
            return
        self._load_entry(entry_id)

    def _on_entry_double_click(self, _event: tk.Event) -> None:
        if not self._is_global_search_active():
            return
        selection = self.entry_tree.selection()
        if not selection:
            return
        entry = self.entries_by_id.get(selection[0])
        if not entry:
            return
        if entry.project_id and entry.project_id != self.current.project_id:
            if not self._select_project_for_context(entry.project_id):
                return
        self._select_entry_for_context(entry.id)

    def _restore_entry_selection(self) -> None:
        self._suppress_entry_select = True
        try:
            self.entry_tree.selection_remove(self.entry_tree.selection())
            if self.current.entry_id:
                self.entry_tree.selection_set(self.current.entry_id)
        finally:
            self._suppress_entry_select = False

    def _select_project_for_context(self, project_id: str) -> bool:
        if project_id == self.current.project_id:
            return True
        self._suppress_project_select = True
        try:
            self.project_tree.selection_set(project_id)
        finally:
            self._suppress_project_select = False
        self._on_project_select(None)
        return self.current.project_id == project_id

    def _select_entry_for_context(self, entry_id: str) -> bool:
        if entry_id == self.current.entry_id:
            return True
        self._suppress_entry_select = True
        try:
            self.entry_tree.selection_set(entry_id)
        finally:
            self._suppress_entry_select = False
        self._on_entry_select(None)
        return self.current.entry_id == entry_id

    def _show_editor_context_menu(self, event: tk.Event) -> None:
        try:
            self.editor_text.focus_set()
            index = self.editor_text.index(f"@{event.x},{event.y}")
            self.editor_text.mark_set("insert", index)
        except Exception:
            logger.exception("Exception caught in GUI operation")
            pass
        try:
            self.editor_context_menu.tk_popup(event.x_root, event.y_root)
        finally:
            self.editor_context_menu.grab_release()

    def _show_project_context_menu(self, event: tk.Event) -> None:
        project_id = self.project_tree.identify_row(event.y)
        if not project_id:
            return
        if not self._select_project_for_context(project_id):
            return
        try:
            self.project_context_menu.tk_popup(event.x_root, event.y_root)
        finally:
            self.project_context_menu.grab_release()

    def _copy_project_id(self) -> None:
        """Copy the current project ID to clipboard."""
        if not self.current.project_id:
            return
        try:
            self.clipboard_clear()
            self.clipboard_append(self.current.project_id)
            self.save_status_var.set(f"Project ID copied: {self.current.project_id[:8]}...")
            self.after(2000, lambda: self.save_status_var.set(""))
        except Exception:
            logger.exception("Exception caught in GUI operation")
            messagebox.showerror("Error", "Failed to copy project ID to clipboard")

    def _show_entry_context_menu(self, event: tk.Event) -> None:
        entry_id = self.entry_tree.identify_row(event.y)
        if not entry_id:
            return
        if not self._select_entry_for_context(entry_id):
            return
        self._update_entry_context_menu(True)
        try:
            self.entry_context_menu.tk_popup(event.x_root, event.y_root)
        finally:
            self.entry_context_menu.grab_release()

    def _entry_context_open(self) -> None:
        if self.current.entry_id:
            self._load_entry(self.current.entry_id)

    def _copy_entry_id(self) -> None:
        """Copy the current entry ID to clipboard."""
        if not self.current.entry_id:
            return
        try:
            self.clipboard_clear()
            self.clipboard_append(self.current.entry_id)
            self.save_status_var.set(f"Entry ID copied: {self.current.entry_id[:8]}...")
            self.after(2000, lambda: self.save_status_var.set(""))
        except Exception:
            logger.exception("Exception caught in GUI operation")
            messagebox.showerror("Error", "Failed to copy entry ID to clipboard")

    def _export_meeting_minutes_from_context(self) -> None:
        entry = self._get_selected_entry_for_export()
        if not entry:
            messagebox.showerror("No entry", "Select an entry first.")
            return
        if entry.type != "meeting":
            messagebox.showerror(
                "Not a meeting",
                "Export meeting minutes only applies to meeting entries.",
            )
            return
        self._export_meeting_minutes_dialog()

    def _update_entry_context_menu(self, has_entry: bool) -> None:
        state = "normal" if has_entry else "disabled"
        self.entry_context_menu.entryconfigure("Open", state=state)
        self.entry_context_menu.entryconfigure("Export meeting minutes...", state=state)
        self.entry_context_menu.entryconfigure("Move to project...", state=state)
        self.entry_context_menu.entryconfigure("Create follow-up tasks...", state=state)
        self.entry_context_menu.entryconfigure("Mark as Actual", state=state)
        self.entry_context_menu.entryconfigure("Mark as Treated", state=state)
        self.entry_context_menu.entryconfigure("Mark as Created", state=state)
        if not has_entry:
            return
        entry = self.entries_by_id.get(self.current.entry_id or "")
        if not entry:
            self.entry_context_menu.entryconfigure("Mark as Actual", state="disabled")
            self.entry_context_menu.entryconfigure("Mark as Treated", state="disabled")
            self.entry_context_menu.entryconfigure("Mark as Created", state="disabled")
            return
        self.entry_context_menu.entryconfigure(
            "Export meeting minutes...",
            state="normal" if entry.type == "meeting" else "disabled",
        )
        context_status = normalize_context_status(getattr(entry, "context_status", None))
        if context_status == "treated":
            self.entry_context_menu.entryconfigure("Mark as Actual", state="normal")
            self.entry_context_menu.entryconfigure("Mark as Treated", state="disabled")
            self.entry_context_menu.entryconfigure("Mark as Created", state="normal")
        elif context_status == "actual":
            self.entry_context_menu.entryconfigure("Mark as Actual", state="disabled")
            self.entry_context_menu.entryconfigure("Mark as Treated", state="normal")
            self.entry_context_menu.entryconfigure("Mark as Created", state="normal")
        else:
            self.entry_context_menu.entryconfigure("Mark as Actual", state="normal")
            self.entry_context_menu.entryconfigure("Mark as Treated", state="normal")
            self.entry_context_menu.entryconfigure("Mark as Created", state="disabled")

    def _extract_task_titles_from_text(self, text: str) -> list[str]:
        titles: list[str] = []
        seen: set[str] = set()
        for raw_line in text.splitlines():
            line = raw_line.strip()
            if not line:
                continue
            line = re.sub(r"^[-*+]\s+\[(?: |x|X)\]\s+", "", line)
            line = re.sub(r"^[-*+]\s+", "", line)
            line = re.sub(r"^\d+\.\s+", "", line)
            line = line.strip()
            if not line:
                continue
            key = line.lower()
            if key in seen:
                continue
            seen.add(key)
            titles.append(line)
        return titles

    def _open_task_bulk_create_dialog(self, entry: EntryMeta, titles: list[str]) -> None:
        dialog = tk.Toplevel(self)
        dialog.title("Create Tasks")
        dialog.transient(self)
        dialog.grab_set()
        dialog.resizable(True, True)
        dialog.columnconfigure(0, weight=1)
        dialog.rowconfigure(1, weight=1)

        ttk.Label(dialog, text=f"Entry: {entry.title}").grid(
            row=0, column=0, sticky="w", padx=8, pady=(8, 4)
        )

        list_frame = ttk.Frame(dialog)
        list_frame.grid(row=1, column=0, sticky="nsew", padx=8, pady=4)
        list_frame.columnconfigure(0, weight=1)
        list_frame.rowconfigure(0, weight=1)

        canvas = tk.Canvas(list_frame, borderwidth=0, highlightthickness=0)
        scroll = ttk.Scrollbar(list_frame, orient=tk.VERTICAL, command=canvas.yview)
        inner = ttk.Frame(canvas)
        inner.bind(
            "<Configure>",
            lambda _e: canvas.configure(scrollregion=canvas.bbox("all")),
        )
        canvas.create_window((0, 0), window=inner, anchor="nw")
        canvas.configure(yscrollcommand=scroll.set)
        canvas.grid(row=0, column=0, sticky="nsew")
        scroll.grid(row=0, column=1, sticky="ns")

        options: list[tuple[tk.BooleanVar, str]] = []
        for title in titles:
            var = tk.BooleanVar(value=True)
            label = title
            if len(label) > 80:
                label = f"{label[:77]}..."
            ttk.Checkbutton(inner, text=label, variable=var).pack(
                anchor="w", fill="x", padx=2, pady=2
            )
            options.append((var, title))

        button_frame = ttk.Frame(dialog)
        button_frame.grid(row=2, column=0, sticky="e", padx=8, pady=8)

        def submit() -> None:
            selected = [title for var, title in options if var.get()]
            if not selected:
                messagebox.showinfo(
                    "No tasks selected", "Select at least one task."
                )
                return
            try:
                created = self.service.create_followup_tasks(entry.id, selected)
            except ValueError as exc:
                messagebox.showerror("Error", str(exc))
                return
            dialog.destroy()
            self.refresh_tasks()
            self._set_status(f"Created {len(created)} tasks")
            messagebox.showinfo(
                "Tasks created", f"Created {len(created)} tasks."
            )

        ttk.Button(button_frame, text="Create", command=submit).pack(
            side=tk.LEFT, padx=(0, 6)
        )
        ttk.Button(button_frame, text="Cancel", command=dialog.destroy).pack(
            side=tk.LEFT
        )

    def _create_followup_tasks_dialog(self) -> None:
        entry = self._get_selected_entry_for_export()
        if not entry:
            messagebox.showerror("No entry", "Select an entry first.")
            return
        try:
            titles = self.service.extract_followup_tasks(entry.id)
        except ValueError as exc:
            messagebox.showerror("Error", str(exc))
            return
        if not titles:
            messagebox.showinfo(
                "No actions found",
                "No follow-up tasks were found in this entry.",
            )
            return

        dialog = tk.Toplevel(self)
        dialog.title("Create Follow-up Tasks")
        dialog.transient(self)
        dialog.grab_set()
        dialog.resizable(True, True)
        dialog.columnconfigure(0, weight=1)
        dialog.rowconfigure(1, weight=1)

        ttk.Label(dialog, text=f"Entry: {entry.title}").grid(
            row=0, column=0, sticky="w", padx=8, pady=(8, 4)
        )

        list_frame = ttk.Frame(dialog)
        list_frame.grid(row=1, column=0, sticky="nsew", padx=8, pady=4)
        list_frame.columnconfigure(0, weight=1)
        list_frame.rowconfigure(0, weight=1)

        canvas = tk.Canvas(list_frame, borderwidth=0, highlightthickness=0)
        scroll = ttk.Scrollbar(list_frame, orient=tk.VERTICAL, command=canvas.yview)
        inner = ttk.Frame(canvas)
        inner.bind(
            "<Configure>",
            lambda _e: canvas.configure(scrollregion=canvas.bbox("all")),
        )
        canvas.create_window((0, 0), window=inner, anchor="nw")
        canvas.configure(yscrollcommand=scroll.set)
        canvas.grid(row=0, column=0, sticky="nsew")
        scroll.grid(row=0, column=1, sticky="ns")

        options: list[tuple[tk.BooleanVar, str]] = []
        for title in titles:
            var = tk.BooleanVar(value=True)
            label = title
            if len(label) > 80:
                label = f"{label[:77]}..."
            ttk.Checkbutton(inner, text=label, variable=var).pack(
                anchor="w", fill="x", padx=2, pady=2
            )
            options.append((var, title))

        button_frame = ttk.Frame(dialog)
        button_frame.grid(row=2, column=0, sticky="e", padx=8, pady=8)

        def submit() -> None:
            selected = [title for var, title in options if var.get()]
            if not selected:
                messagebox.showinfo(
                    "No tasks selected", "Select at least one task."
                )
                return
            try:
                created = self.service.create_followup_tasks(entry.id, selected)
            except ValueError as exc:
                messagebox.showerror("Error", str(exc))
                return
            dialog.destroy()
            self.refresh_tasks()
            self._set_status(f"Created {len(created)} follow-up tasks")
            messagebox.showinfo(
                "Tasks created", f"Created {len(created)} follow-up tasks."
            )

        ttk.Button(button_frame, text="Create", command=submit).pack(
            side=tk.LEFT, padx=(0, 6)
        )
        ttk.Button(button_frame, text="Cancel", command=dialog.destroy).pack(
            side=tk.LEFT
        )

    def _show_task_context_menu(self, event: tk.Event) -> None:
        task_id = self.task_tree.identify_row(event.y)
        if not task_id:
            return
        self.task_tree.selection_set(task_id)
        self._on_task_select(None)
        task = self.tasks_by_id.get(task_id)
        if not task:
            return
        for label, status in (
            ("Mark Open", "open"),
            ("Mark In Progress", "in_progress"),
            ("Mark Done", "done"),
        ):
            state = "disabled" if task.status == status else "normal"
            self.task_context_menu.entryconfigure(label, state=state)
        try:
            self.task_context_menu.tk_popup(event.x_root, event.y_root)
        finally:
            self.task_context_menu.grab_release()

    def _set_task_status(self, status: str) -> None:
        task = self.tasks_by_id.get(self.current_task_id or "")
        if not task:
            messagebox.showerror("No task", "Select a task first.")
            return
        try:
            updated = self.service.update_task(task.id, {"status": status})
        except ValueError as exc:
            messagebox.showerror("Error", str(exc))
            return
        self.refresh_tasks(select_task_id=updated.id)

    def _clear_editor(self) -> None:
        self._cancel_autosave()
        self._loading_entry = True
        self.editor_text.delete("1.0", tk.END)
        self.editor_text.edit_modified(False)
        self._loading_entry = False
        self.dirty = False
        self.current_entry_path = None
        self.editor_title_var.set("No entry selected")
        self._load_entry_details(None)
        self._update_save_button_state()
        self._update_task_action_state()

    def _show_entry_meeting_fields(self, show: bool) -> None:
        if show:
            self.entry_meeting_label.grid()
            self.entry_meeting_frame.grid()
        else:
            self.entry_meeting_label.grid_remove()
            self.entry_meeting_frame.grid_remove()

    def _show_entry_decision_fields(self, show: bool) -> None:
        if show:
            self.entry_decision_label.grid()
            self.entry_decision_check.grid()
        else:
            self.entry_decision_label.grid_remove()
            self.entry_decision_check.grid_remove()

    def _set_entry_fields_state(self, enabled: bool) -> None:
        state = "normal" if enabled else "disabled"
        for widget in (
            self.entry_title_entry,
            self.entry_date_entry,
            self.entry_group_entry,
            self.entry_tags_entry,
            self.entry_start_entry,
            self.entry_end_entry,
        ):
            widget.configure(state=state)
        self.entry_people_text.configure(state=state)

    def _set_entry_editing(self, editing: bool) -> None:
        self.entry_editing = editing
        self.entry_dirty = False
        self._set_entry_fields_state(editing)
        if editing:
            self.entry_edit_save_button.configure(text="Save")
            self.entry_edit_save_button.state(["!disabled"])
            self.entry_cancel_button.state(["!disabled"])
            if not self.entry_cancel_button.winfo_ismapped():
                self.entry_cancel_button.pack(side=tk.LEFT, padx=(0, 6))
            self.entry_delete_button.state(["disabled"])
        else:
            self.entry_edit_save_button.configure(text="Edit")
            self.entry_edit_save_button.state(["!disabled"])
            self.entry_cancel_button.state(["disabled"])
            if self.entry_cancel_button.winfo_ismapped():
                self.entry_cancel_button.pack_forget()
            self.entry_delete_button.state(["!disabled"])

    def _load_entry_details(self, entry: EntryMeta | None) -> None:
        self._entry_detail_updating = True
        try:
            if not entry:
                self.entry_detail_snapshot = None
                self.entry_title_var.set("")
                self.entry_type_var.set("-")
                self.entry_date_var.set("")
                self.entry_people_text.configure(state="normal")
                self.entry_people_text.delete("1.0", tk.END)
                self.entry_people_text.edit_modified(False)
                self.entry_people_text.configure(state="disabled")
                self.entry_group_var.set("")
                self.entry_tags_var.set("")
                self.entry_start_var.set("")
                self.entry_end_var.set("")
                self.entry_decision_var.set(False)
                self._show_entry_meeting_fields(False)
                self._show_entry_decision_fields(False)
                self.entry_decision_check.state(["disabled"])
                self._set_entry_editing(False)
                return
            self.entry_detail_snapshot = entry
            entry_dt = dates.parse_utc_z(entry.ts).astimezone()
            entry_date = getattr(entry, "entry_date", None) or entry_dt.date().isoformat()
            self.entry_title_var.set(entry.title)
            self.entry_type_var.set(_display_entry_type(entry.type))
            self.entry_date_var.set(format_date_ui(entry_date))
            self.entry_people_text.configure(state="normal")
            self.entry_people_text.delete("1.0", tk.END)
            if entry.person:
                people_text = join_people_storage(split_people(entry.person))
                if people_text:
                    self.entry_people_text.insert("1.0", people_text)
            self.entry_people_text.edit_modified(False)
            self.entry_group_var.set(entry.group or "")
            self.entry_tags_var.set(", ".join(entry.tags))
            self.entry_start_var.set(entry.start_time or "")
            self.entry_end_var.set(entry.end_time or "")
            self.entry_decision_var.set(bool(entry.decision_done))
            self._show_entry_meeting_fields(entry.type == "meeting")
            self._show_entry_decision_fields(entry.type == "decision")
            if entry.type == "decision":
                self.entry_decision_check.state(["!disabled"])
            else:
                self.entry_decision_check.state(["disabled"])
        finally:
            self._entry_detail_updating = False
        self._set_entry_editing(False)

    def _on_entry_detail_modified(self, *_args: object) -> None:
        if self._entry_detail_updating or not self.entry_editing:
            return
        self.entry_dirty = True

    def _on_entry_people_modified(self, _event: tk.Event) -> None:
        if self._entry_detail_updating or not self.entry_editing:
            self.entry_people_text.edit_modified(False)
            return
        if self.entry_people_text.edit_modified():
            self.entry_dirty = True
            self.entry_people_text.edit_modified(False)

    def _edit_entry_details(self) -> None:
        if not self.current.entry_id:
            messagebox.showerror("No entry", "Select an entry first.")
            return
        self._set_entry_editing(True)
        self.entry_title_entry.focus_set()

    def _on_entry_edit_save(self) -> None:
        if not self.entry_editing:
            self._edit_entry_details()
            return
        if self._save_entry_details():
            self._set_entry_editing(False)

    def _save_entry_details(self) -> bool:
        if not self.current.entry_id:
            messagebox.showerror("No entry", "Select an entry first.")
            return False
        entry = self.entries_by_id.get(self.current.entry_id)
        if not entry:
            messagebox.showerror("No entry", "Select an entry first.")
            return False
        title = self.entry_title_var.get().strip()
        if not title:
            messagebox.showerror("Validation", "Entry title is required")
            return False
        date_text = self.entry_date_var.get().strip()
        parsed_date = None
        if date_text:
            try:
                parsed_date = parse_date_ui(date_text)
            except ValueError:
                messagebox.showerror(
                    "Validation",
                    f"Invalid date {date_text}. Expected DD/MM/YYYY (or YYYY-MM-DD)",
                )
                return False
        tags = strings.parse_tags(self.entry_tags_var.get())
        kwargs: dict[str, object] = {
            "title": title,
            "tags": tags,
            "entry_date": parsed_date,
            "person": self._get_people_text_value(self.entry_people_text),
            "group": self.entry_group_var.get().strip() or None,
        }
        if entry.type == "meeting":
            kwargs["start_time"] = self.entry_start_var.get().strip() or None
            kwargs["end_time"] = self.entry_end_var.get().strip() or None
        if entry.type == "decision":
            kwargs["decision_done"] = self.entry_decision_var.get()
        try:
            updated = self.service.update_entry_meta(entry.id, **kwargs)
        except ValueError as exc:
            messagebox.showerror("Error", str(exc))
            return False
        self.refresh_entries(select_entry_id=entry.id)
        self._load_entry_details(updated)
        self._set_status("Entry metadata saved")
        return True

    def _delete_entry(self) -> None:
        if not self.current.entry_id:
            messagebox.showerror("No entry", "Select an entry first.")
            return
        entry = self.entries_by_id.get(self.current.entry_id)
        if not entry:
            messagebox.showerror("No entry", "Select an entry first.")
            return
        if not self._confirm_entry_detail_dirty():
            return
        if not self._confirm_save_if_dirty():
            return
        warning_message = (
            f"Delete entry '{entry.title}'?\n\n"
            "This will PERMANENTLY delete the entry content and metadata.\n\n"
            "This action CANNOT be undone!"
        )
        if not messagebox.askyesno("Delete Entry", warning_message):
            return
        try:
            self.service.delete_entry(entry.id)
        except ValueError as exc:
            messagebox.showerror("Error", str(exc))
            return
        self.current.entry_id = None
        self.current_entry_path = None
        self._clear_editor()
        self.refresh_entries()
        self._set_status(f"Entry '{entry.title}' deleted permanently")
        messagebox.showinfo("Deleted", f"Entry '{entry.title}' has been deleted.")

    def _move_entry_dialog(self) -> None:
        entry = self._get_selected_entry_for_export()
        if not entry:
            messagebox.showerror("No entry", "Select an entry first.")
            return

        projects = self.service.list_projects(status="all")
        show_archived = bool(self.show_archived_var.get())
        if not show_archived:
            projects = [project for project in projects if project.status == "active"]
        active_projects = sorted(
            [project for project in projects if project.status == "active"],
            key=lambda item: item.name.lower(),
        )
        archived_projects = sorted(
            [project for project in projects if project.status == "archived"],
            key=lambda item: item.name.lower(),
        )
        project_list = active_projects + archived_projects
        if not project_list:
            messagebox.showerror("No projects", "No projects available.")
            return

        name_counts: dict[str, int] = {}
        for project in project_list:
            key = project.name.strip().lower()
            name_counts[key] = name_counts.get(key, 0) + 1

        label_to_id: dict[str, str] = {}
        id_to_name: dict[str, str] = {}
        labels: list[str] = []
        for project in project_list:
            key = project.name.strip().lower()
            if name_counts.get(key, 0) > 1:
                label = f"{project.name} ({project.id[:8]})"
            else:
                label = project.name
            labels.append(label)
            label_to_id[label] = project.id
            id_to_name[project.id] = project.name

        dialog = tk.Toplevel(self)
        dialog.title("Move Entry")
        dialog.grab_set()
        dialog.transient(self)
        dialog.resizable(False, False)
        dialog.columnconfigure(1, weight=1)

        ttk.Label(dialog, text=f"Move entry: {entry.title}").grid(
            row=0, column=0, columnspan=2, sticky=tk.W, padx=6, pady=6
        )

        ttk.Label(dialog, text="Project").grid(
            row=1, column=0, sticky=tk.W, padx=6, pady=6
        )
        project_var = tk.StringVar()
        project_box = ttk.Combobox(
            dialog, textvariable=project_var, values=labels, state="readonly", width=32
        )
        project_box.grid(row=1, column=1, sticky=tk.W, padx=6, pady=6)

        keep_tags_var = tk.BooleanVar(value=True)
        keep_people_var = tk.BooleanVar(value=True)
        ttk.Checkbutton(dialog, text="Keep tags", variable=keep_tags_var).grid(
            row=2, column=0, columnspan=2, sticky=tk.W, padx=6, pady=4
        )
        ttk.Checkbutton(
            dialog, text="Keep person/group", variable=keep_people_var
        ).grid(row=3, column=0, columnspan=2, sticky=tk.W, padx=6, pady=4)

        default_label = None
        for label, project_id in label_to_id.items():
            if project_id == entry.project_id:
                default_label = label
                break
        if default_label:
            project_var.set(default_label)
        else:
            project_var.set(labels[0])

        button_frame = ttk.Frame(dialog)
        button_frame.grid(row=4, column=0, columnspan=2, sticky=tk.E, padx=6, pady=8)
        ttk.Button(button_frame, text="Cancel", command=dialog.destroy).pack(
            side=tk.RIGHT, padx=(6, 0)
        )

        def submit() -> None:
            label = project_var.get().strip()
            if label not in label_to_id:
                messagebox.showerror("Validation", "Select a valid project.")
                return
            new_project_id = label_to_id[label]
            try:
                self.service.move_entry(
                    entry.id,
                    new_project_id,
                    keep_tags=keep_tags_var.get(),
                    keep_people=keep_people_var.get(),
                )
            except ValueError as exc:
                messagebox.showerror("Error", str(exc))
                return
            dialog.destroy()
            if new_project_id != self.current.project_id:
                switched = self._select_project_for_context(new_project_id)
                if switched:
                    self.refresh_entries(select_entry_id=entry.id)
                else:
                    self.refresh_entries()
            else:
                self.refresh_entries(select_entry_id=entry.id)
            project_name = id_to_name.get(new_project_id, new_project_id)
            self._set_status(f"Entry moved to {project_name}")
            messagebox.showinfo("Entry moved", f"Entry moved to {project_name}.")

        ttk.Button(button_frame, text="Move", command=submit).pack(side=tk.RIGHT)

    def _cancel_entry_details(self) -> None:
        if self.entry_detail_snapshot:
            self._load_entry_details(self.entry_detail_snapshot)
        else:
            self._load_entry_details(None)

    def _confirm_entry_detail_dirty(self) -> bool:
        if not self.entry_dirty:
            return True
        result = messagebox.askyesnocancel(
            "Save changes?", "Save changes to the entry metadata?"
        )
        if result is None:
            return False
        if result:
            return self._save_entry_details()
        if self.entry_detail_snapshot:
            self._load_entry_details(self.entry_detail_snapshot)
        else:
            self._load_entry_details(None)
        return True

    def _on_entry_decision_toggle(self) -> None:
        if self._entry_detail_updating:
            return
        entry = self.entries_by_id.get(self.current.entry_id or "")
        if not entry or entry.type != "decision":
            return
        if self.entry_editing:
            self.entry_dirty = True
            return
        try:
            updated = self.service.update_entry_meta(
                entry.id, decision_done=self.entry_decision_var.get()
            )
        except ValueError as exc:
            messagebox.showerror("Error", str(exc))
            self._load_entry_details(entry)
            return
        self.refresh_entries(select_entry_id=entry.id)
        self._load_entry_details(updated)

    def _set_entry_context_status(self, status: str | None) -> None:
        entry_id = self.current.entry_id
        if not entry_id:
            return
        self._set_entry_context_status_for_id(entry_id, status)

    def _set_entry_context_status_for_id(
        self, entry_id: str, status: str | None
    ) -> None:
        try:
            updated = self.service.set_entry_context_status(entry_id, status)
        except ValueError as exc:
            messagebox.showerror("Error", str(exc))
            return
        if entry_id == self.current.entry_id:
            self.refresh_entries(select_entry_id=entry_id)
            self._load_entry_details(updated)
        else:
            self.refresh_entries()
        self.refresh_in_progress()

    def _collect_known_tags(self) -> list[str]:
        tags: set[str] = set()
        for project in self.service.storage.read_projects():
            for tag in project.tags:
                cleaned = tag.strip()
                if cleaned:
                    tags.add(cleaned)
        for entry in self.service.storage.read_entries_meta():
            for tag in entry.tags:
                cleaned = tag.strip()
                if cleaned:
                    tags.add(cleaned)
        return sorted(tags)

    def _add_tags_from_list(self, listbox: tk.Listbox, tags_var: tk.StringVar) -> None:
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

    def _count_open_tasks_by_project(self) -> dict[str, int]:
        counts: dict[str, int] = {}
        for task in self.service.storage.read_tasks():
            if task.status in ("open", "in_progress"):
                counts[task.project_id] = counts.get(task.project_id, 0) + 1
        return counts

    def _get_all_tags(self) -> list[str]:
        """Get all unique tags from projects, entries, and tasks."""
        tags_set = set()
        
        # Collect from projects
        for project in self.service.storage.read_projects():
            tags_set.update(project.tags)
        
        # Collect from entries
        for entry in self.service.storage.read_entries_meta():
            tags_set.update(entry.tags)
        
        # Collect from tasks
        for task in self.service.storage.read_tasks():
            tags_set.update(task.tags)
        
        # Return sorted list
        return sorted(tags_set, key=str.lower)

    def _set_tasks_visibility(self, has_project: bool) -> None:
        if has_project:
            if self.tasks_empty_label.winfo_ismapped():
                self.tasks_empty_label.grid_remove()
            if not self.tasks_content_frame.winfo_ismapped():
                self.tasks_content_frame.grid(row=0, column=0, sticky="nsew")
        else:
            if self.tasks_content_frame.winfo_ismapped():
                self.tasks_content_frame.grid_remove()
            if not self.tasks_empty_label.winfo_ismapped():
                self.tasks_empty_label.grid(row=0, column=0, sticky="w", padx=8, pady=8)

    def _clear_task_details(self) -> None:
        self.current_task_id = None
        self.task_created_var.set("-")
        self.task_done_var.set("-")
        self.task_note_text.configure(state="normal")
        self.task_note_text.delete("1.0", tk.END)
        self.task_note_text.configure(state="disabled")

    def _load_task_details(self, task: Task | None) -> None:
        if not task:
            self._clear_task_details()
            return
        self.current_task_id = task.id
        created_label = "-"
        done_label = "-"
        try:
            if task.created_at:
                created_label = (
                    dates.parse_utc_z(task.created_at)
                    .astimezone()
                    .replace(microsecond=0)
                    .isoformat()
                )
            if task.done_at:
                done_label = (
                    dates.parse_utc_z(task.done_at)
                    .astimezone()
                    .replace(microsecond=0)
                    .isoformat()
                )
        except Exception:
            logger.exception("Exception caught in GUI operation")
            created_label = task.created_at or "-"
            done_label = task.done_at or "-"
        self.task_created_var.set(created_label)
        self.task_done_var.set(done_label)
        self.task_note_text.configure(state="normal")
        self.task_note_text.delete("1.0", tk.END)
        if task.note:
            self.task_note_text.insert("1.0", task.note)
        self.task_note_text.configure(state="disabled")

    def _task_matches_query(self, task: Task, query: str) -> bool:
        if not query:
            return True
        haystack = " ".join(
            [
                task.title,
                " ".join(task.tags),
                task.note or "",
            ]
        ).lower()
        return query in haystack

    def _update_task_action_state(self) -> None:
        has_project = bool(self.current.project_id)
        has_task = bool(self.current_task_id)
        has_entry = bool(self.current.entry_id)
        if has_project:
            self.task_add_button.state(["!disabled"])
        else:
            self.task_add_button.state(["disabled"])
        for button in (self.task_edit_button, self.task_delete_button):
            if has_task:
                button.state(["!disabled"])
            else:
                button.state(["disabled"])
        if has_project and has_entry:
            self.task_from_entry_button.state(["!disabled"])
        else:
            self.task_from_entry_button.state(["disabled"])

    def _on_task_select(self, _event: tk.Event) -> None:
        selection = self.task_tree.selection()
        if not selection:
            self._clear_task_details()
            self._update_task_action_state()
            return
        task_id = selection[0]
        task = self.tasks_by_id.get(task_id)
        self._load_task_details(task)
        self._update_task_action_state()

    def refresh_tasks(self, select_task_id: str | None = None) -> None:
        if not self.current.project_id:
            self.tasks_by_id = {}
            self.task_tree.delete(*self.task_tree.get_children())
            self._set_tasks_visibility(False)
            self._clear_task_details()
            self._update_task_action_state()
            self.refresh_upcoming()
            return

        self._set_tasks_visibility(True)
        tasks = self.service.list_tasks(self.current.project_id, status="all")
        status_label = self.task_status_filter_var.get().lower()
        if status_label == "open":
            tasks = [task for task in tasks if task.status == "open"]
        elif status_label == "in progress":
            tasks = [task for task in tasks if task.status == "in_progress"]
        elif status_label == "done":
            tasks = [task for task in tasks if task.status == "done"]

        query = self.task_search_var.get().strip().lower()
        if query:
            tasks = [task for task in tasks if self._task_matches_query(task, query)]

        if self.task_current_entries_only_var.get():
            entry_map = {
                entry.id: entry
                for entry in self.service.storage.read_entries_meta()
                if entry.project_id == self.current.project_id
            }
            tasks = [
                task
                for task in tasks
                if not task.linked_entry_id
                or (
                    entry_map.get(task.linked_entry_id)
                    and normalize_context_status(
                        entry_map[task.linked_entry_id].context_status
                    )
                    == "actual"
                )
            ]

        self.tasks_by_id = {task.id: task for task in tasks}
        self.task_tree.delete(*self.task_tree.get_children())
        for index, task in enumerate(tasks):
            if task.status == "done":
                done_label = "☑"
            elif task.status == "in_progress":
                done_label = "IP"
            else:
                done_label = "☐"
            due_label = format_date_ui(task.due_date)
            tags = strings.format_tags(task.tags)
            source = task.linked_entry_id[:8] if task.linked_entry_id else ""
            self.task_tree.insert(
                "",
                tk.END,
                iid=task.id,
                values=(done_label, task.title, due_label, tags, source),
                tags=("even" if index % 2 == 0 else "odd",),
            )

        target_id = select_task_id or self.current_task_id
        if target_id and self.task_tree.exists(target_id):
            self.task_tree.selection_set(target_id)
            self.task_tree.see(target_id)
            self._load_task_details(self.tasks_by_id.get(target_id))
        else:
            self._clear_task_details()
        self._update_task_action_state()
        self._update_project_task_counts()
        self.refresh_upcoming()

    def _toggle_in_progress_sort(self, col_id: str) -> None:
        if col_id not in self.in_progress_column_labels:
            return
        if self.in_progress_sort_col != col_id:
            self.in_progress_sort_col = col_id
            self.in_progress_sort_dir = "asc"
        elif self.in_progress_sort_dir == "asc":
            self.in_progress_sort_dir = "desc"
        else:
            self.in_progress_sort_col = None
            self.in_progress_sort_dir = None
        self.refresh_in_progress()

    def _update_in_progress_sort_headers(self) -> None:
        columns = list(self.in_progress_tree["columns"])
        active_col = self.in_progress_sort_col if self.in_progress_sort_col in columns else None
        active_dir = self.in_progress_sort_dir if active_col else None
        arrow = "↓" if active_dir == "desc" else "↑"
        for col in columns:
            label = self.in_progress_column_labels.get(col, col)
            if col == active_col and active_dir:
                label = f"{label} {arrow}"
            self.in_progress_tree.heading(col, text=label)

    def _get_entry_local_date(self, entry: EntryMeta) -> date:
        if entry.entry_date:
            try:
                return dates.parse_date(entry.entry_date)
            except Exception:
                logger.exception("Exception caught in GUI operation")
                pass
        try:
            return dates.parse_utc_z(entry.ts).astimezone().date()
        except Exception:
            logger.exception("Exception caught in GUI operation")
            return datetime.now().astimezone().date()

    def _sort_in_progress_entries(
        self,
        entries: list[EntryMeta],
        project_names: dict[str, str],
        open_actions_map: dict[str, int],
    ) -> list[EntryMeta]:
        if not self.in_progress_sort_col or not self.in_progress_sort_dir:
            return list(entries)

        col = self.in_progress_sort_col

        def key(entry: EntryMeta) -> tuple:
            if col == "project":
                label = project_names.get(
                    entry.project_id, entry.project_id or ""
                )
                value = label.strip().lower()
                return (not value, value)
            if col == "people":
                value = format_people_inline(entry.person).strip().lower()
                return (not value, value)
            if col == "date":
                value = self._get_entry_local_date(entry)
                return (False, value)
            if col == "type":
                value = (entry.type or "").strip().lower()
                return (not value, value)
            if col == "title":
                value = (entry.title or "").strip().lower()
                return (not value, value)
            if col == "open_actions":
                value = open_actions_map.get(entry.id, 0)
                return (False, value)
            return (0,)

        reverse = self.in_progress_sort_dir == "desc"
        return sorted(list(entries), key=key, reverse=reverse)

    def refresh_in_progress(self) -> None:
        if not hasattr(self, "in_progress_tree"):
            return
        selected = self.in_progress_tree.selection()
        selected_id = selected[0] if selected else None
        include_created = bool(self.in_progress_show_created_var.get())
        include_treated = bool(self.in_progress_show_treated_var.get())
        entries = self.service.list_in_progress_entries(
            include_created=include_created,
            include_treated=include_treated,
        )
        project_names = {
            project_id: project.name for project_id, project in self.projects_by_id.items()
        }
        if not project_names:
            project_names = {
                project.id: project.name
                for project in self.service.list_projects(status="all")
            }

        open_actions_map = self.service.count_open_actions_by_entry(
            [entry.id for entry in entries]
        )
        entries = self._sort_in_progress_entries(entries, project_names, open_actions_map)
        self._update_in_progress_sort_headers()
        self.in_progress_entries_by_id = {}
        self.in_progress_tree.delete(*self.in_progress_tree.get_children())
        for index, entry in enumerate(entries):
            project_name = project_names.get(entry.project_id, entry.project_id or "Unknown")
            open_actions = open_actions_map.get(entry.id, 0)
            values = (
                project_name,
                format_people_inline(entry.person),
                format_date_ui(self._get_entry_local_date(entry)),
                _display_entry_type(entry.type),
                entry.title,
                str(open_actions),
            )
            self.in_progress_entries_by_id[entry.id] = entry
            self.in_progress_tree.insert(
                "",
                tk.END,
                iid=entry.id,
                values=values,
                tags=("even" if index % 2 == 0 else "odd",),
            )
        if selected_id and self.in_progress_tree.exists(selected_id):
            self.in_progress_tree.selection_set(selected_id)
            self.in_progress_tree.see(selected_id)

    def _get_selected_in_progress_entry(self) -> EntryMeta | None:
        selection = self.in_progress_tree.selection()
        if not selection:
            return None
        return self.in_progress_entries_by_id.get(selection[0])

    def _on_in_progress_open(self, _event: tk.Event) -> None:
        self._open_selected_in_progress()

    def _open_selected_in_progress(self) -> None:
        entry = self._get_selected_in_progress_entry()
        if not entry:
            return
        self._open_in_progress_entry(entry)

    def _show_in_progress_context_menu(self, event: tk.Event) -> None:
        entry_id = self.in_progress_tree.identify_row(event.y)
        if not entry_id:
            return
        self.in_progress_tree.selection_set(entry_id)
        try:
            self.in_progress_context_menu.tk_popup(event.x_root, event.y_root)
        finally:
            self.in_progress_context_menu.grab_release()

    def _set_in_progress_entry_context_status(self, status: str | None) -> None:
        entry = self._get_selected_in_progress_entry()
        if not entry:
            return
        self._set_entry_context_status_for_id(entry.id, status)

    def _open_in_progress_entry(self, entry: EntryMeta) -> None:
        if not self._select_project_for_context(entry.project_id):
            return
        self.refresh_entries(select_entry_id=entry.id)
        if self.entry_tree.exists(entry.id):
            self._select_entry_for_context(entry.id)
            return
        if not self._confirm_entry_detail_dirty():
            return
        if not self._confirm_save_if_dirty():
            return
        self._load_entry(entry.id)

    def refresh_upcoming(self) -> None:
        if not hasattr(self, "upcoming_tree"):
            return
        tasks = self.service.storage.read_tasks()
        projects = {
            project.id: project.name
            for project in self.service.list_projects(status="all")
        }
        today = datetime.now().astimezone().date()
        days = UPCOMING_RANGE_DAYS.get(self.upcoming_range_var.get(), None)
        include_overdue = bool(self.upcoming_include_overdue_var.get())
        end_date = today + timedelta(days=days) if days is not None else None
        upcoming: list[tuple[date, str, str, Task]] = []
        for task in tasks:
            if task.status not in ("open", "in_progress"):
                continue
            if not task.due_date:
                continue
            try:
                due_date = dates.parse_date(task.due_date)
            except Exception:
                logger.exception("Exception caught in GUI operation")
                continue
            overdue = due_date < today
            if overdue and not include_overdue:
                continue
            if not overdue:
                if end_date is not None and due_date > end_date:
                    continue
            project_name = projects.get(task.project_id, task.project_id or "Unknown")
            upcoming.append((due_date, project_name, task.title, task))
        upcoming.sort(key=lambda item: (item[0], item[1].lower(), item[2].lower()))

        self.upcoming_tasks_by_id = {}
        self.upcoming_tree.delete(*self.upcoming_tree.get_children())
        for index, (_due, project_name, title, task) in enumerate(upcoming):
            self.upcoming_tasks_by_id[task.id] = task
            self.upcoming_tree.insert(
                "",
                tk.END,
                iid=task.id,
                values=(format_date_ui(task.due_date), project_name, title),
                tags=("even" if index % 2 == 0 else "odd",),
            )

    def _on_upcoming_open(self, _event: tk.Event) -> None:
        selection = self.upcoming_tree.selection()
        if not selection:
            return
        task_id = selection[0]
        task = self.upcoming_tasks_by_id.get(task_id)
        if not task:
            return
        if not self._select_project_for_context(task.project_id):
            return
        self.refresh_tasks(select_task_id=task.id)

    def _add_task_dialog(self, from_entry: bool = False) -> None:
        if not self.current.project_id:
            messagebox.showerror("No project", "Select a project first.")
            return
        entry = self.entries_by_id.get(self.current.entry_id) if from_entry else None

        dialog = tk.Toplevel(self)
        dialog.title("Add Task")
        dialog.grab_set()
        dialog.transient(self)
        dialog.resizable(True, True)
        dialog.columnconfigure(1, weight=1)
        dialog.rowconfigure(4, weight=1)

        ttk.Label(dialog, text="Title").grid(
            row=0, column=0, sticky=tk.W, padx=6, pady=6
        )
        title_var = tk.StringVar(
            value=f"Follow-up: {entry.title}" if entry else ""
        )
        ttk.Entry(dialog, textvariable=title_var).grid(
            row=0, column=1, sticky="ew", padx=6, pady=6
        )

        ttk.Label(dialog, text="Tags").grid(
            row=1, column=0, sticky=tk.W, padx=6, pady=6
        )
        tags_var = tk.StringVar(value=", ".join(entry.tags) if entry else "")
        ttk.Entry(dialog, textvariable=tags_var).grid(
            row=1, column=1, sticky="ew", padx=6, pady=6
        )

        ttk.Label(dialog, text="Due (DD/MM/YYYY)").grid(
            row=2, column=0, sticky=tk.W, padx=6, pady=6
        )
        due_var = tk.StringVar(value="")
        ttk.Entry(dialog, textvariable=due_var).grid(
            row=2, column=1, sticky="ew", padx=6, pady=6
        )

        link_var = tk.BooleanVar(value=bool(entry))
        if entry:
            ttk.Checkbutton(
                dialog, text="Link to current entry", variable=link_var
            ).grid(row=3, column=0, columnspan=2, sticky=tk.W, padx=6, pady=6)

        ttk.Label(dialog, text="Note").grid(
            row=4, column=0, sticky=tk.NW, padx=6, pady=6
        )
        note_frame = ttk.Frame(dialog)
        note_frame.grid(row=4, column=1, sticky="nsew", padx=6, pady=6)
        note_frame.columnconfigure(0, weight=1)
        note_frame.rowconfigure(0, weight=1)
        note_text = tk.Text(note_frame, height=4, wrap="word")
        note_scroll = ttk.Scrollbar(note_frame, orient=tk.VERTICAL, command=note_text.yview)
        note_text.configure(yscrollcommand=note_scroll.set)
        note_text.grid(row=0, column=0, sticky="nsew")
        note_scroll.grid(row=0, column=1, sticky="ns")

        def submit() -> None:
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
            linked_entry_id = entry.id if entry and link_var.get() else None
            try:
                task = self.service.create_task(
                    self.current.project_id,
                    title,
                    tags,
                    note,
                    linked_entry_id,
                    due_date,
                )
            except ValueError as exc:
                messagebox.showerror("Error", str(exc))
                return
            dialog.destroy()
            self.refresh_tasks(select_task_id=task.id)

        ttk.Button(dialog, text="Create", command=submit).grid(
            row=5, column=0, columnspan=2, pady=10
        )

    def _edit_task_dialog(self) -> None:
        task = self.tasks_by_id.get(self.current_task_id or "")
        if not task:
            messagebox.showerror("No task", "Select a task first.")
            return

        dialog = tk.Toplevel(self)
        dialog.title("Edit Task")
        dialog.grab_set()
        dialog.transient(self)
        dialog.resizable(True, True)
        dialog.columnconfigure(1, weight=1)
        dialog.rowconfigure(3, weight=1)

        ttk.Label(dialog, text="Title").grid(
            row=0, column=0, sticky=tk.W, padx=6, pady=6
        )
        title_var = tk.StringVar(value=task.title)
        ttk.Entry(dialog, textvariable=title_var).grid(
            row=0, column=1, sticky="ew", padx=6, pady=6
        )

        ttk.Label(dialog, text="Tags").grid(
            row=1, column=0, sticky=tk.W, padx=6, pady=6
        )
        tags_var = tk.StringVar(value=", ".join(task.tags))
        ttk.Entry(dialog, textvariable=tags_var).grid(
            row=1, column=1, sticky="ew", padx=6, pady=6
        )

        ttk.Label(dialog, text="Due (DD/MM/YYYY)").grid(
            row=2, column=0, sticky=tk.W, padx=6, pady=6
        )
        due_var = tk.StringVar(value=format_date_ui(task.due_date))
        ttk.Entry(dialog, textvariable=due_var).grid(
            row=2, column=1, sticky="ew", padx=6, pady=6
        )

        ttk.Label(dialog, text="Note").grid(
            row=3, column=0, sticky=tk.NW, padx=6, pady=6
        )
        note_frame = ttk.Frame(dialog)
        note_frame.grid(row=3, column=1, sticky="nsew", padx=6, pady=6)
        note_frame.columnconfigure(0, weight=1)
        note_frame.rowconfigure(0, weight=1)
        note_text = tk.Text(note_frame, height=4, wrap="word")
        note_scroll = ttk.Scrollbar(note_frame, orient=tk.VERTICAL, command=note_text.yview)
        note_text.configure(yscrollcommand=note_scroll.set)
        note_text.grid(row=0, column=0, sticky="nsew")
        note_scroll.grid(row=0, column=1, sticky="ns")
        if task.note:
            note_text.insert("1.0", task.note)

        def submit() -> None:
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
                updated = self.service.update_task(
                    task.id,
                    {"title": title, "tags": tags, "note": note, "due_date": due_date},
                )
            except ValueError as exc:
                messagebox.showerror("Error", str(exc))
                return
            dialog.destroy()
            self.refresh_tasks(select_task_id=updated.id)

        ttk.Button(dialog, text="Save", command=submit).grid(
            row=4, column=0, columnspan=2, pady=10
        )

    def _toggle_task_done(self) -> None:
        task = self.tasks_by_id.get(self.current_task_id or "")
        if not task:
            return
        done = task.status != "done"
        try:
            updated = self.service.set_task_done(task.id, done)
        except ValueError as exc:
            messagebox.showerror("Error", str(exc))
            return
        self.refresh_tasks(select_task_id=updated.id)

    def _delete_task(self) -> None:
        task = self.tasks_by_id.get(self.current_task_id or "")
        if not task:
            messagebox.showerror("No task", "Select a task first.")
            return
        if not messagebox.askyesno("Delete task", "Delete the selected task?"):
            return
        try:
            self.service.delete_task(task.id)
        except ValueError as exc:
            messagebox.showerror("Error", str(exc))
            return
        self.refresh_tasks()

    def refresh_projects(self) -> None:
        totals = self.service.time_today()
        task_counts = self._count_open_tasks_by_project()
        self.projects_by_id = {
            project.id: project for project in self.service.storage.read_projects()
        }
        query = self.entry_search_var.get().strip().lower()
        show_archived = bool(self.show_archived_var.get())
        projects = list(self.projects_by_id.values())
        if not show_archived:
            projects = [project for project in projects if project.status == "active"]
        if query:
            projects = [
                project for project in projects if self._project_matches_query(project, query)
            ]
        
        self.project_tree.delete(*self.project_tree.get_children())
        
        # Load expand/collapse state from prefs
        expanded_projects = set(self.gui_prefs.get("expanded_projects", []))
        
        # Build hierarchical structure
        # First pass: insert root projects (no parent)
        def insert_project_recursive(project: Project, parent_iid: str = "", depth: int = 0) -> None:
            status_flag = "●" if project.status == "active" else "○"
            people_label = format_people_inline(project.person)
            open_tasks = task_counts.get(project.id, 0)
            
            # Add indentation prefix for hierarchy display
            indent = "  " * depth
            display_name = f"{indent}{project.name}" if depth > 0 else project.name
            
            values = []
            for col in AVAILABLE_PROJECT_COLUMNS:
                if col == "name":
                    values.append(display_name)
                elif col == "people":
                    values.append(people_label)
                elif col == "tasks_open":
                    values.append(str(open_tasks))
                elif col == "status":
                    values.append(status_flag)
            
            # Insert into tree
            iid = self.project_tree.insert(
                parent_iid,
                tk.END,
                iid=project.id,
                values=values,
                tags=("even" if depth % 2 == 0 else "odd",),
                open=project.id in expanded_projects,  # Restore expand state
            )
            
            # Insert children recursively
            children = self.service.storage.get_project_children(project.id)
            children = [c for c in children if c in projects]  # Filter by query/archived
            for child in children:
                insert_project_recursive(child, iid, depth + 1)
        
        # Get root projects and insert them with their children
        root_projects = [p for p in projects if p.parent_id is None]
        sorted_roots = sorted(root_projects, key=lambda p: p.display_order)
        
        for project in sorted_roots:
            insert_project_recursive(project)
        
        self._update_project_sort_headers()
        if self.current.project_id and self.project_tree.exists(self.current.project_id):
            self.project_tree.selection_set(self.current.project_id)
            self._load_project_details(self.projects_by_id.get(self.current.project_id))
        else:
            self.current.project_id = None
            self._load_project_details(None)
        self.refresh_entries()
        self.refresh_tasks()
        self._update_time_today()
        self._update_project_today_times()
        self._set_status("Projects refreshed")

    def _sort_projects(
        self,
        projects: list[Project],
        totals: dict[str, int],
        task_counts: dict[str, int],
    ) -> list[Project]:
        if not self.project_sort_col or not self.project_sort_dir:
            return sorted(projects, key=lambda item: item.name)

        col = self.project_sort_col

        def value_for(project: Project) -> object:
            if col == "name":
                return project.name
            if col == "people":
                return " ".join(split_people(project.person))
            if col == "tasks_open":
                return task_counts.get(project.id, 0)
            if col == "status":
                return project.status
            if col == "person":
                return project.person or ""
            if col == "group":
                return project.group or ""
            if col == "tags":
                return " ".join(project.tags)
            return project.name

        non_empty: list[tuple[object, Project]] = []
        empty: list[Project] = []
        for project in projects:
            raw_value = value_for(project)
            if raw_value is None:
                empty.append(project)
                continue
            if isinstance(raw_value, str):
                if not raw_value.strip():
                    empty.append(project)
                    continue
                sort_value: object = raw_value.lower()
            else:
                sort_value = raw_value
            non_empty.append((sort_value, project))

        reverse = self.project_sort_dir == "desc"
        non_empty.sort(key=lambda item: item[0], reverse=reverse)
        return [project for _value, project in non_empty] + empty

    def _update_project_today_times(self) -> None:
        if "people" not in self.project_tree["columns"]:
            return
        for project_id in self.project_tree.get_children():
            project = self.projects_by_id.get(project_id)
            label = format_people_inline(project.person) if project else ""
            self.project_tree.set(project_id, "people", label)

    def _update_project_task_counts(self) -> None:
        counts = self._count_open_tasks_by_project()
        for project_id in self.project_tree.get_children():
            self.project_tree.set(project_id, "tasks_open", str(counts.get(project_id, 0)))

    def _on_entry_search_change(self, *_args: object) -> None:
        self._on_project_search_change()
        if self._search_after_id:
            self.after_cancel(self._search_after_id)
        self._search_after_id = self.after(200, self._apply_entry_search)

    def _apply_entry_search(self) -> None:
        if self._search_after_id:
            self.after_cancel(self._search_after_id)
            self._search_after_id = None
        self.refresh_projects()

    def _is_global_search_active(self) -> bool:
        return bool(self.search_global_mode_var.get()) and bool(
            self.entry_search_var.get().strip()
        )

    def _get_global_search_results(self) -> tuple[list[Project], list[EntryMeta]]:
        if not self._is_global_search_active():
            self._global_search_cache_query = ""
            self._global_search_cache_include_body = False
            self._global_search_cache_projects = []
            self._global_search_cache_entries = []
            return [], []
        query = self.entry_search_var.get().strip()
        include_body = bool(self.search_include_body_var.get())
        if (
            query == self._global_search_cache_query
            and include_body == self._global_search_cache_include_body
        ):
            return self._global_search_cache_projects, self._global_search_cache_entries
        
        # Use advanced search if query contains field:value patterns
        # Otherwise fallback to basic search
        if ":" in query and any(
            field in query.lower() 
            for field in ["tag:", "person:", "group:", "type:", "date:", "status:", "title:"]
        ):
            projects, entries = self.service.advanced_search(query, include_body=include_body)
        else:
            projects, entries = self.service.search(query, include_body=include_body)
        
        self._global_search_cache_query = query
        self._global_search_cache_include_body = include_body
        self._global_search_cache_projects = projects
        self._global_search_cache_entries = entries
        return projects, entries

    def _refresh_people_filter_options(
        self, entries: list[EntryMeta] | None = None
    ) -> None:
        if not hasattr(self, "entry_person_filter"):
            return
        if entries is None:
            entries = self.service.storage.read_entries_meta()
        people_map: dict[str, str] = {}
        for entry in entries:
            for person in split_people(entry.person):
                key = person.lower()
                if key not in people_map:
                    people_map[key] = person
        projects = self.service.list_projects(status="all")
        if not self.show_archived_var.get():
            projects = [project for project in projects if project.status == "active"]
        for project in projects:
            for person in split_people(project.person):
                key = person.lower()
                if key not in people_map:
                    people_map[key] = person
        people = sorted(people_map.values(), key=lambda item: item.lower())
        values = ["All", *people]
        self.entry_person_filter.configure(values=values)
        current = self.entry_person_filter_var.get().strip()
        if not current or current == "All":
            if self.entry_person_filter_var.get() != "All":
                self.entry_person_filter_var.set("All")
            return
        current_key = current.lower()
        if current_key in people_map:
            canonical = people_map[current_key]
            if current != canonical:
                self.entry_person_filter_var.set(canonical)
        else:
            self.entry_person_filter_var.set("All")

    def refresh_entries(self, select_entry_id: str | None = None) -> None:
        self.entries_by_id = {}
        self.entry_tree.delete(*self.entry_tree.get_children())
        all_entries = self.service.storage.read_entries_meta()
        self._refresh_people_filter_options(all_entries)
        global_active = self._is_global_search_active()
        query_text = self.entry_search_var.get().strip()
        entries: list[EntryMeta] = []
        if global_active:
            _projects, entries = self._get_global_search_results()
        else:
            if not self.current.project_id:
                self._clear_editor()
                self._update_project_details_stats()
                return
            entries = [
                entry
                for entry in all_entries
                if entry.project_id == self.current.project_id
            ]
            entries.sort(key=lambda item: item.ts)
        for entry in entries:
            self.entries_by_id[entry.id] = entry

        display_entries = list(entries)
        filter_label = self.entry_type_filter_var.get()
        if filter_label and filter_label != "All":
            internal_type = _internal_entry_type(filter_label)
            display_entries = [
                entry for entry in display_entries if entry.type == internal_type
            ]
        query = query_text.lower()
        if query and not global_active:
            display_entries = [
                entry
                for entry in display_entries
                if query
                in " ".join(
                    [
                        entry.title,
                        " ".join(entry.tags),
                        entry.person or "",
                        entry.group or "",
                    ]
                ).lower()
            ]
        person = self.entry_person_filter_var.get().strip()
        if person and person != "All":
            target = person.lower()
            display_entries = [
                entry
                for entry in display_entries
                if target in [name.lower() for name in split_people(entry.person)]
            ]
        if not self.show_treated_var.get():
            display_entries = [
                entry
                for entry in display_entries
                if normalize_context_status(getattr(entry, "context_status", None))
                != "treated"
            ]

        display_entries = self._sort_entries(display_entries)
        self._update_entry_sort_headers()

        project_names: dict[str, str] = {}
        if global_active:
            project_names = {
                project.id: project.name for project in self.service.storage.read_projects()
            }
        for index, entry in enumerate(display_entries):
            entry_dt = dates.parse_utc_z(entry.ts).astimezone()
            entry_date = getattr(entry, "entry_date", None) or entry_dt.date().isoformat()
            entry_date_label = format_date_ui(entry_date)
            start_time = getattr(entry, "start_time", None)
            end_time = getattr(entry, "end_time", None)
            creation_time_label = entry_dt.strftime("%H:%M")
            time_label = creation_time_label
            if entry.type == "meeting" and start_time and end_time:
                time_label = f"{start_time}-{end_time}"
            display_type = _display_entry_type(entry.type)
            context_status = normalize_context_status(getattr(entry, "context_status", None))
            if context_status == "treated":
                context_label = "Treated"
            elif context_status == "actual":
                context_label = "Actual"
            else:
                context_label = "Created"
            done_label = ""
            if entry.type == "decision" and entry.decision_done is not None:
                done_label = "Y" if entry.decision_done else "N"
            people_label = format_people_inline(entry.person)
            tags_label = strings.format_tags(entry.tags)
            title_label = entry.title
            if project_names:
                project_name = project_names.get(entry.project_id, entry.project_id or "Unknown")
                title_label = f"[{project_name}] {entry.title}"
            self.entry_tree.insert(
                "",
                tk.END,
                iid=entry.id,
                values=(
                    entry_date_label,
                    time_label,
                    display_type,
                    context_label,
                    done_label,
                    title_label,
                    people_label,
                    tags_label,
                ),
                tags=("even" if index % 2 == 0 else "odd",),
            )

        target_id = select_entry_id or self.current.entry_id
        if target_id and self.entry_tree.exists(target_id):
            self.entry_tree.selection_set(target_id)
            self.entry_tree.see(target_id)
        else:
            self.current.entry_id = None
            self.current_entry_path = None
            self._clear_editor()
        self._update_project_details_stats()

    def _on_entry_sort(self, col: str) -> None:
        if col == self.entry_sort_col:
            self.entry_sort_desc = not self.entry_sort_desc
        else:
            self.entry_sort_col = col
            self.entry_sort_desc = False
        self.refresh_entries(select_entry_id=self.current.entry_id)

    def _sort_entries(self, entries: list[EntryMeta]) -> list[EntryMeta]:
        def key(entry: EntryMeta) -> tuple:
            if self.entry_sort_col == "date":
                if entry.entry_date:
                    return (entry.entry_date, entry.ts)
                entry_dt = dates.parse_utc_z(entry.ts).astimezone()
                return (entry_dt.date().isoformat(), entry.ts)
            if self.entry_sort_col == "time":
                if entry.type == "meeting" and entry.start_time:
                    return (0, entry.start_time, entry.ts)
                entry_dt = dates.parse_utc_z(entry.ts).astimezone()
                return (1, entry_dt.strftime("%H:%M:%S"), entry.ts)
            if self.entry_sort_col == "type":
                return (entry.type.lower(), entry.ts)
            if self.entry_sort_col == "context":
                status = normalize_context_status(getattr(entry, "context_status", None))
                rank = {"actual": 0, "created": 1, "treated": 2}
                return (rank.get(status, 3), entry.ts)
            if self.entry_sort_col == "done":
                if entry.decision_done is True:
                    flag = 1
                elif entry.decision_done is False:
                    flag = 0
                else:
                    flag = 2
                return (flag, entry.ts)
            if self.entry_sort_col == "title":
                return (entry.title.lower(), entry.ts)
            if self.entry_sort_col == "people":
                return (" ".join(split_people(entry.person)).lower(), entry.ts)
            if self.entry_sort_col == "tags":
                return (", ".join(entry.tags).lower(), entry.ts)
            return (entry.ts,)

        return sorted(entries, key=key, reverse=self.entry_sort_desc)

    def _update_entry_sort_headers(self) -> None:
        labels = {
            "date": "Date",
            "time": "Time",
            "type": "Type",
            "context": "Context",
            "done": "Done",
            "title": "Title",
            "people": "People",
            "tags": "Tags",
        }
        arrow = "↓" if self.entry_sort_desc else "↑"
        for col, text in labels.items():
            label = f"{text} {arrow}" if col == self.entry_sort_col else text
            self.entry_tree.heading(col, text=label)

    def _load_entry(self, entry_id: str) -> None:
        entry = self.entries_by_id.get(entry_id)
        if not entry:
            return
        self.current.entry_id = entry_id
        self.current_entry_path = self.storage.data_dir / entry.content_path
        content = ""
        if self.current_entry_path.exists():
            with open(self.current_entry_path, "r", encoding="utf-8") as handle:
                content = handle.read()
        else:
            messagebox.showwarning(
                "Missing file",
                f"Content file missing: {entry.content_path}",
            )
        self._cancel_autosave()
        self._loading_entry = True
        self.editor_text.delete("1.0", tk.END)
        self.editor_text.insert("1.0", content)
        self.editor_text.edit_modified(False)
        self._loading_entry = False
        self.dirty = False
        self.editor_title_var.set(f"{entry.title} ({_display_entry_type(entry.type)})")
        self._set_status(f"Loaded entry {entry.title}")
        self._load_entry_details(entry)
        self._update_save_button_state()
        self._update_task_action_state()

    def _save_entry(self) -> bool:
        if not self.current.entry_id:
            messagebox.showerror("No entry", "No entry selected to save.")
            return False
        self._cancel_autosave()
        saved = self._write_entry_content(autosave=False, show_error=True)
        if not saved:
            return False
        self._update_save_button_state()
        return True

    def _new_project(self) -> None:
        dialog = tk.Toplevel(self)
        dialog.title("New Project")
        dialog.grab_set()
        dialog.transient(self)
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



        def submit() -> None:
            name = name_var.get().strip()
            if not name:
                messagebox.showerror("Validation", "Project name is required")
                return
            tags = strings.parse_tags(tags_var.get())
            try:
                project = self.service.create_project(
                    name,
                    desc_var.get().strip() or None,
                    tags,
                    self._get_people_text_value(person_text),
                    group_var.get().strip() or None,
                )
            except ValueError as exc:
                messagebox.showerror("Error", str(exc))
                return
            dialog.destroy()
            self.refresh_projects()
            self.project_tree.selection_set(project.id)
            self.project_tree.see(project.id)

        ttk.Button(dialog, text="Create", command=submit).grid(
            row=5, column=0, columnspan=2, pady=10
        )

    def _new_entry(self, prefill_people: list[str] | None = None) -> None:
        if not self.current.project_id:
            messagebox.showerror("No project", "Select a project first.")
            return
        if not self._confirm_save_if_dirty():
            return
        dialog = tk.Toplevel(self)
        dialog.title("New Entry")
        dialog.grab_set()
        dialog.transient(self)
        dialog.resizable(True, True)
        dialog.columnconfigure(1, weight=1)
        dialog.rowconfigure(6, weight=1)
        dialog.rowconfigure(10, weight=1)

        project = self.projects_by_id.get(self.current.project_id)
        today_label = datetime.now().astimezone().date().isoformat()

        ttk.Label(dialog, text="Date (DD/MM/YYYY)").grid(
            row=0, column=0, sticky=tk.W, padx=6, pady=6
        )
        date_var = tk.StringVar(value=format_date_ui(today_label))
        ttk.Entry(dialog, textvariable=date_var, width=18).grid(
            row=0, column=1, padx=6, pady=6, sticky=tk.W
        )
        
        ttk.Label(dialog, text="Type").grid(row=1, column=0, sticky=tk.W, padx=6, pady=6)

        type_var = tk.StringVar(value=TYPE_INTERNAL_TO_DISPLAY["note"])
        type_box = ttk.Combobox(
            dialog,
            textvariable=type_var,
            values=DISPLAY_ENTRY_TYPES,
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
        if prefill_people is not None:
            people_text = join_people_storage(prefill_people)
            if people_text:
                person_text.insert("1.0", people_text)
        elif project and project.person:
            people_text = join_people_storage(split_people(project.person))
            if people_text:
                person_text.insert("1.0", people_text)

        ttk.Label(dialog, text="Group").grid(
            row=4, column=0, sticky=tk.W, padx=6, pady=6
        )
        group_var = tk.StringVar(value=project.group if project else "")
        ttk.Entry(dialog, textvariable=group_var, width=40).grid(
            row=4, column=1, padx=6, pady=6, sticky="ew"
        )

        ttk.Label(dialog, text="Tags").grid(row=5, column=0, sticky=tk.W, padx=6, pady=6)
        tags_var = tk.StringVar()
        ttk.Entry(dialog, textvariable=tags_var, width=40).grid(
            row=5, column=1, padx=6, pady=6, sticky="ew"
        )

        ttk.Label(dialog, text="Known tags").grid(
            row=6, column=0, sticky=tk.NW, padx=6, pady=6
        )
        tag_frame = ttk.Frame(dialog)
        tag_frame.grid(row=6, column=1, padx=6, pady=6, sticky="nsew")
        tag_frame.columnconfigure(0, weight=1)
        tag_frame.rowconfigure(0, weight=1)
        tag_list = tk.Listbox(tag_frame, selectmode=tk.MULTIPLE, height=5)
        tag_scroll = ttk.Scrollbar(tag_frame, orient=tk.VERTICAL, command=tag_list.yview)
        tag_list.configure(yscrollcommand=tag_scroll.set)
        for tag in self._collect_known_tags():
            tag_list.insert(tk.END, tag)
        tag_list.grid(row=0, column=0, padx=4, pady=4, sticky="nsew")
        tag_scroll.grid(row=0, column=1, sticky="ns", padx=(0, 4), pady=4)
        ttk.Button(
            tag_frame,
            text="Add selected",
            command=lambda: self._add_tags_from_list(tag_list, tags_var),
        ).grid(row=1, column=0, columnspan=2, padx=4, pady=4, sticky=tk.W)

        start_label = ttk.Label(dialog, text="Start (HH:MM)")
        start_label.grid(
            row=7, column=0, sticky=tk.W, padx=6, pady=6
        )
        start_var = tk.StringVar()
        start_entry = ttk.Entry(dialog, textvariable=start_var, width=12)
        start_entry.grid(row=7, column=1, padx=6, pady=6, sticky=tk.W)

        end_label = ttk.Label(dialog, text="End (HH:MM)")
        end_label.grid(
            row=8, column=0, sticky=tk.W, padx=6, pady=6
        )
        end_var = tk.StringVar()
        end_entry = ttk.Entry(dialog, textvariable=end_var, width=12)
        end_entry.grid(row=8, column=1, padx=6, pady=6, sticky=tk.W)

        decision_label = ttk.Label(dialog, text="Applied/Done")
        decision_label.grid(
            row=9, column=0, sticky=tk.W, padx=6, pady=6
        )
        decision_var = tk.BooleanVar(value=False)
        decision_check = ttk.Checkbutton(dialog, variable=decision_var)
        decision_check.grid(row=9, column=1, padx=6, pady=6, sticky=tk.W)

        ttk.Label(dialog, text="Body").grid(
            row=10, column=0, sticky=tk.NW, padx=6, pady=6
        )
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
            people_inline = ", ".join(
                split_people(person_text.get("1.0", "end-1c"))
            )
            values = {
                "date": date_var.get().strip(),
                "title": title_var.get().strip(),
                "project": project.name if project else "",
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

        def submit() -> None:
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
                entry, _md_path = self.service.add_entry(
                    self.current.project_id,
                    entry_type,
                    title,
                    tags,
                    body,
                    entry_date=entry_date,
                    person=self._get_people_text_value(person_text),
                    group=group_var.get().strip() or None,
                    start_time=(start_var.get().strip() or None)
                    if entry_type == "meeting"
                    else None,
                    end_time=(end_var.get().strip() or None)
                    if entry_type == "meeting"
                    else None,
                    decision_done=decision_var.get() if entry_type == "decision" else None,
                )
            except ValueError as exc:
                messagebox.showerror("Error", str(exc))
                return
            dialog.destroy()
            self.refresh_entries(select_entry_id=entry.id)
            self._load_entry(entry.id)

        type_box.bind("<<ComboboxSelected>>", toggle_fields)
        toggle_fields()

        ttk.Button(dialog, text="Create", command=submit).grid(
            row=11, column=0, columnspan=2, pady=10
        )

    def _add_manual_time_dialog(self) -> None:
        if not self.current.project_id:
            messagebox.showerror("No project", "Select a project first.")
            return

        dialog = tk.Toplevel(self)
        dialog.title("Add Manual Time")
        dialog.grab_set()
        dialog.transient(self)
        dialog.resizable(False, False)
        dialog.columnconfigure(1, weight=1)

        ttk.Label(dialog, text="Duration (HH:MM or minutes)").grid(
            row=0, column=0, sticky=tk.W, padx=6, pady=6
        )
        duration_var = tk.StringVar(value="00:30")
        duration_entry = ttk.Entry(dialog, textvariable=duration_var, width=16)
        duration_entry.grid(row=0, column=1, padx=6, pady=6, sticky=tk.W)

        ttk.Label(dialog, text="Date (DD/MM/YYYY)").grid(
            row=1, column=0, sticky=tk.W, padx=6, pady=6
        )
        today_label = format_date_ui(datetime.now().astimezone().date())
        date_var = tk.StringVar(value=today_label)
        ttk.Entry(dialog, textvariable=date_var, width=16).grid(
            row=1, column=1, padx=6, pady=6, sticky=tk.W
        )

        ttk.Label(dialog, text="Note").grid(
            row=2, column=0, sticky=tk.W, padx=6, pady=6
        )
        note_var = tk.StringVar(value="")
        ttk.Entry(dialog, textvariable=note_var, width=40).grid(
            row=2, column=1, padx=6, pady=6, sticky=tk.W
        )

        activity_var = tk.BooleanVar(value=bool(self.create_activity_var.get()))
        ttk.Checkbutton(
            dialog, text="Create activity entry", variable=activity_var
        ).grid(row=3, column=0, columnspan=2, sticky=tk.W, padx=6, pady=6)

        button_frame = ttk.Frame(dialog)
        button_frame.grid(row=4, column=0, columnspan=2, padx=6, pady=10, sticky=tk.E)
        ttk.Button(button_frame, text="Cancel", command=dialog.destroy).pack(
            side=tk.RIGHT, padx=(6, 0)
        )

        def submit() -> None:
            try:
                duration_sec = self._parse_manual_duration(duration_var.get())
            except ValueError as exc:
                messagebox.showerror("Validation", str(exc))
                return
            if duration_sec <= 0:
                messagebox.showerror("Validation", "Duration must be greater than zero")
                return
            date_text = date_var.get().strip()
            if date_text:
                try:
                    day_value = parse_date_ui(date_text)
                except Exception:
                    logger.exception("Exception caught in GUI operation")
                    messagebox.showerror(
                        "Validation", "Date must be DD/MM/YYYY (or YYYY-MM-DD)"
                    )
                    return
            else:
                day_value = datetime.now().astimezone().date()
            note = note_var.get().strip() or None
            try:
                self.service.add_manual_time(
                    self.current.project_id,
                    duration_sec,
                    day_value,
                    note,
                    activity_var.get(),
                )
            except ValueError as exc:
                messagebox.showerror("Error", str(exc))
                return
            dialog.destroy()
            self.refresh_entries()
            self._update_time_today()
            self._update_project_today_times()
            self._set_status("Manual time added")

        ttk.Button(button_frame, text="Add", command=submit).pack(side=tk.RIGHT)
        duration_entry.focus_set()

    def _start_timer(self) -> None:
        if not self.current.project_id:
            messagebox.showerror("No project", "Select a project first.")
            return
        note = simpledialog.askstring("Timer note", "Note (optional):")
        try:
            project = self.service.time_start(self.current.project_id, note)
        except ValueError as exc:
            messagebox.showerror("Error", str(exc))
            return
        self._set_status(f"Timer started for {project.name}")

    def _stop_timer(self) -> None:
        try:
            timelog, _project = self.service.time_stop(
                create_activity=self.create_activity_var.get()
            )
        except ValueError as exc:
            messagebox.showerror("Error", str(exc))
            return
        duration_sec = timelog.duration_sec or (timelog.duration_min or 0) * 60
        messagebox.showinfo(
            "Timer stopped", f"Duration: {self._format_duration(duration_sec)}"
        )
        self.refresh_entries()
        self._update_time_today()
        self._update_project_today_times()

    def _toggle_timer(self) -> None:
        state = self.storage.read_timer_state()
        if state.running:
            self._stop_timer()
        else:
            self._start_timer()

    def _get_selected_entry_for_export(self) -> EntryMeta | None:
        entry_id = self.current.entry_id
        if not entry_id:
            return None
        entry = self.entries_by_id.get(entry_id)
        if entry:
            return entry
        for item in self.service.storage.read_entries_meta():
            if item.id == entry_id:
                return item
        return None

    def _update_export_menu_state(self) -> None:
        project_state = "normal" if self.current.project_id else "disabled"
        self.export_menu.entryconfigure("Project (Raw)", state=project_state)
        self.export_menu.entryconfigure("Project (Narrative)...", state=project_state)
        entry = self._get_selected_entry_for_export()
        meeting_state = (
            "normal" if entry and entry.type == "meeting" else "disabled"
        )
        self.export_menu.entryconfigure("Meeting minutes...", state=meeting_state)

    def _show_export_menu(self) -> None:
        self._update_export_menu_state()
        try:
            x = self.export_button.winfo_rootx()
            y = self.export_button.winfo_rooty() + self.export_button.winfo_height()
            self.export_menu.tk_popup(x, y)
        finally:
            self.export_menu.grab_release()

    def _export_meeting_minutes_dialog(self) -> None:
        entry = self._get_selected_entry_for_export()
        if not entry or entry.type != "meeting":
            messagebox.showerror("No meeting", "Select a meeting entry first.")
            return

        dialog = tk.Toplevel(self)
        dialog.title("Export Meeting Minutes")
        dialog.grab_set()
        dialog.transient(self)
        dialog.resizable(False, False)
        dialog.columnconfigure(1, weight=1)

        include_decisions_var = tk.BooleanVar(value=True)
        include_tasks_var = tk.BooleanVar(value=True)
        internal_var = tk.BooleanVar(value=False)
        window_days_var = tk.StringVar(value="1")
        out_var = tk.StringVar(value="")

        ttk.Checkbutton(
            dialog, text="Include decisions", variable=include_decisions_var
        ).grid(row=0, column=0, columnspan=2, sticky=tk.W, padx=6, pady=4)
        ttk.Checkbutton(
            dialog, text="Include tasks", variable=include_tasks_var
        ).grid(row=1, column=0, columnspan=2, sticky=tk.W, padx=6, pady=4)
        ttk.Label(dialog, text="Window (days)").grid(
            row=2, column=0, sticky=tk.W, padx=6, pady=4
        )
        ttk.Entry(dialog, textvariable=window_days_var, width=8).grid(
            row=2, column=1, sticky=tk.W, padx=6, pady=4
        )
        ttk.Checkbutton(
            dialog, text="Internal annexes", variable=internal_var
        ).grid(row=3, column=0, columnspan=2, sticky=tk.W, padx=6, pady=4)
        redact_var = tk.BooleanVar(value=False)
        ttk.Checkbutton(
            dialog,
            text="Redact entry content",
            variable=redact_var,
        ).grid(row=4, column=0, columnspan=2, sticky=tk.W, padx=6, pady=4)

        ttk.Label(dialog, text="Save as").grid(
            row=5, column=0, sticky=tk.W, padx=6, pady=4
        )
        ttk.Entry(dialog, textvariable=out_var).grid(
            row=5, column=1, sticky="ew", padx=6, pady=4
        )

        def browse_out() -> None:
            path = filedialog.asksaveasfilename(
                parent=dialog,
                title="Save meeting minutes",
                defaultextension=".md",
                initialdir=str(self.storage.exports_dir),
            )
            if path:
                out_var.set(path)

        ttk.Button(dialog, text="Browse", command=browse_out).grid(
            row=5, column=2, padx=6, pady=4
        )

        button_frame = ttk.Frame(dialog)
        button_frame.grid(row=6, column=0, columnspan=3, sticky=tk.E, padx=6, pady=8)
        ttk.Button(button_frame, text="Cancel", command=dialog.destroy).pack(
            side=tk.RIGHT, padx=(6, 0)
        )

        def submit() -> None:
            try:
                window_days = int(window_days_var.get().strip() or "1")
            except ValueError:
                messagebox.showerror("Validation", "Window must be an integer.")
                return
            if window_days < 0:
                messagebox.showerror(
                    "Validation", "Window must be zero or positive."
                )
                return
            out_path = out_var.get().strip() or None
            try:
                export_path = self.service.export_meeting_minutes(
                    entry.id,
                    out_path,
                    include_decisions=include_decisions_var.get(),
                    include_tasks=include_tasks_var.get(),
                    window_days=window_days,
                    internal=internal_var.get(),
                    redact_bodies=redact_var.get(),
                )
            except ValueError as exc:
                messagebox.showerror("Error", str(exc))
                return
            dialog.destroy()
            export_path_obj = Path(export_path)
            if messagebox.askyesno("Exported", "Open exported file?"):
                if not _open_path(export_path_obj):
                    messagebox.showinfo("Exported", str(export_path_obj))
            else:
                self._set_status(f"Exported to {export_path_obj}")

        ttk.Button(button_frame, text="Export", command=submit).pack(side=tk.RIGHT)

    def _export_weekly_summary_dialog(self) -> None:
        dialog = tk.Toplevel(self)
        dialog.title("Export Weekly Summary")
        dialog.grab_set()
        dialog.transient(self)
        dialog.resizable(False, False)
        dialog.columnconfigure(1, weight=1)

        today = datetime.now().astimezone().date()
        default_start = today - timedelta(days=6)
        default_end = today

        ttk.Label(dialog, text="From (DD/MM/YYYY)").grid(
            row=0, column=0, sticky=tk.W, padx=6, pady=6
        )
        from_var = tk.StringVar(value=format_date_ui(default_start))
        ttk.Entry(dialog, textvariable=from_var, width=14).grid(
            row=0, column=1, sticky=tk.W, padx=6, pady=6
        )

        ttk.Label(dialog, text="To (DD/MM/YYYY)").grid(
            row=1, column=0, sticky=tk.W, padx=6, pady=6
        )
        to_var = tk.StringVar(value=format_date_ui(default_end))
        ttk.Entry(dialog, textvariable=to_var, width=14).grid(
            row=1, column=1, sticky=tk.W, padx=6, pady=6
        )

        projects = self.service.storage.read_projects()
        name_counts: dict[str, int] = {}
        for project in projects:
            key = project.name.strip().lower()
            name_counts[key] = name_counts.get(key, 0) + 1

        project_labels = ["All"]
        project_lookup: dict[str, str | None] = {"All": None}
        for project in sorted(projects, key=lambda item: item.name.lower()):
            key = project.name.strip().lower()
            if name_counts.get(key, 0) > 1:
                label = f"{project.name} ({project.id[:8]})"
            else:
                label = project.name
            project_labels.append(label)
            project_lookup[label] = project.id

        ttk.Label(dialog, text="Project").grid(
            row=2, column=0, sticky=tk.W, padx=6, pady=6
        )
        project_var = tk.StringVar(value="All")
        project_box = ttk.Combobox(
            dialog,
            textvariable=project_var,
            values=project_labels,
            state="readonly",
            width=28,
        )
        project_box.grid(row=2, column=1, sticky=tk.W, padx=6, pady=6)

        include_time_var = tk.BooleanVar(value=False)
        ttk.Checkbutton(
            dialog, text="Include time", variable=include_time_var
        ).grid(row=3, column=0, columnspan=2, sticky=tk.W, padx=6, pady=6)

        button_frame = ttk.Frame(dialog)
        button_frame.grid(row=4, column=0, columnspan=2, sticky=tk.E, padx=6, pady=10)
        ttk.Button(button_frame, text="Cancel", command=dialog.destroy).pack(
            side=tk.RIGHT, padx=(6, 0)
        )

        def submit() -> None:
            try:
                start = parse_date_ui(from_var.get())
                end = parse_date_ui(to_var.get())
            except ValueError as exc:
                messagebox.showerror("Validation", str(exc))
                return
            if start > end:
                messagebox.showerror("Validation", "Start date is after end date.")
                return
            project_label = project_var.get().strip()
            if project_label not in project_lookup:
                messagebox.showerror("Validation", "Select a valid project.")
                return
            project_id = project_lookup.get(project_label)
            try:
                export_path = self.service.export_weekly_summary(
                    start,
                    end,
                    project_id,
                    None,
                    include_time=include_time_var.get(),
                )
            except ValueError as exc:
                messagebox.showerror("Error", str(exc))
                return
            dialog.destroy()
            export_path_obj = Path(export_path)
            if messagebox.askyesno("Exported", "Open exported file?"):
                if not _open_path(export_path_obj):
                    messagebox.showinfo("Exported", str(export_path_obj))
            else:
                self._set_status(f"Exported to {export_path_obj}")

        ttk.Button(button_frame, text="Export", command=submit).pack(side=tk.RIGHT)

    def _export_raw(self, redact_bodies: bool = False) -> None:
        if not self.current.project_id:
            messagebox.showerror("No project", "Select a project first.")
            return
        try:
            export_path, warnings = self.service.export_project_raw(
                self.current.project_id,
                None,
                None,
                None,
                redact_bodies=redact_bodies,
            )
        except ValueError as exc:
            messagebox.showerror("Error", str(exc))
            return
        if warnings:
            messagebox.showwarning("Export warnings", "\n".join(warnings))
        if messagebox.askyesno("Exported", "Open exported file?"):
            if not _open_path(export_path):
                messagebox.showinfo("Exported", str(export_path))
        else:
            self._set_status(f"Exported to {export_path}")

    def _export_narrative_dialog(self) -> None:
        if not self.current.project_id:
            messagebox.showerror("No project", "Select a project first.")
            return
        dialog = tk.Toplevel(self)
        dialog.title("Export Narrative")
        dialog.grab_set()
        dialog.transient(self)
        dialog.resizable(False, False)
        dialog.columnconfigure(1, weight=1)
        ttk.Label(dialog, text="From (DD/MM/YYYY, optional)").grid(
            row=0, column=0, sticky=tk.W, padx=6, pady=6
        )
        from_var = tk.StringVar(value="")
        ttk.Entry(dialog, textvariable=from_var, width=14).grid(
            row=0, column=1, sticky=tk.W, padx=6, pady=6
        )
        ttk.Label(dialog, text="To (DD/MM/YYYY, optional)").grid(
            row=1, column=0, sticky=tk.W, padx=6, pady=6
        )
        to_var = tk.StringVar(value="")
        ttk.Entry(dialog, textvariable=to_var, width=14).grid(
            row=1, column=1, sticky=tk.W, padx=6, pady=6
        )
        ttk.Label(dialog, text="Leave both empty for full range.").grid(
            row=2, column=0, columnspan=2, sticky=tk.W, padx=6, pady=2
        )
        redact_var = tk.BooleanVar(value=False)
        ttk.Checkbutton(
            dialog,
            text="Redact entry content (replace body with [Content redacted])",
            variable=redact_var,
        ).grid(row=3, column=0, columnspan=2, sticky=tk.W, padx=6, pady=4)
        button_frame = ttk.Frame(dialog)
        button_frame.grid(row=4, column=0, columnspan=2, sticky=tk.E, padx=6, pady=10)
        ttk.Button(button_frame, text="Cancel", command=dialog.destroy).pack(
            side=tk.RIGHT, padx=(6, 0)
        )

        def submit() -> None:
            from_text = from_var.get().strip()
            to_text = to_var.get().strip()
            from_date = None
            to_date = None
            if from_text:
                try:
                    from_date = parse_date_ui(from_var.get())
                except ValueError as exc:
                    messagebox.showerror("Validation", str(exc))
                    return
            if to_text:
                try:
                    to_date = parse_date_ui(to_var.get())
                except ValueError as exc:
                    messagebox.showerror("Validation", str(exc))
                    return
            if from_date is not None and to_date is not None and from_date > to_date:
                messagebox.showerror("Validation", "Start date is after end date.")
                return
            try:
                export_path = self.service.export_project_narrative(
                    self.current.project_id,
                    from_date,
                    to_date,
                    None,
                    redact_bodies=redact_var.get(),
                )
            except ValueError as exc:
                messagebox.showerror("Error", str(exc))
                return
            dialog.destroy()
            if messagebox.askyesno("Exported", "Open exported file?"):
                if not _open_path(export_path):
                    messagebox.showinfo("Exported", str(export_path))
            else:
                self._set_status(f"Exported to {export_path}")

        ttk.Button(button_frame, text="Export", command=submit).pack(side=tk.RIGHT)

    def _backup_data_dialog(self) -> None:
        if not self._confirm_project_dirty():
            return
        if not self._confirm_entry_detail_dirty():
            return
        if not self._confirm_save_if_dirty():
            return
        path = filedialog.asksaveasfilename(
            parent=self,
            title="Save Backup",
            defaultextension=".zip",
            filetypes=[("Zip files", "*.zip")],
            initialdir=str(self.storage.exports_dir),
        )
        if not path:
            return
        try:
            output = self.service.backup_data(path)
        except ValueError as exc:
            messagebox.showerror("Backup failed", str(exc))
            return
        output_path = Path(output)
        messagebox.showinfo("Backup created", f"Backup saved to:\n{output_path}")
        self._set_status(f"Backup created: {output_path.name}")

    def _restore_data_dialog(self) -> None:
        if not self._confirm_project_dirty():
            return
        if not self._confirm_entry_detail_dirty():
            return
        if not self._confirm_save_if_dirty():
            return
        path = filedialog.askopenfilename(
            parent=self,
            title="Restore Backup",
            filetypes=[("Zip files", "*.zip")],
        )
        if not path:
            return
        if not messagebox.askyesno(
            "Restore Backup",
            "This will overwrite current data.\n\nContinue?",
        ):
            return
        try:
            self.service.restore_data(path)
        except ValueError as exc:
            messagebox.showerror("Restore failed", str(exc))
            return
        messagebox.showinfo(
            "Restore complete",
            "Restore completed successfully.\n\nPlease restart PIGE.",
        )
        self._set_status("Restore complete - restart required")

    def _compact_entries_dialog(self) -> None:
        if not self._confirm_save_if_dirty():
            return
        if not messagebox.askyesno(
            "Compact entries log",
            "This will rewrite the entries log as a snapshot of current entries only.\n\n"
            "Update and delete history will be removed. File size and load time may decrease.\n\n"
            "Consider creating a backup first (File → Backup...).\n\n"
            "Continue?",
        ):
            return
        try:
            recap = self.service.compact_entries()
        except Exception as exc:
            logger.exception("Compaction failed")
            messagebox.showerror("Compact failed", str(exc))
            return
        self.refresh_projects()
        messagebox.showinfo(
            "Compaction complete",
            f"Entries log compacted:\n{recap['before_lines']} lines → {recap['after_lines']} lines "
            f"({recap['entries_count']} entries)",
        )
        self._set_status("Entries log compacted")

    def _select_data_dir(self) -> None:
        env_dir = os.environ.get("PIGE_DATA_DIR")
        if env_dir:
            messagebox.showinfo(
                "Data Directory",
                "PIGE_DATA_DIR environment variable is set; "
                "data directory is controlled externally.\n\n"
                f"Current path:\n{env_dir}",
            )
            return
        chosen = filedialog.askdirectory(parent=self, title="Select Data Directory")
        if not chosen:
            return
        path = Path(chosen).expanduser()
        if not path.exists() or not path.is_dir():
            messagebox.showerror("Data Directory", f"Folder not found:\n{path}")
            return
        looks_like, recap = _detect_pige_data_dir(path)
        if looks_like:
            message = self._format_data_dir_recap(path, recap)
            if not messagebox.askyesno("Use this folder?", message):
                return
            self._apply_selected_data_dir(path)
            return
        if _is_dir_empty(path):
            choice = messagebox.askyesnocancel(
                "Empty folder",
                "Folder is empty. Do you want to move your CURRENT PIGE data into it?\n\n"
                f"Path:\n{path}\n\n"
                "Yes: Move current data here (recommended)\n"
                "No: Use empty folder (start fresh)\n"
                "Cancel: Abort",
            )
            if choice is None:
                return
            if choice is False:
                self._apply_selected_data_dir(path)
                return
            if not self._confirm_project_dirty():
                return
            if not self._confirm_entry_detail_dirty():
                return
            if not self._confirm_save_if_dirty():
                return
            state = self.storage.read_timer_state()
            if state.running:
                messagebox.showerror(
                    "Timer running", "Stop the timer before moving data."
                )
                return
            src_dir = self.storage.data_dir
            try:
                src_resolved = src_dir.resolve()
            except Exception:
                logger.exception("Exception caught in GUI operation")
                src_resolved = src_dir
            try:
                dest_resolved = path.resolve()
            except Exception:
                logger.exception("Exception caught in GUI operation")
                dest_resolved = path
            if dest_resolved == src_resolved:
                messagebox.showerror(
                    "Data Directory", "Selected folder is already the current data directory."
                )
                return
            if _is_subpath(dest_resolved, src_resolved) or _is_subpath(
                src_resolved, dest_resolved
            ):
                messagebox.showerror(
                    "Data Directory",
                    "Destination cannot be inside the current data directory (or vice versa).",
                )
                return
            try:
                recap = self.service.migrate_data_dir(dest_resolved)
            except ValueError as exc:
                messagebox.showerror("Data Directory", f"Migration failed:\n{exc}")
                return
            messagebox.showinfo(
                "Data Directory", self._format_data_dir_recap(dest_resolved, recap)
            )
            self._apply_selected_data_dir(dest_resolved)
            return
        messagebox.showwarning(
            "Data Directory",
            "Folder is not empty and does not look like PIGE data. Choose another folder.",
        )

    def _apply_selected_data_dir(self, path: Path) -> None:
        try:
            resolved = path.resolve()
        except Exception:
            logger.exception("Exception caught in GUI operation")
            resolved = path
        cfg = _load_global_config()
        cfg["data_dir"] = str(resolved)
        try:
            _save_global_config(cfg)
        except OSError as exc:
            messagebox.showerror("Data Directory", f"Failed to save preference:\n{exc}")
            return
        if messagebox.askyesno(
            "Restart required", "Restart PIGE now to apply the new data directory?"
        ):
            self._restart_app(confirm=False)
        else:
            messagebox.showinfo("Data Directory", "Will apply on next launch.")

    def _format_data_dir_recap(self, path: Path, recap: dict[str, int]) -> str:
        lines = [
            f"Path: {path}",
            f"Projects: {recap.get('projects', 0)}",
            f"Entries: {recap.get('entries', 0)}",
            f"Tasks: {recap.get('tasks', 0)}",
            f"Time logs: {recap.get('timelogs', 0)}",
        ]
        if "entry_files" in recap:
            lines.append(f"Entry files: {recap.get('entry_files', 0)}")
        return "\n".join(lines)

    def _open_current(self) -> None:
        if not self.current_entry_path:
            messagebox.showerror("No entry", "Select an entry first.")
            return
        if not _open_path(self.current_entry_path):
            messagebox.showinfo("Path", str(self.current_entry_path))

    def _open_data_folder(self) -> None:
        path = self.storage.data_dir
        try:
            path.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            messagebox.showerror("Error", str(exc))
            return

        if not _open_path(path):
            messagebox.showinfo("Data folder", str(path))


    def _poll_timer(self) -> None:
        if self._closing:
            return
        state = self.storage.read_timer_state()
        if state.running and state.start_ts:
            project_name = "unknown"
            if state.project_id and state.project_id in self.projects_by_id:
                project_name = self.projects_by_id[state.project_id].name
            elif state.project_id:
                project_name = state.project_id
            start_dt = dates.parse_utc_z(state.start_ts)
            now_dt = datetime.now(timezone.utc).replace(microsecond=0)
            elapsed = int((now_dt - start_dt).total_seconds())
            elapsed_label = self._format_duration(elapsed)
            self.timer_elapsed_var.set(elapsed_label)
            self.stats_timer_elapsed_var.set(elapsed_label)
            self.stats_timer_state_var.set(f"Running ({project_name})")
            self.timer_tracking_var.set(f"Tracking: {project_name} • {elapsed_label}")
            self.timer_button.configure(text="Stop Timer")
            self.timer_button.state(["!disabled"])
        else:
            self.timer_elapsed_var.set("00:00:00")
            self.stats_timer_elapsed_var.set("00:00:00")
            self.stats_timer_state_var.set("Idle")
            self.timer_tracking_var.set("Tracking: Idle")
            self.timer_button.configure(text="Start Timer")
            if self.current.project_id:
                self.timer_button.state(["!disabled"])
            else:
                self.timer_button.state(["disabled"])
        self._update_time_today()
        self._update_project_today_times()
        self._poll_after_id = self.after(1000, self._poll_timer)

    def _update_time_today(self) -> None:
        totals = self.service.time_today()
        if not self.current.project_id:
            self.stats_today_project_var.set("-")
        else:
            seconds = totals.get(self.current.project_id, 0)
            self.stats_today_project_var.set(self._format_duration(seconds))
        total_seconds = sum(totals.values())
        self.stats_today_all_var.set(self._format_duration(total_seconds))
        self._update_project_details_stats()

    def _on_close(self) -> None:
        if not self._confirm_project_dirty():
            return
        if not self._confirm_entry_detail_dirty():
            return
        if not self._confirm_save_if_dirty():
            return
        self._closing = True
        for after_id in (
            self._poll_after_id,
            self._resize_after_id,
            self._prefs_after_id,
            self._toolbar_after_id,
            self._autosave_after_id,
            self._search_after_id,
        ):
            if after_id:
                try:
                    self.after_cancel(after_id)
                except Exception:
                    logger.exception("Exception caught in GUI operation")
                    pass
        self._poll_after_id = None
        self._resize_after_id = None
        self._prefs_after_id = None
        self._toolbar_after_id = None
        self._autosave_after_id = None
        self._search_after_id = None
        self.destroy()

    def _restart_app(self, confirm: bool = True) -> None:
        if not self._confirm_project_dirty():
            return
        if not self._confirm_entry_detail_dirty():
            return
        if not self._confirm_save_if_dirty():
            return
        if confirm and not messagebox.askyesno("Restart", "Restart PIGE now?"):
            return

        # Important: relancer en mode module, pas en mode "script", sinon import pige peut échouer.
        python = sys.executable
        args = [python, "-m", "pige", "gui"]

        # Optionnel mais très recommande: se remettre a la racine du projet pour garantir l'import.
        try:
            project_root = Path(__file__).resolve().parents[2]  # .../Programme Journaling/
            os.chdir(project_root)
        except Exception:
            logger.exception("Exception caught in GUI operation")
            pass

        os.execv(python, args)

    def _show_keyboard_shortcuts(self) -> None:
        """Show a dialog with all keyboard shortcuts."""
        dialog = tk.Toplevel(self)
        dialog.title("Keyboard Shortcuts - PIGE")
        dialog.geometry("600x500")
        dialog.resizable(True, True)
        
        # Create main frame with scrollbar
        main_frame = ttk.Frame(dialog, padding=10)
        main_frame.pack(fill=tk.BOTH, expand=True)
        
        # Title
        title_label = ttk.Label(
            main_frame,
            text="Keyboard Shortcuts",
            font=("TkDefaultFont", 14, "bold")
        )
        title_label.pack(pady=(0, 10))
        
        # Create canvas and scrollbar
        canvas = tk.Canvas(main_frame, highlightthickness=0)
        scrollbar = ttk.Scrollbar(main_frame, orient=tk.VERTICAL, command=canvas.yview)
        scrollable_frame = ttk.Frame(canvas)
        
        scrollable_frame.bind(
            "<Configure>",
            lambda e: canvas.configure(scrollregion=canvas.bbox("all"))
        )
        
        canvas.create_window((0, 0), window=scrollable_frame, anchor="nw")
        canvas.configure(yscrollcommand=scrollbar.set)
        
        # Define shortcuts by category
        shortcuts = [
            ("File Operations", [
                (f"{_menu_accel('N')}", "New Project"),
                (f"{_menu_accel('E')}", "New Entry"),
                (f"{_menu_accel('S')}", "Save Entry"),
                (f"{_menu_accel('Q')}", "Quit"),
                ("Delete / Backspace", "Delete selected item"),
            ]),
            ("View", [
                ("F9", "Toggle Focus Mode"),
            ]),
            ("Editor", [
                ("Ctrl+Shift+X", "Toggle checkbox (Windows/Linux)"),
                ("Cmd+Shift+X", "Toggle checkbox (macOS)"),
                ("Ctrl++", "Zoom in (Windows/Linux)"),
                ("Ctrl+-", "Zoom out (Windows/Linux)"),
                ("Ctrl+0", "Reset zoom (Windows/Linux)"),
                ("Cmd++", "Zoom in (macOS)"),
                ("Cmd+-", "Zoom out (macOS)"),
                ("Cmd+0", "Reset zoom (macOS)"),
            ]),
            ("Navigation", [
                ("Double-click", "Open entry or toggle task"),
                ("Enter", "Apply search filter"),
            ]),
            ("Help", [
                ("F1", "Show this dialog"),
            ]),
        ]
        
        # Add shortcuts to scrollable frame
        for category, items in shortcuts:
            category_frame = ttk.LabelFrame(scrollable_frame, text=category, padding=10)
            category_frame.pack(fill=tk.X, padx=5, pady=5)
            
            for key, description in items:
                row = ttk.Frame(category_frame)
                row.pack(fill=tk.X, pady=2)
                
                key_label = ttk.Label(
                    row,
                    text=key,
                    font=("TkDefaultFont", 9, "bold"),
                    width=25,
                    anchor="w"
                )
                key_label.pack(side=tk.LEFT)
                
                desc_label = ttk.Label(row, text=description, anchor="w")
                desc_label.pack(side=tk.LEFT, fill=tk.X, expand=True)
        
        canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        
        # Close button
        button_frame = ttk.Frame(dialog)
        button_frame.pack(fill=tk.X, padx=10, pady=10)
        
        close_button = ttk.Button(
            button_frame,
            text="Close",
            command=dialog.destroy
        )
        close_button.pack(side=tk.RIGHT)
        
        # Bind Escape and F1 to close
        dialog.bind("<Escape>", lambda e: dialog.destroy())
        dialog.bind("<F1>", lambda e: dialog.destroy())
        
        # Center dialog on parent
        dialog.transient(self)
        dialog.grab_set()
        self.wait_window(dialog)

    def _show_about_dialog(self) -> None:
        """Show About PIGE dialog."""
        dialog = tk.Toplevel(self)
        dialog.title("About PIGE")
        dialog.geometry("400x300")
        dialog.resizable(False, False)
        
        frame = ttk.Frame(dialog, padding=20)
        frame.pack(fill=tk.BOTH, expand=True)
        
        # Title
        title_label = ttk.Label(
            frame,
            text="PIGE",
            font=("TkDefaultFont", 20, "bold")
        )
        title_label.pack(pady=(0, 5))
        
        # Subtitle
        subtitle_label = ttk.Label(
            frame,
            text="Project Integrated Journaling Engine",
            font=("TkDefaultFont", 10)
        )
        subtitle_label.pack(pady=(0, 20))
        
        # Version
        version_label = ttk.Label(
            frame,
            text="Version 0.2.0-dev",
            font=("TkDefaultFont", 9)
        )
        version_label.pack(pady=(0, 20))
        
        # Description
        desc_text = (
            "PIGE is a local-first project journaling tool\n"
            "that helps you organize and track your work.\n\n"
            "Features:\n"
            "• Project-based organization\n"
            "• Multiple entry types (notes, meetings, decisions)\n"
            "• Task management with time tracking\n"
            "• Export capabilities\n"
            "• All data stored locally in JSON/Markdown"
        )
        desc_label = ttk.Label(
            frame,
            text=desc_text,
            justify=tk.LEFT
        )
        desc_label.pack(pady=(0, 20))
        
        # Close button
        close_button = ttk.Button(
            frame,
            text="Close",
            command=dialog.destroy
        )
        close_button.pack()
        
        # Center dialog on parent
        dialog.transient(self)
        dialog.grab_set()



def main(argv: list[str] | None = None) -> int:
    _ = argv
    app = PigeApp(_resolve_data_dir())
    app.mainloop()
    return 0
