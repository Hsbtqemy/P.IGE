"""Dashboard panel for PIGE GUI.

This panel provides an overview of work status:
- In Progress items (entries and tasks)
- Pending/Blocked items
- Upcoming items (timeline)
- Focus suggestions
"""

from __future__ import annotations

import logging
import tkinter as tk
from datetime import date, datetime, timedelta
from tkinter import ttk
from typing import TYPE_CHECKING

from pige.core.storage import read_calendar_events
from pige.interfaces.gui.dialogs import show_edit_entry_dialog, show_edit_task_dialog

if TYPE_CHECKING:
    from pige.core.service import PigeService

logger = logging.getLogger(__name__)


class DashboardPanel(ttk.Frame):
    """Dashboard panel showing work overview and status."""
    
    def __init__(
        self,
        parent: tk.Widget,
        service: PigeService,
        initial_days: int = 7,
        **kwargs
    ) -> None:
        """Initialize dashboard panel.
        
        Args:
            parent: Parent widget
            service: PIGE service instance
            initial_days: Initial timeline period (days)
            **kwargs: Additional frame options
        """
        super().__init__(parent, **kwargs)
        self.service = service
        self.timeline_days = initial_days
        self._dashboard_sort: dict[str, tuple[str, bool]] = {}  # tree_id -> (column, reverse)

        # Setup UI
        self._setup_toolbar()
        self._setup_sections()
        
        # Initial refresh
        self.refresh()
        
        logger.debug("DashboardPanel initialized")
    
    def _setup_toolbar(self) -> None:
        """Create the toolbar with actions."""
        toolbar = ttk.Frame(self)
        toolbar.pack(fill=tk.X, pady=(0, 10))
        
        # Title
        ttk.Label(
            toolbar,
            text="📊 Dashboard - Vue d'Ensemble",
            font=("TkDefaultFont", 12, "bold")
        ).pack(side=tk.LEFT, padx=5)
        
        # Spacer
        ttk.Frame(toolbar).pack(side=tk.LEFT, fill=tk.X, expand=True)
        
        # Period filter
        ttk.Label(toolbar, text="Timeline:").pack(side=tk.LEFT, padx=(0, 5))
        
        self.period_var = tk.StringVar(value="7 days")
        period_combo = ttk.Combobox(
            toolbar,
            textvariable=self.period_var,
            values=["7 days", "14 days", "30 days"],
            state="readonly",
            width=10
        )
        period_combo.pack(side=tk.LEFT, padx=2)
        period_combo.bind("<<ComboboxSelected>>", lambda e: self._on_period_change())
        
        # Refresh button
        ttk.Button(
            toolbar,
            text="Refresh",
            command=self.refresh
        ).pack(side=tk.LEFT, padx=5)
    
    def _setup_sections(self) -> None:
        """Create the main sections."""
        # Main container with scrollbar
        main_container = ttk.Frame(self)
        main_container.pack(fill=tk.BOTH, expand=True)

        # Canvas for scrolling (vertical only); scrollbar only shown when content overflows
        self._canvas = tk.Canvas(main_container, highlightthickness=0)
        self._scrollbar = ttk.Scrollbar(main_container, orient=tk.VERTICAL, command=self._canvas.yview)
        self.scrollable_frame = ttk.Frame(self._canvas)

        def _update_scroll_visibility():
            self._canvas.update_idletasks()
            bbox = self._canvas.bbox("all")
            canvas_h = self._canvas.winfo_height()
            if not bbox or canvas_h <= 0:
                self._scrollbar.pack_forget()
                return
            content_h = bbox[3] - bbox[1]
            if content_h <= canvas_h:
                self._scrollbar.pack_forget()
                w = self._canvas.winfo_width()
                self._canvas.configure(scrollregion=(0, 0, w, canvas_h))
            else:
                if not self._scrollbar.winfo_ismapped():
                    self._scrollbar.pack(side=tk.RIGHT, fill=tk.Y)

        def _on_canvas_configure(event):
            w = event.width
            h = self._canvas.winfo_height()
            self._canvas.itemconfig(self._canvas_window_id, width=w, height=h)
            self._canvas.configure(scrollregion=self._canvas.bbox("all"))
            self.after_idle(_update_scroll_visibility)
            self.after(50, _update_scroll_visibility)

        def _on_frame_configure(_e):
            self._canvas.configure(scrollregion=self._canvas.bbox("all"))
            self.after_idle(_update_scroll_visibility)
            self.after(50, _update_scroll_visibility)

        self.scrollable_frame.bind("<Configure>", _on_frame_configure)

        self._canvas_window_id = self._canvas.create_window(
            (0, 0), window=self.scrollable_frame, anchor="nw"
        )
        self._canvas.bind("<Configure>", _on_canvas_configure)
        self._canvas.configure(yscrollcommand=self._scrollbar.set)

        self._canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        # Scrollbar packed on first overflow (see _update_scroll_visibility)

        # Mouse wheel: active only when pointer is over dashboard (avoid stealing scroll elsewhere)
        def _on_mousewheel(event):
            self._canvas.yview_scroll(int(-1 * (event.delta / 120)), "units")

        def _on_enter(_event):
            self._canvas.bind_all("<MouseWheel>", _on_mousewheel)

        def _on_leave(_event):
            self._canvas.unbind_all("<MouseWheel>")

        main_container.bind("<Enter>", _on_enter)
        main_container.bind("<Leave>", _on_leave)

        # Two columns: left = En cours + En attente, right = Journée en cours + À venir; Focus full width below
        top_row = ttk.Frame(self.scrollable_frame)
        top_row.pack(fill=tk.BOTH, expand=True)
        left_col = ttk.Frame(top_row)
        left_col.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=(10, 5), pady=5)
        right_col = ttk.Frame(top_row)
        right_col.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=(5, 10), pady=5)

        self._create_in_progress_section(parent=left_col)
        self._create_pending_section(parent=left_col)
        self._create_today_section(parent=right_col)
        self._create_upcoming_section(parent=right_col)
        self._create_focus_section()

    def _create_today_section(self, parent: tk.Widget | None = None) -> None:
        """Create the 'Journée en cours' section (entries, tasks, events for today)."""
        container = parent or self.scrollable_frame
        section = ttk.LabelFrame(
            container,
            text="📅 Journée en cours",
            padding=10
        )
        section.pack(fill=tk.BOTH, expand=True, padx=0, pady=5)

        tree_frame = ttk.Frame(section)
        tree_frame.pack(fill=tk.BOTH, expand=True)

        scrollbar = ttk.Scrollbar(tree_frame, orient=tk.VERTICAL)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)

        self.today_tree = ttk.Treeview(
            tree_frame,
            columns=("type", "title", "time", "project", "priority"),
            show="headings",
            height=5,
            yscrollcommand=scrollbar.set
        )
        self.today_tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        scrollbar.config(command=self.today_tree.yview)

        self.today_tree.heading("type", text="Type", command=lambda: self._sort_dashboard_tree(self.today_tree, "type"))
        self.today_tree.heading("title", text="Titre", command=lambda: self._sort_dashboard_tree(self.today_tree, "title"))
        self.today_tree.heading("time", text="Heure", command=lambda: self._sort_dashboard_tree(self.today_tree, "time"))
        self.today_tree.heading("project", text="Projet", command=lambda: self._sort_dashboard_tree(self.today_tree, "project"))
        self.today_tree.heading("priority", text="Prio", command=lambda: self._sort_dashboard_tree(self.today_tree, "priority"))

        self.today_tree.column("type", width=80, stretch=False)
        self.today_tree.column("title", width=260, stretch=True)
        self.today_tree.column("time", width=70, stretch=False)
        self.today_tree.column("project", width=120, stretch=False)
        self.today_tree.column("priority", width=40, stretch=False)

        self.today_tree.bind("<Double-Button-1>", self._on_today_item_double_click)

    def _sort_dashboard_tree(self, tree: ttk.Treeview, column_id: str) -> None:
        """Sort a dashboard tree by column; toggle direction if same column."""
        key = str(id(tree))
        cols = tree["columns"]
        if column_id not in cols:
            return
        col_idx = cols.index(column_id)
        cur_col, cur_rev = self._dashboard_sort.get(key, (None, False))
        if cur_col == column_id:
            reverse = not cur_rev
        else:
            reverse = column_id in ("date", "time", "since", "age")
        self._dashboard_sort[key] = (column_id, reverse)
        items = [(iid, tree.item(iid, "values"), tree.item(iid, "tags")) for iid in tree.get_children("")]
        if not items:
            return
        def sort_key(x):
            iid, vals, tags = x
            if not vals or col_idx >= len(vals):
                return "" if column_id != "priority" else 99
            v = (vals[col_idx] or "").strip().lower()
            if column_id == "priority":
                try:
                    return int(v) if v and v != "-" else 99
                except ValueError:
                    return 99
            if column_id in ("date", "time", "since", "age") and v:
                try:
                    return datetime.fromisoformat(v.replace("Z", "+00:00")).timestamp()
                except Exception:
                    pass
            return v
        items.sort(key=sort_key, reverse=reverse)
        for iid in tree.get_children(""):
            tree.delete(iid)
        for iid, vals, tags in items:
            tree.insert("", tk.END, iid=iid, values=vals, tags=tags)

    def _create_in_progress_section(self, parent: tk.Widget | None = None) -> None:
        """Create the 'In Progress' section."""
        container = parent or self.scrollable_frame
        section = ttk.LabelFrame(
            container,
            text="📋 En Cours",
            padding=10
        )
        section.pack(fill=tk.BOTH, expand=True, padx=0, pady=5)
        
        # TreeView for in-progress items
        tree_frame = ttk.Frame(section)
        tree_frame.pack(fill=tk.BOTH, expand=True)
        
        scrollbar = ttk.Scrollbar(tree_frame, orient=tk.VERTICAL)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        
        self.in_progress_tree = ttk.Treeview(
            tree_frame,
            columns=("type", "title", "project", "age", "priority"),
            show="headings",
            height=6,
            yscrollcommand=scrollbar.set
        )
        self.in_progress_tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        scrollbar.config(command=self.in_progress_tree.yview)
        
        # Configure columns
        self.in_progress_tree.heading("type", text="Type", command=lambda: self._sort_dashboard_tree(self.in_progress_tree, "type"))
        self.in_progress_tree.heading("title", text="Titre", command=lambda: self._sort_dashboard_tree(self.in_progress_tree, "title"))
        self.in_progress_tree.heading("project", text="Projet", command=lambda: self._sort_dashboard_tree(self.in_progress_tree, "project"))
        self.in_progress_tree.heading("age", text="Âge", command=lambda: self._sort_dashboard_tree(self.in_progress_tree, "age"))
        self.in_progress_tree.heading("priority", text="Prio", command=lambda: self._sort_dashboard_tree(self.in_progress_tree, "priority"))
        
        self.in_progress_tree.column("type", width=80, stretch=False)
        self.in_progress_tree.column("title", width=260, stretch=True)
        self.in_progress_tree.column("project", width=130, stretch=False)
        self.in_progress_tree.column("age", width=70, stretch=False)
        self.in_progress_tree.column("priority", width=40, stretch=False)
        
        # Bind events
        self.in_progress_tree.bind("<Double-Button-1>", self._on_item_double_click)
    
    def _create_pending_section(self, parent: tk.Widget | None = None) -> None:
        """Create the 'Pending' section."""
        container = parent or self.scrollable_frame
        section = ttk.LabelFrame(
            container,
            text="⏸️ En Attente",
            padding=10
        )
        section.pack(fill=tk.BOTH, expand=True, padx=0, pady=5)
        
        # TreeView for pending items
        tree_frame = ttk.Frame(section)
        tree_frame.pack(fill=tk.BOTH, expand=True)
        
        scrollbar = ttk.Scrollbar(tree_frame, orient=tk.VERTICAL)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        
        self.pending_tree = ttk.Treeview(
            tree_frame,
            columns=("type", "title", "project", "since", "priority"),
            show="headings",
            height=4,
            yscrollcommand=scrollbar.set
        )
        self.pending_tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        scrollbar.config(command=self.pending_tree.yview)
        
        # Configure columns
        self.pending_tree.heading("type", text="Type", command=lambda: self._sort_dashboard_tree(self.pending_tree, "type"))
        self.pending_tree.heading("title", text="Titre", command=lambda: self._sort_dashboard_tree(self.pending_tree, "title"))
        self.pending_tree.heading("project", text="Projet", command=lambda: self._sort_dashboard_tree(self.pending_tree, "project"))
        self.pending_tree.heading("since", text="Depuis", command=lambda: self._sort_dashboard_tree(self.pending_tree, "since"))
        self.pending_tree.heading("priority", text="Prio", command=lambda: self._sort_dashboard_tree(self.pending_tree, "priority"))
        
        self.pending_tree.column("type", width=80, stretch=False)
        self.pending_tree.column("title", width=260, stretch=True)
        self.pending_tree.column("project", width=130, stretch=False)
        self.pending_tree.column("since", width=70, stretch=False)
        self.pending_tree.column("priority", width=40, stretch=False)
        
        # Bind events
        self.pending_tree.bind("<Double-Button-1>", self._on_item_double_click)
    
    def _create_upcoming_section(self, parent: tk.Widget | None = None) -> None:
        """Create the 'Upcoming' section."""
        container = parent or self.scrollable_frame
        section = ttk.LabelFrame(
            container,
            text="📅 À Venir (7 prochains jours)",
            padding=10
        )
        section.pack(fill=tk.BOTH, expand=True, padx=0, pady=5)
        
        # TreeView for upcoming items
        tree_frame = ttk.Frame(section)
        tree_frame.pack(fill=tk.BOTH, expand=True)
        
        scrollbar = ttk.Scrollbar(tree_frame, orient=tk.VERTICAL)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        
        self.upcoming_tree = ttk.Treeview(
            tree_frame,
            columns=("date", "type", "title", "project", "priority"),
            show="headings",
            height=5,
            yscrollcommand=scrollbar.set
        )
        self.upcoming_tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        scrollbar.config(command=self.upcoming_tree.yview)
        
        # Configure columns
        self.upcoming_tree.heading("date", text="Date", command=lambda: self._sort_dashboard_tree(self.upcoming_tree, "date"))
        self.upcoming_tree.heading("type", text="Type", command=lambda: self._sort_dashboard_tree(self.upcoming_tree, "type"))
        self.upcoming_tree.heading("title", text="Titre", command=lambda: self._sort_dashboard_tree(self.upcoming_tree, "title"))
        self.upcoming_tree.heading("project", text="Projet", command=lambda: self._sort_dashboard_tree(self.upcoming_tree, "project"))
        self.upcoming_tree.heading("priority", text="Prio", command=lambda: self._sort_dashboard_tree(self.upcoming_tree, "priority"))
        
        self.upcoming_tree.column("date", width=100, stretch=False)
        self.upcoming_tree.column("type", width=80, stretch=False)
        self.upcoming_tree.column("title", width=260, stretch=True)
        self.upcoming_tree.column("project", width=110, stretch=False)
        self.upcoming_tree.column("priority", width=40, stretch=False)
        
        # Bind events
        self.upcoming_tree.bind("<Double-Button-1>", self._on_item_double_click)
    
    def _create_focus_section(self) -> None:
        """Create the 'Focus Suggestions' section (full width at bottom)."""
        section = ttk.LabelFrame(
            self.scrollable_frame,
            text="🎯 Focus Suggéré",
            padding=10
        )
        section.pack(fill=tk.X, padx=10, pady=5)
        
        # Text widget for suggestions
        self.focus_text = tk.Text(
            section,
            height=4,
            wrap=tk.WORD,
            relief=tk.FLAT,
            font=("TkDefaultFont", 10)
        )
        self.focus_text.pack(fill=tk.BOTH, expand=True)
        self.focus_text.config(state=tk.DISABLED)  # Read-only
    
    def refresh(self) -> None:
        """Refresh all dashboard sections."""
        logger.debug("Refreshing dashboard")

        self._refresh_today()
        self._refresh_in_progress()
        self._refresh_pending()
        self._refresh_upcoming()
        self._refresh_focus()

    def _refresh_today(self) -> None:
        """Refresh the 'Journée en cours' section with entries, tasks and events for today."""
        for item in self.today_tree.get_children():
            self.today_tree.delete(item)

        today_iso = date.today().isoformat()
        projects = self.service.list_projects(status="all")
        projects_by_id = {p.id: p for p in projects}

        # Entries for today
        all_entries = self.service.storage.read_entries_meta()
        for entry in all_entries:
            if not entry.entry_date:
                continue
            try:
                entry_date = datetime.fromisoformat(entry.entry_date).date()
                if entry_date.isoformat() != today_iso:
                    continue
            except Exception:
                continue
            proj = projects_by_id.get(entry.project_id)
            project_name = proj.name if proj else (entry.project_id[:8] if entry.project_id else "")
            time_str = entry.start_time or ""
            prio = getattr(entry, "priority", 3)
            self.today_tree.insert(
                "",
                tk.END,
                iid=f"entry_{entry.id}",
                values=("Entry", entry.title, time_str, project_name, str(prio)),
                tags=("entry",)
            )

        # Tasks due today
        for project in projects:
            try:
                tasks = self.service.list_tasks(project_id=project.id, status="all")
            except Exception:
                continue
            for task in tasks:
                if not task.due_date:
                    continue
                try:
                    task_date = datetime.fromisoformat(task.due_date).date()
                    if task_date.isoformat() != today_iso:
                        continue
                except Exception:
                    continue
                proj_prio = getattr(project, "priority", 3)
                self.today_tree.insert(
                    "",
                    tk.END,
                    iid=f"task_{task.id}",
                    values=("Task", task.title, "", project.name, str(proj_prio)),
                    tags=("task",)
                )

        # Calendar events for today
        try:
            all_events = read_calendar_events(self.service.storage)
        except Exception:
            all_events = []
        for event in all_events:
            if getattr(event, "start_date", None) != today_iso:
                continue
            time_str = getattr(event, "start_time", None) or ""
            self.today_tree.insert(
                "",
                tk.END,
                iid=f"event_{event.id}",
                values=("Event", event.title, time_str, "", "-"),
                tags=("event",)
            )

        if not self.today_tree.get_children():
            self.today_tree.insert(
                "",
                tk.END,
                values=("", "Rien de prévu aujourd'hui", "", "", "")
            )

    def _refresh_in_progress(self) -> None:
        """Refresh the 'In Progress' section."""
        # Clear existing items
        for item in self.in_progress_tree.get_children():
            self.in_progress_tree.delete(item)
        
        projects = self.service.list_projects(status="all")
        projects_by_id = {p.id: p for p in projects}
        in_progress = self.service.get_in_progress_items(days=self.timeline_days)
        
        # Add entries
        for entry in in_progress["entries"]:
            proj = projects_by_id.get(entry.project_id)
            project_name = proj.name if proj else (entry.project_id[:8] if entry.project_id else "")
            
            # Calculate age
            from datetime import datetime
            if entry.entry_date:
                entry_date = datetime.fromisoformat(entry.entry_date)
                age_days = (datetime.now().date() - entry_date.date()).days
                age_str = f"{age_days}j" if age_days > 0 else "Aujourd'hui"
            else:
                age_str = "?"
            
            # Insert into tree
            prio = getattr(entry, "priority", 3)
            self.in_progress_tree.insert(
                "",
                tk.END,
                iid=f"entry_{entry.id}",
                values=("📝 Entry", entry.title, project_name, age_str, str(prio)),
                tags=("entry",)
            )
        
        # Add tasks
        for task in in_progress["tasks"]:
            proj = projects_by_id.get(task.project_id)
            project_name = proj.name if proj else (task.project_id[:8] if task.project_id else "")
            proj_prio = getattr(proj, "priority", 3) if proj else 3
            
            # Calculate age
            from datetime import datetime
            if task.created_at:
                created_date = datetime.fromisoformat(task.created_at).replace(tzinfo=None)
                age_days = (datetime.now() - created_date).days
                age_str = f"{age_days}j" if age_days > 0 else "Aujourd'hui"
            else:
                age_str = "?"
            
            # Insert into tree
            self.in_progress_tree.insert(
                "",
                tk.END,
                iid=f"task_{task.id}",
                values=("✅ Task", task.title, project_name, age_str, str(proj_prio)),
                tags=("task",)
            )
        
        # Show message if empty
        if not in_progress["entries"] and not in_progress["tasks"]:
            self.in_progress_tree.insert(
                "",
                tk.END,
                values=("", "Aucun item en cours", "", "", "")
            )
    
    def _refresh_pending(self) -> None:
        """Refresh the 'Pending' section."""
        # Clear existing items
        for item in self.pending_tree.get_children():
            self.pending_tree.delete(item)
        
        projects = self.service.list_projects(status="all")
        projects_by_id = {p.id: p for p in projects}
        pending = self.service.get_pending_items()
        
        # Add tasks
        for task in pending["tasks"]:
            proj = projects_by_id.get(task.project_id)
            project_name = proj.name if proj else (task.project_id[:8] if task.project_id else "")
            
            # Calculate time since creation
            from datetime import datetime
            if task.created_at:
                created_date = datetime.fromisoformat(task.created_at).replace(tzinfo=None)
                days_since = (datetime.now() - created_date).days
                since_str = f"{days_since}j" if days_since > 0 else "Aujourd'hui"
            else:
                since_str = "?"
            
            # Insert into tree
            proj_prio = getattr(proj, "priority", 3) if proj else 3
            self.pending_tree.insert(
                "",
                tk.END,
                iid=f"task_{task.id}",
                values=("✅ Task", task.title, project_name, since_str, str(proj_prio)),
                tags=("task",)
            )
        
        # Add entries (if any with waiting/blocked tags)
        for entry in pending["entries"]:
            proj = projects_by_id.get(entry.project_id)
            project_name = proj.name if proj else (entry.project_id[:8] if entry.project_id else "")
            prio = getattr(entry, "priority", 3)
            
            # Calculate age
            from datetime import datetime
            if entry.entry_date:
                entry_date = datetime.fromisoformat(entry.entry_date)
                days_since = (datetime.now().date() - entry_date.date()).days
                since_str = f"{days_since}j" if days_since > 0 else "Aujourd'hui"
            else:
                since_str = "?"
            
            self.pending_tree.insert(
                "",
                tk.END,
                iid=f"entry_{entry.id}",
                values=("📝 Entry", entry.title, project_name, since_str, str(prio)),
                tags=("entry",)
            )
        
        # Show message if empty
        if not pending["tasks"] and not pending["entries"]:
            self.pending_tree.insert(
                "",
                tk.END,
                values=("", "Aucun item en attente", "", "", "")
            )
    
    def _refresh_upcoming(self) -> None:
        """Refresh the 'Upcoming' section."""
        # Clear existing items
        for item in self.upcoming_tree.get_children():
            self.upcoming_tree.delete(item)
        
        # Get upcoming items from service
        upcoming = self.service.get_upcoming_items(days=self.timeline_days)
        
        # Add items
        for item in upcoming:
            # Format date
            from datetime import datetime
            item_date = datetime.fromisoformat(item["date"])
            date_str = item_date.strftime("%d/%m/%Y")
            
            # Calculate days until
            days_until = (item_date.date() - datetime.now().date()).days
            if days_until == 0:
                date_display = f"{date_str} (Aujourd'hui)"
            elif days_until == 1:
                date_display = f"{date_str} (Demain)"
            else:
                date_display = f"{date_str} (dans {days_until}j)"
            
            # Insert into tree
            prio = item.get("priority", "-")
            if prio != "-":
                prio = str(prio)
            self.upcoming_tree.insert(
                "",
                tk.END,
                iid=f"{item['type'].lower()}_{item['item_id']}",
                values=(
                    date_display,
                    item["type"],
                    item["title"],
                    item["project_name"],
                    prio,
                ),
                tags=(item["type"].lower(),)
            )
        
        # Show message if empty
        if not upcoming:
            self.upcoming_tree.insert(
                "",
                tk.END,
                values=("", "", f"Aucun événement dans les {self.timeline_days} prochains jours", "", "")
            )
    
    def _refresh_focus(self) -> None:
        """Refresh the 'Focus Suggestions' section."""
        self.focus_text.config(state=tk.NORMAL)
        self.focus_text.delete("1.0", tk.END)
        
        # Get focus suggestions from service
        focus = self.service.get_focus_suggestions()
        weekly = focus.get("weekly", {})
        
        suggestions = []
        
        # Busiest project suggestion
        if focus["busiest_project"]:
            project, task_count = focus["busiest_project"]
            suggestions.append(
                f"🎯 Projet actif: \"{project.name}\" ({task_count} tâches ouvertes)"
            )
        
        # Oldest in-progress item
        if focus["oldest_entry"]:
            entry = focus["oldest_entry"]
            from datetime import datetime
            if entry.entry_date:
                entry_date = datetime.fromisoformat(entry.entry_date)
                age_days = (datetime.now().date() - entry_date.date()).days
                suggestions.append(
                    f"⏰ Entrée la plus ancienne: \"{entry.title}\" ({age_days} jours)"
                )
        
        # Summary stats
        suggestions.append("")
        suggestions.append(
            f"📊 Résumé: {focus['total_in_progress']} en cours, "
            f"{focus['total_pending']} en attente"
        )

        # Weekly actionable view
        meetings = int(weekly.get("meetings", 0))
        overdue = int(weekly.get("overdue_tasks", 0))
        due_tasks = int(weekly.get("due_tasks", 0))
        pending_decisions = int(weekly.get("pending_decisions", 0))
        suggestions.append("")
        suggestions.append(
            "🗓️ Semaine actionnable: "
            f"{meetings} réunion(s), {overdue} task(s) en retard, "
            f"{due_tasks} task(s) dues, {pending_decisions} décision(s) en attente"
        )

        top_overdue = weekly.get("top_overdue_tasks", [])
        if top_overdue:
            suggestions.append("Tâches en retard prioritaires:")
            for task in top_overdue:
                due_label = getattr(task, "due_date", None) or "sans date"
                suggestions.append(f"- {task.title} (échéance {due_label})")
        
        # Default message if no actionable signal
        has_signal = (
            focus["busiest_project"] is not None
            or focus["oldest_entry"] is not None
            or meetings > 0
            or overdue > 0
            or due_tasks > 0
            or pending_decisions > 0
        )
        if not has_signal:
            suggestions.insert(0, "✅ Aucune action urgente détectée")
            suggestions.insert(1, "")
        
        self.focus_text.insert("1.0", "\n".join(suggestions))
        self.focus_text.config(state=tk.DISABLED)
    
    def _on_period_change(self) -> None:
        """Handle period filter change."""
        period_str = self.period_var.get()
        self.timeline_days = int(period_str.split()[0])
        
        # Update section label
        for widget in self.scrollable_frame.winfo_children():
            if isinstance(widget, ttk.LabelFrame) and "À Venir" in widget.cget("text"):
                widget.config(text=f"📅 À Venir ({self.timeline_days} prochains jours)")
        
        self.refresh()
    
    def _on_today_item_double_click(self, event: tk.Event) -> None:
        """Handle double-click on an item in the 'Journée en cours' tree."""
        tree = event.widget
        selection = tree.selection()
        if not selection:
            return
        item_id = selection[0]
        if item_id.startswith("entry_"):
            self._open_entry(item_id.replace("entry_", ""))
        elif item_id.startswith("task_"):
            self._open_task(item_id.replace("task_", ""))
        # Event: no action (external calendar)

    def _on_item_double_click(self, event: tk.Event) -> None:
        """Handle double-click on an item."""
        tree = event.widget
        selection = tree.selection()
        if not selection:
            return

        item_id = selection[0]
        values = tree.item(item_id, "values")
        tags = tree.item(item_id, "tags")

        if not tags:
            return

        # Extract type and ID
        if item_id.startswith("entry_"):
            entry_id = item_id.replace("entry_", "")
            self._open_entry(entry_id)
        elif item_id.startswith("task_"):
            task_id = item_id.replace("task_", "")
            self._open_task(task_id)
        elif item_id.startswith("meeting_"):
            meeting_id = item_id.replace("meeting_", "")
            self._open_entry(meeting_id)
    
    def _open_entry(self, entry_id: str) -> None:
        """Open entry edit dialog."""
        logger.info(f"Opening entry: {entry_id}")
        parent = self.winfo_toplevel()
        result = show_edit_entry_dialog(parent, self.service, entry_id)
        if result:
            self._refresh_today()
            self._refresh_pending()
            self._refresh_in_progress()
            self._refresh_upcoming()

    def _open_task(self, task_id: str) -> None:
        """Open task edit dialog."""
        logger.info(f"Opening task: {task_id}")
        parent = self.winfo_toplevel()
        result = show_edit_task_dialog(parent, self.service, task_id)
        if result:
            self._refresh_today()
            self._refresh_pending()
            self._refresh_in_progress()
            self._refresh_upcoming()
