# PIGE (Project Integrated Journaling Engine)

PIGE is a local, cross-platform journaling engine for projects: notes, meetings,
decisions, time tracking, and long-form narrative writing in Markdown. Storage
is open and local (JSON/JSONL + Markdown).

## Philosophy

- Core domain logic lives in `pige/core`.
- Interfaces live in `pige/interfaces`.
- The CLI delegates to the service layer and keeps business logic out of the UI.

## Quick start

```sh
python -m pige init
python -m pige project add "My Project" --desc "Context" --tags "alpha,client"
python -m pige entry add <PROJECT_ID> --type note --title "Kickoff" --body "Notes" --open
python -m pige time start <PROJECT_ID> --note "Focus block"
python -m pige time stop
python -m pige export project <PROJECT_ID> --mode raw
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
  exports/
```

## Narrative export

Narrative export produces a structured Markdown report per project (optional date
range): front-matter, résumé (counts, type breakdown, total time), objectifs
placeholder, full decisions section, chronologie with full entry content, time
tables per day, and annexes listing source files. Use `--mode narrative` with
`export project` in the CLI, or "Project (Narrative)..." in the GUI Export menu.

## GUI

Launch the Tkinter GUI:

```sh
python -m pige gui
```

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
- Project and entry metadata are editable in the bottom panel (date, tags,
  person/group, meeting times, decision done).
- Keyboard shortcuts: Save (Ctrl+S / ⌘S), Quit (Ctrl+Q / ⌘Q), Focus (F9),
  zoom editor (Ctrl/Cmd + Plus/Minus/0).
- Preferences are stored in `data/.pige_prefs.json` (search, show archived,
  create-activity toggle, project columns order).

## Tasks

Tasks are stored per project in `data/tasks.json`. Use the GUI Tasks panel
below the editor to add, edit, and complete tasks (optionally linked to an
entry). Tasks are included in raw exports under a "## Tasks" section.

## Maintenance & sharing

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
