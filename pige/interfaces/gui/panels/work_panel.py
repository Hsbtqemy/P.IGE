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
        
        # Setup UI with 3-pane layout
        self._setup_timer_display()
        
        # Main horizontal splitter: Explorer | Editor+Tasks
        self.main_splitter = ttk.PanedWindow(self, orient=tk.HORIZONTAL)
        self.main_splitter.pack(fill=tk.BOTH, expand=True, padx=10, pady=(0, 10))
        
        # Left pane: Project/Entry explorer
        self._setup_explorer()
        
        # Right pane: Editor + Tasks (vertical splitter)
        right_frame = ttk.Frame(self.main_splitter)
        self.main_splitter.add(right_frame, weight=3)
        
        self.right_splitter = ttk.PanedWindow(right_frame, orient=tk.VERTICAL)
        self.right_splitter.pack(fill=tk.BOTH, expand=True)
        
        # Right top: Editor
        self._setup_editor()
        
        # Right bottom: Tasks
        self._setup_tasks_section()
        
        # Load initial data
        self.refresh()
    
    def _setup_timer_display(self) -> None:
        """Setup timer display and controls."""
        timer_frame = ttk.LabelFrame(self, text="⏱️ Timer", padding=10)
        timer_frame.pack(fill=tk.X, padx=10, pady=10)
        
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
    
    def _setup_explorer(self) -> None:
        """Setup project/entry explorer tree."""
        explorer_frame = ttk.LabelFrame(self.main_splitter, text="📂 Projets & Entries", padding=5)
        self.main_splitter.add(explorer_frame, weight=1)
        
        # Toolbar
        toolbar = ttk.Frame(explorer_frame)
        toolbar.pack(fill=tk.X, pady=(0, 5))
        
        ttk.Button(
            toolbar,
            text="🔄",
            width=3,
            command=self.refresh
        ).pack(side=tk.LEFT)
        
        ttk.Button(
            toolbar,
            text="➕ Entry",
            command=self._on_new_entry_from_explorer
        ).pack(side=tk.LEFT, padx=(5, 0))
        
        # Tree
        tree_frame = ttk.Frame(explorer_frame)
        tree_frame.pack(fill=tk.BOTH, expand=True)
        
        scrollbar = ttk.Scrollbar(tree_frame)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        
        self.explorer_tree = ttk.Treeview(
            tree_frame,
            yscrollcommand=scrollbar.set,
            selectmode="browse"
        )
        self.explorer_tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        scrollbar.config(command=self.explorer_tree.yview)
        
        # Configure tree appearance
        self.explorer_tree.heading("#0", text="Navigation")
        
        # Bind events
        self.explorer_tree.bind("<<TreeviewSelect>>", self._on_explorer_select)
        self.explorer_tree.bind("<Double-Button-1>", self._on_explorer_double_click)
    
    def _setup_editor(self) -> None:
        """Setup markdown editor."""
        editor_frame = ttk.LabelFrame(self.right_splitter, text="✍️ Entry Editor", padding=10)
        self.right_splitter.add(editor_frame, weight=3)
        
        # Top toolbar: Type, Title, Entry selector
        top_row = ttk.Frame(editor_frame)
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
        ttk.Label(editor_frame, text="Contenu (Markdown):").pack(anchor=tk.W, pady=(5, 2))
        
        text_frame = ttk.Frame(editor_frame)
        text_frame.pack(fill=tk.BOTH, expand=True, pady=(0, 5))
        
        # Scrollbar for text editor
        text_scroll = ttk.Scrollbar(text_frame)
        text_scroll.pack(side=tk.RIGHT, fill=tk.Y)
        
        self.entry_body_text = tk.Text(
            text_frame,
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
        btn_row = ttk.Frame(editor_frame)
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
    
    
    def refresh(self) -> None:
        """Refresh all data."""
        logger.debug("Refreshing work panel")
        
        # Load projects
        projects = self.service.list_projects(status="active")
        self._projects_by_id = {p.id: p for p in projects}
        
        # Refresh explorer tree
        self._refresh_explorer()
        
        # Refresh timer
        self._refresh_timer()
        
        # Refresh current project data
        if self.current_project_id:
            self._refresh_tasks()
    
    def _refresh_explorer(self) -> None:
        """Refresh the project/entry explorer tree."""
        # Clear tree
        for item in self.explorer_tree.get_children():
            self.explorer_tree.delete(item)
        
        # Get all entries
        all_entries = self.service.storage.read_entries_meta()
        entries_by_project: dict[str, list] = {}
        
        for entry in all_entries:
            if entry.project_id not in entries_by_project:
                entries_by_project[entry.project_id] = []
            entries_by_project[entry.project_id].append(entry)
        
        # Sort entries by date (newest first)
        for entries in entries_by_project.values():
            entries.sort(key=lambda e: e.entry_date or e.ts, reverse=True)
        
        # Build tree: Projects with their entries
        for project in sorted(self._projects_by_id.values(), key=lambda p: p.name):
            # Add project node
            project_text = f"📂 {project.name}"
            project_node = self.explorer_tree.insert(
                "",
                tk.END,
                iid=f"project:{project.id}",
                text=project_text,
                open=False
            )
            
            # Add entries under project
            project_entries = entries_by_project.get(project.id, [])
            for entry in project_entries[:20]:  # Limit to 20 most recent
                entry_icon = {
                    "note": "📝",
                    "meeting": "🤝",
                    "decision": "✅",
                    "activity": "⚡"
                }.get(entry.type, "📄")
                
                entry_text = f"{entry_icon} {entry.title[:50]}"
                if entry.entry_date:
                    entry_text += f" ({entry.entry_date})"
                
                self.explorer_tree.insert(
                    project_node,
                    tk.END,
                    iid=f"entry:{entry.id}",
                    text=entry_text
                )
    
    def _on_explorer_select(self, event=None) -> None:
        """Handle selection in explorer tree."""
        selection = self.explorer_tree.selection()
        if not selection:
            return
        
        item_id = selection[0]
        
        if item_id.startswith("project:"):
            # Project selected
            project_id = item_id.replace("project:", "")
            self.current_project_id = project_id
            self._refresh_tasks()
            # Don't load in editor, just update tasks
            
        elif item_id.startswith("entry:"):
            # Entry selected - show preview or wait for double-click
            pass
    
    def _on_explorer_double_click(self, event=None) -> None:
        """Handle double-click in explorer tree."""
        selection = self.explorer_tree.selection()
        if not selection:
            return
        
        item_id = selection[0]
        
        if item_id.startswith("entry:"):
            # Load entry in editor
            entry_id = item_id.replace("entry:", "")
            self._load_entry_in_editor(entry_id)
            
            # Set current project
            entries = self.service.storage.read_entries_meta()
            entry = next((e for e in entries if e.id == entry_id), None)
            if entry:
                self.current_project_id = entry.project_id
                self._refresh_tasks()
    
    def _on_new_entry_from_explorer(self) -> None:
        """Create new entry from explorer."""
        # Get selected project or ask user
        selection = self.explorer_tree.selection()
        
        if selection and selection[0].startswith("project:"):
            project_id = selection[0].replace("project:", "")
            self.current_project_id = project_id
        elif selection and selection[0].startswith("entry:"):
            # Get project from entry
            entry_id = selection[0].replace("entry:", "")
            entries = self.service.storage.read_entries_meta()
            entry = next((e for e in entries if e.id == entry_id), None)
            if entry:
                self.current_project_id = entry.project_id
        
        if not self.current_project_id:
            messagebox.showwarning("Attention", "Sélectionnez d'abord un projet dans l'arborescence")
            return
        
        # Start new entry
        self._on_new_entry_editor()
    
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
            
            # Refresh explorer
            self._refresh_explorer()
            
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
            
            # Refresh explorer
            self._refresh_explorer()
            
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
                self._refresh_explorer()
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
