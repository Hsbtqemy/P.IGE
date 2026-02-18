"""Dialog for managing calendar subscriptions."""

import logging
import tkinter as tk
from tkinter import ttk, messagebox, filedialog
from typing import Callable

from pige.core.calendar_sync import CalendarSyncManager
from pige.core.service import PigeService

logger = logging.getLogger(__name__)


class CalendarSubscriptionsDialog(tk.Toplevel):
    """Dialog for managing calendar subscriptions."""
    
    def __init__(self, parent: tk.Widget, service: PigeService, on_close: Callable | None = None) -> None:
        super().__init__(parent)
        self.service = service
        self.sync_manager = CalendarSyncManager(service)
        self.on_close_callback = on_close
        
        self.title("Abonnements Calendrier")
        self.geometry("800x500")
        self.transient(parent)
        
        self._setup_ui()
        self._refresh_list()
        
        # Center on parent
        self.update_idletasks()
        x = parent.winfo_x() + (parent.winfo_width() - self.winfo_width()) // 2
        y = parent.winfo_y() + (parent.winfo_height() - self.winfo_height()) // 2
        self.geometry(f"+{x}+{y}")
        
        self.protocol("WM_DELETE_WINDOW", self._on_close)
    
    def _setup_ui(self) -> None:
        """Setup UI components."""
        # Toolbar
        toolbar = ttk.Frame(self)
        toolbar.pack(fill=tk.X, padx=10, pady=10)
        
        ttk.Button(
            toolbar,
            text="➕ Nouvel Abonnement",
            command=self._on_new_subscription
        ).pack(side=tk.LEFT, padx=2)
        
        ttk.Button(
            toolbar,
            text="🔄 Synchroniser Tous",
            command=self._on_sync_all
        ).pack(side=tk.LEFT, padx=2)
        
        ttk.Button(
            toolbar,
            text="🔄 Rafraîchir",
            command=self._refresh_list
        ).pack(side=tk.RIGHT, padx=2)
        
        # Subscriptions list
        list_frame = ttk.Frame(self)
        list_frame.pack(fill=tk.BOTH, expand=True, padx=10, pady=(0, 10))
        
        # Scrollbars
        vsb = ttk.Scrollbar(list_frame, orient=tk.VERTICAL)
        hsb = ttk.Scrollbar(list_frame, orient=tk.HORIZONTAL)
        
        # Treeview
        self.tree = ttk.Treeview(
            list_frame,
            columns=("name", "project", "url", "active", "auto_sync", "last_sync", "events"),
            show="headings",
            yscrollcommand=vsb.set,
            xscrollcommand=hsb.set
        )
        
        # Configure columns
        self.tree.heading("name", text="Nom")
        self.tree.heading("project", text="Projet")
        self.tree.heading("url", text="Source")
        self.tree.heading("active", text="Actif")
        self.tree.heading("auto_sync", text="Auto-Sync")
        self.tree.heading("last_sync", text="Dernière Synchro")
        self.tree.heading("events", text="Événements")
        
        self.tree.column("name", width=150, minwidth=100)
        self.tree.column("project", width=120, minwidth=80)
        self.tree.column("url", width=200, minwidth=150)
        self.tree.column("active", width=60, minwidth=50)
        self.tree.column("auto_sync", width=80, minwidth=60)
        self.tree.column("last_sync", width=130, minwidth=100)
        self.tree.column("events", width=80, minwidth=60)
        
        vsb.config(command=self.tree.yview)
        hsb.config(command=self.tree.xview)
        
        # Grid layout
        self.tree.grid(row=0, column=0, sticky=(tk.N, tk.S, tk.E, tk.W))
        vsb.grid(row=0, column=1, sticky=(tk.N, tk.S))
        hsb.grid(row=1, column=0, sticky=(tk.E, tk.W))
        
        list_frame.rowconfigure(0, weight=1)
        list_frame.columnconfigure(0, weight=1)
        
        # Bind events
        self.tree.bind("<Double-Button-1>", self._on_edit_subscription)
        self.tree.bind("<Button-3>", self._on_context_menu)
        
        # Status bar
        self.status_var = tk.StringVar(value="Prêt")
        status_bar = ttk.Label(
            self,
            textvariable=self.status_var,
            relief=tk.SUNKEN,
            anchor=tk.W
        )
        status_bar.pack(fill=tk.X, side=tk.BOTTOM, padx=10, pady=5)
    
    def _refresh_list(self) -> None:
        """Refresh subscriptions list."""
        # Clear tree
        for item in self.tree.get_children():
            self.tree.delete(item)
        
        # Load subscriptions
        subscriptions = self.sync_manager.list_subscriptions()
        
        # Load projects for display
        projects = self.service.list_projects(status="all")
        projects_by_id = {p.id: p for p in projects}
        
        # Populate tree
        for sub in subscriptions:
            project = projects_by_id.get(sub.project_id)
            project_name = project.name if project else sub.project_id[:8]
            
            # Format last sync
            last_sync_str = "Jamais"
            if sub.last_sync:
                try:
                    from datetime import datetime
                    dt = datetime.fromisoformat(sub.last_sync)
                    last_sync_str = dt.strftime("%d/%m/%Y %H:%M")
                except Exception:
                    last_sync_str = sub.last_sync[:16]
            
            # Truncate URL
            url_display = sub.source_url
            if len(url_display) > 40:
                url_display = url_display[:37] + "..."
            
            self.tree.insert(
                "",
                tk.END,
                iid=sub.id,
                values=(
                    sub.name,
                    project_name,
                    url_display,
                    "✓" if sub.active else "✗",
                    "✓" if sub.auto_sync else "✗",
                    last_sync_str,
                    len(sub.event_mapping)
                )
            )
        
        self.status_var.set(f"{len(subscriptions)} abonnement(s)")
    
    def _on_new_subscription(self) -> None:
        """Show dialog to create new subscription."""
        dialog = NewSubscriptionDialog(self, self.service, self.sync_manager)
        self.wait_window(dialog)
        self._refresh_list()
    
    def _on_edit_subscription(self, event=None) -> None:
        """Edit selected subscription."""
        selection = self.tree.selection()
        if not selection:
            return
        
        sub_id = selection[0]
        subs = self.sync_manager.list_subscriptions()
        sub = next((s for s in subs if s.id == sub_id), None)
        
        if sub:
            dialog = EditSubscriptionDialog(self, self.service, self.sync_manager, sub)
            self.wait_window(dialog)
            self._refresh_list()
    
    def _on_context_menu(self, event) -> None:
        """Show context menu for subscription."""
        item = self.tree.identify_row(event.y)
        if not item:
            return
        
        self.tree.selection_set(item)
        
        menu = tk.Menu(self, tearoff=0)
        menu.add_command(label="🔄 Synchroniser", command=self._on_sync_selected)
        menu.add_command(label="✏️ Éditer", command=self._on_edit_subscription)
        menu.add_separator()
        menu.add_command(label="⏸️ Activer/Désactiver", command=self._on_toggle_active)
        menu.add_separator()
        menu.add_command(label="🗑️ Supprimer", command=self._on_delete_subscription)
        
        menu.post(event.x_root, event.y_root)
    
    def _on_sync_selected(self) -> None:
        """Sync selected subscription."""
        selection = self.tree.selection()
        if not selection:
            return
        
        sub_id = selection[0]
        self.status_var.set("Synchronisation en cours...")
        self.update()
        
        try:
            stats = self.sync_manager.sync_subscription(sub_id)
            
            if stats["errors"]:
                error_msg = "\n".join(stats["errors"][:5])
                messagebox.showwarning(
                    "Synchronisation avec erreurs",
                    f"Ajoutés: {stats['added']}\n"
                    f"Modifiés: {stats['updated']}\n"
                    f"Supprimés: {stats['deleted']}\n\n"
                    f"Erreurs:\n{error_msg}"
                )
            else:
                messagebox.showinfo(
                    "Synchronisation réussie",
                    f"✓ Ajoutés: {stats['added']}\n"
                    f"✓ Modifiés: {stats['updated']}\n"
                    f"✓ Supprimés: {stats['deleted']}"
                )
            
            self._refresh_list()
        except Exception as e:
            messagebox.showerror("Erreur", f"Échec de la synchronisation:\n{e}")
        finally:
            self.status_var.set("Prêt")
    
    def _on_sync_all(self) -> None:
        """Sync all active subscriptions."""
        self.status_var.set("Synchronisation de tous les abonnements...")
        self.update()
        
        try:
            results = self.sync_manager.sync_all_active()
            
            if not results:
                messagebox.showinfo("Info", "Aucun abonnement actif avec auto-sync activé")
                return
            
            total_added = sum(r["added"] for r in results.values())
            total_updated = sum(r["updated"] for r in results.values())
            total_deleted = sum(r["deleted"] for r in results.values())
            
            messagebox.showinfo(
                "Synchronisation terminée",
                f"{len(results)} abonnement(s) synchronisé(s)\n\n"
                f"✓ Ajoutés: {total_added}\n"
                f"✓ Modifiés: {total_updated}\n"
                f"✓ Supprimés: {total_deleted}"
            )
            
            self._refresh_list()
        except Exception as e:
            messagebox.showerror("Erreur", f"Échec de la synchronisation:\n{e}")
        finally:
            self.status_var.set("Prêt")
    
    def _on_toggle_active(self) -> None:
        """Toggle active status of selected subscription."""
        selection = self.tree.selection()
        if not selection:
            return
        
        sub_id = selection[0]
        subs = self.sync_manager.list_subscriptions()
        sub = next((s for s in subs if s.id == sub_id), None)
        
        if sub:
            self.sync_manager.update_subscription(sub_id, {"active": not sub.active})
            self._refresh_list()
    
    def _on_delete_subscription(self) -> None:
        """Delete selected subscription."""
        selection = self.tree.selection()
        if not selection:
            return
        
        sub_id = selection[0]
        subs = self.sync_manager.list_subscriptions()
        sub = next((s for s in subs if s.id == sub_id), None)
        
        if not sub:
            return
        
        # Confirm deletion
        result = messagebox.askyesnocancel(
            "Confirmer suppression",
            f"Supprimer l'abonnement '{sub.name}'?\n\n"
            f"OUI: Supprimer l'abonnement ET les {len(sub.event_mapping)} entrée(s) importée(s)\n"
            f"NON: Supprimer seulement l'abonnement (garder les entrées)\n"
            f"ANNULER: Ne rien supprimer"
        )
        
        if result is None:  # Cancel
            return
        
        delete_entries = result  # True=Yes, False=No
        
        try:
            self.sync_manager.delete_subscription(sub_id, delete_entries=delete_entries)
            messagebox.showinfo("Succès", f"Abonnement '{sub.name}' supprimé")
            self._refresh_list()
        except Exception as e:
            messagebox.showerror("Erreur", f"Échec de la suppression:\n{e}")
    
    def _on_close(self) -> None:
        """Handle window close."""
        if self.on_close_callback:
            self.on_close_callback()
        self.destroy()


class NewSubscriptionDialog(tk.Toplevel):
    """Dialog for creating a new calendar subscription."""
    
    def __init__(self, parent: tk.Widget, service: PigeService, sync_manager: CalendarSyncManager) -> None:
        super().__init__(parent)
        self.service = service
        self.sync_manager = sync_manager
        
        self.title("Nouvel Abonnement Calendrier")
        self.geometry("500x400")
        self.transient(parent)
        
        self._setup_ui()
        
        # Center on parent
        self.update_idletasks()
        x = parent.winfo_x() + (parent.winfo_width() - self.winfo_width()) // 2
        y = parent.winfo_y() + (parent.winfo_height() - self.winfo_height()) // 2
        self.geometry(f"+{x}+{y}")
    
    def _setup_ui(self) -> None:
        """Setup UI."""
        form_frame = ttk.Frame(self, padding=20)
        form_frame.pack(fill=tk.BOTH, expand=True)
        
        # Name
        ttk.Label(form_frame, text="Nom:").grid(row=0, column=0, sticky=tk.W, pady=5)
        self.name_var = tk.StringVar()
        ttk.Entry(form_frame, textvariable=self.name_var, width=40).grid(row=0, column=1, sticky=tk.EW, pady=5)
        
        # Source
        ttk.Label(form_frame, text="Source:").grid(row=1, column=0, sticky=tk.W, pady=5)
        source_frame = ttk.Frame(form_frame)
        source_frame.grid(row=1, column=1, sticky=tk.EW, pady=5)
        
        self.source_var = tk.StringVar()
        ttk.Entry(source_frame, textvariable=self.source_var, width=32).pack(side=tk.LEFT, fill=tk.X, expand=True)
        ttk.Button(source_frame, text="📁", command=self._browse_file, width=3).pack(side=tk.LEFT, padx=(2, 0))
        
        ttk.Label(form_frame, text="(URL ou chemin fichier .ics)", font=("TkDefaultFont", 8)).grid(
            row=2, column=1, sticky=tk.W, pady=(0, 5)
        )
        
        # Help button for getting calendar URL
        help_btn = ttk.Button(
            form_frame,
            text="❓ Comment obtenir l'URL du calendrier?",
            command=self._show_url_help
        )
        help_btn.grid(row=3, column=1, sticky=tk.W, pady=(0, 10))
        
        # Project
        ttk.Label(form_frame, text="Projet cible:").grid(row=4, column=0, sticky=tk.W, pady=5)
        
        project_frame = ttk.Frame(form_frame)
        project_frame.grid(row=4, column=1, sticky=tk.EW, pady=5)
        
        self.project_var = tk.StringVar()
        self.project_combo = ttk.Combobox(project_frame, textvariable=self.project_var, state="readonly", width=30)
        self.project_combo.pack(side=tk.LEFT, fill=tk.X, expand=True)
        
        # Load projects with "Créer nouveau projet" option
        projects = self.service.list_projects(status="all")
        self.projects_by_name = {p.name: p.id for p in projects}
        self.projects_by_name["➕ Créer un nouveau projet pour ce calendrier"] = None
        
        project_names = ["➕ Créer un nouveau projet pour ce calendrier"] + [p.name for p in projects]
        self.project_combo["values"] = project_names
        self.project_combo.current(0)  # Default to create new project
        
        # Options
        ttk.Separator(form_frame, orient=tk.HORIZONTAL).grid(row=5, column=0, columnspan=2, sticky=tk.EW, pady=15)
        
        # Authentication (optional, collapsed by default)
        auth_label = ttk.Label(form_frame, text="🔐 Authentification (optionnelle):", font=("TkDefaultFont", 9, "bold"))
        auth_label.grid(row=6, column=0, columnspan=2, sticky=tk.W, pady=(5, 5))
        
        ttk.Label(form_frame, text="Nom d'utilisateur:", font=("TkDefaultFont", 8)).grid(row=7, column=0, sticky=tk.W, padx=(10, 0))
        self.username_var = tk.StringVar()
        ttk.Entry(form_frame, textvariable=self.username_var, width=38).grid(row=7, column=1, sticky=tk.EW, pady=2)
        
        ttk.Label(form_frame, text="Mot de passe:", font=("TkDefaultFont", 8)).grid(row=8, column=0, sticky=tk.W, padx=(10, 0))
        self.password_var = tk.StringVar()
        ttk.Entry(form_frame, textvariable=self.password_var, show="*", width=38).grid(row=8, column=1, sticky=tk.EW, pady=2)
        
        ttk.Label(form_frame, text="(Nécessaire pour certains calendriers universitaires)", font=("TkDefaultFont", 7, "italic")).grid(
            row=9, column=1, sticky=tk.W, pady=(0, 10)
        )
        
        ttk.Separator(form_frame, orient=tk.HORIZONTAL).grid(row=10, column=0, columnspan=2, sticky=tk.EW, pady=10)
        
        self.import_past_var = tk.BooleanVar(value=False)
        ttk.Checkbutton(
            form_frame,
            text="Importer les événements passés",
            variable=self.import_past_var
        ).grid(row=11, column=0, columnspan=2, sticky=tk.W, pady=5)
        
        self.auto_sync_var = tk.BooleanVar(value=False)
        ttk.Checkbutton(
            form_frame,
            text="Activer la synchronisation automatique",
            variable=self.auto_sync_var
        ).grid(row=12, column=0, columnspan=2, sticky=tk.W, pady=5)
        
        form_frame.columnconfigure(1, weight=1)
        
        # Buttons
        btn_frame = ttk.Frame(self, padding=10)
        btn_frame.pack(fill=tk.X, side=tk.BOTTOM)
        
        ttk.Button(btn_frame, text="Annuler", command=self.destroy).pack(side=tk.RIGHT, padx=2)
        ttk.Button(btn_frame, text="Créer", command=self._on_create).pack(side=tk.RIGHT, padx=2)
    
    def _browse_file(self) -> None:
        """Browse for ICS file."""
        file_path = filedialog.askopenfilename(
            title="Sélectionner fichier ICS",
            filetypes=[("iCalendar files", "*.ics"), ("All files", "*.*")]
        )
        if file_path:
            self.source_var.set(file_path)
    
    def _show_url_help(self) -> None:
        """Show help dialog for obtaining calendar URLs."""
        help_text = """
📅 Comment obtenir l'URL de votre calendrier:

═══════════════════════════════════════

📗 Google Calendar:
1. Ouvrez Google Calendar (calendar.google.com)
2. Cliquez sur ⚙️ puis "Paramètres"
3. Dans la colonne de gauche, sélectionnez votre calendrier
4. Faites défiler jusqu'à "Intégrer le calendrier"
5. Copiez l'URL "Adresse secrète au format iCal"
   Format: https://calendar.google.com/calendar/ical/...

📘 Outlook / Office 365:
1. Ouvrez Outlook Web (outlook.office.com)
2. Calendrier > Paramètres > Calendriers partagés
3. Publiez votre calendrier
4. Copiez le lien ICS généré

📙 Apple iCloud:
1. Ouvrez iCloud.com > Calendrier
2. Cliquez sur l'icône de partage à côté du calendrier
3. Activez "Calendrier public"
4. Copiez l'URL webcal:// ou webcals://
   (sera auto-converti en http:// ou https://)

🏫 Calendriers universitaires (Zimbra, etc.):
Les URLs webcals:// sont automatiquement supportées.
Exemple: webcals://mail.univ.fr/home/user@univ.fr/Calendar

💡 Fichier local:
Utilisez le bouton 📁 pour sélectionner un fichier .ics
sur votre ordinateur
"""
        messagebox.showinfo("Aide - Obtenir URL Calendrier", help_text)
    
    def _on_create(self) -> None:
        """Create subscription."""
        name = self.name_var.get().strip()
        source = self.source_var.get().strip()
        project_name = self.project_var.get()
        
        if not name:
            messagebox.showwarning("Attention", "Le nom est requis")
            return
        
        if not source:
            messagebox.showwarning("Attention", "La source est requise")
            return
        
        if not project_name:
            messagebox.showwarning("Attention", "Sélectionnez un projet")
            return
        
        project_id = self.projects_by_name[project_name]
        create_new_project = (project_id is None)
        
        # Get optional auth credentials
        username = self.username_var.get().strip() or None
        password = self.password_var.get().strip() or None
        
        try:
            sub = self.sync_manager.create_subscription(
                name=name,
                source_url=source,
                project_id=project_id,
                import_past_events=self.import_past_var.get(),
                auto_sync=self.auto_sync_var.get(),
                create_project_per_calendar=create_new_project,
                username=username,
                password=password
            )
            
            # Optionally sync immediately
            result = messagebox.askyesno(
                "Abonnement créé",
                f"Abonnement '{name}' créé avec succès!\n\nSynchroniser maintenant?"
            )
            
            if result:
                stats = self.sync_manager.sync_subscription(sub.id)
                
                # Get project name for display
                if sub.project_id:
                    projects = self.service.list_projects(status="all")
                    project = next((p for p in projects if p.id == sub.project_id), None)
                    project_name = project.name if project else "Projet créé"
                else:
                    project_name = "Aucun projet"
                
                messagebox.showinfo(
                    "Synchronisation initiale",
                    f"✓ {stats['added']} événement(s) importé(s)\n"
                    f"Projet: {project_name}"
                )
            
            self.destroy()
        except Exception as e:
            messagebox.showerror("Erreur", f"Impossible de créer l'abonnement:\n{e}")


class EditSubscriptionDialog(tk.Toplevel):
    """Dialog for editing a calendar subscription."""
    
    def __init__(self, parent: tk.Widget, service: PigeService, sync_manager: CalendarSyncManager, subscription) -> None:
        super().__init__(parent)
        self.service = service
        self.sync_manager = sync_manager
        self.subscription = subscription
        
        self.title(f"Éditer: {subscription.name}")
        self.geometry("500x350")
        self.transient(parent)
        
        self._setup_ui()
        
        # Center on parent
        self.update_idletasks()
        x = parent.winfo_x() + (parent.winfo_width() - self.winfo_width()) // 2
        y = parent.winfo_y() + (parent.winfo_height() - self.winfo_height()) // 2
        self.geometry(f"+{x}+{y}")
    
    def _setup_ui(self) -> None:
        """Setup UI."""
        form_frame = ttk.Frame(self, padding=20)
        form_frame.pack(fill=tk.BOTH, expand=True)
        
        # Name
        ttk.Label(form_frame, text="Nom:").grid(row=0, column=0, sticky=tk.W, pady=5)
        self.name_var = tk.StringVar(value=self.subscription.name)
        ttk.Entry(form_frame, textvariable=self.name_var, width=40).grid(row=0, column=1, sticky=tk.EW, pady=5)
        
        # Source (read-only)
        ttk.Label(form_frame, text="Source:").grid(row=1, column=0, sticky=tk.W, pady=5)
        ttk.Label(form_frame, text=self.subscription.source_url[:50], foreground="#666").grid(
            row=1, column=1, sticky=tk.W, pady=5
        )
        
        # Active
        self.active_var = tk.BooleanVar(value=self.subscription.active)
        ttk.Checkbutton(
            form_frame,
            text="Abonnement actif",
            variable=self.active_var
        ).grid(row=2, column=0, columnspan=2, sticky=tk.W, pady=10)
        
        # Auto-sync
        self.auto_sync_var = tk.BooleanVar(value=self.subscription.auto_sync)
        ttk.Checkbutton(
            form_frame,
            text="Synchronisation automatique",
            variable=self.auto_sync_var
        ).grid(row=3, column=0, columnspan=2, sticky=tk.W, pady=5)
        
        # Sync interval
        ttk.Label(form_frame, text="Intervalle (minutes):").grid(row=4, column=0, sticky=tk.W, pady=5)
        self.interval_var = tk.IntVar(value=self.subscription.sync_interval_minutes)
        ttk.Spinbox(
            form_frame,
            from_=5,
            to=1440,
            textvariable=self.interval_var,
            width=10
        ).grid(row=4, column=1, sticky=tk.W, pady=5)
        
        # Import past events
        self.import_past_var = tk.BooleanVar(value=self.subscription.import_past_events)
        ttk.Checkbutton(
            form_frame,
            text="Importer les événements passés",
            variable=self.import_past_var
        ).grid(row=5, column=0, columnspan=2, sticky=tk.W, pady=5)
        
        form_frame.columnconfigure(1, weight=1)
        
        # Buttons
        btn_frame = ttk.Frame(self, padding=10)
        btn_frame.pack(fill=tk.X, side=tk.BOTTOM)
        
        ttk.Button(btn_frame, text="Annuler", command=self.destroy).pack(side=tk.RIGHT, padx=2)
        ttk.Button(btn_frame, text="Enregistrer", command=self._on_save).pack(side=tk.RIGHT, padx=2)
    
    def _on_save(self) -> None:
        """Save changes."""
        name = self.name_var.get().strip()
        if not name:
            messagebox.showwarning("Attention", "Le nom est requis")
            return
        
        try:
            self.sync_manager.update_subscription(
                self.subscription.id,
                {
                    "name": name,
                    "active": self.active_var.get(),
                    "auto_sync": self.auto_sync_var.get(),
                    "sync_interval_minutes": self.interval_var.get(),
                    "import_past_events": self.import_past_var.get()
                }
            )
            messagebox.showinfo("Succès", "Abonnement mis à jour")
            self.destroy()
        except Exception as e:
            messagebox.showerror("Erreur", f"Impossible de sauvegarder:\n{e}")
