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
from datetime import datetime, timedelta
from tkinter import ttk
from typing import TYPE_CHECKING

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
        
        # Canvas for scrolling
        canvas = tk.Canvas(main_container, highlightthickness=0)
        scrollbar = ttk.Scrollbar(main_container, orient=tk.VERTICAL, command=canvas.yview)
        self.scrollable_frame = ttk.Frame(canvas)
        
        self.scrollable_frame.bind(
            "<Configure>",
            lambda e: canvas.configure(scrollregion=canvas.bbox("all"))
        )
        
        canvas.create_window((0, 0), window=self.scrollable_frame, anchor="nw")
        canvas.configure(yscrollcommand=scrollbar.set)
        
        canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        
        # Mouse wheel scrolling
        def _on_mousewheel(event):
            canvas.yview_scroll(int(-1*(event.delta/120)), "units")
        canvas.bind_all("<MouseWheel>", _on_mousewheel)
        
        # Create sections
        self._create_in_progress_section()
        self._create_pending_section()
        self._create_upcoming_section()
        self._create_focus_section()
    
    def _create_in_progress_section(self) -> None:
        """Create the 'In Progress' section."""
        section = ttk.LabelFrame(
            self.scrollable_frame,
            text="📋 En Cours",
            padding=10
        )
        section.pack(fill=tk.BOTH, expand=True, padx=10, pady=5)
        
        # TreeView for in-progress items
        tree_frame = ttk.Frame(section)
        tree_frame.pack(fill=tk.BOTH, expand=True)
        
        scrollbar = ttk.Scrollbar(tree_frame, orient=tk.VERTICAL)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        
        self.in_progress_tree = ttk.Treeview(
            tree_frame,
            columns=("type", "title", "project", "age"),
            show="headings",
            height=6,
            yscrollcommand=scrollbar.set
        )
        self.in_progress_tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        scrollbar.config(command=self.in_progress_tree.yview)
        
        # Configure columns
        self.in_progress_tree.heading("type", text="Type")
        self.in_progress_tree.heading("title", text="Titre")
        self.in_progress_tree.heading("project", text="Projet")
        self.in_progress_tree.heading("age", text="Âge")
        
        self.in_progress_tree.column("type", width=80, stretch=False)
        self.in_progress_tree.column("title", width=300, stretch=True)
        self.in_progress_tree.column("project", width=150, stretch=False)
        self.in_progress_tree.column("age", width=80, stretch=False)
        
        # Bind events
        self.in_progress_tree.bind("<Double-Button-1>", self._on_item_double_click)
    
    def _create_pending_section(self) -> None:
        """Create the 'Pending' section."""
        section = ttk.LabelFrame(
            self.scrollable_frame,
            text="⏸️ En Attente",
            padding=10
        )
        section.pack(fill=tk.BOTH, expand=True, padx=10, pady=5)
        
        # TreeView for pending items
        tree_frame = ttk.Frame(section)
        tree_frame.pack(fill=tk.BOTH, expand=True)
        
        scrollbar = ttk.Scrollbar(tree_frame, orient=tk.VERTICAL)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        
        self.pending_tree = ttk.Treeview(
            tree_frame,
            columns=("type", "title", "project", "since"),
            show="headings",
            height=4,
            yscrollcommand=scrollbar.set
        )
        self.pending_tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        scrollbar.config(command=self.pending_tree.yview)
        
        # Configure columns
        self.pending_tree.heading("type", text="Type")
        self.pending_tree.heading("title", text="Titre")
        self.pending_tree.heading("project", text="Projet")
        self.pending_tree.heading("since", text="Depuis")
        
        self.pending_tree.column("type", width=80, stretch=False)
        self.pending_tree.column("title", width=300, stretch=True)
        self.pending_tree.column("project", width=150, stretch=False)
        self.pending_tree.column("since", width=80, stretch=False)
        
        # Bind events
        self.pending_tree.bind("<Double-Button-1>", self._on_item_double_click)
    
    def _create_upcoming_section(self) -> None:
        """Create the 'Upcoming' section."""
        section = ttk.LabelFrame(
            self.scrollable_frame,
            text="📅 À Venir (7 prochains jours)",
            padding=10
        )
        section.pack(fill=tk.BOTH, expand=True, padx=10, pady=5)
        
        # TreeView for upcoming items
        tree_frame = ttk.Frame(section)
        tree_frame.pack(fill=tk.BOTH, expand=True)
        
        scrollbar = ttk.Scrollbar(tree_frame, orient=tk.VERTICAL)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        
        self.upcoming_tree = ttk.Treeview(
            tree_frame,
            columns=("date", "type", "title", "project"),
            show="headings",
            height=5,
            yscrollcommand=scrollbar.set
        )
        self.upcoming_tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        scrollbar.config(command=self.upcoming_tree.yview)
        
        # Configure columns
        self.upcoming_tree.heading("date", text="Date")
        self.upcoming_tree.heading("type", text="Type")
        self.upcoming_tree.heading("title", text="Titre")
        self.upcoming_tree.heading("project", text="Projet")
        
        self.upcoming_tree.column("date", width=100, stretch=False)
        self.upcoming_tree.column("type", width=80, stretch=False)
        self.upcoming_tree.column("title", width=300, stretch=True)
        self.upcoming_tree.column("project", width=130, stretch=False)
        
        # Bind events
        self.upcoming_tree.bind("<Double-Button-1>", self._on_item_double_click)
    
    def _create_focus_section(self) -> None:
        """Create the 'Focus Suggestions' section."""
        section = ttk.LabelFrame(
            self.scrollable_frame,
            text="🎯 Focus Suggéré",
            padding=10
        )
        section.pack(fill=tk.BOTH, padx=10, pady=5)
        
        # Text widget for suggestions
        self.focus_text = tk.Text(
            section,
            height=4,
            wrap=tk.WORD,
            relief=tk.FLAT,
            background=self.cget("background"),
            font=("TkDefaultFont", 10)
        )
        self.focus_text.pack(fill=tk.BOTH, expand=True)
        self.focus_text.config(state=tk.DISABLED)  # Read-only
    
    def refresh(self) -> None:
        """Refresh all dashboard sections."""
        logger.debug("Refreshing dashboard")
        
        self._refresh_in_progress()
        self._refresh_pending()
        self._refresh_upcoming()
        self._refresh_focus()
    
    def _refresh_in_progress(self) -> None:
        """Refresh the 'In Progress' section."""
        # Clear existing items
        for item in self.in_progress_tree.get_children():
            self.in_progress_tree.delete(item)
        
        # Get in-progress items from service
        in_progress = self.service.get_in_progress_items(days=self.timeline_days)
        
        # Add entries
        for entry in in_progress["entries"]:
            # Get project name
            try:
                project = self.service.get_project(entry.project_id)
                project_name = project.name
            except Exception:
                project_name = entry.project_id[:8]
            
            # Calculate age
            from datetime import datetime
            if entry.entry_date:
                entry_date = datetime.fromisoformat(entry.entry_date)
                age_days = (datetime.now().date() - entry_date.date()).days
                age_str = f"{age_days}j" if age_days > 0 else "Aujourd'hui"
            else:
                age_str = "?"
            
            # Insert into tree
            self.in_progress_tree.insert(
                "",
                tk.END,
                iid=f"entry_{entry.id}",
                values=("📝 Entry", entry.title, project_name, age_str),
                tags=("entry",)
            )
        
        # Add tasks
        for task in in_progress["tasks"]:
            # Get project name
            try:
                project = self.service.get_project(task.project_id)
                project_name = project.name
            except Exception:
                project_name = task.project_id[:8]
            
            # Calculate age
            from datetime import datetime
            if task.created_at:
                created_date = datetime.fromisoformat(task.created_at)
                age_days = (datetime.now() - created_date).days
                age_str = f"{age_days}j" if age_days > 0 else "Aujourd'hui"
            else:
                age_str = "?"
            
            # Insert into tree
            self.in_progress_tree.insert(
                "",
                tk.END,
                iid=f"task_{task.id}",
                values=("✅ Task", task.title, project_name, age_str),
                tags=("task",)
            )
        
        # Show message if empty
        if not in_progress["entries"] and not in_progress["tasks"]:
            self.in_progress_tree.insert(
                "",
                tk.END,
                values=("", "Aucun item en cours", "", "")
            )
    
    def _refresh_pending(self) -> None:
        """Refresh the 'Pending' section."""
        # Clear existing items
        for item in self.pending_tree.get_children():
            self.pending_tree.delete(item)
        
        # Get pending items from service
        pending = self.service.get_pending_items()
        
        # Add tasks
        for task in pending["tasks"]:
            # Get project name
            try:
                project = self.service.get_project(task.project_id)
                project_name = project.name
            except Exception:
                project_name = task.project_id[:8]
            
            # Calculate time since creation
            from datetime import datetime
            if task.created_at:
                created_date = datetime.fromisoformat(task.created_at)
                days_since = (datetime.now() - created_date).days
                since_str = f"{days_since}j" if days_since > 0 else "Aujourd'hui"
            else:
                since_str = "?"
            
            # Insert into tree
            self.pending_tree.insert(
                "",
                tk.END,
                iid=f"task_{task.id}",
                values=("✅ Task", task.title, project_name, since_str),
                tags=("task",)
            )
        
        # Add entries (if any with waiting/blocked tags)
        for entry in pending["entries"]:
            try:
                project = self.service.get_project(entry.project_id)
                project_name = project.name
            except Exception:
                project_name = entry.project_id[:8]
            
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
                values=("📝 Entry", entry.title, project_name, since_str),
                tags=("entry",)
            )
        
        # Show message if empty
        if not pending["tasks"] and not pending["entries"]:
            self.pending_tree.insert(
                "",
                tk.END,
                values=("", "Aucun item en attente", "", "")
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
            self.upcoming_tree.insert(
                "",
                tk.END,
                iid=f"{item['type'].lower()}_{item['item_id']}",
                values=(
                    date_display,
                    item["type"],
                    item["title"],
                    item["project_name"]
                ),
                tags=(item["type"].lower(),)
            )
        
        # Show message if empty
        if not upcoming:
            self.upcoming_tree.insert(
                "",
                tk.END,
                values=("", "", f"Aucun événement dans les {self.timeline_days} prochains jours", "")
            )
    
    def _refresh_focus(self) -> None:
        """Refresh the 'Focus Suggestions' section."""
        self.focus_text.config(state=tk.NORMAL)
        self.focus_text.delete("1.0", tk.END)
        
        # Get focus suggestions from service
        focus = self.service.get_focus_suggestions()
        
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
        
        # Default message if no suggestions
        if len(suggestions) == 1:  # Only the summary
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
    
    def _on_item_double_click(self, event: tk.Event) -> None:
        """Handle double-click on an item."""
        tree = event.widget
        selection = tree.selection()
        if not selection:
            return
        
        item_id = selection[0]
        values = tree.item(item_id, "values")
        
        logger.info(f"Dashboard item double-clicked: {values}")
        # TODO: Open entry/task detail dialog or navigate to item
