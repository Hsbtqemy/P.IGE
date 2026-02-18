"""Work panel - Focus mode for daily journaling and task management."""

import logging
import tkinter as tk
from datetime import date, datetime
from tkinter import ttk, messagebox, scrolledtext

from pige.core.service import PigeService

logger = logging.getLogger(__name__)


class WorkPanel(ttk.Frame):
    """Work panel for focused daily work - journaling, tasks, and time tracking."""
    
    def __init__(self, parent: tk.Widget, service: PigeService, **kwargs) -> None:
        super().__init__(parent, **kwargs)
        self.service = service
        
        # State
        self.current_project_id: str | None = None
        self._projects_by_id: dict = {}
        self._projects_by_name: dict = {}
        
        # Setup UI
        self._setup_project_selector()
        self._setup_timer_display()
        self._setup_quick_entry()
        self._setup_tasks_section()
        self._setup_recent_entries()
        
        # Load initial data
        self.refresh()
    
    def _setup_project_selector(self) -> None:
        """Setup project selection dropdown."""
        selector_frame = ttk.Frame(self)
        selector_frame.pack(fill=tk.X, padx=10, pady=10)
        
        ttk.Label(
            selector_frame,
            text="📂 Projet actif:",
            font=("TkDefaultFont", 10, "bold")
        ).pack(side=tk.LEFT, padx=(0, 10))
        
        self.project_var = tk.StringVar()
        self.project_combo = ttk.Combobox(
            selector_frame,
            textvariable=self.project_var,
            state="readonly",
            width=40,
            font=("TkDefaultFont", 10)
        )
        self.project_combo.pack(side=tk.LEFT, fill=tk.X, expand=True)
        self.project_combo.bind("<<ComboboxSelected>>", self._on_project_changed)
        
        ttk.Button(
            selector_frame,
            text="🔄",
            width=3,
            command=self.refresh
        ).pack(side=tk.LEFT, padx=(5, 0))
    
    def _setup_timer_display(self) -> None:
        """Setup timer display and controls."""
        timer_frame = ttk.LabelFrame(self, text="⏱️ Timer", padding=10)
        timer_frame.pack(fill=tk.X, padx=10, pady=(0, 10))
        
        # Timer display
        self.timer_var = tk.StringVar(value="Aucun timer actif")
        timer_label = ttk.Label(
            timer_frame,
            textvariable=self.timer_var,
            font=("TkDefaultFont", 11)
        )
        timer_label.pack(side=tk.LEFT, padx=(0, 20))
        
        # Timer buttons
        self.btn_start_timer = ttk.Button(
            timer_frame,
            text="▶ Start",
            command=self._on_start_timer,
            width=10
        )
        self.btn_start_timer.pack(side=tk.LEFT, padx=2)
        
        self.btn_stop_timer = ttk.Button(
            timer_frame,
            text="⏹ Stop",
            command=self._on_stop_timer,
            state=tk.DISABLED,
            width=10
        )
        self.btn_stop_timer.pack(side=tk.LEFT, padx=2)
    
    def _setup_quick_entry(self) -> None:
        """Setup quick entry creation form."""
        entry_frame = ttk.LabelFrame(self, text="✍️ Nouvelle Entry", padding=10)
        entry_frame.pack(fill=tk.BOTH, expand=True, padx=10, pady=(0, 10))
        
        # Type and Title
        top_row = ttk.Frame(entry_frame)
        top_row.pack(fill=tk.X, pady=(0, 5))
        
        ttk.Label(top_row, text="Type:").pack(side=tk.LEFT)
        self.entry_type_var = tk.StringVar(value="note")
        type_combo = ttk.Combobox(
            top_row,
            textvariable=self.entry_type_var,
            values=["note", "meeting", "decision", "activity"],
            state="readonly",
            width=12
        )
        type_combo.pack(side=tk.LEFT, padx=(5, 20))
        
        ttk.Label(top_row, text="Titre:").pack(side=tk.LEFT)
        self.entry_title_var = tk.StringVar()
        title_entry = ttk.Entry(top_row, textvariable=self.entry_title_var, width=50)
        title_entry.pack(side=tk.LEFT, padx=5, fill=tk.X, expand=True)
        
        # Body
        ttk.Label(entry_frame, text="Contenu:").pack(anchor=tk.W, pady=(5, 2))
        self.entry_body_text = scrolledtext.ScrolledText(
            entry_frame,
            height=10,
            wrap=tk.WORD,
            font=("Consolas", 10)
        )
        self.entry_body_text.pack(fill=tk.BOTH, expand=True, pady=(0, 5))
        
        # Buttons
        btn_row = ttk.Frame(entry_frame)
        btn_row.pack(fill=tk.X)
        
        ttk.Button(
            btn_row,
            text="➕ Ajouter Entry",
            command=self._on_add_entry,
            style="Accent.TButton"
        ).pack(side=tk.LEFT)
        
        ttk.Button(
            btn_row,
            text="🗑️ Effacer",
            command=self._on_clear_form
        ).pack(side=tk.LEFT, padx=(5, 0))
    
    def _setup_tasks_section(self) -> None:
        """Setup tasks list for active project."""
        tasks_frame = ttk.LabelFrame(self, text="✓ Tasks du Projet", padding=10)
        tasks_frame.pack(fill=tk.BOTH, expand=True, padx=10, pady=(0, 10))
        
        # Toolbar
        toolbar = ttk.Frame(tasks_frame)
        toolbar.pack(fill=tk.X, pady=(0, 5))
        
        ttk.Button(
            toolbar,
            text="➕ Nouvelle Task",
            command=self._on_add_task
        ).pack(side=tk.LEFT)
        
        # Tasks tree
        tree_frame = ttk.Frame(tasks_frame)
        tree_frame.pack(fill=tk.BOTH, expand=True)
        
        scrollbar = ttk.Scrollbar(tree_frame)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        
        self.tasks_tree = ttk.Treeview(
            tree_frame,
            columns=("title", "status", "due"),
            show="tree headings",
            yscrollcommand=scrollbar.set,
            height=6
        )
        
        self.tasks_tree.heading("#0", text="✓")
        self.tasks_tree.heading("title", text="Titre")
        self.tasks_tree.heading("status", text="Statut")
        self.tasks_tree.heading("due", text="Échéance")
        
        self.tasks_tree.column("#0", width=30, stretch=False)
        self.tasks_tree.column("title", width=300)
        self.tasks_tree.column("status", width=100)
        self.tasks_tree.column("due", width=100)
        
        self.tasks_tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        scrollbar.config(command=self.tasks_tree.yview)
        
        # Bind events
        self.tasks_tree.bind("<Double-Button-1>", self._on_task_double_click)
        self.tasks_tree.bind("<space>", self._on_task_toggle)
    
    def _setup_recent_entries(self) -> None:
        """Setup recent entries list."""
        recent_frame = ttk.LabelFrame(self, text="📝 Entries Récentes", padding=10)
        recent_frame.pack(fill=tk.BOTH, expand=True, padx=10, pady=(0, 10))
        
        # Entries tree
        tree_frame = ttk.Frame(recent_frame)
        tree_frame.pack(fill=tk.BOTH, expand=True)
        
        scrollbar = ttk.Scrollbar(tree_frame)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        
        self.entries_tree = ttk.Treeview(
            tree_frame,
            columns=("date", "type", "title"),
            show="headings",
            yscrollcommand=scrollbar.set,
            height=5
        )
        
        self.entries_tree.heading("date", text="Date")
        self.entries_tree.heading("type", text="Type")
        self.entries_tree.heading("title", text="Titre")
        
        self.entries_tree.column("date", width=100)
        self.entries_tree.column("type", width=100)
        self.entries_tree.column("title", width=400)
        
        self.entries_tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        scrollbar.config(command=self.entries_tree.yview)
        
        self.entries_tree.bind("<Double-Button-1>", self._on_entry_double_click)
    
    def refresh(self) -> None:
        """Refresh all data."""
        logger.debug("Refreshing work panel")
        
        # Load projects
        projects = self.service.list_projects(status="active")
        self._projects_by_id = {p.id: p for p in projects}
        self._projects_by_name = {p.name: p for p in projects}
        
        # Update project dropdown
        project_names = sorted([p.name for p in projects])
        self.project_combo.config(values=project_names)
        
        # Select first project if none selected
        if not self.current_project_id and project_names:
            self.project_var.set(project_names[0])
            self._on_project_changed(None)
        
        # Refresh timer
        self._refresh_timer()
        
        # Refresh current project data
        if self.current_project_id:
            self._refresh_tasks()
            self._refresh_entries()
    
    def _on_project_changed(self, event) -> None:
        """Handle project selection change."""
        project_name = self.project_var.get()
        project = self._projects_by_name.get(project_name)
        
        if project:
            self.current_project_id = project.id
            self._refresh_tasks()
            self._refresh_entries()
    
    def _refresh_timer(self) -> None:
        """Refresh timer display."""
        projects = self.service.list_projects(status="all")
        active_timer = next((p for p in projects if p.timer_start), None)
        
        if active_timer:
            start_time = datetime.fromisoformat(active_timer.timer_start.replace('Z', '+00:00'))
            elapsed = datetime.now(start_time.tzinfo) - start_time
            hours = int(elapsed.total_seconds() // 3600)
            minutes = int((elapsed.total_seconds() % 3600) // 60)
            
            self.timer_var.set(f"⏱️ {active_timer.name} - {hours:02d}:{minutes:02d}")
            self.btn_start_timer.config(state=tk.DISABLED)
            self.btn_stop_timer.config(state=tk.NORMAL)
        else:
            self.timer_var.set("Aucun timer actif")
            self.btn_start_timer.config(state=tk.NORMAL)
            self.btn_stop_timer.config(state=tk.DISABLED)
    
    def _refresh_tasks(self) -> None:
        """Refresh tasks list for current project."""
        # Clear tree
        for item in self.tasks_tree.get_children():
            self.tasks_tree.delete(item)
        
        if not self.current_project_id:
            return
        
        # Load and display tasks
        try:
            tasks = self.service.list_tasks(self.current_project_id, status="all")
            tasks.sort(key=lambda t: (
                t.status == "done",  # Open tasks first
                t.due_date or "9999-99-99"  # Then by due date
            ))
            
            for task in tasks[:20]:  # Limit to 20 tasks
                icon = "✓" if task.status == "done" else "○"
                due_str = task.due_date or "-"
                
                self.tasks_tree.insert(
                    "",
                    tk.END,
                    iid=task.id,
                    text=icon,
                    values=(task.title, task.status, due_str)
                )
        except Exception as e:
            logger.error(f"Failed to load tasks: {e}")
    
    def _refresh_entries(self) -> None:
        """Refresh recent entries for current project."""
        # Clear tree
        for item in self.entries_tree.get_children():
            self.entries_tree.delete(item)
        
        if not self.current_project_id:
            return
        
        # Load and display recent entries
        all_entries = self.service.storage.read_entries_meta()
        project_entries = [e for e in all_entries if e.project_id == self.current_project_id]
        project_entries.sort(key=lambda e: e.entry_date or e.ts, reverse=True)
        
        for entry in project_entries[:10]:  # Show last 10
            date_str = entry.entry_date or "?"
            
            self.entries_tree.insert(
                "",
                tk.END,
                iid=entry.id,
                values=(date_str, entry.type, entry.title)
            )
    
    def _on_add_entry(self) -> None:
        """Add new entry."""
        if not self.current_project_id:
            messagebox.showwarning("Attention", "Veuillez sélectionner un projet")
            return
        
        title = self.entry_title_var.get().strip()
        if not title:
            messagebox.showwarning("Attention", "Le titre est requis")
            return
        
        body = self.entry_body_text.get("1.0", tk.END).strip()
        entry_type = self.entry_type_var.get()
        
        try:
            self.service.add_entry(
                project_id=self.current_project_id,
                entry_type=entry_type,
                title=title,
                body=body,
                entry_date=date.today()
            )
            
            # Clear form
            self._on_clear_form()
            
            # Refresh
            self._refresh_entries()
            
            messagebox.showinfo("Succès", f"Entry '{title}' créée!")
        except Exception as e:
            messagebox.showerror("Erreur", f"Impossible de créer l'entry:\n{e}")
    
    def _on_clear_form(self) -> None:
        """Clear entry form."""
        self.entry_title_var.set("")
        self.entry_body_text.delete("1.0", tk.END)
        self.entry_type_var.set("note")
    
    def _on_add_task(self) -> None:
        """Add new task (placeholder)."""
        if not self.current_project_id:
            messagebox.showwarning("Attention", "Veuillez sélectionner un projet")
            return
        
        # Simple dialog for task
        from tkinter import simpledialog
        
        title = simpledialog.askstring("Nouvelle Task", "Titre de la task:")
        if not title:
            return
        
        try:
            self.service.create_task(
                project_id=self.current_project_id,
                title=title,
                status="open"
            )
            
            self._refresh_tasks()
            messagebox.showinfo("Succès", f"Task '{title}' créée!")
        except Exception as e:
            messagebox.showerror("Erreur", f"Impossible de créer la task:\n{e}")
    
    def _on_task_double_click(self, event) -> None:
        """Handle task double-click (edit)."""
        selection = self.tasks_tree.selection()
        if not selection:
            return
        
        task_id = selection[0]
        messagebox.showinfo("TODO", f"Éditer task {task_id[:8]} (à implémenter)")
    
    def _on_task_toggle(self, event) -> None:
        """Toggle task done/open."""
        selection = self.tasks_tree.selection()
        if not selection:
            return
        
        task_id = selection[0]
        
        try:
            tasks = self.service.list_tasks(self.current_project_id, status="all")
            task = next((t for t in tasks if t.id == task_id), None)
            
            if task:
                new_status = "open" if task.status == "done" else "done"
                self.service.set_task_done(task_id, new_status == "done")
                self._refresh_tasks()
        except Exception as e:
            logger.error(f"Failed to toggle task: {e}")
    
    def _on_entry_double_click(self, event) -> None:
        """Handle entry double-click (open MD file)."""
        selection = self.entries_tree.selection()
        if not selection:
            return
        
        entry_id = selection[0]
        entry_path = self.service.storage.data_dir / "entries" / f"{entry_id}.md"
        
        if not entry_path.exists():
            messagebox.showerror("Erreur", f"Fichier non trouvé: {entry_path}")
            return
        
        # Open with default editor
        import subprocess
        import sys
        
        try:
            if sys.platform.startswith("win"):
                import os
                os.startfile(str(entry_path))
            elif sys.platform == "darwin":
                subprocess.run(["open", str(entry_path)], check=True)
            else:
                subprocess.run(["xdg-open", str(entry_path)], check=True)
        except Exception as e:
            messagebox.showerror("Erreur", f"Impossible d'ouvrir le fichier:\n{e}")
    
    def _on_start_timer(self) -> None:
        """Start timer for current project."""
        if not self.current_project_id:
            messagebox.showwarning("Attention", "Veuillez sélectionner un projet")
            return
        
        try:
            self.service.time_start(self.current_project_id, note=None)
            self._refresh_timer()
            messagebox.showinfo("Timer", "Timer démarré!")
        except Exception as e:
            messagebox.showerror("Erreur", f"Impossible de démarrer le timer:\n{e}")
    
    def _on_stop_timer(self) -> None:
        """Stop active timer."""
        try:
            self.service.time_stop(create_activity=False)
            self._refresh_timer()
            messagebox.showinfo("Timer", "Timer arrêté!")
        except Exception as e:
            messagebox.showerror("Erreur", f"Impossible d'arrêter le timer:\n{e}")
