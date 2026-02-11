"""Constants and display mapping for the PIGE GUI."""

from __future__ import annotations

# Types stockés (métadonnées)
VALID_ENTRY_TYPES = ("note", "meeting", "decision", "log")

# Libellés affichés dans l'UI (majuscule + "Activity" pour log)
TYPE_INTERNAL_TO_DISPLAY = {
    "note": "Note",
    "meeting": "Meeting",
    "decision": "Decision",
    "log": "Activity",
}

# Conversion UI -> stockage
TYPE_DISPLAY_TO_INTERNAL = {v: k for k, v in TYPE_INTERNAL_TO_DISPLAY.items()}

# Valeurs de la combobox (affichage)
DISPLAY_ENTRY_TYPES = tuple(TYPE_INTERNAL_TO_DISPLAY[t] for t in VALID_ENTRY_TYPES)

AVAILABLE_ENTRY_COLUMNS = [
    "date",
    "time",
    "type",
    "context",
    "done",
    "title",
    "people",
    "tags",
]
AVAILABLE_PROJECT_COLUMNS = ["name", "people", "tasks_open", "status"]
DEFAULT_PROJECT_DISPLAYCOLUMNS = ["name", "people", "tasks_open", "status"]

DEFAULT_ENTRY_DISPLAYCOLUMNS = [
    "date",
    "time",
    "type",
    "context",
    "done",
    "title",
    "people",
]
ENTRY_COLUMN_LABELS = {
    "date": "Date",
    "time": "Time",
    "type": "Type",
    "context": "Context",
    "done": "Done",
    "title": "Title",
    "people": "People",
    "tags": "Tags",
}

UPCOMING_RANGE_LABELS = ("Next 7 days", "Next 14 days", "Next 30 days", "All")
UPCOMING_RANGE_DAYS = {
    "Next 7 days": 7,
    "Next 14 days": 14,
    "Next 30 days": 30,
    "All": None,
}

ENTRY_BODY_TEMPLATES: dict[str, str] = {
    "note": (
        "# {title}\n\n"
        "**Date:** {date}\n"
        "**Project:** {project}\n"
        "**Person/Group:** {person} {group}\n"
        "**Tags:** {tags}\n\n"
        "## Notes\n"
        "- \n\n"
        "## Next steps\n"
        "- \n"
    ),
    "meeting": (
        "# {title}\n\n"
        "**Date:** {date}\n"
        "**Project:** {project}\n"
        "**People:** {person} {group}\n"
        "**Time:** {start} - {end}\n"
        "**Tags:** {tags}\n\n"
        "## Agenda\n"
        "- \n\n"
        "## Notes\n"
        "- \n\n"
        "## Decisions\n"
        "- \n\n"
        "## Actions\n"
        "- [ ] \n"
    ),
    "decision": (
        "# {title}\n\n"
        "**Date:** {date}\n"
        "**Project:** {project}\n"
        "**Person/Group:** {person} {group}\n"
        "**Tags:** {tags}\n\n"
        "## Context\n"
        "- \n\n"
        "## Decision\n"
        "- \n\n"
        "## Rationale\n"
        "- \n\n"
        "## Consequences\n"
        "- \n\n"
        "## Follow-up\n"
        "- \n\n"
        "## Status\n"
        "- Applied/Done: \n"
    ),
    "log": (
        "# {title}\n\n"
        "**Date:** {date}\n"
        "**Project:** {project}\n"
        "**Person/Group:** {person} {group}\n"
        "**Tags:** {tags}\n\n"
        "## What was done\n"
        "- \n\n"
        "## Outcomes\n"
        "- \n\n"
        "## Blockers\n"
        "- \n\n"
        "## Next steps\n"
        "- \n"
    ),
}

AUTOSAVE_DELAY_MS = 1200
TOOLBAR_LAYOUT_DEBOUNCE_MS = 100
TOOLBAR_COMPACT_WIDTH = 900
TOOLBAR_EXPAND_WIDTH = 980

UI_DATE_FORMAT = "%d/%m/%Y"
