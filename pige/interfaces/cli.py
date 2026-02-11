from __future__ import annotations

import argparse
import os
import subprocess
import sys
from datetime import date
from pathlib import Path

from pige.core.service import PigeService
from pige.core.storage import Storage
from pige.utils import dates, strings


def build_service() -> PigeService:
    env = os.environ.get("PIGE_DATA_DIR")
    data_dir = Path(env).expanduser() if env else (Path.cwd() / "data")
    storage = Storage(data_dir)
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
    project_list = project_sub.add_parser("list")
    project_list.add_argument(
        "--status",
        choices=["active", "archived", "all"],
        default="active",
    )

    entry_parser = subparsers.add_parser("entry")
    entry_sub = entry_parser.add_subparsers(dest="entry_cmd", required=True)
    entry_add = entry_sub.add_parser("add")
    entry_add.add_argument("project_id")
    entry_add.add_argument("--type", required=True)
    entry_add.add_argument("--title", required=True)
    entry_add.add_argument("--tags")
    entry_add.add_argument("--body")
    entry_add.add_argument("--open", action="store_true")

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
    export_meeting = export_sub.add_parser("meeting")
    export_meeting.add_argument("--entry", required=True)
    export_meeting.add_argument("--out")
    export_meeting.add_argument("--no-decisions", action="store_true")
    export_meeting.add_argument("--no-tasks", action="store_true")
    export_meeting.add_argument("--window-days", type=int, default=1)
    export_meeting.add_argument("--internal", action="store_true")
    export_weekly = export_sub.add_parser("weekly")
    export_weekly.add_argument("--from", dest="from_date", required=True)
    export_weekly.add_argument("--to", dest="to_date", required=True)
    export_weekly.add_argument("--project")
    export_weekly.add_argument("--out")
    export_weekly.add_argument("--include-time", action="store_true")

    args = parser.parse_args(argv)
    service = build_service()

    try:
        if args.command == "init":
            service.init_storage()
            return 0

        if args.command == "project":
            if args.project_cmd == "add":
                tags = strings.parse_tags(args.tags)
                project = service.create_project(args.name, args.desc, tags)
                print(f"Project created: {project.id}")
                return 0
            if args.project_cmd == "list":
                projects = service.list_projects(args.status)
                for project in projects:
                    tags = strings.format_tags(project.tags)
                    print(
                        f"{project.id} | {project.name} | {project.status} | tags: {tags}"
                    )
                return 0

        if args.command == "entry" and args.entry_cmd == "add":
            tags = strings.parse_tags(args.tags)
            entry, md_path = service.add_entry(
                args.project_id, args.type, args.title, tags, args.body
            )
            print(f"Entry created: {entry.id}")
            if args.open:
                if not _open_file(md_path):
                    print(str(md_path))
            else:
                print(str(md_path))
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
                    args.project_id, from_date, to_date, out_path
                )
                for warning in warnings:
                    _print_warning(warning)
                print(str(export_path))
                return 0
            export_path = service.export_project_narrative(
                args.project_id, from_date, to_date, out_path
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
