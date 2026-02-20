"""Enhanced calendar panel with week view and improved visuals."""

import calendar
import logging

# Noms de mois en français (index 0 vide, 1–12 = janvier–décembre)
FRENCH_MONTHS = [
    "", "janvier", "février", "mars", "avril", "mai", "juin",
    "juillet", "août", "septembre", "octobre", "novembre", "décembre"
]
FRENCH_MONTHS_ABBREV = [
    "", "janv.", "févr.", "mars", "avr.", "mai", "juin",
    "juil.", "août", "sept.", "oct.", "nov.", "déc."
]
import tkinter as tk
from datetime import date, datetime, timedelta
from tkinter import ttk, messagebox, filedialog
from pathlib import Path
from typing import Callable, Any

from pige.core.service import PigeService
from pige.interfaces.gui.dialogs import (
    show_edit_entry_dialog,
    show_edit_task_dialog,
    show_new_entry_dialog,
    show_new_task_dialog,
)

logger = logging.getLogger(__name__)


class CalendarPanel(ttk.Frame):
    """Panel for displaying entries and tasks in calendar views (month/week)."""
    
    def __init__(
        self, 
        parent: tk.Widget, 
        service: PigeService, 
        on_entry_open=None,
        **kwargs
    ) -> None:
        super().__init__(parent, **kwargs)
        self.service = service
        self.on_entry_open = on_entry_open  # Callback to open entry in WorkPanel
        
        # Current view state
        today = date.today()
        self.current_year = today.year
        self.current_month = today.month
        self.current_week_start: date = self._get_week_start(today)
        self.selected_date: date | None = None
        self.view_mode: str = "month"  # "month" or "week"
        
        # Data cache
        self._entries_by_date: dict[str, list] = {}
        self._tasks_by_date: dict[str, list] = {}
        self._events_by_date: dict[str, list] = {}
        self._projects_by_id: dict = {}
        self._day_redraw_callbacks: dict[str, Callable[[], None]] = {}
        self._visible_dates: set[str] = set()
        self._current_entries: list = []
        self._current_tasks: list = []
        self._current_events: list = []
        
        # Color scheme for better visuals
        self.colors = {
            "today": "#fff4cc",
            "selected": "#cce5ff",
            "weekend": "#f5f5f5",
            "has_items": "#e8f5e9",
            "overdue": "#ffebee",
            "default": "white"
        }
        
        # Setup UI
        self._setup_toolbar()
        self._setup_view_container()
        self._setup_details_panel()
        
        # Set splitter position after UI is rendered
        self.after(100, self._set_initial_splitter_position)
        
        # Load initial data
        self.refresh()
    
    def _get_week_start(self, d: date) -> date:
        """Get Monday of the week containing date d."""
        return d - timedelta(days=d.weekday())
    
    def _setup_toolbar(self) -> None:
        """Setup navigation toolbar."""
        toolbar = ttk.Frame(self)
        toolbar.pack(fill=tk.X, padx=5, pady=5)
        
        # View mode selector
        view_frame = ttk.LabelFrame(toolbar, text="Vue", padding=3)
        view_frame.pack(side=tk.LEFT, padx=5)
        
        self.view_var = tk.StringVar(value="month")
        ttk.Radiobutton(
            view_frame,
            text="📅 Mois",
            variable=self.view_var,
            value="month",
            command=self._switch_view
        ).pack(side=tk.LEFT, padx=2)
        
        ttk.Radiobutton(
            view_frame,
            text="📆 Semaine",
            variable=self.view_var,
            value="week",
            command=self._switch_view
        ).pack(side=tk.LEFT, padx=2)
        
        ttk.Separator(toolbar, orient=tk.VERTICAL).pack(side=tk.LEFT, fill=tk.Y, padx=10)
        
        # Navigation buttons
        ttk.Button(
            toolbar,
            text="‹‹ Année",
            command=self._prev_year,
            width=12
        ).pack(side=tk.LEFT, padx=1)
        
        ttk.Button(
            toolbar,
            text="‹ Mois",
            command=self._prev_period,
            width=10
        ).pack(side=tk.LEFT, padx=1)
        
        # Current period label
        self.period_label = ttk.Label(
            toolbar,
            text="",
            font=("TkDefaultFont", 11, "bold"),
            width=25,
            anchor=tk.CENTER
        )
        self.period_label.pack(side=tk.LEFT, padx=15)
        
        ttk.Button(
            toolbar,
            text="Mois ›",
            command=self._next_period,
            width=10
        ).pack(side=tk.LEFT, padx=1)
        
        ttk.Button(
            toolbar,
            text="Année ››",
            command=self._next_year,
            width=12
        ).pack(side=tk.LEFT, padx=1)
        
        ttk.Button(
            toolbar,
            text="📅 Aujourd'hui",
            command=self._goto_today
        ).pack(side=tk.LEFT, padx=10)
        
        ttk.Separator(toolbar, orient=tk.VERTICAL).pack(side=tk.LEFT, fill=tk.Y, padx=10)
        
        # Actions
        ttk.Button(
            toolbar,
            text="📋 Abonnements",
            command=self._manage_subscriptions
        ).pack(side=tk.LEFT, padx=2)
        
        ttk.Button(
            toolbar,
            text="📥 Importer ICS",
            command=self._import_ics
        ).pack(side=tk.LEFT, padx=2)
        
        ttk.Button(
            toolbar,
            text="🔄 Rafraîchir",
            command=self.refresh
        ).pack(side=tk.RIGHT, padx=2)
    
    def _setup_view_container(self) -> None:
        """Setup container for calendar views (month/week)."""
        # Main container with grid layout (more reliable than PanedWindow)
        main_container = ttk.Frame(self)
        main_container.pack(fill=tk.BOTH, expand=True, padx=5, pady=5)
        
        # Configure grid weights (60% calendar, 40% details)
        main_container.columnconfigure(0, weight=3, minsize=400)
        main_container.columnconfigure(1, weight=2, minsize=300)
        main_container.rowconfigure(0, weight=1)
        
        # View container (will hold month or week view)
        self.view_container = ttk.Frame(main_container, relief=tk.SUNKEN, borderwidth=1)
        self.view_container.grid(row=0, column=0, sticky="nsew", padx=(0, 3))
        
        # Store reference for details panel
        self.main_container = main_container
    
    def _set_initial_splitter_position(self) -> None:
        """No longer needed with grid layout."""
        pass
    
    def _setup_details_panel(self) -> None:
        """Setup details panel for selected date."""
        details_frame = ttk.LabelFrame(self.main_container, text="📋 Détails", padding=10)
        details_frame.grid(row=0, column=1, sticky="nsew", padx=(3, 0))
        
        # Selected date label
        self.selected_date_label = ttk.Label(
            details_frame,
            text="Aucune date sélectionnée",
            font=("TkDefaultFont", 10, "bold")
        )
        self.selected_date_label.pack(anchor=tk.W, pady=(0, 10))
        
        # Quick actions
        actions_frame = ttk.Frame(details_frame)
        actions_frame.pack(fill=tk.X, pady=(0, 10))
        
        ttk.Button(
            actions_frame,
            text="➕ Nouvelle Entrée",
            command=self._create_entry_for_date,
            width=18
        ).pack(side=tk.LEFT, padx=2)
        
        ttk.Button(
            actions_frame,
            text="✓ Nouvelle Tâche",
            command=self._create_task_for_date,
            width=18
        ).pack(side=tk.LEFT, padx=2)
        
        # Notebook for entries and tasks
        self.details_notebook = ttk.Notebook(details_frame)
        self.details_notebook.pack(fill=tk.BOTH, expand=True)
        
        # Calendar Events tab
        events_tab = ttk.Frame(self.details_notebook)
        self.details_notebook.add(events_tab, text="📅 Événements")
        
        events_scroll = ttk.Scrollbar(events_tab, orient=tk.VERTICAL)
        events_scroll.pack(side=tk.RIGHT, fill=tk.Y)
        
        self.events_listbox = tk.Listbox(
            events_tab,
            yscrollcommand=events_scroll.set,
            font=("TkDefaultFont", 9)
        )
        self.events_listbox.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        events_scroll.config(command=self.events_listbox.yview)
        self.events_listbox.bind("<Double-Button-1>", self._on_event_double_click)
        
        # Entries tab
        entries_tab = ttk.Frame(self.details_notebook)
        self.details_notebook.add(entries_tab, text="📝 Entrées")
        
        entries_scroll = ttk.Scrollbar(entries_tab, orient=tk.VERTICAL)
        entries_scroll.pack(side=tk.RIGHT, fill=tk.Y)
        
        self.entries_listbox = tk.Listbox(
            entries_tab,
            yscrollcommand=entries_scroll.set,
            font=("TkDefaultFont", 9)
        )
        self.entries_listbox.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        entries_scroll.config(command=self.entries_listbox.yview)
        self.entries_listbox.bind("<Double-Button-1>", self._on_entry_double_click)
        
        # Tasks tab
        tasks_tab = ttk.Frame(self.details_notebook)
        self.details_notebook.add(tasks_tab, text="✓ Tâches")
        
        tasks_scroll = ttk.Scrollbar(tasks_tab, orient=tk.VERTICAL)
        tasks_scroll.pack(side=tk.RIGHT, fill=tk.Y)
        
        self.tasks_listbox = tk.Listbox(
            tasks_tab,
            yscrollcommand=tasks_scroll.set,
            font=("TkDefaultFont", 9)
        )
        self.tasks_listbox.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        tasks_scroll.config(command=self.tasks_listbox.yview)
        self.tasks_listbox.bind("<Double-Button-1>", self._on_task_double_click)
    
    def _switch_view(self) -> None:
        """Switch between month and week view."""
        self.view_mode = self.view_var.get()
        self.refresh()
    
    def _prev_period(self) -> None:
        """Navigate to previous period (month or week)."""
        if self.view_mode == "month":
            self._prev_month()
        else:
            self._prev_week()
    
    def _next_period(self) -> None:
        """Navigate to next period (month or week)."""
        if self.view_mode == "month":
            self._next_month()
        else:
            self._next_week()
    
    def _prev_week(self) -> None:
        """Navigate to previous week."""
        self.current_week_start -= timedelta(days=7)
        self.refresh()
    
    def _next_week(self) -> None:
        """Navigate to next week."""
        self.current_week_start += timedelta(days=7)
        self.refresh()
    
    def _prev_month(self) -> None:
        """Navigate to previous month."""
        if self.current_month == 1:
            self.current_month = 12
            self.current_year -= 1
        else:
            self.current_month -= 1
        self.refresh()
    
    def _next_month(self) -> None:
        """Navigate to next month."""
        if self.current_month == 12:
            self.current_month = 1
            self.current_year += 1
        else:
            self.current_month += 1
        self.refresh()
    
    def _prev_year(self) -> None:
        """Navigate to previous year."""
        if self.view_mode == "month":
            self.current_year -= 1
        else:
            self.current_week_start -= timedelta(days=365)
        self.refresh()
    
    def _next_year(self) -> None:
        """Navigate to next year."""
        if self.view_mode == "month":
            self.current_year += 1
        else:
            self.current_week_start += timedelta(days=365)
        self.refresh()
    
    def _goto_today(self) -> None:
        """Navigate to today's date."""
        today = date.today()
        self.current_year = today.year
        self.current_month = today.month
        self.current_week_start = self._get_week_start(today)
        self.selected_date = today
        self.refresh()
    
    def refresh(self) -> None:
        """Refresh calendar data and view."""
        # Load data
        self._load_data()
        
        # Update period label
        self._update_period_label()
        
        # Render appropriate view
        if self.view_mode == "month":
            self._render_month_view()
        else:
            self._render_week_view()
        
        # Update details if date selected
        if self.selected_date:
            self._update_details_panel()
    
    def _update_period_label(self) -> None:
        """Update the period label in toolbar."""
        if self.view_mode == "month":
            month_name = FRENCH_MONTHS[self.current_month]
            self.period_label.config(text=f"{month_name} {self.current_year}")
        else:
            week_end = self.current_week_start + timedelta(days=6)
            if self.current_week_start.month == week_end.month:
                label = f"{self.current_week_start.day}-{week_end.day} {FRENCH_MONTHS[self.current_week_start.month]} {self.current_week_start.year}"
            else:
                d1, m1, y1 = self.current_week_start.day, FRENCH_MONTHS_ABBREV[self.current_week_start.month], self.current_week_start.year
                d2, m2, y2 = week_end.day, FRENCH_MONTHS_ABBREV[week_end.month], week_end.year
                label = f"{d1} {m1} - {d2} {m2} {y2}"
            self.period_label.config(text=label)
    
    def _load_data(self) -> None:
        """Load entries, tasks, and calendar events."""
        logger.debug(f"Loading calendar data for {self.view_mode} view")
        
        # Load all entries
        all_entries = self.service.storage.read_entries_meta()
        
        # Load projects
        projects = self.service.list_projects(status="all")
        self._projects_by_id = {p.id: p for p in projects}
        
        # Group entries by date
        self._entries_by_date = {}
        for entry in all_entries:
            if entry.entry_date:
                try:
                    entry_date = datetime.fromisoformat(entry.entry_date).date()
                    date_str = entry_date.isoformat()
                    if date_str not in self._entries_by_date:
                        self._entries_by_date[date_str] = []
                    self._entries_by_date[date_str].append(entry)
                except Exception:
                    pass
        
        # Load calendar events
        from pige.core.storage import read_calendar_events
        all_events = read_calendar_events(self.service.storage)
        
        # Group calendar events by start_date
        self._events_by_date: dict[str, list] = {}
        for event in all_events:
            if event.start_date:
                try:
                    date_str = event.start_date  # Already ISO format
                    if date_str not in self._events_by_date:
                        self._events_by_date[date_str] = []
                    self._events_by_date[date_str].append(event)
                except Exception:
                    pass
        
        # Load all tasks from all projects
        all_tasks = []
        for project in projects:
            tasks = self.service.list_tasks(project_id=project.id, status="all")
            all_tasks.extend(tasks)
        
        # Group tasks by due date
        self._tasks_by_date = {}
        for task in all_tasks:
            if task.due_date:
                try:
                    task_date = datetime.fromisoformat(task.due_date).date()
                    date_str = task_date.isoformat()
                    if date_str not in self._tasks_by_date:
                        self._tasks_by_date[date_str] = []
                    self._tasks_by_date[date_str].append(task)
                except Exception:
                    pass

    @staticmethod
    def _parse_iso_date(value: object) -> date | None:
        if not value:
            return None
        try:
            return datetime.fromisoformat(str(value)).date()
        except Exception:
            return None

    @staticmethod
    def _parse_iso_time(value: object) -> tuple[int, int]:
        if not value:
            return (99, 99)
        raw = str(value).strip()
        if not raw:
            return (99, 99)
        if "T" in raw:
            raw = raw.split("T", 1)[1]
        if len(raw) >= 5:
            raw = raw[:5]
        try:
            hh, mm = raw.split(":", 1)
            return (int(hh), int(mm))
        except Exception:
            return (99, 99)

    def _sort_day_events(self, events: list) -> list:
        return sorted(
            events,
            key=lambda event: (
                self._parse_iso_time(getattr(event, "start_time", None)),
                (getattr(event, "title", "") or "").lower(),
            ),
        )

    def _sort_day_entries(self, entries: list) -> list:
        type_rank = {"meeting": 0, "decision": 1, "note": 2, "log": 3, "activity": 4}
        return sorted(
            entries,
            key=lambda entry: (
                type_rank.get(getattr(entry, "type", ""), 9),
                self._parse_iso_time(getattr(entry, "start_time", None)),
                int(getattr(entry, "priority", 3)) if isinstance(getattr(entry, "priority", 3), int) else 3,
                (getattr(entry, "title", "") or "").lower(),
            ),
        )

    def _sort_day_tasks(self, tasks: list) -> list:
        today = date.today()
        status_rank = {"in_progress": 0, "open": 1, "done": 2}

        def task_key(task) -> tuple:
            status = getattr(task, "status", "open")
            due_date = self._parse_iso_date(getattr(task, "due_date", None))
            is_done = status == "done"
            is_overdue = bool(due_date and due_date < today and not is_done)
            is_due_today = bool(due_date and due_date == today and not is_done)
            return (
                0 if is_overdue else (1 if is_due_today else 2),
                status_rank.get(status, 9),
                (getattr(task, "title", "") or "").lower(),
            )

        return sorted(tasks, key=task_key)

    def _capture_details_context(self) -> dict[str, Any]:
        context: dict[str, Any] = {}
        if not self.selected_date:
            return context

        try:
            context["tab_index"] = self.details_notebook.index("current")
        except Exception:
            context["tab_index"] = 0

        context["entries_y"] = self.entries_listbox.yview()[0] if self.entries_listbox.size() else 0.0
        context["tasks_y"] = self.tasks_listbox.yview()[0] if self.tasks_listbox.size() else 0.0
        context["events_y"] = self.events_listbox.yview()[0] if self.events_listbox.size() else 0.0

        entry_sel = self.entries_listbox.curselection()
        task_sel = self.tasks_listbox.curselection()
        event_sel = self.events_listbox.curselection()

        context["entry_id"] = (
            self._current_entries[entry_sel[0]].id
            if entry_sel and entry_sel[0] < len(self._current_entries)
            else None
        )
        context["task_id"] = (
            self._current_tasks[task_sel[0]].id
            if task_sel and task_sel[0] < len(self._current_tasks)
            else None
        )
        context["event_id"] = (
            self._current_events[event_sel[0]].id
            if event_sel and event_sel[0] < len(self._current_events)
            else None
        )
        return context

    def _restore_details_context(self, context: dict[str, Any]) -> None:
        if not context:
            return

        try:
            self.details_notebook.select(int(context.get("tab_index", 0)))
        except Exception:
            pass

        self._restore_listbox_selection(
            self.entries_listbox,
            self._current_entries,
            context.get("entry_id"),
            context.get("entries_y", 0.0),
        )
        self._restore_listbox_selection(
            self.tasks_listbox,
            self._current_tasks,
            context.get("task_id"),
            context.get("tasks_y", 0.0),
        )
        self._restore_listbox_selection(
            self.events_listbox,
            self._current_events,
            context.get("event_id"),
            context.get("events_y", 0.0),
        )

    def _restore_listbox_selection(
        self,
        listbox: tk.Listbox,
        current_items: list,
        target_id: object,
        yview: object,
    ) -> None:
        if target_id is not None:
            for idx, item in enumerate(current_items):
                if getattr(item, "id", None) == target_id:
                    listbox.selection_clear(0, tk.END)
                    listbox.selection_set(idx)
                    listbox.activate(idx)
                    break
        try:
            fraction = float(yview)
            listbox.yview_moveto(max(0.0, min(1.0, fraction)))
        except Exception:
            pass

    def _refresh_visible_dates(self, changed_dates: set[date]) -> None:
        for day in changed_dates:
            callback = self._day_redraw_callbacks.get(day.isoformat())
            if callback is not None:
                callback()

    def _load_data_for_dates(self, dates_to_refresh: set[date]) -> None:
        """Reload only buckets for specific dates and keep the rest of caches intact."""
        if not dates_to_refresh:
            return

        date_keys = {day.isoformat() for day in dates_to_refresh}

        projects = self.service.list_projects(status="all")
        self._projects_by_id = {p.id: p for p in projects}

        for key in date_keys:
            self._entries_by_date.pop(key, None)
            self._tasks_by_date.pop(key, None)
            self._events_by_date.pop(key, None)

        # Entries
        for entry in self.service.storage.read_entries_meta():
            entry_date = self._parse_iso_date(getattr(entry, "entry_date", None))
            if not entry_date:
                continue
            key = entry_date.isoformat()
            if key not in date_keys:
                continue
            self._entries_by_date.setdefault(key, []).append(entry)

        # Events
        from pige.core.storage import read_calendar_events

        for cal_event in read_calendar_events(self.service.storage):
            key = getattr(cal_event, "start_date", None)
            if not key or key not in date_keys:
                continue
            self._events_by_date.setdefault(key, []).append(cal_event)

        # Tasks
        all_tasks = []
        for project in projects:
            try:
                all_tasks.extend(self.service.list_tasks(project_id=project.id, status="all"))
            except Exception:
                continue
        for task in all_tasks:
            task_date = self._parse_iso_date(getattr(task, "due_date", None))
            if not task_date:
                continue
            key = task_date.isoformat()
            if key not in date_keys:
                continue
            self._tasks_by_date.setdefault(key, []).append(task)

    def _refresh_after_mutation(self, changed_dates: set[date] | None = None) -> None:
        """Refresh only impacted dates when possible, while preserving details context."""
        context = self._capture_details_context()

        if not changed_dates:
            self.refresh()
            self._restore_details_context(context)
            return

        self._load_data_for_dates(changed_dates)
        self._refresh_visible_dates(changed_dates)

        if self.selected_date is not None:
            self._update_details_panel()

        self._restore_details_context(context)
    
    def _navigate_period(self, forward: bool) -> None:
        """Navigate to next or previous period (same logic as flèches)."""
        if forward:
            self._next_period()
        else:
            self._prev_period()

    def _on_calendar_mousewheel(self, event) -> None:
        """Same behavior as arrow keys: scroll down = next, scroll up = prev; debounce 180ms so one turn = one change."""
        import time
        delta = getattr(event, "delta", 0) or (120 if getattr(event, "num", None) == 4 else (-120 if getattr(event, "num", None) == 5 else 0))
        if delta == 0:
            return
        now = time.time()
        if not hasattr(self, "_last_calendar_wheel"):
            self._last_calendar_wheel = 0.0
        if now - self._last_calendar_wheel < 0.18:
            return
        self._last_calendar_wheel = now
        self._navigate_period(forward=(delta < 0))

    def _on_calendar_key(self, event) -> None:
        """Navigate month/week with arrow keys; return 'break' to avoid tab switch."""
        if event.keysym == "Left":
            self._navigate_period(forward=False)
            return "break"
        if event.keysym == "Right":
            self._navigate_period(forward=True)
            return "break"

    def _bind_calendar_nav(self, main_frame: tk.Widget) -> None:
        """Bind mouse wheel and arrow keys on calendar area; allow focus for keyboard."""
        main_frame.bind("<MouseWheel>", self._on_calendar_mousewheel)
        main_frame.bind("<Button-4>", self._on_calendar_mousewheel)
        main_frame.bind("<Button-5>", self._on_calendar_mousewheel)
        main_frame.bind("<Left>", self._on_calendar_key)
        main_frame.bind("<Right>", self._on_calendar_key)
        main_frame.configure(takefocus=True)
        main_frame.focus_set()

    def _render_month_view(self) -> None:
        """Render month calendar view with proper grid alignment."""
        # Clear container
        for widget in self.view_container.winfo_children():
            widget.destroy()

        self._day_redraw_callbacks = {}
        self._visible_dates = set()
        
        # Main container
        main_frame = ttk.Frame(self.view_container)
        main_frame.pack(fill=tk.BOTH, expand=True, padx=5, pady=5)
        self._bind_calendar_nav(main_frame)
        
        # Day headers with fixed width
        day_names = ["Lundi", "Mardi", "Mercredi", "Jeudi", "Vendredi", "Samedi", "Dimanche"]
        for col, day_name in enumerate(day_names):
            is_weekend = col >= 5
            header = tk.Label(
                main_frame,
                text=day_name,
                font=("TkDefaultFont", 10, "bold"),
                bg="#e0e0e0",
                fg="#666" if is_weekend else "#333",
                relief=tk.RAISED,
                borderwidth=2,
                anchor=tk.CENTER,
                padx=5,
                pady=8
            )
            header.grid(row=0, column=col, sticky="nsew", padx=1, pady=1)
            main_frame.columnconfigure(col, weight=1, uniform="day")
        
        # Calendar grid
        cal = calendar.monthcalendar(self.current_year, self.current_month)
        today = date.today()
        
        for week_idx, week in enumerate(cal):
            # Configure row height
            main_frame.rowconfigure(week_idx + 1, weight=1, uniform="week")
            
            for day_idx, day_num in enumerate(week):
                self._create_day_cell_grid(main_frame, day_num, week_idx + 1, day_idx, today)
    
    def _create_day_cell_grid(self, parent, day_num: int, row: int, col: int, today: date) -> None:
        """Create a single day cell for month view using grid layout with rounded corners."""
        is_weekend = col >= 5

        if day_num == 0:
            empty_cell = tk.Canvas(
                parent,
                bg="#f5f5f5" if is_weekend else "#fafafa",
                highlightthickness=0
            )
            empty_cell.grid(row=row, column=col, sticky="nsew", padx=1, pady=1)
            return

        day_date = date(self.current_year, self.current_month, day_num)
        date_str = day_date.isoformat()
        self._visible_dates.add(date_str)

        canvas = tk.Canvas(
            parent,
            bg="#d9d9d9",
            highlightthickness=0,
            cursor="hand2"
        )
        canvas.grid(row=row, column=col, sticky="nsew", padx=2, pady=2)

        def _day_state() -> tuple[str, list, list, list, bool]:
            entries = self._sort_day_entries(self._entries_by_date.get(date_str, []))
            tasks = self._sort_day_tasks(self._tasks_by_date.get(date_str, []))
            events = self._sort_day_events(self._events_by_date.get(date_str, []))
            has_items = bool(entries or tasks or events)
            has_overdue = any(getattr(t, "status", "open") != "done" and day_date < today for t in tasks)

            if day_date == today:
                bg_color = self.colors["today"]
            elif day_date == self.selected_date:
                bg_color = self.colors["selected"]
            elif has_overdue:
                bg_color = self.colors["overdue"]
            elif is_weekend:
                bg_color = self.colors["weekend"]
            elif has_items:
                bg_color = self.colors["has_items"]
            else:
                bg_color = self.colors["default"]
            return bg_color, entries, tasks, events, has_overdue

        def draw_cell(hover: bool = False) -> None:
            canvas.delete("all")
            width = canvas.winfo_width()
            height = canvas.winfo_height()

            if width <= 1 or height <= 1:
                canvas.after(50, lambda: draw_cell(hover))
                return

            bg_color, entries, tasks, events, has_overdue = _day_state()
            self._draw_rounded_rectangle(
                canvas,
                0,
                0,
                width,
                height,
                8,
                fill=bg_color,
                outline="#1f6feb" if hover else "#8f8f8f",
                width=2,
            )

            canvas.create_text(
                10,
                10,
                text=str(day_num),
                font=("TkDefaultFont", 12, "bold"),
                fill="#333" if not is_weekend else "#888",
                anchor=tk.NW,
            )

            y_offset = 35

            for event in events[:2]:
                title = event.title
                if len(title) > 15:
                    title = title[:12] + "..."
                time_str = f" {event.start_time[:5]}" if event.start_time else ""
                canvas.create_text(
                    10,
                    y_offset,
                    text=f"📅{time_str} {title}",
                    font=("TkDefaultFont", 8),
                    fill="#9c27b0",
                    anchor=tk.W,
                )
                y_offset += 16
            if len(events) > 2:
                canvas.create_text(
                    10,
                    y_offset,
                    text=f"+ {len(events) - 2} autres...",
                    font=("TkDefaultFont", 7, "italic"),
                    fill="#9c27b0",
                    anchor=tk.W,
                )
                y_offset += 14

            for entry in entries[:2]:
                title = entry.title
                if len(title) > 15:
                    title = title[:12] + "..."
                icon = {"note": "📄", "meeting": "👥", "decision": "⚠️", "activity": "🎯"}.get(entry.type, "📝")
                canvas.create_text(
                    10,
                    y_offset,
                    text=f"{icon} {title}",
                    font=("TkDefaultFont", 8),
                    fill="#0066cc",
                    anchor=tk.W,
                )
                y_offset += 16
            if len(entries) > 2:
                canvas.create_text(
                    10,
                    y_offset,
                    text=f"+ {len(entries) - 2} autres...",
                    font=("TkDefaultFont", 7, "italic"),
                    fill="#0066cc",
                    anchor=tk.W,
                )
                y_offset += 14

            tasks_done = len([t for t in tasks if t.status == "done"])
            tasks_total = len(tasks)
            if tasks_total > 0:
                color = "#00aa00" if tasks_done == tasks_total else ("#cc0000" if has_overdue else "#ff9800")
                icon = "✓" if tasks_done == tasks_total else ("⚠️" if has_overdue else "✓ ")
                canvas.create_text(
                    10,
                    y_offset,
                    text=f"{icon} {tasks_done}/{tasks_total}",
                    font=("TkDefaultFont", 8),
                    fill=color,
                    anchor=tk.W,
                )

        canvas.bind("<Configure>", lambda e: draw_cell(False))
        canvas.bind("<Enter>", lambda e: draw_cell(True))
        canvas.bind("<Leave>", lambda e: draw_cell(False))
        canvas.bind("<Button-1>", lambda e, d=day_date: self._on_day_click(d))
        self._day_redraw_callbacks[date_str] = lambda: draw_cell(False)
    
    def _draw_rounded_rectangle(self, canvas, x1, y1, x2, y2, radius, **kwargs):
        """Draw a rounded rectangle on canvas."""
        points = [
            x1+radius, y1,
            x2-radius, y1,
            x2, y1,
            x2, y1+radius,
            x2, y2-radius,
            x2, y2,
            x2-radius, y2,
            x1+radius, y2,
            x1, y2,
            x1, y2-radius,
            x1, y1+radius,
            x1, y1
        ]
        
        return canvas.create_polygon(points, smooth=True, **kwargs)
    
    def _create_day_cell(self, parent, day_num: int, day_idx: int, today: date) -> None:
        """Create a single day cell for month view."""
        # Determine background color
        if day_num == 0:
            bg_color = self.colors["weekend"] if day_idx >= 5 else "#fafafa"
            day_frame = tk.Frame(parent, relief=tk.FLAT, borderwidth=1, bg=bg_color)
            day_frame.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=1, pady=1)
            return
        
        day_date = date(self.current_year, self.current_month, day_num)
        date_str = day_date.isoformat()
        
        # Choose background color
        if day_date == today:
            bg_color = self.colors["today"]
        elif day_date == self.selected_date:
            bg_color = self.colors["selected"]
        elif day_idx >= 5:  # Weekend
            bg_color = self.colors["weekend"]
        elif date_str in self._entries_by_date or date_str in self._tasks_by_date:
            bg_color = self.colors["has_items"]
        else:
            bg_color = self.colors["default"]
        
        # Check for overdue tasks
        tasks = self._tasks_by_date.get(date_str, [])
        has_overdue = any(t.status != "done" and day_date < today for t in tasks)
        if has_overdue:
            bg_color = self.colors["overdue"]
        
        day_frame = tk.Frame(
            parent,
            relief=tk.RAISED,
            borderwidth=1,
            bg=bg_color,
            cursor="hand2"
        )
        day_frame.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=1, pady=1)
        
        # Day number
        day_label = tk.Label(
            day_frame,
            text=str(day_num),
            font=("TkDefaultFont", 10, "bold"),
            bg=bg_color,
            anchor=tk.NW,
            fg="#333" if day_idx < 5 else "#888"
        )
        day_label.pack(anchor=tk.NW, padx=3, pady=2)
        
        # Entry/task indicators
        entries_count = len(self._entries_by_date.get(date_str, []))
        if entries_count > 0:
            tk.Label(
                day_frame,
                text=f"📝 {entries_count}",
                font=("TkDefaultFont", 8),
                bg=bg_color,
                fg="#0066cc"
            ).pack(anchor=tk.W, padx=3)
        
        tasks_done = len([t for t in tasks if t.status == "done"])
        tasks_total = len(tasks)
        if tasks_total > 0:
            color = "#00aa00" if tasks_done == tasks_total else ("#cc6600" if has_overdue else "#ff9800")
            tk.Label(
                day_frame,
                text=f"✓  {tasks_done}/{tasks_total}",
                font=("TkDefaultFont", 8),
                bg=bg_color,
                fg=color
            ).pack(anchor=tk.W, padx=3)
        
        # Bind click
        for widget in [day_frame, day_label]:
            widget.bind("<Button-1>", lambda e, d=day_date: self._on_day_click(d))
    
    def _render_week_view(self) -> None:
        """Render week calendar view with proper grid alignment."""
        # Clear container
        for widget in self.view_container.winfo_children():
            widget.destroy()

        self._day_redraw_callbacks = {}
        self._visible_dates = set()
        
        # Main container
        main_frame = ttk.Frame(self.view_container)
        main_frame.pack(fill=tk.BOTH, expand=True, padx=5, pady=5)
        self._bind_calendar_nav(main_frame)
        
        # Day headers with fixed width
        day_names = ["Lundi", "Mardi", "Mercredi", "Jeudi", "Vendredi", "Samedi", "Dimanche"]
        today = date.today()
        
        for col in range(7):
            day_date = self.current_week_start + timedelta(days=col)
            day_name = day_names[col]
            is_today = day_date == today
            is_weekend = col >= 5
            
            # Header with date
            header_text = f"{day_name}\n{day_date.day}/{day_date.month}"
            if is_today:
                header_text = f"📅 {day_name}\n{day_date.day}/{day_date.month}"
            
            header = tk.Label(
                main_frame,
                text=header_text,
                font=("TkDefaultFont", 10, "bold" if is_today else "normal"),
                bg="#e0e0e0",
                fg="#0066cc" if is_today else ("#666" if is_weekend else "#333"),
                relief=tk.RAISED,
                borderwidth=2,
                anchor=tk.CENTER,
                padx=5,
                pady=8
            )
            header.grid(row=0, column=col, sticky="nsew", padx=1, pady=1)
            main_frame.columnconfigure(col, weight=1, uniform="day")
        
        # Single row for week view
        main_frame.rowconfigure(1, weight=1, uniform="week")
        
        # Create day cells
        for col in range(7):
            day_date = self.current_week_start + timedelta(days=col)
            self._create_week_day_cell(main_frame, day_date, 1, col, today)
    
    def _create_week_day_cell(self, parent, day_date: date, row: int, col: int, today: date) -> None:
        """Create a single day cell for week view with rounded corners."""
        is_weekend = col >= 5
        date_str = day_date.isoformat()
        self._visible_dates.add(date_str)

        canvas = tk.Canvas(
            parent,
            bg="#d9d9d9",
            highlightthickness=0,
            cursor="hand2"
        )
        canvas.grid(row=row, column=col, sticky="nsew", padx=2, pady=2)

        def _day_state() -> tuple[str, list, list, list, bool]:
            entries = self._sort_day_entries(self._entries_by_date.get(date_str, []))
            tasks = self._sort_day_tasks(self._tasks_by_date.get(date_str, []))
            events = self._sort_day_events(self._events_by_date.get(date_str, []))
            has_items = bool(entries or tasks or events)
            has_overdue = any(getattr(t, "status", "open") != "done" and day_date < today for t in tasks)

            if day_date == today:
                bg_color = self.colors["today"]
            elif day_date == self.selected_date:
                bg_color = self.colors["selected"]
            elif has_overdue:
                bg_color = self.colors["overdue"]
            elif is_weekend:
                bg_color = self.colors["weekend"]
            elif has_items:
                bg_color = self.colors["has_items"]
            else:
                bg_color = self.colors["default"]
            return bg_color, entries, tasks, events, has_overdue

        def draw_cell(hover: bool = False) -> None:
            canvas.delete("all")
            width = canvas.winfo_width()
            height = canvas.winfo_height()

            if width <= 1 or height <= 1:
                canvas.after(50, lambda: draw_cell(hover))
                return

            bg_color, entries, tasks, events, has_overdue = _day_state()
            self._draw_rounded_rectangle(
                canvas,
                0,
                0,
                width,
                height,
                8,
                fill=bg_color,
                outline="#1f6feb" if hover else "#8f8f8f",
                width=2,
            )

            y_offset = 10
            for event in events[:4]:
                title = event.title[:32] + "..." if len(event.title) > 32 else event.title
                time_str = f"{event.start_time[:5]} " if event.start_time else ""
                canvas.create_text(
                    10,
                    y_offset,
                    text=f"📅 {time_str}{title}",
                    font=("TkDefaultFont", 9),
                    fill="#9c27b0",
                    anchor=tk.W,
                )
                y_offset += 18
            if len(events) > 4:
                canvas.create_text(
                    10,
                    y_offset,
                    text=f"+ {len(events) - 4} événements...",
                    font=("TkDefaultFont", 8, "italic"),
                    fill="#9c27b0",
                    anchor=tk.W,
                )
                y_offset += 18

            for entry in entries[:6]:
                icon = {"note": "📄", "meeting": "👥", "decision": "⚠️", "activity": "🎯"}.get(entry.type, "📝")
                title = entry.title[:32] + "..." if len(entry.title) > 32 else entry.title
                canvas.create_text(
                    10,
                    y_offset,
                    text=f"{icon} {title}",
                    font=("TkDefaultFont", 9),
                    fill="#0066cc",
                    anchor=tk.W,
                )
                y_offset += 18
            if len(entries) > 6:
                canvas.create_text(
                    10,
                    y_offset,
                    text=f"+ {len(entries) - 6} entries...",
                    font=("TkDefaultFont", 8, "italic"),
                    fill="#666",
                    anchor=tk.W,
                )
                y_offset += 18

            if (events or entries) and tasks:
                y_offset += 4
                canvas.create_line(10, y_offset, width - 10, y_offset, fill="#b3b3b3", width=1)
                y_offset += 8

            for task in tasks[:6]:
                is_done = task.status == "done"
                due_date = self._parse_iso_date(task.due_date)
                overdue = bool(due_date and due_date < today and not is_done)
                icon = "✓" if is_done else ("⚠️" if overdue else "○")
                color = "#00aa00" if is_done else ("#cc0000" if overdue else "#ff6600")
                title = task.title[:32] + "..." if len(task.title) > 32 else task.title
                canvas.create_text(
                    10,
                    y_offset,
                    text=f"{icon} {title}",
                    font=("TkDefaultFont", 9),
                    fill=color,
                    anchor=tk.W,
                )
                y_offset += 18
            if len(tasks) > 6:
                canvas.create_text(
                    10,
                    y_offset,
                    text=f"+ {len(tasks) - 6} tasks...",
                    font=("TkDefaultFont", 8, "italic"),
                    fill="#666",
                    anchor=tk.W,
                )

        canvas.bind("<Configure>", lambda e: draw_cell(False))
        canvas.bind("<Enter>", lambda e: draw_cell(True))
        canvas.bind("<Leave>", lambda e: draw_cell(False))
        canvas.bind("<Button-1>", lambda e, d=day_date: self._on_day_click(d))
        self._day_redraw_callbacks[date_str] = lambda: draw_cell(False)

    
    def _on_day_click(self, day_date: date) -> None:
        """Handle day click."""
        previous_date = self.selected_date
        self.selected_date = day_date
        period_changed = False
        
        # Update view based on mode
        if self.view_mode == "month":
            # Update month to match selected date if needed
            if day_date.year != self.current_year or day_date.month != self.current_month:
                self.current_year = day_date.year
                self.current_month = day_date.month
                period_changed = True
        else:
            # Update week to match selected date if needed
            week_start = self._get_week_start(day_date)
            if week_start != self.current_week_start:
                self.current_week_start = week_start
                period_changed = True

        if period_changed:
            self.refresh()
            return

        changed_dates: set[date] = {day_date}
        if previous_date is not None:
            changed_dates.add(previous_date)
        self._refresh_visible_dates(changed_dates)
        self._update_details_panel()
    
    def _update_details_panel(self) -> None:
        """Update details panel for selected date."""
        if not self.selected_date:
            return
        
        date_str = self.selected_date.isoformat()
        logger.info(f"Updating details panel for date: {date_str}")
        
        # Update label
        day_name = ["Lundi", "Mardi", "Mercredi", "Jeudi", "Vendredi", "Samedi", "Dimanche"][self.selected_date.weekday()]
        self.selected_date_label.config(
            text=f"{day_name} {self.selected_date.strftime('%d/%m/%Y')}"
        )
        
        # Update calendar events list
        self.events_listbox.delete(0, tk.END)
        events = self._sort_day_events(self._events_by_date.get(date_str, []))
        self._current_events = events  # Store for double-click
        logger.info(f"Found {len(events)} events for {date_str}")
        for event in events:
            time_str = f" {event.start_time[:5]}" if event.start_time else ""
            location_str = f" 📍 {event.location}" if event.location else ""
            self.events_listbox.insert(tk.END, f"📅{time_str} {event.title}{location_str}")
        
        if not events:
            self.events_listbox.insert(tk.END, "(aucun événement ce jour)")
        
        # Update entries list
        self.entries_listbox.delete(0, tk.END)
        entries = self._sort_day_entries(self._entries_by_date.get(date_str, []))
        self._current_entries = entries  # Store for double-click
        logger.info(f"Found {len(entries)} entries for {date_str}")
        for entry in entries:
            type_icon = {"note": "📄", "meeting": "👥", "decision": "⚠️", "activity": "🎯"}.get(entry.type, "📝")
            project = self._projects_by_id.get(entry.project_id)
            project_name = f" [{project.name}]" if project else ""
            self.entries_listbox.insert(tk.END, f"{type_icon} {entry.title}{project_name}")
        
        if not entries:
            self.entries_listbox.insert(tk.END, "(aucune entry ce jour)")
        
        # Update tasks list
        self.tasks_listbox.delete(0, tk.END)
        tasks = self._sort_day_tasks(self._tasks_by_date.get(date_str, []))
        self._current_tasks = tasks  # Store for double-click
        logger.info(f"Found {len(tasks)} tasks for {date_str}")
        for task in tasks:
            due_date = self._parse_iso_date(task.due_date)
            is_overdue = bool(due_date and due_date < date.today() and task.status != "done")
            status_icon = "✓" if task.status == "done" else ("⚠️" if is_overdue else "○")
            self.tasks_listbox.insert(tk.END, f"{status_icon} {task.title}")
        
        if not tasks:
            self.tasks_listbox.insert(tk.END, "(aucune task ce jour)")
    
    def _on_entry_double_click(self, event: tk.Event) -> None:
        """Handle double-click on entry."""
        selection = self.entries_listbox.curselection()
        if not selection or not hasattr(self, "_current_entries"):
            return

        idx = selection[0]
        if idx >= len(self._current_entries):
            return

        entry = self._current_entries[idx]
        logger.info(f"Entry double-clicked: {entry.id}")

        if self.on_entry_open:
            self.on_entry_open(entry.id)
            return

        parent = self.winfo_toplevel()
        result = show_edit_entry_dialog(parent, self.service, entry.id)
        if result:
            changed_date = self._parse_iso_date(getattr(result, "entry_date", None))
            changed_dates: set[date] = set()
            if changed_date is not None:
                changed_dates.add(changed_date)
            if self.selected_date is not None:
                changed_dates.add(self.selected_date)
            self._refresh_after_mutation(changed_dates if changed_dates else None)

    def _on_event_double_click(self, event: tk.Event) -> None:
        """Handle double-click on calendar event."""
        selection = self.events_listbox.curselection()
        if not selection or not hasattr(self, "_current_events"):
            return

        idx = selection[0]
        if idx >= len(self._current_events):
            return

        cal_event = self._current_events[idx]
        logger.info(f"Calendar event double-clicked: {cal_event.id}")

        linked_entry_id = getattr(cal_event, "linked_entry_id", None)
        if linked_entry_id:
            linked_entry = self.service.storage.get_entry(linked_entry_id)
            if linked_entry is not None:
                if self.on_entry_open:
                    self.on_entry_open(linked_entry_id)
                    return
                parent = self.winfo_toplevel()
                result = show_edit_entry_dialog(parent, self.service, linked_entry_id)
                if result:
                    changed_dates: set[date] = set()
                    event_date = self._parse_iso_date(getattr(cal_event, "start_date", None))
                    entry_date = self._parse_iso_date(getattr(result, "entry_date", None))
                    if event_date is not None:
                        changed_dates.add(event_date)
                    if entry_date is not None:
                        changed_dates.add(entry_date)
                    self._refresh_after_mutation(changed_dates if changed_dates else None)
                return

        details = f"Événement: {cal_event.title}\n\n"
        details += f"Date: {cal_event.start_date}"
        if cal_event.start_time:
            details += f" {cal_event.start_time[:5]}"
        if cal_event.end_date and cal_event.end_date != cal_event.start_date:
            details += f" - {cal_event.end_date}"
        if cal_event.end_time:
            details += f" {cal_event.end_time[:5]}"
        details += "\n"

        if cal_event.location:
            details += f"\nLieu: {cal_event.location}\n"

        if cal_event.description:
            details += f"\nDescription:\n{cal_event.description}\n"

        if linked_entry_id:
            details += "\nL'entrée liée est introuvable."

        details += "\nCréer une note PIGE pour cet événement ?"

        result = messagebox.askquestion(
            "Événement de calendrier",
            details,
            icon="question",
        )

        if result == "yes":
            self._link_entry_to_event(cal_event)

    def _on_task_double_click(self, event: tk.Event) -> None:
        """Handle double-click on task."""
        selection = self.tasks_listbox.curselection()
        if not selection or not hasattr(self, "_current_tasks"):
            return

        idx = selection[0]
        if idx >= len(self._current_tasks):
            return

        task = self._current_tasks[idx]
        old_due_date = self._parse_iso_date(getattr(task, "due_date", None))
        logger.info(f"Task double-clicked: {task.id}")
        parent = self.winfo_toplevel()
        result = show_edit_task_dialog(parent, self.service, task.id)
        if result:
            changed_dates: set[date] = set()
            new_due_date = self._parse_iso_date(getattr(result, "due_date", None))
            if old_due_date is not None:
                changed_dates.add(old_due_date)
            if new_due_date is not None:
                changed_dates.add(new_due_date)
            if self.selected_date is not None:
                changed_dates.add(self.selected_date)
            self._refresh_after_mutation(changed_dates if changed_dates else None)
    
    def _create_entry_for_date(self) -> None:
        """Create new entry for selected date."""
        if not self.selected_date:
            messagebox.showwarning("Attention", "Sélectionnez d'abord une date dans le calendrier")
            return
        projects = self.service.list_projects(status="active")
        if not projects:
            messagebox.showerror("Erreur", "Aucun projet actif. Créez d'abord un projet.")
            return
        project_id = projects[0].id
        parent = self.winfo_toplevel()
        result = show_new_entry_dialog(
            parent,
            self.service,
            project_id,
            initial_date=self.selected_date,
        )
        if result:
            entry, _ = result
            changed_dates: set[date] = set()
            created_date = self._parse_iso_date(getattr(entry, "entry_date", None))
            if created_date is not None:
                changed_dates.add(created_date)
            if self.selected_date is not None:
                changed_dates.add(self.selected_date)
            self._refresh_after_mutation(changed_dates if changed_dates else None)
    
    def _link_entry_to_event(self, cal_event) -> None:
        """Create and link a PIGE entry to a calendar event."""
        from tkinter import simpledialog
        from pige.core.storage import upsert_calendar_event

        # Get projects (exclude calendar-sync folders); put "En attente" first (option 0)
        active = self.service.list_projects(status="active")
        active = [p for p in active if "calendar-sync" not in (p.tags or [])]
        hold_project = self.service.get_or_create_hold_project()
        others = [p for p in active if p.id != hold_project.id]
        projects = [hold_project] + others

        # Ask user: 0 = En attente (move later), 1..n = project by number, or project name
        prompt_lines = ["Projets disponibles:"]
        for i, p in enumerate(projects):
            if p.id == hold_project.id:
                prompt_lines.append(f"  {i}. En attente (déplacer plus tard)")
            else:
                prompt_lines.append(f"  {i}. {p.name}")
        prompt_lines.append("\nEntrez le numéro (0, 1, 2, ...) ou le nom du projet:")
        project_choice = simpledialog.askstring(
            "Choisir un projet",
            "\n".join(prompt_lines),
            parent=self.winfo_toplevel()
        )

        if not project_choice or not project_choice.strip():
            return

        raw = project_choice.strip()
        project = None
        if raw.isdigit():
            idx = int(raw)
            if 0 <= idx < len(projects):
                project = projects[idx]
        if project is None:
            # Match by name (case-insensitive), including "en attente"
            if raw.lower() in ("en attente", "0"):
                project = hold_project
            else:
                for p in projects:
                    if (p.name or "").strip().lower() == raw.lower():
                        project = p
                        break
        if project is None:
            messagebox.showerror("Erreur", "Projet introuvable. Utilisez le numéro (0, 1, 2, ...) ou le nom exact.")
            return

        # Create entry
        try:
            # Build body with event details
            body = f"# Note pour: {cal_event.title}\n\n"
            body += f"**Date événement**: {cal_event.start_date}"
            if cal_event.start_time:
                body += f" {cal_event.start_time[:5]}"
            body += "\n\n"

            if cal_event.location:
                body += f"**Lieu**: {cal_event.location}\n\n"

            if cal_event.description:
                body += f"## Description de l'événement\n\n{cal_event.description}\n\n"

            body += "## Notes\n\n(Ajoutez vos notes ici)\n"

            # Create entry (add_entry returns (EntryMeta, Path))
            entry, _path = self.service.add_entry(
                project.id,
                "note",
                f"\N{CALENDAR} {cal_event.title}",
                ["calendar-event"],
                body,
                entry_date=cal_event.start_date,
            )
            
            # Link event to entry
            cal_event.linked_entry_id = entry.id
            upsert_calendar_event(self.service.storage, cal_event)

            if project.id == hold_project.id:
                msg = (
                    "Note créée en « En attente » et liée à l'événement.\n\n"
                    "Vous pourrez la déplacer vers un projet plus tard :\n"
                    "onglet Work → clic droit sur l'entrée → Déplacer vers..."
                )
            else:
                msg = f"Note créée et liée à l'événement!\n\nID entrée: {entry.id}"
            messagebox.showinfo("Succès", msg)
            changed_dates: set[date] = set()
            event_date = self._parse_iso_date(getattr(cal_event, "start_date", None))
            entry_date = self._parse_iso_date(getattr(entry, "entry_date", None))
            if event_date is not None:
                changed_dates.add(event_date)
            if entry_date is not None:
                changed_dates.add(entry_date)
            if self.selected_date is not None:
                changed_dates.add(self.selected_date)
            self._refresh_after_mutation(changed_dates if changed_dates else None)
            
        except Exception as e:
            logger.error(f"Failed to create linked entry: {e}", exc_info=True)
            messagebox.showerror("Erreur", f"Impossible de créer la note:\n{e}")
    
    def _create_task_for_date(self) -> None:
        """Create new task for selected date."""
        if not self.selected_date:
            messagebox.showwarning("Attention", "Sélectionnez d'abord une date dans le calendrier")
            return
        projects = self.service.list_projects(status="active")
        if not projects:
            messagebox.showerror("Erreur", "Aucun projet actif. Créez d'abord un projet.")
            return
        project_id = projects[0].id
        parent = self.winfo_toplevel()
        result = show_new_task_dialog(
            parent,
            self.service,
            project_id,
            initial_due_date=self.selected_date,
        )
        if result:
            changed_dates: set[date] = set()
            due_date = self._parse_iso_date(getattr(result, "due_date", None))
            if due_date is not None:
                changed_dates.add(due_date)
            if self.selected_date is not None:
                changed_dates.add(self.selected_date)
            self._refresh_after_mutation(changed_dates if changed_dates else None)
    
    def _manage_subscriptions(self) -> None:
        """Open subscriptions management dialog."""
        from pige.interfaces.gui.dialogs.calendar_subscriptions import CalendarSubscriptionsDialog
        
        dialog = CalendarSubscriptionsDialog(self, self.service, on_close=self.refresh)
        # Don't wait - allow non-modal interaction
    
    def _import_ics(self) -> None:
        """Import calendar from ICS file."""
        file_path = filedialog.askopenfilename(
            title="Importer calendrier ICS",
            filetypes=[
                ("iCalendar files", "*.ics"),
                ("All files", "*.*")
            ]
        )
        
        if not file_path:
            return
        
        try:
            # Import icalendar library
            try:
                from icalendar import Calendar as ICalendar
            except ImportError:
                messagebox.showerror(
                    "Erreur",
                    "La bibliothèque 'icalendar' n'est pas installée.\n\n"
                    "Installez-la avec: pip install icalendar"
                )
                return
            
            # Parse ICS file
            with open(file_path, 'rb') as f:
                cal = ICalendar.from_ical(f.read())
            
            # Extract events
            events_imported = 0
            projects = self.service.list_projects(status="active")
            
            # Use first project or create "Importé" project
            if projects:
                import_project = projects[0]
            else:
                import_project = self.service.create_project(
                    name="Calendrier Importé",
                    description="Événements importés depuis fichier ICS",
                    tags=["import", "ics"]
                )
            
            for component in cal.walk():
                if component.name == "VEVENT":
                    summary = str(component.get('summary', 'Sans titre'))
                    description = str(component.get('description', ''))
                    dtstart = component.get('dtstart')
                    
                    if dtstart:
                        event_date = dtstart.dt
                        if isinstance(event_date, datetime):
                            event_date = event_date.date()
                        
                        # Create entry
                        self.service.add_entry(
                            project_id=import_project.id,
                            entry_type="activity",
                            title=summary,
                            body=description or f"# {summary}\n\nImporté depuis ICS",
                            tags=["import-ics"],
                            entry_date=event_date
                        )
                        events_imported += 1
            
            self.refresh()
            messagebox.showinfo(
                "Import réussi",
                f"{events_imported} événement(s) importé(s) dans le projet '{import_project.name}'"
            )
        
        except Exception as e:
            logger.error(f"ICS import error: {e}", exc_info=True)
            messagebox.showerror("Erreur d'import", f"Impossible d'importer le fichier ICS:\n{e}")


