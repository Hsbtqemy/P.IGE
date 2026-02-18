"""Enhanced calendar panel with week view and improved visuals."""

import calendar
import logging
import tkinter as tk
from datetime import date, datetime, timedelta
from tkinter import ttk, messagebox, filedialog
from pathlib import Path

from pige.core.service import PigeService

logger = logging.getLogger(__name__)


class CalendarPanel(ttk.Frame):
    """Panel for displaying entries and tasks in calendar views (month/week)."""
    
    def __init__(self, parent: tk.Widget, service: PigeService, **kwargs) -> None:
        super().__init__(parent, **kwargs)
        self.service = service
        
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
        self._projects_by_id: dict = {}
        
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
            text="◀◀",
            command=self._prev_year,
            width=4
        ).pack(side=tk.LEFT, padx=1)
        
        ttk.Button(
            toolbar,
            text="◀",
            command=self._prev_period,
            width=4
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
            text="▶",
            command=self._next_period,
            width=4
        ).pack(side=tk.LEFT, padx=1)
        
        ttk.Button(
            toolbar,
            text="▶▶",
            command=self._next_year,
            width=4
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
        # Main splitter
        self.main_splitter = ttk.PanedWindow(self, orient=tk.HORIZONTAL)
        self.main_splitter.pack(fill=tk.BOTH, expand=True, padx=5, pady=5)
        
        # View container (will hold month or week view)
        self.view_container = ttk.Frame(self.main_splitter)
        self.main_splitter.add(self.view_container, weight=2)
    
    def _setup_details_panel(self) -> None:
        """Setup details panel for selected date."""
        details_frame = ttk.LabelFrame(self.main_splitter, text="📋 Détails", padding=10)
        self.main_splitter.add(details_frame, weight=1)
        
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
            text="➕ Nouvelle Entry",
            command=self._create_entry_for_date,
            width=18
        ).pack(side=tk.LEFT, padx=2)
        
        ttk.Button(
            actions_frame,
            text="✓ Nouvelle Task",
            command=self._create_task_for_date,
            width=18
        ).pack(side=tk.LEFT, padx=2)
        
        # Notebook for entries and tasks
        details_notebook = ttk.Notebook(details_frame)
        details_notebook.pack(fill=tk.BOTH, expand=True)
        
        # Entries tab
        entries_tab = ttk.Frame(details_notebook)
        details_notebook.add(entries_tab, text="📝 Entries")
        
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
        tasks_tab = ttk.Frame(details_notebook)
        details_notebook.add(tasks_tab, text="✓ Tasks")
        
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
            month_name = calendar.month_name[self.current_month]
            self.period_label.config(text=f"{month_name} {self.current_year}")
        else:
            week_end = self.current_week_start + timedelta(days=6)
            if self.current_week_start.month == week_end.month:
                label = f"{self.current_week_start.day}-{week_end.day} {calendar.month_name[self.current_week_start.month]} {self.current_week_start.year}"
            else:
                label = f"{self.current_week_start.strftime('%d %b')} - {week_end.strftime('%d %b %Y')}"
            self.period_label.config(text=label)
    
    def _load_data(self) -> None:
        """Load entries and tasks."""
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
    
    def _render_month_view(self) -> None:
        """Render month calendar view."""
        # Clear container
        for widget in self.view_container.winfo_children():
            widget.destroy()
        
        # Create canvas with scrollbar
        canvas_frame = ttk.Frame(self.view_container)
        canvas_frame.pack(fill=tk.BOTH, expand=True)
        
        # Day headers
        headers_frame = ttk.Frame(canvas_frame)
        headers_frame.pack(fill=tk.X, pady=(0, 2))
        
        day_names = ["Lundi", "Mardi", "Mercredi", "Jeudi", "Vendredi", "Samedi", "Dimanche"]
        for i, day_name in enumerate(day_names):
            label = ttk.Label(
                headers_frame,
                text=day_name,
                anchor=tk.CENTER,
                font=("TkDefaultFont", 9, "bold")
            )
            label.pack(side=tk.LEFT, fill=tk.X, expand=True)
            if i >= 5:  # Weekend
                label.config(foreground="#888")
        
        # Calendar grid
        cal = calendar.monthcalendar(self.current_year, self.current_month)
        today = date.today()
        
        grid_frame = ttk.Frame(canvas_frame)
        grid_frame.pack(fill=tk.BOTH, expand=True)
        
        for week_idx, week in enumerate(cal):
            week_frame = ttk.Frame(grid_frame)
            week_frame.pack(fill=tk.BOTH, expand=True)
            
            for day_idx, day_num in enumerate(week):
                self._create_day_cell(week_frame, day_num, day_idx, today)
    
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
                text=f"✓ {tasks_done}/{tasks_total}",
                font=("TkDefaultFont", 8),
                bg=bg_color,
                fg=color
            ).pack(anchor=tk.W, padx=3)
        
        # Bind click
        for widget in [day_frame, day_label]:
            widget.bind("<Button-1>", lambda e, d=day_date: self._on_day_click(d))
    
    def _render_week_view(self) -> None:
        """Render week calendar view with hourly slots."""
        # Clear container
        for widget in self.view_container.winfo_children():
            widget.destroy()
        
        week_frame = ttk.Frame(self.view_container)
        week_frame.pack(fill=tk.BOTH, expand=True)
        
        # Create scrollable canvas
        canvas = tk.Canvas(week_frame, bg="white")
        scrollbar = ttk.Scrollbar(week_frame, orient=tk.VERTICAL, command=canvas.yview)
        scrollable_frame = ttk.Frame(canvas)
        
        scrollable_frame.bind(
            "<Configure>",
            lambda e: canvas.configure(scrollregion=canvas.bbox("all"))
        )
        
        canvas.create_window((0, 0), window=scrollable_frame, anchor="nw")
        canvas.configure(yscrollcommand=scrollbar.set)
        
        canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        
        # Day headers
        headers_frame = ttk.Frame(scrollable_frame)
        headers_frame.grid(row=0, column=0, columnspan=8, sticky="ew", pady=(0, 5))
        
        ttk.Label(headers_frame, text="", width=8).grid(row=0, column=0)  # Time column
        
        today = date.today()
        for i in range(7):
            day_date = self.current_week_start + timedelta(days=i)
            day_name = ["Lun", "Mar", "Mer", "Jeu", "Ven", "Sam", "Dim"][i]
            
            is_today = day_date == today
            is_weekend = i >= 5
            
            header_text = f"{day_name}\n{day_date.day}/{day_date.month}"
            if is_today:
                header_text = f"🔵 {header_text}"
            
            label = ttk.Label(
                headers_frame,
                text=header_text,
                font=("TkDefaultFont", 9, "bold" if is_today else "normal"),
                anchor=tk.CENTER,
                foreground="#0066cc" if is_today else ("#888" if is_weekend else "#333")
            )
            label.grid(row=0, column=i+1, sticky="ew", padx=1)
            headers_frame.columnconfigure(i+1, weight=1)
        
        # Week grid with day cells
        for i in range(7):
            day_date = self.current_week_start + timedelta(days=i)
            date_str = day_date.isoformat()
            
            is_today = day_date == today
            is_weekend = i >= 5
            is_selected = day_date == self.selected_date
            
            # Choose background
            if is_today:
                bg = self.colors["today"]
            elif is_selected:
                bg = self.colors["selected"]
            elif is_weekend:
                bg = self.colors["weekend"]
            else:
                bg = self.colors["default"]
            
            # Day cell
            day_cell = tk.Frame(
                scrollable_frame,
                bg=bg,
                relief=tk.RAISED,
                borderwidth=1,
                cursor="hand2"
            )
            day_cell.grid(row=1, column=i+1, sticky="nsew", padx=1, pady=1)
            scrollable_frame.columnconfigure(i+1, weight=1)
            
            # Add entries
            entries = self._entries_by_date.get(date_str, [])
            for entry in entries[:5]:  # Limit to 5 visible
                project = self._projects_by_id.get(entry.project_id)
                icon = {"note": "📄", "meeting": "👥", "decision": "⚖️", "activity": "🎯"}.get(entry.type, "📝")
                text = f"{icon} {entry.title[:30]}"
                
                entry_label = tk.Label(
                    day_cell,
                    text=text,
                    bg=bg,
                    fg="#0066cc",
                    font=("TkDefaultFont", 8),
                    anchor=tk.W,
                    cursor="hand2"
                )
                entry_label.pack(fill=tk.X, padx=2, pady=1)
                entry_label.bind("<Button-1>", lambda e, d=day_date: self._on_day_click(d))
            
            if len(entries) > 5:
                tk.Label(
                    day_cell,
                    text=f"+ {len(entries)-5} autres...",
                    bg=bg,
                    fg="#666",
                    font=("TkDefaultFont", 7, "italic")
                ).pack(padx=2)
            
            # Add tasks
            tasks = self._tasks_by_date.get(date_str, [])
            for task in tasks[:5]:
                icon = "✅" if task.status == "done" else "⬜"
                text = f"{icon} {task.title[:30]}"
                
                task_label = tk.Label(
                    day_cell,
                    text=text,
                    bg=bg,
                    fg="#00aa00" if task.status == "done" else "#ff6600",
                    font=("TkDefaultFont", 8),
                    anchor=tk.W
                )
                task_label.pack(fill=tk.X, padx=2, pady=1)
            
            if len(tasks) > 5:
                tk.Label(
                    day_cell,
                    text=f"+ {len(tasks)-5} autres...",
                    bg=bg,
                    fg="#666",
                    font=("TkDefaultFont", 7, "italic")
                ).pack(padx=2)
            
            # Bind click
            day_cell.bind("<Button-1>", lambda e, d=day_date: self._on_day_click(d))
        
        scrollable_frame.rowconfigure(1, weight=1)
    
    def _on_day_click(self, day_date: date) -> None:
        """Handle day click."""
        self.selected_date = day_date
        
        # Update view based on mode
        if self.view_mode == "month":
            # Update month to match selected date if needed
            if day_date.year != self.current_year or day_date.month != self.current_month:
                self.current_year = day_date.year
                self.current_month = day_date.month
        else:
            # Update week to match selected date if needed
            week_start = self._get_week_start(day_date)
            if week_start != self.current_week_start:
                self.current_week_start = week_start
        
        self.refresh()
    
    def _update_details_panel(self) -> None:
        """Update details panel for selected date."""
        if not self.selected_date:
            return
        
        date_str = self.selected_date.isoformat()
        
        # Update label
        day_name = ["Lundi", "Mardi", "Mercredi", "Jeudi", "Vendredi", "Samedi", "Dimanche"][self.selected_date.weekday()]
        self.selected_date_label.config(
            text=f"{day_name} {self.selected_date.strftime('%d/%m/%Y')}"
        )
        
        # Update entries list
        self.entries_listbox.delete(0, tk.END)
        entries = self._entries_by_date.get(date_str, [])
        self._current_entries = entries  # Store for double-click
        for entry in entries:
            type_icon = {"note": "📄", "meeting": "👥", "decision": "⚖️", "activity": "🎯"}.get(entry.type, "📝")
            project = self._projects_by_id.get(entry.project_id)
            project_name = f" [{project.name}]" if project else ""
            self.entries_listbox.insert(tk.END, f"{type_icon} {entry.title}{project_name}")
        
        if not entries:
            self.entries_listbox.insert(tk.END, "(aucune entry ce jour)")
        
        # Update tasks list
        self.tasks_listbox.delete(0, tk.END)
        tasks = self._tasks_by_date.get(date_str, [])
        self._current_tasks = tasks  # Store for double-click
        for task in tasks:
            status_icon = "✅" if task.status == "done" else "⬜"
            self.tasks_listbox.insert(tk.END, f"{status_icon} {task.title}")
        
        if not tasks:
            self.tasks_listbox.insert(tk.END, "(aucune task ce jour)")
    
    def _on_entry_double_click(self, event: tk.Event) -> None:
        """Handle double-click on entry."""
        selection = self.entries_listbox.curselection()
        if not selection or not hasattr(self, '_current_entries'):
            return
        
        idx = selection[0]
        if idx < len(self._current_entries):
            entry = self._current_entries[idx]
            logger.info(f"Entry double-clicked: {entry.id}")
            messagebox.showinfo("TODO", f"Ouvrir éditeur pour entry: {entry.title}\n\n(À connecter au WorkPanel)")
    
    def _on_task_double_click(self, event: tk.Event) -> None:
        """Handle double-click on task."""
        selection = self.tasks_listbox.curselection()
        if not selection or not hasattr(self, '_current_tasks'):
            return
        
        idx = selection[0]
        if idx < len(self._current_tasks):
            task = self._current_tasks[idx]
            logger.info(f"Task double-clicked: {task.id}")
            messagebox.showinfo("TODO", f"Éditer task: {task.title}\n\n(Dialogue à implémenter)")
    
    def _create_entry_for_date(self) -> None:
        """Create new entry for selected date."""
        if not self.selected_date:
            messagebox.showwarning("Attention", "Sélectionnez d'abord une date dans le calendrier")
            return
        
        messagebox.showinfo("TODO", f"Créer entry pour {self.selected_date}\n\n(Dialogue à implémenter)")
    
    def _create_task_for_date(self) -> None:
        """Create new task for selected date."""
        if not self.selected_date:
            messagebox.showwarning("Attention", "Sélectionnez d'abord une date dans le calendrier")
            return
        
        messagebox.showinfo("TODO", f"Créer task pour {self.selected_date}\n\n(Dialogue à implémenter)")
    
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
