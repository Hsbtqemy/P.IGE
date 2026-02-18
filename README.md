# PIGE (Project Integrated Journaling Engine)

PIGE is a local, cross-platform journaling engine for projects: notes, meetings,
decisions, time tracking, full-text search, and long-form narrative writing in Markdown.  
Storage is open and local (JSON/JSONL + Markdown).

## Key Features

- 📝 **Project Journaling**: Notes, meetings, decisions with metadata
- 🔍 **Full-Text Search**: SQLite FTS5 for instant search (<50ms)
- 📊 **Project Hierarchy**: Nested projects with unlimited depth
- ⏱️ **Time Tracking**: Built-in timer with activity logs
- 📄 **Pagination**: Handle 10K+ items smoothly
- 🎨 **Modern GUI**: Tkinter interface with incremental updates
- 💾 **Local Storage**: Open formats (JSON/JSONL + Markdown)
- 🔄 **Event Sourcing**: Full history for entries metadata

## Philosophy

- Core domain logic lives in `pige/core`.
- Interfaces live in `pige/interfaces`.
- The CLI delegates to the service layer and keeps business logic out of the UI.

## Quick start

```sh
# Initialize data directory
python -m pige init

# Create a project
python -m pige project add "My Project" --desc "Context" --tags "alpha,client"

# Create a sub-project (hierarchy)
python -m pige project add "Sub-Project" --desc "Child project" --parent <PARENT_PROJECT_ID>

# List projects
python -m pige project list

# Add entries with full parameters
python -m pige entry add <PROJECT_ID> --type note --title "Kickoff" --body "Notes" --open
python -m pige entry add <PROJECT_ID> --type meeting --title "Sprint Planning" \
  --date 2024-01-15 --person "John Doe" --group "Dev Team" \
  --meeting-start 10:00 --meeting-end 11:30 --tags "sprint,planning"
python -m pige entry add <PROJECT_ID> --type decision --title "Use PostgreSQL" --decision-done

# List, update, move, and delete entries
python -m pige entry list <PROJECT_ID> --type meeting --limit 10
python -m pige entry update <ENTRY_ID> --title "New Title" --tags "updated"
python -m pige entry move <ENTRY_ID> <DEST_PROJECT_ID> --keep-tags --keep-people
python -m pige entry delete <ENTRY_ID> --yes

# Time tracking
python -m pige time start <PROJECT_ID> --note "Focus block"
python -m pige time stop
python -m pige time today

# Export project data
python -m pige export project <PROJECT_ID> --mode raw
python -m pige export project <PROJECT_ID> --mode narrative --from 2024-01-01 --to 2024-12-31
python -m pige export meeting --entry <ENTRY_ID>
python -m pige export weekly --from 2024-01-01 --to 2024-01-07
python -m pige export hierarchy  # Export full project tree with indentation

# Data migration and maintenance
python -m pige migrate  # Migrate to latest schema (adds hierarchy fields)
python -m pige compact  # Compact entries log (remove history, keep snapshot)
python -m pige rebuild-index  # Rebuild full-text search index (FTS5)
```

## Project Hierarchy

PIGE supports hierarchical project organization (max 10 levels):

```sh
# Create parent project
python -m pige project add "Client A" --desc "Main client folder"

# Create child projects
python -m pige project add "Project 1" --parent <CLIENT_A_ID>
python -m pige project add "Project 2" --parent <CLIENT_A_ID>

# Export hierarchy as indented Markdown
python -m pige export hierarchy --include-archived
```

**Features:**
- Maximum 10 levels of nesting (0-9)
- Automatic cycle detection when moving projects
- Custom display order within same level
- Migration command for existing projects: `python -m pige migrate`
```

## Data layout

```
data/
  projects.json
  entries.jsonl
  entries/<entry_id>.md
  tasks.json
  timers.json
  timelogs.jsonl
  .pige_index.db         # FTS5 full-text search index
  .pige_prefs.json       # GUI preferences (pagination, etc.)
  exports/
```

## Full-Text Search

PIGE uses SQLite FTS5 for instant full-text search:

```sh
# CLI search (coming soon)
python -m pige search "meeting notes" --type entries

# GUI search (available now!)
python -m pige gui
# Then: Menu "Search > Find..." or press Ctrl+F
# Search across: All / Entries / Projects / Tasks
# Results show: Type, Title, Context with timing (<50ms)
```

**Features:**
- Automatic indexing on create/update/delete
- Search syntax: plain text or FTS5 queries
- Performance: <50ms for 10K+ entries
- Manual rebuild: `python -m pige rebuild-index`

## Narrative export

Narrative export produces a structured Markdown report per project (optional date
range): front-matter, résumé (counts, type breakdown, total time), objectifs
placeholder, full decisions section, chronologie with full entry content, time
tables per day, and annexes listing source files. Use `--mode narrative` with
`export project` in the CLI, or "Project (Narrative)..." in the GUI Export menu.

## GUI

Launch the Tkinter GUI (modern, modular interface):

```sh
python -m pige gui
```

**Features:**
- 🔍 **Search Tab**: Full-text search with instant results (Ctrl+F)
- 📂 **Projects Tab**: Hierarchical view with pagination (50/100/200/500/1K/All)
- ⚡ **Smooth UX**: Incremental tree updates (no flickering)
- 💾 **Preferences**: Pagination settings auto-saved
- 📋 **Context Menus**: Right-click for quick actions
- ⌨️ **Keyboard Shortcuts**: Full navigation (F1 for shortcuts list)

**Keyboard Shortcuts:**
- `Ctrl+F`: Open search
- `Ctrl+N`: New project
- `Ctrl+E`: New entry
- `F1`: Show keyboard shortcuts
- `Ctrl+Q`: Quit

Set a custom data directory with `PIGE_DATA_DIR`:
Default is `./data` when `PIGE_DATA_DIR` is not set.

Windows 11 (PowerShell):

```powershell
$env:PIGE_DATA_DIR = "C:\\pige\\data"
python -m pige gui
```

macOS (zsh):

```sh
export PIGE_DATA_DIR="/Users/me/pige-data"
python -m pige gui
```

GUI layout highlights:
- Three-pane workflow (Projects, Entries, Editor) with a bottom Details panel
  (Project, Entry, Stats) and a bottom action bar (Timer + Save).
- **Project Hierarchy**: TreeView supports parent-child relationships with expand/collapse.
  - Click ▸/▾ to expand/collapse sub-projects
  - Indentation shows hierarchy levels (max 10 levels)
  - Expand/collapse state persisted in preferences
  - Create sub-projects via CLI: `python -m pige project add "Child" --parent <PARENT_ID>`
- **Tag Autocomplete**: Type in Tags fields to get dynamic suggestions from all existing tags.
  - Press ↓ arrow or start typing to see suggestions
  - Navigate with ↑/↓ arrows, select with Enter, dismiss with Esc
  - Smart filtering: excludes already-entered tags, case-insensitive search
  - Supports comma-separated tags with contextual completion
- **Context Menus**: Right-click on items for quick actions:
  - **Projects**: New Entry, Edit, Copy ID, Delete
  - **Entries**: Open, Edit, Delete, Export Meeting, Mark Status, Create Tasks, Copy ID, Move to Project
- Project and entry metadata are editable in the bottom panel (date, tags,
  person/group, meeting times, decision done).
- **Advanced Search**: Use field-specific filters in the global search box:
  - `tag:value` - Filter by tag (e.g., `tag:alpha tag:urgent`)
  - `person:value` - Filter by person (e.g., `person:John` or `person:"Jane Doe"`)
  - `group:value` - Filter by group
  - `type:value` - Filter by entry type (note, meeting, decision, log)
  - `date:YYYY-MM-DD` - Filter by exact date
  - `date:>=YYYY-MM-DD` - Filter entries on or after date
  - `date:<=YYYY-MM-DD` - Filter entries on or before date
  - `status:value` - Filter by context status (created, actual, treated)
  - `title:value` - Filter by title substring
  - Example: `tag:sprint person:John type:meeting date:>=2024-01-01`
- Keyboard shortcuts: 
  - New Project (Ctrl+N / ⌘N)
  - New Entry (Ctrl+E / ⌘E)
  - Save (Ctrl+S / ⌘S)
  - Quit (Ctrl+Q / ⌘Q)
  - Focus Mode (F9)
  - Zoom editor (Ctrl/Cmd + Plus/Minus/0)
  - Toggle checkbox (Ctrl+Shift+X / ⌘Shift+X)
  - Show keyboard shortcuts (F1)
  - Delete selected item (Delete/Backspace)
- Preferences are stored in `data/.pige_prefs.json` (search, show archived,
  create-activity toggle, project columns order).

## Tasks

Tasks are stored per project in `data/tasks.json`. Use the GUI Tasks panel
below the editor to add, edit, and complete tasks (optionally linked to an
entry). Tasks are included in raw exports under a "## Tasks" section.

## Maintenance & sharing

**Full-Text Search** — PIGE includes SQLite FTS5 for fast full-text search across entries, projects, and tasks. Build the search index manually:

```sh
python -m pige rebuild-index
# Search index rebuilt successfully:
#   Entries: 150
#   Projects: 12
#   Tasks: 85
```

Recommended after bulk imports or periodically for large databases (1000+ entries). Search is performed on titles, summaries, tags, and metadata.

**Compaction** — The entries log (`entries.jsonl`) is append-only (events for create/update/delete). To reduce file size and load time, you can compact it to a snapshot (one line per current entry; history is removed). Use the GUI: Tools → Compact entries log… (with confirmation), or the CLI:

```sh
python -m pige compact
```

**Export redacted** — For sharing reports without exposing note content, use redacted exports: entry bodies are replaced with `[Content redacted]`; metadata (titles, dates, people, tags) is kept. In the GUI: choose "Project (Raw, redacted)" or check "Redact entry content" in the Narrative or Meeting minutes export dialogs. In the CLI:

```sh
python -m pige export project <PROJECT_ID> --mode raw --redact
python -m pige export project <PROJECT_ID> --mode narrative --redact
python -m pige export meeting --entry <ENTRY_ID> --redact
```

**Backup** — File → Backup… (GUI) or create a zip of the data folder. A backup is created automatically before Restore.

## Tests

```sh
python -m unittest discover tests/
```

You can also run tests with pytest:

```sh
pytest tests/ -v
```
