# Plan d'Action - Phase 4.0: Dashboard Vue d'Ensemble

**Objectif**: Créer un dashboard actionnable affichant l'état global du travail

**Durée estimée**: 2-3 jours  
**Priorité**: TRÈS HAUTE (besoin utilisateur #1)  
**Prérequis**: Phase 3.9 complétée ✅

---

## Vue d'Ensemble

Le Dashboard est un onglet central qui répond à la question:  
**"Qu'est-ce qui nécessite mon attention maintenant?"**

### Sections du Dashboard

1. **📋 En Cours** - Ce qui est actif maintenant
2. **⏸️ En Attente** - Ce qui est bloqué/pending
3. **📅 À Venir** - Deadlines et meetings prochains (7 jours)
4. **🎯 Focus Suggéré** - Intelligence sur où concentrer efforts

---

## 📋 Tâches Détaillées

### 4.0.1 - Créer DashboardPanel (1 jour)

#### Tâche 1.1: Structure de base
**Durée**: 2-3h  
**Fichier**: `pige/interfaces/gui/panels/dashboard_panel.py`

**Fonctionnalités**:
- Frame principal avec sections scrollables
- Section "En Cours" avec TreeView
- Section "En Attente" avec TreeView  
- Section "À Venir" avec TreeView
- Section "Focus Suggéré" avec labels/stats
- Bouton Refresh + filtre période (7/14/30 jours)

**Code à créer**:
```python
class DashboardPanel(ttk.Frame):
    def __init__(self, parent, service, initial_days=7):
        # Toolbar avec Refresh + dropdown période
        # Notebook ou LabelFrames pour sections
        # TreeViews pour listes
        # Labels pour suggestions
        pass
    
    def refresh(self):
        # Charger données
        # Afficher en cours
        # Afficher en attente
        # Afficher à venir
        # Calculer focus suggéré
        pass
```

#### Tâche 1.2: Section "En Cours"
**Durée**: 1-2h

**Données à afficher**:
- Entrées avec status `in_progress` (via metadata ou récentes non closes)
- Tâches `in_progress`
- Timer actif (si présent)
- Dernières entrées des 7 derniers jours

**Colonnes TreeView**:
- Type (Entry/Task)
- Titre
- Projet
- Âge (jours depuis création)
- Action (bouton "Open")

#### Tâche 1.3: Section "En Attente"
**Durée**: 1h

**Données à afficher**:
- Tâches avec status `pending` ou `blocked`
- Entrées avec tag "waiting" ou "blocked"
- Threads non résolus (entrées avec followup tasks ouverts)

**Colonnes TreeView**:
- Type
- Titre
- Projet
- Raison (pending reason si disponible)
- Depuis (jours)

#### Tâche 1.4: Section "À Venir"
**Durée**: 2-3h

**Données à afficher**:
- Meetings dans les N prochains jours
- Tâches avec deadline proche
- Décisions en attente de validation
- Entrées récurrentes à créer

**Colonnes TreeView**:
- Date
- Type
- Titre
- Projet
- Délai (dans X jours)

**Tri**: Par date croissante

#### Tâche 1.5: Section "Focus Suggéré"
**Durée**: 1-2h

**Métriques à calculer**:
- Projet avec le plus de tâches ouvertes
- Projet le plus "ancien" sans activité
- Entrée in_progress la plus ancienne
- Tâches urgentes sans deadline

**Affichage**:
- Cards/Labels avec métriques clés
- Recommendations textuelles
- Liens cliquables vers projets/entrées

---

### 4.0.2 - Logique Métier Dashboard (1 jour)

#### Tâche 2.1: Méthodes dans PigeService
**Durée**: 2-3h  
**Fichier**: `pige/core/service.py`

**Méthodes à ajouter**:
```python
def get_in_progress_items(self) -> dict[str, list]:
    """Retourne entrées et tâches en cours."""
    return {
        "entries": [...],  # Entries récentes ou in_progress
        "tasks": [...]     # Tasks in_progress
    }

def get_pending_items(self) -> dict[str, list]:
    """Retourne items en attente."""
    return {
        "tasks": [...],    # Tasks pending/blocked
        "entries": [...]   # Entries avec tag waiting
    }

def get_upcoming_items(self, days: int = 7) -> list:
    """Retourne items à venir dans N jours."""
    return [...]  # Meetings, deadlines, etc.

def get_focus_suggestions(self) -> dict:
    """Calcule suggestions de focus."""
    return {
        "busiest_project": ...,
        "oldest_in_progress": ...,
        "stale_projects": [...],
        "urgent_tasks": [...]
    }
```

#### Tâche 2.2: Filtres et tri
**Durée**: 1h

**Fonctionnalités**:
- Filtre par période (7/14/30 jours)
- Filtre par projet (optionnel)
- Tri par urgence/date/priorité
- Cache pour performance

#### Tâche 2.3: Détection "in_progress"
**Durée**: 1-2h

**Problème**: Pas de status explicite pour entrées

**Solutions**:
1. **Tag-based**: Entrées avec tag "in-progress"
2. **Time-based**: Entrées modifiées récemment (< 7 jours)
3. **Followup-based**: Entrées avec tasks non complétés
4. **Hybrid**: Combinaison des 3

**Implémentation recommandée**: Hybrid avec préférence

---

### 4.0.3 - Intégration Main Window (2h)

#### Tâche 3.1: Ajouter onglet Dashboard
**Fichier**: `pige/interfaces/gui/main_window.py`

**Modifications**:
- Importer `DashboardPanel`
- Créer instance avec service
- Ajouter comme **premier onglet** (vue par défaut)
- Lier événements refresh

#### Tâche 3.2: Menu & shortcuts
**Ajouts**:
- Menu "View → Dashboard" (Ctrl+D)
- Menu "View → Refresh Dashboard" (F5)
- Auto-refresh au focus (optionnel)

---

### 4.0.4 - Features Avancées (optionnel, 1 jour)

#### Tâche 4.1: Actions rapides
**Durée**: 2h

**Fonctionnalités**:
- Double-click pour ouvrir entrée/tâche
- Right-click context menu:
  - "Mark as Done"
  - "Move to Pending"
  - "Open Project"
  - "Add Note"

#### Tâche 4.2: Indicateurs visuels
**Durée**: 1h

**Améliorations**:
- Couleurs par urgence (rouge/orange/vert)
- Icons par type (📝📅✅⏸️)
- Progress bars pour projets
- Badges pour compteurs

#### Tâche 4.3: Stats en temps réel
**Durée**: 2h

**Widgets supplémentaires**:
- Compteur total items en cours
- Compteur pending
- Compteur à venir aujourd'hui
- Graphique simple (optionnel)

---

## 📊 Livrables Phase 4.0

### Code
- [ ] `pige/interfaces/gui/panels/dashboard_panel.py` (400+ lignes)
- [ ] Méthodes dans `pige/core/service.py` (4 nouvelles)
- [ ] Intégration `main_window.py`
- [ ] Tests unitaires (10+ tests)

### Fonctionnalités Utilisateur
- [ ] Onglet Dashboard visible au lancement
- [ ] Section "En Cours" avec données réelles
- [ ] Section "En Attente" avec tâches pending
- [ ] Section "À Venir" avec timeline 7 jours
- [ ] Section "Focus Suggéré" avec recommendations
- [ ] Refresh manuel + auto (optionnel)
- [ ] Actions rapides (double-click, context menu)

### Documentation
- [ ] CHANGELOG.md - Entrée Phase 4.0
- [ ] ROADMAP.md - Phase 4.0 marquée complétée
- [ ] README.md - Section Dashboard

---

## ⚡ Ordre d'Exécution Recommandé

### Jour 1: Structure & En Cours
1. Créer `DashboardPanel` basique avec sections
2. Implémenter `get_in_progress_items()` dans service
3. Afficher section "En Cours" avec données réelles
4. Intégrer dans main_window comme 1er onglet
5. Tests manuels

### Jour 2: En Attente & À Venir
6. Implémenter `get_pending_items()` et `get_upcoming_items()`
7. Afficher sections "En Attente" et "À Venir"
8. Ajouter filtres période (7/14/30 jours)
9. Tests manuels

### Jour 3: Focus & Polish
10. Implémenter `get_focus_suggestions()`
11. Afficher section "Focus Suggéré"
12. Actions rapides (double-click, context menu)
13. Indicateurs visuels (couleurs, icons)
14. Tests unitaires
15. Documentation

---

## ✅ Critères de Succès

### Performance
- [ ] Dashboard refresh < 100ms
- [ ] Pas de lag lors switch onglet
- [ ] Cache efficace pour données

### Fonctionnalités
- [ ] Affiche tous items en cours (entries + tasks)
- [ ] Affiche tous items en attente
- [ ] Timeline 7 jours correcte
- [ ] Suggestions de focus pertinentes

### UX
- [ ] Interface claire et lisible
- [ ] Navigation rapide (double-click)
- [ ] Refresh manuel fonctionne
- [ ] Aucune régression tests (177+)

### Impact Utilisateur
- [ ] Répond à la question: "Que dois-je faire maintenant?"
- [ ] Visibilité immédiate sur état global
- [ ] Gain de temps vs navigation manuelle

---

## 🔧 Stack Technique

### Modules Utilisés
- `pige.core.service.PigeService` - Logique métier
- `pige.interfaces.gui.panels.*` - Architecture modulaire
- `tkinter.ttk.Treeview` - Affichage listes
- `tkinter.ttk.LabelFrame` - Sections visuelles

### Nouveaux Modules
- `pige.interfaces.gui.panels.dashboard_panel` - Panel principal
- Méthodes service pour requêtes dashboard

### Tests
- `pytest` - Framework test
- Tests unitaires pour logique service
- Tests manuels GUI

---

## 📈 Impact Attendu

### Avant Dashboard
- ❌ Navigation manuelle entre onglets
- ❌ Pas de vue d'ensemble
- ❌ Difficile de prioriser
- ❌ Risque d'oubli items en attente

### Après Dashboard
- ✅ Vue centralisée au lancement
- ✅ État global en un coup d'œil
- ✅ Priorisation guidée (focus suggéré)
- ✅ Rien ne passe entre les mailles

**Gain utilisateur**: Dashboard = **Hub de pilotage quotidien**! 🎯

---

## 🚀 Prochaines Étapes Après Dashboard

Une fois Dashboard complété:

1. **Phase 4.7 - Calendrier Import** (intégration .ics)
2. **Phase 4.1 - Attachments** (drag & drop)
3. **Phase 4.3 - Sync Git Auto** (backup)

---

**Date création**: 2026-02-18  
**Phase**: 4.0 Dashboard Vue d'Ensemble  
**Priorité**: TRÈS HAUTE  
**Statut**: PLANIFIÉE - Prêt à démarrer!
