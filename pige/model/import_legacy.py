"""Import legacy P.IGE data (JSON files) into the new model.

Usage::

    python -m pige.model.import_legacy SOURCE_DIR TARGET.sqlite3 [--as-tag "DOCTORANT.ES=doctorant·es"] [--skip test]

The source folder is never modified (it is copied to a temporary folder before
reading). The target database must be empty. Rules, from the shape of real data:

* top-level projects become **spaces** ("- FoReLLIS -" -> "FoReLLIS", "Z - DEV" -> "DEV");
* inside a space, a project whose name starts with "-" is a **container**:
  "- FORELLIS A" gives its children the team "A", "- GENERAL" none; the
  container's own entries and tasks go to the space itself;
* the next level gives **projects**, the one below **sub-projects**; anything
  deeper is merged into its sub-project (reported);
* calendar-sync projects are dropped (the agenda will come from CalDAV), the
  inbox becomes the space "À trier", ``--as-tag`` turns a project into a tag on
  its entries, tasks and people, ``--skip`` drops empty projects by name;
* tags repeating the hierarchy (a space or team name) are dropped, "a; b" is split;
* entry bodies lose the empty template (**Date:**, **Project:**, empty sections);
* an entry marked « en cours » becomes an in-progress task linked to it;
* « - [ ] » lines in a task note become steps.
"""

from __future__ import annotations

import argparse
import re
import shutil
import sys
import tempfile
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable

from pige.core.models import Project as LegacyProject
from pige.core.storage import Storage
from pige.model.store import InvalidOperationError, ModelStore
from pige.model.text import fold, split_people

INBOX_SPACE = "À trier"
KIND = {"note": "note", "meeting": "meeting", "decision": "decision", "log": "activity"}
_HEADER_LINE = re.compile(r"^\*\*(Date|Project|Projet|Person/Group|People|Time|Tags):\*\*", re.IGNORECASE)
_PLACEHOLDER = re.compile(r"^-?\s*(\[\s?\]\s*)?(Applied/Done:\s*)?$")
_STEP = re.compile(r"^\s*-\s*\[\s*([xX ]?)\s*\]\s*(.+?)\s*$")


@dataclass
class Report:
    spaces: int = 0
    projects: int = 0
    tasks: int = 0
    entries: int = 0
    people: int = 0
    blocks: int = 0
    warnings: list[str] = field(default_factory=list)

    def summary(self) -> str:
        lines = [
            f"Espaces : {self.spaces}",
            f"Projets : {self.projects}",
            f"Tâches : {self.tasks}",
            f"Entrées : {self.entries}",
            f"Personnes : {self.people}",
            f"Blocs de temps : {self.blocks}",
        ]
        if self.warnings:
            lines.append("Remarques :")
            counts: dict[str, int] = {}
            for w in self.warnings:
                counts[w] = counts.get(w, 0) + 1
            lines += [f"  - {w}" + (f" (×{n})" if n > 1 else "") for w, n in counts.items()]
        return "\n".join(lines)


# ---------------------------------------------------------------- text clean-up


_SUSPECT_RUN = re.compile("[\u0080-\u00ff\u0152\u0153\u0160\u0161\u0178\u017d\u017e\u0192\u02c6\u02dc\u2013-\u2122]{2,}")


def fix_mojibake(text: str) -> str:
    """Repair UTF-8 read as CP1252 ("ðŸ“…" -> "📅"), run by run, so correct accents
    in the same text ("Francoralité") are left alone."""

    def repair(match: re.Match[str]) -> str:
        run = match.group(0)
        try:
            return run.encode("cp1252").decode("utf-8")
        except (UnicodeEncodeError, UnicodeDecodeError):
            return run

    return _SUSPECT_RUN.sub(repair, text)


def clean_name(name: str) -> str:
    """ "- FoReLLIS -" -> "FoReLLIS", "Z- PERSO/ADMIN." -> "PERSO/ADMIN", "Z - DEV" -> "DEV"."""
    cleaned = re.sub(r"^\s*(Z\s*-\s*|-\s*)", "", name)
    cleaned = re.sub(r"\s*-\s*$", "", cleaned).strip().rstrip(".").strip()
    return cleaned or name.strip()


def clean_body(body: str) -> str:
    """Drop the legacy template: header lines and sections left empty."""
    lines = body.replace("\r\n", "\n").split("\n")
    # leading "# title" line written by the template
    while lines and not lines[0].strip():
        lines.pop(0)
    if lines and re.match(r"^#\s", lines[0] + " ") and not lines[0].startswith("##"):
        lines.pop(0)
    lines = [line for line in lines if not _HEADER_LINE.match(line.strip())]
    sections: list[tuple[str | None, list[str]]] = [(None, [])]
    for line in lines:
        if line.startswith("## "):
            sections.append((line, []))
        else:
            sections[-1][1].append(line)
    out: list[str] = []
    for heading, content in sections:
        meaningful = [c for c in content if c.strip() and not _PLACEHOLDER.match(c.strip())]
        if not meaningful:
            continue
        kept = [c for c in content if not _PLACEHOLDER.match(c.strip()) or not c.strip()]
        if heading is not None:
            out.append(heading)
        out.extend(kept)
        out.append("")
    text = "\n".join(out)
    return re.sub(r"\n{3,}", "\n\n", text).strip() + ("\n" if text.strip() else "")


def split_note(note: str | None) -> tuple[str | None, list[tuple[str, bool]]]:
    """A task note -> (note without checkbox lines, [(step, done)])."""
    if not note:
        return note, []
    steps: list[tuple[str, bool]] = []
    rest: list[str] = []
    for line in note.replace("\r\n", "\n").split("\n"):
        match = _STEP.match(line)
        if match:
            steps.append((match.group(2), match.group(1).lower() == "x"))
        else:
            rest.append(line)
    text = "\n".join(rest).strip()
    return (text or None), steps


def split_tags(tags: Iterable[str]) -> list[str]:
    out: list[str] = []
    for tag in tags:
        for part in re.split(r"[;,]", tag):
            if part.strip():
                out.append(part.strip())
    return out


def _utc_text(value: str | None) -> str | None:
    if not value:
        return None
    try:
        moment = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=timezone.utc)
    return moment.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ")


# ---------------------------------------------------------------- import


@dataclass
class _Place:
    space: str
    project: str | None
    team: str | None = None


def import_legacy(
    source: Path,
    store: ModelStore,
    *,
    as_tags: dict[str, str] | None = None,
    skip: Iterable[str] = (),
) -> Report:
    report = Report()
    if store.list_spaces(include_archived=True):
        raise InvalidOperationError("the target database is not empty")
    as_tags = {fold(k): v for k, v in (as_tags or {}).items()}
    skip_names = {fold(s) for s in skip}
    with tempfile.TemporaryDirectory() as tmp:
        copy = Path(tmp) / "data"
        shutil.copytree(source, copy, ignore=shutil.ignore_patterns("calendar_subscriptions.json", "*.lock"))
        legacy = Storage(copy)
        projects = legacy.read_projects()
        entries = legacy.read_entries_meta()
        tasks = legacy.read_tasks()
        timelogs = legacy.read_timelogs()
        bodies = {e.id: legacy.read_entry_body(e) for e in entries}

    by_id = {p.id: p for p in projects}
    children: dict[str | None, list[LegacyProject]] = defaultdict(list)
    for p in projects:
        parent = p.parent_id if p.parent_id in by_id else None
        children[parent].append(p)
    for items in children.values():
        items.sort(key=lambda p: (p.display_order, p.created_at))

    content_count: dict[str, int] = defaultdict(int)
    for e in entries:
        content_count[e.project_id] += 1
    for t in tasks:
        content_count[t.project_id] += 1

    def subtree_has_content(p: LegacyProject) -> bool:
        return content_count[p.id] > 0 or any(subtree_has_content(c) for c in children[p.id])

    place: dict[str, _Place] = {}  # legacy project id -> where its content goes
    tag_of: dict[str, str] = {}  # legacy project id -> tag (for --as-tag projects)
    hierarchy_words: set[str] = set()
    spaces_by_name: dict[str, str] = {}

    with store.transaction():
        def space_for(name: str) -> str:
            key = fold(name)
            if key not in spaces_by_name:
                spaces_by_name[key] = store.create_space(name).id
                report.spaces += 1
                hierarchy_words.add(key)
            return spaces_by_name[key]

        def walk_projects(items: list[LegacyProject], space: str, parent: str | None, team: str | None, depth: int) -> None:
            for p in items:
                if fold(p.name) in skip_names and not subtree_has_content(p):
                    report.warnings.append(f"projet vide ignoré : {p.name}")
                    continue
                if depth >= 2 and parent is not None:
                    # deeper than a sub-project: merge into the sub-project
                    place[p.id] = place[_legacy_of[parent]]
                    if subtree_has_content(p):
                        report.warnings.append(f"« {p.name} » fusionné dans son sous-projet (trop profond)")
                    walk_projects(children[p.id], space, parent, team, depth + 1)
                    continue
                description = p.description
                people = ", ".join(split_people(p.person or ""))
                if people:
                    description = (description + "\n\n" if description else "") + f"Personnes : {people}"
                created = store.create_project(
                    space, clean_name(fix_mojibake(p.name)), parent_id=parent,
                    description=description, team=team,
                )
                if p.status == "archived":
                    store.update_project(created.id, state="closed")
                if p.links:
                    store.set_project_links(created.id, [(url, None) for url in p.links if url.startswith("http")])
                report.projects += 1
                place[p.id] = _Place(space, created.id, team)
                _legacy_of[created.id] = p.id
                walk_projects(children[p.id], space, created.id, team, depth + 1)

        _legacy_of: dict[str, str] = {}

        for top in children[None]:
            if "calendar-sync" in top.tags:
                report.warnings.append(f"projet d'agenda ignoré : {fix_mojibake(top.name)}")
                place[top.id] = _Place("", None)
                continue
            if fold(top.name) in as_tags:
                tag_of[top.id] = as_tags[fold(top.name)]
                continue
            if fold(top.name) in skip_names and not subtree_has_content(top):
                report.warnings.append(f"projet vide ignoré : {top.name}")
                continue
            name = INBOX_SPACE if "inbox" in top.tags else clean_name(top.name)
            space = space_for(name)
            place[top.id] = _Place(space, None)
            for child in children[top.id]:
                if child.name.strip().startswith("-"):
                    container = clean_name(child.name)
                    last = container.split()[-1] if container.split() else ""
                    team = last if len(last) <= 2 and len(container.split()) > 1 else None
                    if team:
                        hierarchy_words.add(fold(container))
                        hierarchy_words.add(fold(f"{name} {team}"))
                    place[child.id] = _Place(space, None, team)
                    walk_projects(children[child.id], space, None, team, 0)
                else:
                    walk_projects([child], space, None, None, 0)

        # projects nested under an --as-tag project: their content follows the tag too
        def tag_subtree(pid: str, tag: str) -> None:
            for c in children[pid]:
                tag_of[c.id] = tag
                tag_subtree(c.id, tag)

        for pid, tag in list(tag_of.items()):
            tag_subtree(pid, tag)

        fallback_space = next(iter(spaces_by_name.values()), None) or space_for(INBOX_SPACE)

        def resolve(project_id: str, tags: list[str]) -> tuple[_Place, list[str]]:
            """Where content goes, and its tags without the ones repeating the hierarchy."""
            extra: list[str] = []
            if project_id in tag_of:
                extra.append(tag_of[project_id])
                target = None
                for t in tags:  # an entry tagged with a space name goes to that space
                    if fold(t) in spaces_by_name:
                        target = _Place(spaces_by_name[fold(t)], None)
                        break
                where = target or _Place(fallback_space, None)
            else:
                where = place.get(project_id) or _Place(fallback_space, None)
                if project_id not in place:
                    report.warnings.append(f"contenu d'un projet disparu ({project_id[:8]}) rangé dans le premier espace")
            kept = [t for t in tags if fold(t) not in hierarchy_words and fold(t) not in {"journal"}]
            return where, kept + extra

        # ---------------------------------------------------- entries
        entry_ids: dict[str, str] = {}
        for e in sorted(entries, key=lambda x: x.ts):
            where, tags = resolve(e.project_id, split_tags(e.tags))
            if not where.space:  # calendar project: keep the entry, in the first space
                where = _Place(fallback_space, None)
            title = fix_mojibake(e.title or "").replace("📅", "").strip()
            body = clean_body(fix_mojibake(bodies.get(e.id, "")))
            names = split_people(fix_mojibake(e.person or ""))
            try:
                new = store.create_entry(
                    entry_date=(e.entry_date or e.ts[:10]),
                    project_id=where.project,
                    space_id=where.space if where.project is None else None,
                    kind=KIND.get(e.type, "note"),  # type: ignore[arg-type]
                    title=title,
                    body=body,
                    start_time=e.start_time or None,
                    end_time=e.end_time or None,
                    source="import",
                    people=names,
                    tags=tags,
                )
            except InvalidOperationError as exc:
                report.warnings.append(f"entrée « {title or e.id[:8]} » non reprise : {exc}")
                continue
            created_at = _utc_text(e.ts)
            if created_at:
                store.conn.execute(
                    "UPDATE entries SET created_at = ?, updated_at = ? WHERE id = ?", (created_at, created_at, new.id)
                )
            if e.type == "decision" and e.decision_done:
                store.conn.execute("UPDATE entries SET decision_applied = 1 WHERE id = ?", (new.id,))
            if tag_of.get(e.project_id):
                for person in store.entry_people(new.id):
                    store.tag_person(person.id, [tag_of[e.project_id]])
            entry_ids[e.id] = new.id
            report.entries += 1
            if e.context_status == "actual":
                follow = store.create_task(
                    f"Reprendre : {title or 'entrée du ' + (e.entry_date or e.ts[:10])}",
                    project_id=where.project,
                    space_id=where.space if where.project is None else None,
                    origin_entry_id=new.id,
                    tags=[tag_of[e.project_id]] if e.project_id in tag_of else [],
                )
                store.set_task_status(follow.id, "in_progress")
                report.tasks += 1

        # ---------------------------------------------------- tasks
        for t in sorted(tasks, key=lambda x: x.created_at):
            where, tags = resolve(t.project_id, split_tags(t.tags))
            if not where.space:
                where = _Place(fallback_space, None)
            note, steps = split_note(t.note)
            try:
                new_task = store.create_task(
                    fix_mojibake(t.title),
                    project_id=where.project,
                    space_id=where.space if where.project is None else None,
                    note=note,
                    due_date=t.due_date or None,
                    origin_entry_id=entry_ids.get(t.linked_entry_id or ""),
                    tags=tags,
                )
            except InvalidOperationError as exc:
                report.warnings.append(f"tâche « {t.title} » non reprise : {exc}")
                continue
            for label, done in steps:
                step = store.add_step(new_task.id, label)
                if done:
                    store.set_step_done(step.id, True)
            status = {"open": "open", "in_progress": "in_progress", "done": "done"}.get(t.status, "open")
            if status != "open":
                store.set_task_status(new_task.id, status)  # type: ignore[arg-type]
            created_at = _utc_text(t.created_at) or new_task.created_at
            done_at = _utc_text(t.done_at) if status == "done" else None
            store.conn.execute(
                "UPDATE tasks SET created_at = ?, status_since = ?, done_at = coalesce(?, done_at) WHERE id = ?",
                (created_at, done_at or created_at, done_at, new_task.id),
            )
            report.tasks += 1

        # ---------------------------------------------------- time
        for log in timelogs:
            where, _ = resolve(log.project_id, [])
            if not where.space:
                continue
            try:
                start = datetime.fromisoformat(log.start.replace("Z", "+00:00"))
                end = datetime.fromisoformat(log.end.replace("Z", "+00:00"))
                if start.tzinfo is None:
                    start, end = start.replace(tzinfo=timezone.utc), end.replace(tzinfo=timezone.utc)
                store.add_block(start, end, project_id=where.project,
                                space_id=where.space if where.project is None else None,
                                source="manual", note=log.note)
                report.blocks += 1
            except (ValueError, InvalidOperationError) as exc:
                report.warnings.append(f"temps du {log.start[:10]} non repris : {exc}")

        report.people = len(store.list_people())
    return report


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Importer les données de l'ancien P.IGE dans le nouveau modèle.")
    parser.add_argument("source", type=Path, help="dossier de données de l'ancien P.IGE (jamais modifié)")
    parser.add_argument("target", type=Path, help="base SQLite à remplir (doit être vide)")
    parser.add_argument("--as-tag", action="append", default=[], metavar="PROJET=étiquette",
                        help="transformer un projet de premier niveau en étiquette (répétable)")
    parser.add_argument("--skip", action="append", default=[], metavar="NOM",
                        help="ignorer les projets vides portant ce nom (répétable)")
    args = parser.parse_args(argv)
    if not (args.source / "projects.json").is_file():
        print(f"{args.source} ne contient pas de projects.json", file=sys.stderr)
        return 2
    as_tags = {}
    for item in args.as_tag:
        project, _, tag = item.partition("=")
        if not project or not tag:
            print(f"--as-tag attend PROJET=étiquette, reçu {item!r}", file=sys.stderr)
            return 2
        as_tags[project.strip()] = tag.strip()
    store = ModelStore(args.target)
    try:
        report = import_legacy(args.source, store, as_tags=as_tags, skip=args.skip)
    except InvalidOperationError as exc:
        print(f"Import refusé : {exc}", file=sys.stderr)
        return 1
    finally:
        store.close()
    print(report.summary())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
