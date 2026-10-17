from __future__ import annotations

import argparse
import os
import subprocess
import sys
from datetime import date
from pathlib import Path

from pige.core import paths
from pige.core.service import PigeService
from pige.core.storage import Storage
from pige.utils import dates, strings


def build_service() -> PigeService:
    storage = Storage(paths.resolve_data_dir())
    return PigeService(storage)


def _print_error(message: str) -> None:
    if message.startswith("Error: "):
        print(message, file=sys.stderr)
    else:
        print(f"Error: {message}", file=sys.stderr)


def _print_warning(message: str) -> None:
    if message.startswith("Warning: "):
        print(message, file=sys.stderr)
    else:
        print(f"Warning: {message}", file=sys.stderr)


def _format_duration(seconds: int) -> str:
    total = max(0, int(seconds))
    hours = total // 3600
    minutes = (total % 3600) // 60
    secs = total % 60
    return f"{hours:02d}:{minutes:02d}:{secs:02d}"


def _open_file(path: Path) -> bool:
    try:
        if sys.platform.startswith("win"):
            os.startfile(path)  # type: ignore[attr-defined]
            return True
        if sys.platform == "darwin":
            result = subprocess.run(["open", str(path)], check=False)
            return result.returncode == 0
        result = subprocess.run(["xdg-open", str(path)], check=False)
        return result.returncode == 0
    except Exception:
        return False


def _parse_date_arg(value: str | None) -> date | None:
    if value is None:
        return None
    try:
        return dates.parse_date(value)
    except ValueError as exc:
        raise ValueError(f"Invalid date {value}. Expected YYYY-MM-DD") from exc


def _resolve_project_arg(service: PigeService, value: str) -> str:
    projects = service.storage.read_projects()
    for project in projects:
        if project.id == value:
            return project.id
    lowered = value.strip().lower()
    matches = [project for project in projects if project.name.lower() == lowered]
    if not matches:
        raise ValueError(f"Project not found: {value}")
    if len(matches) > 1:
        raise ValueError(f"Multiple projects match name: {value}")
    return matches[0].id


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="pige")
    subparsers = parser.add_subparsers(dest="command", required=True)

    subparsers.add_parser("init")

    project_parser = subparsers.add_parser("project")
    project_sub = project_parser.add_subparsers(dest="project_cmd", required=True)
    project_add = project_sub.add_parser("add")
    project_add.add_argument("name")
    project_add.add_argument("--desc")
    project_add.add_argument("--tags")
    project_add.add_argument("--parent", help="Parent project ID (for hierarchy)")
    project_list = project_sub.add_parser("list")
    project_list.add_argument(
        "--status",
        choices=["active", "archived", "all"],
        default="active",
    )

    entry_parser = subparsers.add_parser("entry")
    entry_sub = entry_parser.add_subparsers(dest="entry_cmd", required=True)
    
    # entry add - Enhanced with all parameters
    entry_add = entry_sub.add_parser("add")
    entry_add.add_argument("project_id")
    entry_add.add_argument("--type", required=True, choices=["note", "meeting", "decision", "log"])
    entry_add.add_argument("--title", required=True)
    entry_add.add_argument("--tags", help="Comma-separated list of tags")
    entry_add.add_argument("--body", help="Entry body content")
    entry_add.add_argument("--date", dest="entry_date", help="Entry date (YYYY-MM-DD, default: today)")
    entry_add.add_argument("--person", help="Person associated with entry")
    entry_add.add_argument("--group", help="Group associated with entry")
    entry_add.add_argument("--meeting-start", dest="meeting_start", help="Meeting start time (HH:MM)")
    entry_add.add_argument("--meeting-end", dest="meeting_end", help="Meeting end time (HH:MM)")
    entry_add.add_argument("--decision-done", dest="decision_done", action="store_true", help="Mark decision as done")
    entry_add.add_argument("--open", action="store_true", help="Open entry file after creation")

    # entry update - New command
    entry_update = entry_sub.add_parser("update")
    entry_update.add_argument("entry_id", help="Entry ID to update")
    entry_update.add_argument("--title", help="New title")
    entry_update.add_argument("--tags", help="New tags (comma-separated)")
    entry_update.add_argument("--date", dest="entry_date", help="New entry date (YYYY-MM-DD)")
    entry_update.add_argument("--person", help="New person")
    entry_update.add_argument("--group", help="New group")
    entry_update.add_argument("--meeting-start", dest="meeting_start", help="New meeting start time (HH:MM)")
    entry_update.add_argument("--meeting-end", dest="meeting_end", help="New meeting end time (HH:MM)")
    entry_update.add_argument("--decision-done", dest="decision_done", type=lambda x: x.lower() in ('true', '1', 'yes'), help="Decision done status (true/false)")
    entry_update.add_argument("--context-status", dest="context_status", choices=["created", "actual", "treated"], help="Context status")

    # entry delete - New command
    entry_delete = entry_sub.add_parser("delete")
    entry_delete.add_argument("entry_id", help="Entry ID to delete")
    entry_delete.add_argument("--yes", action="store_true", help="Skip confirmation")

    # entry move - New command
    entry_move = entry_sub.add_parser("move")
    entry_move.add_argument("entry_id", help="Entry ID to move")
    entry_move.add_argument("dest_project_id", help="Destination project ID")
    entry_move.add_argument("--keep-tags", action="store_true", help="Keep tags when moving")
    entry_move.add_argument("--keep-people", action="store_true", help="Keep person/group when moving")

    # entry list - New command
    entry_list = entry_sub.add_parser("list")
    entry_list.add_argument("project_id", help="Project ID to list entries from")
    entry_list.add_argument("--type", help="Filter by entry type")
    entry_list.add_argument("--limit", type=int, default=20, help="Maximum number of entries to show")

    log_parser = subparsers.add_parser("log")
    log_sub = log_parser.add_subparsers(dest="log_cmd", required=True)
    log_sub.add_parser("today")

    time_parser = subparsers.add_parser("time")
    time_sub = time_parser.add_subparsers(dest="time_cmd", required=True)
    time_start = time_sub.add_parser("start")
    time_start.add_argument("project_id")
    time_start.add_argument("--note")
    time_sub.add_parser("stop")
    time_sub.add_parser("today")

    export_parser = subparsers.add_parser("export")
    export_sub = export_parser.add_subparsers(dest="export_cmd", required=True)
    export_project = export_sub.add_parser("project")
    export_project.add_argument("project_id")
    export_project.add_argument("--from", dest="from_date")
    export_project.add_argument("--to", dest="to_date")
    export_project.add_argument("--out")
    export_project.add_argument("--mode", choices=["raw", "narrative"], default="raw")
    export_project.add_argument(
        "--redact",
        action="store_true",
        help="Hide entry bodies and time-log notes (titles, people and tags stay visible)",
    )
    export_meeting = export_sub.add_parser("meeting")
    export_meeting.add_argument("--entry", required=True)
    export_meeting.add_argument("--out")
    export_meeting.add_argument("--no-decisions", action="store_true")
    export_meeting.add_argument("--no-tasks", action="store_true")
    export_meeting.add_argument("--window-days", type=int, default=1)
    export_meeting.add_argument("--internal", action="store_true")
    export_meeting.add_argument(
        "--redact",
        action="store_true",
        help="Hide the meeting notes (title, people and date stay visible)",
    )
    export_weekly = export_sub.add_parser("weekly")
    export_weekly.add_argument("--from", dest="from_date", required=True)
    export_weekly.add_argument("--to", dest="to_date", required=True)
    export_weekly.add_argument("--project")
    export_weekly.add_argument("--out")
    export_weekly.add_argument("--include-time", action="store_true")

    export_hierarchy = export_sub.add_parser("hierarchy", help="Export project hierarchy tree")
    export_hierarchy.add_argument("--out", help="Output file path")
    export_hierarchy.add_argument(
        "--include-archived",
        action="store_true",
        help="Include archived projects in export"
    )

    compact_parser = subparsers.add_parser(
        "compact",
        help="Compact entries log to a snapshot (removes update/delete history)",
    )

    migrate_parser = subparsers.add_parser(
        "migrate",
        help="Migrate data to latest schema (adds hierarchy fields to projects)",
    )
    
    rebuild_index_parser = subparsers.add_parser(
        "rebuild-index",
        help="Rebuild full-text search index from all data",
    )

    args = parser.parse_args(argv)
    service = build_service()

    try:
        if args.command == "init":
            service.init_storage()
            print(f"Data directory: {service.storage.data_dir}")
            legacy = Path.cwd() / "data"
            if legacy.is_dir() and legacy.resolve() != service.storage.data_dir.resolve():
                _print_warning(
                    f"{legacy} exists but is not a P.IGE data folder, so it was not used. "
                    "Set PIGE_DATA_DIR to choose a folder explicitly."
                )
            return 0

        if args.command == "compact":
            recap = service.compact_entries()
            print(
                f"Compacted: {recap['before_lines']} lines -> {recap['after_lines']} lines "
                f"({recap['entries_count']} entries)"
            )
            return 0
        
        if args.command == "migrate":
            stats = service.storage.migrate_projects_hierarchy()
            print("Migration complete:")
            print(f"  Total projects: {stats['total']}")
            print(f"  Migrated: {stats['migrated']}")
            print(f"  Already migrated: {stats['already_migrated']}")
            return 0
        
        if args.command == "rebuild-index":
            print("Rebuilding search index...")
            stats = service.storage.rebuild_search_index()
            print("Search index rebuilt successfully:")
            print(f"  Entries: {stats['entries']}")
            print(f"  Projects: {stats['projects']}")
            print(f"  Tasks: {stats['tasks']}")
            return 0

        if args.command == "project":
            if args.project_cmd == "add":
                tags = strings.parse_tags(args.tags)
                parent_id = getattr(args, "parent", None)
                project = service.create_project(
                    args.name, 
                    args.desc, 
                    tags,
                    parent_id=parent_id
                )
                print(f"Project created: {project.id}")
                if parent_id:
                    print(f"  Parent: {parent_id}")
                return 0
            if args.project_cmd == "list":
                projects = service.list_projects(args.status)
                for project in projects:
                    tags = strings.format_tags(project.tags)
                    print(
                        f"{project.id} | {project.name} | {project.status} | tags: {tags}"
                    )
                return 0

        if args.command == "entry":
            if args.entry_cmd == "add":
                tags = strings.parse_tags(args.tags)
                # Parse optional parameters
                entry_date = _parse_date_arg(getattr(args, 'entry_date', None))
                person = getattr(args, 'person', None) or None
                group = getattr(args, 'group', None) or None
                start_time = getattr(args, 'meeting_start', None) or None
                end_time = getattr(args, 'meeting_end', None) or None
                decision_done = getattr(args, 'decision_done', False)
                
                entry, md_path = service.add_entry(
                    args.project_id, 
                    args.type, 
                    args.title, 
                    tags, 
                    args.body,
                    entry_date=entry_date,
                    person=person,
                    group=group,
                    start_time=start_time,
                    end_time=end_time,
                    decision_done=decision_done if args.type == "decision" else None
                )
                print(f"Entry created: {entry.id}")
                if args.open:
                    if not _open_file(md_path):
                        print(str(md_path))
                else:
                    print(str(md_path))
                return 0

            if args.entry_cmd == "update":
                # Prepare update parameters (only non-None values)
                update_kwargs = {}
                if args.title:
                    update_kwargs['title'] = args.title
                if args.tags is not None:
                    update_kwargs['tags'] = strings.parse_tags(args.tags)
                if hasattr(args, 'entry_date') and args.entry_date:
                    update_kwargs['entry_date'] = _parse_date_arg(args.entry_date)
                if hasattr(args, 'person') and args.person is not None:
                    update_kwargs['person'] = args.person
                if hasattr(args, 'group') and args.group is not None:
                    update_kwargs['group'] = args.group
                if hasattr(args, 'meeting_start') and args.meeting_start:
                    update_kwargs['start_time'] = args.meeting_start
                if hasattr(args, 'meeting_end') and args.meeting_end:
                    update_kwargs['end_time'] = args.meeting_end
                if hasattr(args, 'decision_done') and args.decision_done is not None:
                    update_kwargs['decision_done'] = args.decision_done
                if hasattr(args, 'context_status') and args.context_status:
                    update_kwargs['context_status'] = args.context_status
                
                if not update_kwargs:
                    _print_error("No fields to update. Specify at least one --field option.")
                    return 1
                
                entry = service.update_entry_meta(args.entry_id, **update_kwargs)
                print(f"Entry updated: {entry.id}")
                return 0

            if args.entry_cmd == "delete":
                if not args.yes:
                    # Get entry info for confirmation
                    entries = service.storage.read_entries_meta()
                    entry = next((e for e in entries if e.id == args.entry_id), None)
                    if not entry:
                        _print_error(f"Entry not found: {args.entry_id}")
                        return 1
                    print(f"About to delete entry: {entry.title} ({entry.type})")
                    response = input("Are you sure? (yes/no): ")
                    if response.lower() not in ('yes', 'y'):
                        print("Cancelled.")
                        return 0
                
                service.delete_entry(args.entry_id)
                print(f"Entry deleted: {args.entry_id}")
                return 0

            if args.entry_cmd == "move":
                service.move_entry(
                    args.entry_id,
                    args.dest_project_id,
                    keep_tags=args.keep_tags,
                    keep_people=args.keep_people
                )
                print(f"Entry moved to project: {args.dest_project_id}")
                return 0

            if args.entry_cmd == "list":
                entries = service.storage.read_entries_meta()
                # Filter by project
                entries = [e for e in entries if e.project_id == args.project_id]
                # Filter by type if specified
                if args.type:
                    entries = [e for e in entries if e.type == args.type]
                # Sort by date (newest first)
                entries.sort(key=lambda e: e.entry_date, reverse=True)
                # Limit results
                entries = entries[:args.limit]
                
                if not entries:
                    print("No entries found.")
                    return 0
                
                for entry in entries:
                    tags_str = strings.format_tags(entry.tags)
                    status_str = f" [{entry.context_status}]" if entry.context_status != "created" else ""
                    print(f"{entry.id} | {entry.entry_date} | {entry.type} | {entry.title}{status_str} | tags: {tags_str}")
                return 0

        if args.command == "log" and args.log_cmd == "today":
            grouped = service.log_today()
            if not grouped:
                print("No entries today.")
                return 0
            for project, entries in grouped:
                print(f"Project: {project.name}")
                for entry in entries:
                    entry_dt = dates.parse_utc_z(entry.ts).astimezone()
                    time_label = entry_dt.strftime("%H:%M")
                    print(
                        f"  {time_label} | {entry.type} | {entry.title} | {entry.content_path}"
                    )
            return 0

        if args.command == "time":
            if args.time_cmd == "start":
                project = service.time_start(args.project_id, args.note)
                print(f"Timer started for project {project.name}")
                return 0
            if args.time_cmd == "stop":
                timelog, _project = service.time_stop()
                duration_sec = timelog.duration_sec or (timelog.duration_min or 0) * 60
                print(
                    f"Timer stopped. Duration: {_format_duration(duration_sec)} ({duration_sec} sec)"
                )
                return 0
            if args.time_cmd == "today":
                totals = service.time_today()
                if not totals:
                    print("No time logged today.")
                    return 0
                project_map = {
                    project.id: project.name for project in service.storage.read_projects()
                }
                items = [
                    (project_map.get(project_id, project_id), seconds)
                    for project_id, seconds in totals.items()
                ]
                items.sort(key=lambda item: item[0])
                for name, seconds in items:
                    print(f"{name}: {_format_duration(seconds)}")
                return 0

        if args.command == "export" and args.export_cmd == "project":
            from_date = _parse_date_arg(args.from_date)
            to_date = _parse_date_arg(args.to_date)
            if from_date and to_date and from_date > to_date:
                raise ValueError("Invalid date range: from is after to")
            out_path = Path(args.out) if args.out else None
            if args.mode == "raw":
                export_path, warnings = service.export_project_raw(
                    args.project_id,
                    from_date,
                    to_date,
                    out_path,
                    redact_bodies=getattr(args, "redact", False),
                )
                for warning in warnings:
                    _print_warning(warning)
                print(str(export_path))
                return 0
            export_path = service.export_project_narrative(
                args.project_id,
                from_date,
                to_date,
                out_path,
                redact_bodies=getattr(args, "redact", False),
            )
            print(str(export_path))
            return 0
        if args.command == "export" and args.export_cmd == "meeting":
            export_path = service.export_meeting_minutes(
                args.entry,
                args.out,
                include_decisions=not args.no_decisions,
                include_tasks=not args.no_tasks,
                window_days=args.window_days,
                internal=args.internal,
                redact_bodies=getattr(args, "redact", False),
            )
            print(export_path)
            return 0
        if args.command == "export" and args.export_cmd == "weekly":
            start = _parse_date_arg(args.from_date)
            end = _parse_date_arg(args.to_date)
            if start is None or end is None:
                raise ValueError("Both --from and --to are required")
            if start > end:
                raise ValueError("Invalid date range: from is after to")
            project_id = None
            if args.project:
                project_id = _resolve_project_arg(service, args.project)
            export_path = service.export_weekly_summary(
                start,
                end,
                project_id,
                args.out,
                include_time=args.include_time,
            )
            print(export_path)
            return 0
        
        if args.command == "export" and args.export_cmd == "hierarchy":
            out_path = Path(args.out) if args.out else None
            export_path = service.export_project_hierarchy(
                out_path,
                include_archived=args.include_archived,
            )
            print(f"Project hierarchy exported to: {export_path}")
            return 0

        _print_error("Not implemented")
        return 2
    except NotImplementedError as exc:
        _print_error(str(exc))
        return 2
    except (ValueError, OSError) as exc:
        _print_error(str(exc))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
