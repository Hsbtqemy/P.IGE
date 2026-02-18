"""Work panel - Focus mode for daily journaling and task management."""

import logging
import tkinter as tk
from datetime import date, datetime
from tkinter import ttk, messagebox

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
        
        # Create main paned window (horizontal splitter)
        self.main_paned = ttk.PanedWindow(self, orient=tk.VERTICAL)
        self.main_paned.pack(fill=tk.BOTH, expand=True, padx=10, pady=(0, 10))
        
        # Top pane: Editor
        self._setup_quick_entry()
        
        # Bottom pane: Tasks and Recent entries
        bottom_frame = ttk.Frame(self.main_paned)
        self.main_paned.add(bottom_frame, weight=1)
        
        # Create bottom paned window (tasks | entries)
        self.bottom_paned = ttk.PanedWindow(bottom_frame, orient=tk.HORIZONTAL)
        self.bottom_paned.pack(fill=tk.BOTH, expand=True)
        
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
        entry_frame = ttk.LabelFrame(self.main_paned, text="✍️ Entry Editor", padding=10)
        self.main_paned.add(entry_frame, weight=3)
        
        # Top toolbar: Type, Title, Entry selector
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
        title_entry = ttk.Entry(top_row, textvariable=self.entry_title_var, width=40)
        title_entry.pack(side=tk.LEFT, padx=5, fill=tk.X, expand=True)
        
        # Current entry indicator
        self.current_entry_var = tk.StringVar(value="Nouvelle entry")
        ttk.Label(
            top_row,
            textvariable=self.current_entry_var,
            font=("TkDefaultFont", 9),
            foreground="gray"
        ).pack(side=tk.LEFT, padx=(10, 0))
        
        # Markdown editor
        ttk.Label(entry_frame, text="Contenu (Markdown):").pack(anchor=tk.W, pady=(5, 2))
        
        editor_frame = ttk.Frame(entry_frame)
        editor_frame.pack(fill=tk.BOTH, expand=True, pady=(0, 5))
        
        # Scrollbar for text editor
        text_scroll = ttk.Scrollbar(editor_frame)
        text_scroll.pack(side=tk.RIGHT, fill=tk.Y)
        
        self.entry_body_text = tk.Text(
            editor_frame,
            wrap=tk.WORD,
            font=("Consolas", 10),
            yscrollcommand=text_scroll.set,
            undo=True,
            maxundo=-1
        )
        self.entry_body_text.pack(fill=tk.BOTH, expand=True, side=tk.LEFT)
        text_scroll.config(command=self.entry_body_text.yview)
        
        # Track if content is modified
        self.entry_body_text.bind("<<Modified>>", self._on_content_modified)
        self._current_entry_id: str | None = None
        self._entry_modified = False
        
        # Buttons
        btn_row = ttk.Frame(entry_frame)
        btn_row.pack(fill=tk.X)
        
        self.btn_save = ttk.Button(
            btn_row,
            text="💾 Enregistrer",
            command=self._on_save_entry,
            state=tk.DISABLED
        )
        self.btn_save.pack(side=tk.LEFT)
        
        ttk.Button(
            btn_row,
            text="➕ Nouvelle",
            command=self._on_new_entry_editor
        ).pack(side=tk.LEFT, padx=(5, 0))
        
        ttk.Button(
            btn_row,
            text="🗑️ Supprimer",
            command=self._on_delete_current_entry
        ).pack(side=tk.LEFT, padx=(5, 0))
        
        ttk.Button(
            btn_row,
            text="📄 Ouvrir MD externe",
            command=self._on_open_external
        ).pack(side=tk.LEFT, padx=(5, 0))
    
    def _setup_tasks_section(self) -> None:
        """Setup tasks list for active project."""
        tasks_frame = ttk.LabelFrame(self.bottom_paned, text="✓ Tasks du Projet", padding=10)
        self.bottom_paned.add(tasks_frame, weight=1)
        
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
        recent_frame = ttk.LabelFrame(self.bottom_paned, text="📝 Entries Récentes", padding=10)
        self.bottom_paned.add(recent_frame, weight=1)
        
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
        # Check timer state from storage
        state = self.service.storage.read_timer_state()
        
        if state.running and state.project_id:
            # Get project info
            project = self._projects_by_id.get(state.project_id)
            
            if project and state.start_time:
                try:
                    start_time = datetime.fromisoformat(state.start_time.replace('Z', '+00:00'))
                    elapsed = datetime.now(start_time.tzinfo) - start_time
                    hours = int(elapsed.total_seconds() // 3600)
                    minutes = int((elapsed.total_seconds() % 3600) // 60)
                    
                    self.timer_var.set(f"⏱️ {project.name} - {hours:02d}:{minutes:02d}")
                    self.btn_start_timer.config(state=tk.DISABLED)
                    self.btn_stop_timer.config(state=tk.NORMAL)
                    return
                except Exception as e:
                    logger.error(f"Failed to parse timer: {e}")
        
        # No timer running
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
    
    def _on_save_entry(self) -> None:
        """Save current entry modifications."""
        if not self._current_entry_id:
            # No entry loaded, create new one
            self._on_add_entry()
            return
        
        title = self.entry_title_var.get().strip()
        if not title:
            messagebox.showwarning("Attention", "Le titre est requis")
            return
        
        body = self.entry_body_text.get("1.0", tk.END).strip()
        
        try:
            # Update entry content (body in MD file)
            self.service.update_entry_content(self._current_entry_id, body)
            
            # Update metadata if title changed
            entries = self.service.storage.read_entries_meta()
            entry = next((e for e in entries if e.id == self._current_entry_id), None)
            
            if entry and entry.title != title:
                self.service.update_entry_meta(self._current_entry_id, {"title": title})
            
            # Reset modified flag
            self._entry_modified = False
            self.entry_body_text.edit_modified(False)
            self.btn_save.config(state=tk.DISABLED)
            self.current_entry_var.set(f"✓ Enregistré: {title[:40]}")
            
            # Refresh list
            self._refresh_entries()
            
        except Exception as e:
            messagebox.showerror("Erreur", f"Impossible d'enregistrer:\n{e}")
    
    def _on_new_entry_editor(self) -> None:
        """Start editing a new entry."""
        if self._entry_modified:
            result = messagebox.askyesnocancel(
                "Modifications non enregistrées",
                "Voulez-vous enregistrer les modifications avant de créer une nouvelle entry?"
            )
            if result is None:  # Cancel
                return
            elif result:  # Yes
                self._on_save_entry()
        
        # Clear editor
        self._current_entry_id = None
        self.entry_title_var.set("")
        self.entry_body_text.delete("1.0", tk.END)
        self.entry_type_var.set("note")
        self.current_entry_var.set("Nouvelle entry")
        self._entry_modified = False
        self.btn_save.config(state=tk.DISABLED)
    
    def _on_delete_current_entry(self) -> None:
        """Delete currently loaded entry."""
        if not self._current_entry_id:
            messagebox.showwarning("Attention", "Aucune entry chargée")
            return
        
        title = self.entry_title_var.get()
        result = messagebox.askyesno(
            "Confirmer suppression",
            f"Supprimer l'entry \"{title}\"?\n\nCette action est irréversible."
        )
        
        if result:
            try:
                self.service.delete_entry(self._current_entry_id)
                self._on_new_entry_editor()  # Clear editor
                self._refresh_entries()
                messagebox.showinfo("Succès", "Entry supprimée")
            except Exception as e:
                messagebox.showerror("Erreur", f"Impossible de supprimer:\n{e}")
    
    def _on_open_external(self) -> None:
        """Open current entry in external editor."""
        if not self._current_entry_id:
            messagebox.showwarning("Attention", "Aucune entry chargée")
            return
        
        entry_path = self.service.storage.data_dir / "entries" / f"{self._current_entry_id}.md"
        
        if not entry_path.exists():
            messagebox.showerror("Erreur", f"Fichier non trouvé: {entry_path}")
            return
        
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
    
    def _on_content_modified(self, event=None) -> None:
        """Handle text content modification."""
        if self.entry_body_text.edit_modified():
            self._entry_modified = True
            self.btn_save.config(state=tk.NORMAL)
    
    def _load_entry_in_editor(self, entry_id: str) -> None:
        """Load an entry into the editor."""
        # Check for unsaved changes
        if self._entry_modified:
            result = messagebox.askyesnocancel(
                "Modifications non enregistrées",
                "Voulez-vous enregistrer les modifications?"
            )
            if result is None:  # Cancel
                return
            elif result:  # Yes
                self._on_save_entry()
        
        # Load entry
        try:
            entries = self.service.storage.read_entries_meta()
            entry = next((e for e in entries if e.id == entry_id), None)
            
            if not entry:
                messagebox.showerror("Erreur", "Entry non trouvée")
                return
            
            # Load content
            entry_path = self.service.storage.data_dir / "entries" / f"{entry_id}.md"
            if entry_path.exists():
                content = entry_path.read_text(encoding="utf-8")
            else:
                content = ""
            
            # Update editor
            self._current_entry_id = entry_id
            self.entry_title_var.set(entry.title)
            self.entry_type_var.set(entry.type)
            self.entry_body_text.delete("1.0", tk.END)
            self.entry_body_text.insert("1.0", content)
            self.current_entry_var.set(f"📝 {entry.title[:40]}{'...' if len(entry.title) > 40 else ''}")
            
            # Reset modified flag
            self._entry_modified = False
            self.entry_body_text.edit_modified(False)
            self.btn_save.config(state=tk.DISABLED)
            
        except Exception as e:
            messagebox.showerror("Erreur", f"Impossible de charger l'entry:\n{e}")
    
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
        """Handle entry double-click (load in editor)."""
        selection = self.entries_tree.selection()
        if not selection:
            return
        
        entry_id = selection[0]
        self._load_entry_in_editor(entry_id)
    
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
