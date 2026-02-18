from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional


@dataclass
class Project:
    id: str
    name: str
    description: Optional[str] = None
    status: str = "active"
    tags: list[str] = field(default_factory=list)
    created_at: str = ""
    person: Optional[str] = None
    group: Optional[str] = None
    links: list[str] = field(default_factory=list)
    parent_id: Optional[str] = None  # Parent project ID for hierarchy
    display_order: int = 0  # Custom display order within same level


@dataclass
class EntryMeta:
    id: str
    ts: str
    project_id: str
    type: str
    title: str
    tags: list[str]
    content_path: str
    summary: Optional[str] = None
    entry_date: Optional[str] = None
    person: Optional[str] = None
    group: Optional[str] = None
    start_time: Optional[str] = None
    end_time: Optional[str] = None
    decision_done: Optional[bool] = None
    context_status: Optional[str] = None


@dataclass
class EntryUpdateEvent:
    kind: str
    ts: str
    entry_id: str
    patch: dict[str, object]


@dataclass
class TimeLog:
    id: str
    project_id: str
    start: str
    end: str
    duration_sec: Optional[int] = None
    duration_min: Optional[int] = None
    note: Optional[str] = None
    tags: list[str] = field(default_factory=list)


@dataclass
class TimerState:
    running: bool
    project_id: Optional[str]
    start_ts: Optional[str]
    note: Optional[str]


@dataclass
class Task:
    id: str
    project_id: str
    title: str
    status: str = "open"
    created_at: str = ""
    done_at: Optional[str] = None
    due_date: Optional[str] = None
    tags: list[str] = field(default_factory=list)
    linked_entry_id: Optional[str] = None
    note: Optional[str] = None


@dataclass
class CalendarSubscription:
    """Calendar subscription for syncing external ICS calendars."""
    id: str
    name: str
    source_url: str  # URL or file path to ICS
    project_id: str  # Target project for imported entries
    active: bool = True
    last_sync: Optional[str] = None  # ISO timestamp
    sync_interval_minutes: int = 60  # Auto-sync interval
    created_at: str = ""
    # Mapping of ICS event UID -> PIGE entry ID
    event_mapping: dict[str, str] = field(default_factory=dict)
    # Options
    import_past_events: bool = False  # Import events before today
    auto_sync: bool = False  # Enable automatic sync

