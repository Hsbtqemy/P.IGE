"""Entries panel for viewing and managing journal entries."""

import logging
import tkinter as tk
from datetime import datetime
from tkinter import ttk, messagebox

from pige.core.service import PigeService
from pige.interfaces.gui.pagination import PaginationControl, PaginationState

logger = logging.getLogger(__name__)


class EntriesPanel(ttk.Frame):
    """Panel for viewing and managing entries."""
    
    def __init__(self, parent: tk.Widget, service: PigeService, initial_page_size: int = 50, **kwargs) -> None:
        super().__init__(parent, **kwargs)
        self.service = service
        
        # State
        self._all_entries: list = []
        self._filtered_entries: list = []
        self._projects_by_id: dict = {}
        
        # Pagination
        self.pagination = PaginationState(page_size=initial_page_size)
        
        # Setup UI
        self._setup_toolbar()
        self._setup_filters()
        self._setup_tree()
        self._setup_pagination()
        self._setup_status()
        
        # Load data
        self.refresh()
    
    def _setup_toolbar(self) -> None:
        """Setup toolbar with action buttons."""
        toolbar = ttk.Frame(self)
        toolbar.pack(fill=tk.X, padx=5, pady=5)
        
        ttk.Button(
            toolbar,
            text="➕ Nouvelle Entry",
            command=self._on_new_entry
        ).pack(side=tk.LEFT, padx=2)
        
        ttk.Button(
            toolbar,
            text="🔄 Rafraîchir",
            command=self.refresh
        ).pack(side=tk.LEFT, padx=2)
        
        ttk.Button(
            toolbar,
            text="📄 Ouvrir MD",
            command=self._on_open_markdown
        ).pack(side=tk.LEFT, padx=2)
    
    def _setup_filters(self) -> None:
        """Setup filter controls."""
        filters_frame = ttk.LabelFrame(self, text="Filtres", padding=5)
        filters_frame.pack(fill=tk.X, padx=5, pady=5)
        
        # Project filter
        ttk.Label(filters_frame, text="Projet:").grid(row=0, column=0, sticky=tk.W, padx=2)
        self.project_var = tk.StringVar(value="Tous")
        self.project_combo = ttk.Combobox(
            filters_frame,
            textvariable=self.project_var,
            state="readonly",
            width=25
        )
        self.project_combo.grid(row=0, column=1, sticky=tk.W, padx=2)
        self.project_combo.bind("<<ComboboxSelected>>", lambda e: self._apply_filters())
        
        # Type filter
        ttk.Label(filters_frame, text="Type:").grid(row=0, column=2, sticky=tk.W, padx=2)
        self.type_var = tk.StringVar(value="Tous")
        self.type_combo = ttk.Combobox(
            filters_frame,
            textvariable=self.type_var,
            values=["Tous", "note", "meeting", "decision", "activity"],
            state="readonly",
            width=15
        )
        self.type_combo.grid(row=0, column=3, sticky=tk.W, padx=2)
        self.type_combo.bind("<<ComboboxSelected>>", lambda e: self._apply_filters())
        
        # Search
        ttk.Label(filters_frame, text="Recherche:").grid(row=0, column=4, sticky=tk.W, padx=2)
        self.search_var = tk.StringVar()
        self.search_var.trace_add("write", lambda *args: self._apply_filters())
        search_entry = ttk.Entry(filters_frame, textvariable=self.search_var, width=20)
        search_entry.grid(row=0, column=5, sticky=tk.W, padx=2)
        
        ttk.Button(
            filters_frame,
            text="❌ Effacer",
            command=self._clear_filters
        ).grid(row=0, column=6, padx=5)
    
    def _setup_tree(self) -> None:
        """Setup treeview for entries list."""
        tree_frame = ttk.Frame(self)
        tree_frame.pack(fill=tk.BOTH, expand=True, padx=5, pady=5)
        
        # Scrollbars
        vsb = ttk.Scrollbar(tree_frame, orient=tk.VERTICAL)
        hsb = ttk.Scrollbar(tree_frame, orient=tk.HORIZONTAL)
        
        # Treeview
        self.tree = ttk.Treeview(
            tree_frame,
            columns=("date", "type", "title", "project", "tags"),
            show="headings",
            yscrollcommand=vsb.set,
            xscrollcommand=hsb.set
        )
        
        # Configure columns
        self.tree.heading("date", text="Date")
        self.tree.heading("type", text="Type")
        self.tree.heading("title", text="Titre")
        self.tree.heading("project", text="Projet")
        self.tree.heading("tags", text="Tags")
        
        self.tree.column("date", width=100, minwidth=80)
        self.tree.column("type", width=100, minwidth=80)
        self.tree.column("title", width=300, minwidth=150)
        self.tree.column("project", width=200, minwidth=100)
        self.tree.column("tags", width=150, minwidth=80)
        
        # Configure scrollbars
        vsb.config(command=self.tree.yview)
        hsb.config(command=self.tree.xview)
        
        # Grid layout
        self.tree.grid(row=0, column=0, sticky=(tk.N, tk.S, tk.E, tk.W))
        vsb.grid(row=0, column=1, sticky=(tk.N, tk.S))
        hsb.grid(row=1, column=0, sticky=(tk.E, tk.W))
        
        tree_frame.rowconfigure(0, weight=1)
        tree_frame.columnconfigure(0, weight=1)
        
        # Bind events
        self.tree.bind("<Double-Button-1>", self._on_entry_double_click)
        self.tree.bind("<Button-3>", self._on_entry_right_click)
    
    def _setup_pagination(self) -> None:
        """Setup pagination control."""
        self.pagination_control = PaginationControl(
            self,
            self.pagination,
            on_page_change=self._on_page_change
        )
        self.pagination_control.pack(fill=tk.X, padx=5, pady=5)
    
    def _setup_status(self) -> None:
        """Setup status bar."""
        self.status_var = tk.StringVar(value="Prêt")
        status_bar = ttk.Label(
            self,
            textvariable=self.status_var,
            relief=tk.SUNKEN,
            anchor=tk.W
        )
        status_bar.pack(fill=tk.X, side=tk.BOTTOM, padx=5, pady=2)
    
    def refresh(self) -> None:
        """Refresh entries list."""
        logger.debug("Refreshing entries panel")
        
        # Load entries and projects
        self._all_entries = self.service.storage.read_entries_meta()
        self._all_entries.sort(key=lambda e: e.entry_date or e.ts, reverse=True)
        
        projects = self.service.list_projects(status="all")
        self._projects_by_id = {p.id: p for p in projects}
        
        # Update project filter dropdown
        project_names = ["Tous"] + [p.name for p in projects]
        self.project_combo.config(values=project_names)
        
        # Apply filters and update display
        self._apply_filters()
    
    def _apply_filters(self) -> None:
        """Apply current filters to entries list."""
        filtered = self._all_entries
        
        # Project filter
        selected_project = self.project_var.get()
        if selected_project != "Tous":
            project_id = next(
                (p.id for p in self._projects_by_id.values() if p.name == selected_project),
                None
            )
            if project_id:
                filtered = [e for e in filtered if e.project_id == project_id]
        
        # Type filter
        selected_type = self.type_var.get()
        if selected_type != "Tous":
            filtered = [e for e in filtered if e.type == selected_type]
        
        # Search filter (in title)
        search_text = self.search_var.get().strip().lower()
        if search_text:
            filtered = [e for e in filtered if search_text in e.title.lower()]
        
        self._filtered_entries = filtered
        self.pagination.set_total_items(len(filtered))
        self._refresh_current_page()
        
        # Update status
        self.status_var.set(f"{len(filtered)} entries (sur {len(self._all_entries)} total)")
    
    def _refresh_current_page(self) -> None:
        """Refresh current page display."""
        # Clear tree
        for item in self.tree.get_children():
            self.tree.delete(item)
        
        # Get current page slice
        start_idx = self.pagination.state.start_index
        end_idx = self.pagination.state.end_index
        page_entries = self._filtered_entries[start_idx:end_idx]
        
        # Populate tree
        for entry in page_entries:
            project = self._projects_by_id.get(entry.project_id)
            project_name = project.name if project else entry.project_id[:8]
            
            # Format date
            if entry.entry_date:
                date_str = entry.entry_date
            else:
                try:
                    dt = datetime.fromisoformat(entry.ts.replace('Z', '+00:00'))
                    date_str = dt.strftime("%Y-%m-%d")
                except Exception:
                    date_str = "?"
            
            # Format tags
            tags_str = ", ".join(entry.tags) if entry.tags else ""
            
            self.tree.insert(
                "",
                tk.END,
                iid=entry.id,
                values=(date_str, entry.type, entry.title, project_name, tags_str)
            )
    
    def _on_page_change(self) -> None:
        """Handle pagination page change."""
        self._refresh_current_page()
        self.event_generate("<<PaginationChanged>>")
    
    def _clear_filters(self) -> None:
        """Clear all filters."""
        self.project_var.set("Tous")
        self.type_var.set("Tous")
        self.search_var.set("")
        self._apply_filters()
    
    def _on_new_entry(self) -> None:
        """Handle new entry button."""
        # TODO: Open CreateEntryDialog
        messagebox.showinfo("TODO", "CreateEntryDialog à implémenter")
    
    def _on_entry_double_click(self, event: tk.Event) -> None:
        """Handle double-click on entry."""
        selection = self.tree.selection()
        if not selection:
            return
        
        entry_id = selection[0]
        logger.info(f"Double-click on entry: {entry_id}")
        
        # TODO: Open EditEntryDialog
        messagebox.showinfo("TODO", f"EditEntryDialog à implémenter pour entry {entry_id[:8]}")
    
    def _on_entry_right_click(self, event: tk.Event) -> None:
        """Handle right-click on entry (context menu)."""
        # Select item under cursor
        item = self.tree.identify_row(event.y)
        if not item:
            return
        
        self.tree.selection_set(item)
        
        # Create context menu
        menu = tk.Menu(self, tearoff=0)
        menu.add_command(label="✏️ Éditer", command=lambda: self._on_entry_double_click(None))
        menu.add_command(label="📄 Ouvrir MD", command=self._on_open_markdown)
        menu.add_separator()
        menu.add_command(label="🗑️ Supprimer", command=self._on_delete_entry)
        
        menu.post(event.x_root, event.y_root)
    
    def _on_open_markdown(self) -> None:
        """Open selected entry markdown file."""
        selection = self.tree.selection()
        if not selection:
            messagebox.showwarning("Attention", "Aucune entry sélectionnée")
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
    
    def _on_delete_entry(self) -> None:
        """Delete selected entry."""
        selection = self.tree.selection()
        if not selection:
            return
        
        entry_id = selection[0]
        entry = next((e for e in self._all_entries if e.id == entry_id), None)
        if not entry:
            return
        
        # Confirm deletion
        result = messagebox.askyesno(
            "Confirmer suppression",
            f"Supprimer l'entry \"{entry.title}\"?\n\nCette action est irréversible."
        )
        
        if result:
            try:
                self.service.delete_entry(entry_id)
                self.refresh()
                self.status_var.set(f"Entry supprimée: {entry.title}")
            except Exception as e:
                messagebox.showerror("Erreur", f"Impossible de supprimer l'entry:\n{e}")
    
    def get_page_size(self) -> int:
        """Get current page size for preference saving."""
        return self.pagination.state.page_size
