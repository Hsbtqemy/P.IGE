"""Calendar panel for PIGE GUI - visualize entries and tasks over time."""

import calendar
import logging
import tkinter as tk
from datetime import date, datetime, timedelta
from tkinter import ttk

from pige.core.service import PigeService

logger = logging.getLogger(__name__)


class CalendarPanel(ttk.Frame):
    """Panel for displaying entries and tasks in a calendar view."""
    
    def __init__(self, parent: tk.Widget, service: PigeService, **kwargs) -> None:
        super().__init__(parent, **kwargs)
        self.service = service
        
        # Current view state
        today = date.today()
        self.current_year = today.year
        self.current_month = today.month
        self.selected_date: date | None = None
        
        # Data cache
        self._entries_by_date: dict[str, list] = {}
        self._tasks_by_date: dict[str, list] = {}
        
        # Setup UI
        self._setup_toolbar()
        self._setup_calendar_view()
        self._setup_details_panel()
        
        # Load initial data
        self.refresh()
    
    def _setup_toolbar(self) -> None:
        """Setup navigation toolbar."""
        toolbar = ttk.Frame(self)
        toolbar.pack(fill=tk.X, padx=5, pady=5)
        
        # Navigation buttons
        ttk.Button(
            toolbar,
            text="◀◀ Année",
            command=self._prev_year,
            width=10
        ).pack(side=tk.LEFT, padx=2)
        
        ttk.Button(
            toolbar,
            text="◀ Mois",
            command=self._prev_month,
            width=10
        ).pack(side=tk.LEFT, padx=2)
        
        # Current month/year label
        self.month_label = ttk.Label(
            toolbar,
            text="",
            font=("TkDefaultFont", 12, "bold")
        )
        self.month_label.pack(side=tk.LEFT, padx=20)
        
        ttk.Button(
            toolbar,
            text="Mois ▶",
            command=self._next_month,
            width=10
        ).pack(side=tk.LEFT, padx=2)
        
        ttk.Button(
            toolbar,
            text="Année ▶▶",
            command=self._next_year,
            width=10
        ).pack(side=tk.LEFT, padx=2)
        
        ttk.Button(
            toolbar,
            text="📅 Aujourd'hui",
            command=self._goto_today
        ).pack(side=tk.LEFT, padx=20)
        
        ttk.Button(
            toolbar,
            text="🔄 Rafraîchir",
            command=self.refresh
        ).pack(side=tk.RIGHT, padx=2)
    
    def _setup_calendar_view(self) -> None:
        """Setup monthly calendar grid."""
        # Main container with splitter
        self.splitter = ttk.PanedWindow(self, orient=tk.HORIZONTAL)
        self.splitter.pack(fill=tk.BOTH, expand=True, padx=5, pady=5)
        
        # Left: Calendar grid
        calendar_frame = ttk.Frame(self.splitter)
        self.splitter.add(calendar_frame, weight=2)
        
        # Day headers (Mon-Sun)
        headers_frame = ttk.Frame(calendar_frame)
        headers_frame.pack(fill=tk.X, pady=(0, 2))
        
        day_names = ["Lun", "Mar", "Mer", "Jeu", "Ven", "Sam", "Dim"]
        for day_name in day_names:
            label = ttk.Label(
                headers_frame,
                text=day_name,
                anchor=tk.CENTER,
                font=("TkDefaultFont", 9, "bold")
            )
            label.pack(side=tk.LEFT, fill=tk.X, expand=True)
        
        # Calendar grid (6 weeks x 7 days)
        self.calendar_grid_frame = ttk.Frame(calendar_frame)
        self.calendar_grid_frame.pack(fill=tk.BOTH, expand=True)
        
        self.day_frames = {}  # date_str -> Frame
        
        for week in range(6):
            week_frame = ttk.Frame(self.calendar_grid_frame)
            week_frame.pack(fill=tk.BOTH, expand=True)
            
            for day in range(7):
                day_frame = tk.Frame(
                    week_frame,
                    relief=tk.RAISED,
                    borderwidth=1,
                    bg="white"
                )
                day_frame.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=1, pady=1)
                
                # Store frame reference (will be populated later)
                day_id = f"{week}_{day}"
                self.day_frames[day_id] = day_frame
    
    def _setup_details_panel(self) -> None:
        """Setup details panel for selected date."""
        details_frame = ttk.LabelFrame(self.splitter, text="Détails du jour", padding=10)
        self.splitter.add(details_frame, weight=1)
        
        # Selected date label
        self.selected_date_label = ttk.Label(
            details_frame,
            text="Aucune date sélectionnée",
            font=("TkDefaultFont", 10, "bold")
        )
        self.selected_date_label.pack(anchor=tk.W, pady=(0, 10))
        
        # Entries list
        entries_label = ttk.Label(details_frame, text="📝 Entries:", font=("TkDefaultFont", 9, "bold"))
        entries_label.pack(anchor=tk.W, pady=(5, 2))
        
        entries_list_frame = ttk.Frame(details_frame)
        entries_list_frame.pack(fill=tk.BOTH, expand=True)
        
        entries_scroll = ttk.Scrollbar(entries_list_frame, orient=tk.VERTICAL)
        entries_scroll.pack(side=tk.RIGHT, fill=tk.Y)
        
        self.entries_listbox = tk.Listbox(
            entries_list_frame,
            yscrollcommand=entries_scroll.set,
            height=8
        )
        self.entries_listbox.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        entries_scroll.config(command=self.entries_listbox.yview)
        self.entries_listbox.bind("<Double-Button-1>", self._on_entry_double_click)
        
        # Tasks list
        tasks_label = ttk.Label(details_frame, text="✓ Tasks:", font=("TkDefaultFont", 9, "bold"))
        tasks_label.pack(anchor=tk.W, pady=(10, 2))
        
        tasks_list_frame = ttk.Frame(details_frame)
        tasks_list_frame.pack(fill=tk.BOTH, expand=True)
        
        tasks_scroll = ttk.Scrollbar(tasks_list_frame, orient=tk.VERTICAL)
        tasks_scroll.pack(side=tk.RIGHT, fill=tk.Y)
        
        self.tasks_listbox = tk.Listbox(
            tasks_list_frame,
            yscrollcommand=tasks_scroll.set,
            height=8
        )
        self.tasks_listbox.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        tasks_scroll.config(command=self.tasks_listbox.yview)
    
    def refresh(self) -> None:
        """Refresh calendar data and view."""
        logger.debug(f"Refreshing calendar for {self.current_year}-{self.current_month:02d}")
        
        # Load entries and tasks for current month (+ buffer)
        self._load_month_data()
        
        # Update calendar display
        self._update_calendar_grid()
        
        # Update month label
        month_name = calendar.month_name[self.current_month]
        self.month_label.config(text=f"{month_name} {self.current_year}")
        
        # Update details if date selected
        if self.selected_date:
            self._update_details_panel()
    
    def _load_month_data(self) -> None:
        """Load entries and tasks for current month."""
        # Get month boundaries
        first_day = date(self.current_year, self.current_month, 1)
        if self.current_month == 12:
            last_day = date(self.current_year + 1, 1, 1) - timedelta(days=1)
        else:
            last_day = date(self.current_year, self.current_month + 1, 1) - timedelta(days=1)
        
        # Load all entries
        all_entries = self.service.storage.read_entries_meta()
        
        # Group by date
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
        
        # Load all tasks from all projects
        projects = self.service.list_projects(status="all")
        all_tasks = []
        for project in projects:
            tasks = self.service.list_tasks(project_id=project.id, status="all")
            all_tasks.extend(tasks)
        
        # Group by due date
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
    
    def _update_calendar_grid(self) -> None:
        """Update calendar grid with current month."""
        # Get calendar for current month
        cal = calendar.monthcalendar(self.current_year, self.current_month)
        today = date.today()
        
        # Populate each day frame
        for week_idx, week in enumerate(cal):
            for day_idx, day_num in enumerate(week):
                day_id = f"{week_idx}_{day_idx}"
                frame = self.day_frames.get(day_id)
                
                if not frame:
                    continue
                
                # Clear frame
                for widget in frame.winfo_children():
                    widget.destroy()
                
                if day_num == 0:
                    # Empty day (prev/next month)
                    frame.config(bg="#f0f0f0")
                    continue
                
                # Valid day
                day_date = date(self.current_year, self.current_month, day_num)
                date_str = day_date.isoformat()
                
                # Background color
                if day_date == today:
                    frame.config(bg="#ffffcc")  # Light yellow for today
                elif day_date == self.selected_date:
                    frame.config(bg="#cce5ff")  # Light blue for selected
                else:
                    frame.config(bg="white")
                
                # Day number
                day_label = tk.Label(
                    frame,
                    text=str(day_num),
                    font=("TkDefaultFont", 10, "bold"),
                    bg=frame.cget("bg"),
                    anchor=tk.NW
                )
                day_label.pack(anchor=tk.NW, padx=2, pady=2)
                
                # Entries count
                entries_count = len(self._entries_by_date.get(date_str, []))
                if entries_count > 0:
                    entries_indicator = tk.Label(
                        frame,
                        text=f"📝 {entries_count}",
                        font=("TkDefaultFont", 8),
                        bg=frame.cget("bg"),
                        fg="#0066cc"
                    )
                    entries_indicator.pack(anchor=tk.W, padx=2)
                
                # Tasks count
                tasks = self._tasks_by_date.get(date_str, [])
                tasks_done = len([t for t in tasks if t.status == "done"])
                tasks_total = len(tasks)
                if tasks_total > 0:
                    tasks_indicator = tk.Label(
                        frame,
                        text=f"✓ {tasks_done}/{tasks_total}",
                        font=("TkDefaultFont", 8),
                        bg=frame.cget("bg"),
                        fg="#00aa00" if tasks_done == tasks_total else "#cc6600"
                    )
                    tasks_indicator.pack(anchor=tk.W, padx=2)
                
                # Bind click event
                frame.bind("<Button-1>", lambda e, d=day_date: self._on_day_click(d))
                day_label.bind("<Button-1>", lambda e, d=day_date: self._on_day_click(d))
    
    def _on_day_click(self, day_date: date) -> None:
        """Handle day click."""
        self.selected_date = day_date
        self._update_calendar_grid()
        self._update_details_panel()
    
    def _update_details_panel(self) -> None:
        """Update details panel for selected date."""
        if not self.selected_date:
            return
        
        date_str = self.selected_date.isoformat()
        
        # Update label
        day_name = calendar.day_name[self.selected_date.weekday()]
        self.selected_date_label.config(
            text=f"{day_name} {self.selected_date.strftime('%d/%m/%Y')}"
        )
        
        # Update entries list
        self.entries_listbox.delete(0, tk.END)
        entries = self._entries_by_date.get(date_str, [])
        for entry in entries:
            type_icon = {"note": "📄", "meeting": "👥", "decision": "⚖️", "activity": "🎯"}.get(entry.type, "📝")
            self.entries_listbox.insert(tk.END, f"{type_icon} {entry.title}")
        
        if not entries:
            self.entries_listbox.insert(tk.END, "(aucune entry)")
        
        # Update tasks list
        self.tasks_listbox.delete(0, tk.END)
        tasks = self._tasks_by_date.get(date_str, [])
        for task in tasks:
            status_icon = "✅" if task.status == "done" else "⬜"
            self.tasks_listbox.insert(tk.END, f"{status_icon} {task.title}")
        
        if not tasks:
            self.tasks_listbox.insert(tk.END, "(aucune task)")
    
    def _on_entry_double_click(self, event: tk.Event) -> None:
        """Handle double-click on entry in details panel."""
        selection = self.entries_listbox.curselection()
        if not selection:
            return
        
        idx = selection[0]
        date_str = self.selected_date.isoformat()
        entries = self._entries_by_date.get(date_str, [])
        
        if idx < len(entries):
            entry = entries[idx]
            logger.info(f"Entry double-clicked: {entry.id}")
            # TODO: Open entry editor or switch to Work panel
    
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
        self.current_year -= 1
        self.refresh()
    
    def _next_year(self) -> None:
        """Navigate to next year."""
        self.current_year += 1
        self.refresh()
    
    def _goto_today(self) -> None:
        """Navigate to today's date."""
        today = date.today()
        self.current_year = today.year
        self.current_month = today.month
        self.selected_date = today
        self.refresh()
