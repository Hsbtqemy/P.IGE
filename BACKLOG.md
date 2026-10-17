# PIGE – Backlog et priorités

**Dernière mise à jour** : 17 octobre 2026  
**Référence** : `ROADMAP.md` pour le détail des phases et la timeline.

---

## 1. TODOs restant dans le code

| Fichier | Description | Action |
|---------|-------------|--------|
| `pige/interfaces/gui/panels/projects_panel.py` | Double-clic sur un projet sans effet | Ouvrir les détails du projet ou déclencher un callback |
| `pige/core/models.py` | Mot de passe HTTP Basic des abonnements calendrier stocké en clair | Chiffrer ou déplacer hors du fichier de données (étape 2) |

Les dialogues `new_project`, `new_entry`, `new_task`, `edit_entry` et `edit_task` existent dans `pige/interfaces/gui/dialogs/`. Le filtre waiting/blocked de `get_pending_items()` est fait.

---

## 2. GUI Tkinter (maintenance seulement)

L'interface Tkinter sera retirée à l'étape 9 ; on n'y investit plus que le nécessaire.

- [ ] Tests unitaires pour panels/dialogs.
- [ ] Supprimer `gui_legacy.py` (encore importable, plus lancé par défaut).

---

## 3. ROADMAP – Éléments pending (résumé)

Le détail complet est dans **`ROADMAP.md`**. Ci-dessous : résumé des items non cochés par phase.

### Phase 1 (optionnel)
- [ ] **1.7** Validation des dates dans la GUI (1 jour).

### Phase 2 (reportés)
- [ ] Liens entre projets (interface, panneau détails, validation).
- [ ] Filtres combinés et vues personnalisées (sauvegarde, dropdown, dialogue).

### Phase 3 (reportés / optionnels)
- [ ] Drag & drop pour réorganisation (Phase 4+).
- [ ] Intégration recherche dans GUI legacy (déjà fait dans modular).
- [ ] Tests intégration GUI.
- [ ] **3.5** Architecture MVC/MVP (Presenters, vues, tests unitaires).

### Phase 4+
- [ ] Pièces jointes, versioning, sync Git, analytics, templates, thèmes, etc.  
  → Voir `ROADMAP.md` sections Phase 4, 5, 6.

---

## 4. Plan en cours (depuis octobre 2026)

1. **Étape 2 – « socle sûr » (en cours)**
   - Chemins de données et de logs via `platformdirs`.
   - Écritures sûres avec verrou.
   - Indexation plein texte du corps des entrées (et indexation automatique des projets et tâches).
   - Corrections de sécurité : synchronisation calendrier et logs.
   - Durcissement de la CI.
2. **Étape 3 – « service assaini »** : supprimer les ~49 accès directs à `service.storage` depuis les interfaces (CLI, GUI) ; découper `service.py` (~2 450 lignes).
3. **Étape 4** : SQLite comme source de vérité.
4. **Étape 5** : sécurité du serveur hébergé (passkeys, sessions…).
5. **Étape 6** : interface web (`web/`).
6. **Étape 7** : extension Thunderbird (`thunderbird/`).
7. **Étape 8** : agenda et contacts via CalDAV/CardDAV.
8. **Étape 9** : retrait de l'interface Tkinter.

---

## 5. Références

- **ROADMAP.md** – Phases 1–6, timeline, critères de succès.
- **pige/interfaces/gui/README.md** – Architecture GUI modulaire.
- **deploy/README.md** – Déploiement du serveur et de l'interface web.
- **docs/archives/** – Notes historiques (février–mars 2026).
- **CHANGELOG.md** – Historique des livrés.
