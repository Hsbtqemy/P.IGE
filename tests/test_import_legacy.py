"""Import of legacy JSON data into the new model (synthetic data shaped like the real thing)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from pige.model import InvalidOperationError, ModelStore
from pige.model.import_legacy import clean_body, clean_name, fix_mojibake, import_legacy, main, split_note


def _p(pid, name, parent=None, order=0, tags=(), person=None, links=(), description=None, status="active"):
    return {"id": pid, "name": name, "description": description, "status": status, "tags": list(tags),
            "created_at": "2026-01-14T16:48:18Z", "person": person, "group": None, "links": list(links),
            "parent_id": parent, "display_order": order, "priority": 3}


def _write_legacy(root: Path) -> Path:
    data = root / "DATAPIGE"
    (data / "entries").mkdir(parents=True)
    projects = [
        _p("f" * 32, "- FoReLLIS -", order=0),
        _p("a" * 32, "- FORELLIS A", parent="f" * 32, order=1),
        _p("b" * 32, "- FORELLIS B", parent="f" * 32, order=2),
        _p("1" * 32, "DICODIACHRO", parent="a" * 32, links=["https://gitlab.example/dico"]),
        _p("2" * 32, "PHOTO NON REPRODUCTIBLE", parent="b" * 32, person="Martin Anne\nDurand Paul"),
        _p("3" * 32, "test", parent="2" * 32),
        _p("4" * 32, "tesfg", parent="3" * 32),
        _p("m" * 32, "- MIMMOC", order=1),
        _p("5" * 32, "PORTAIL DES REVUES", parent="m" * 32),
        _p("6" * 32, "POR FAVOR", parent="5" * 32),
        _p("7" * 32, "Numéros anciens", parent="6" * 32),  # too deep: merged into POR FAVOR
        _p("d" * 32, "DOCTORANT.ES", order=3),
        _p("c" * 32, "📅 UPoitiers", order=4, tags=["calendar-sync", "external"]),
        _p("i" * 32, "En attente", order=8, tags=["inbox"]),
        _p("z" * 32, "Z - DEV", order=5),
    ]
    (data / "projects.json").write_text(json.dumps(projects), encoding="utf-8")

    def entry(eid, pid, title, typ="note", **extra):
        body = extra.pop("body", None)
        row = {"id": eid, "ts": "2026-01-15T12:38:27Z", "project_id": pid, "type": typ, "title": title,
               "tags": extra.pop("tags", []), "content_path": f"entries/{eid}.md", "summary": None,
               "entry_date": extra.pop("entry_date", "2026-01-15"), "person": extra.pop("person", None),
               "group": None, "start_time": extra.pop("start", None), "end_time": extra.pop("end", None),
               "decision_done": extra.pop("decision_done", None), "kind": "entry", **extra}
        (data / "entries" / f"{eid}.md").write_text(body or "", encoding="utf-8")
        return row

    template = ("# \n\n**Date:** 15/01/2026\n**Project:** X\n**Person/Group:**  \n**Tags:** \n\n"
                "## Notes\n- \n\n## Next steps\n- \n")
    rows = [
        entry("e1" + "0" * 30, "a" * 32, "Présentation de l'équipe A", tags=["FoReLLIS"],
              body="# \n\n**Date:** 15/01/2026\n**Project:** FORELLIS A\n\n## Notes\nAxes bilinguisme\n\n## Next steps\n- \n"),
        entry("e2" + "0" * 30, "6" * 32, "Prise de contact", typ="meeting", start="10:30", end="11:50",
              person="Thouverez Ludivine", tags=["MIMMOC"], body=template),
        entry("e3" + "0" * 30, "6" * 32, "Planification", typ="decision", decision_done=True,
              person="Thouverez Ludivine", context_status="actual", body="Trois chantiers."),
        entry("e4" + "0" * 30, "d" * 32, "Brunet Maréva", person="Brunet Maréva", tags=["FoReLLIS"], body="Manuscrit."),
        entry("e5" + "0" * 30, "c" * 32, "ðŸ“… Francoralité RDV", tags=["calendar-event"], body=""),
        entry("e6" + "0" * 30, "7" * 32, "Bilan ancien", tags=["FoReLLIS; PPrim"], body="Archive."),
        entry("e7" + "0" * 30, "2" * 32, "Suivi", typ="log", person="PEYROL-KLEIBER Elodie", body="Fait."),
    ]
    rows.append({"kind": "entry_update", "ts": "2026-01-16T08:00:00Z", "entry_id": "e7" + "0" * 30,
                 "patch": {"person": "PEYROL KLEIBER Elodie"}})
    (data / "entries.jsonl").write_text("\n".join(json.dumps(r) for r in rows) + "\n", encoding="utf-8")

    def task(tid, pid, title, status="open", **extra):
        return {"id": tid, "project_id": pid, "title": title, "status": status, "created_at": "2026-01-16T08:11:03Z",
                "done_at": "2026-01-30T13:03:26Z" if status == "done" else None, "due_date": extra.get("due"),
                "tags": extra.get("tags", []), "linked_entry_id": extra.get("linked"), "note": extra.get("note")}

    tasks = [
        task("t1", "6" * 32, "Planification: POR FAVOR", "in_progress", linked="e3" + "0" * 30,
             note="3. Por Favor.\n-[] Modifier les métadonnées\n- [x] Choisir Quarto\nObjectifs : valoriser."),
        task("t2", "1" * 32, "1. Buchanan", "done", due="2026-02-28"),
        task("t3", "d" * 32, "Follow-up: café", "done", tags=["FoReLLIS"]),
        task("t4", "i" * 32, "Rappeler la graphiste"),
    ]
    (data / "tasks.json").write_text(json.dumps(tasks), encoding="utf-8")
    (data / "timelogs.jsonl").write_text(json.dumps({
        "id": "l1", "project_id": "1" * 32, "start": "2026-01-15T09:00:00Z", "end": "2026-01-15T10:30:00Z",
        "duration_sec": 5400, "duration_min": 90, "note": "regroupement", "tags": []}) + "\n", encoding="utf-8")
    (data / "calendar_subscriptions.json").write_text(json.dumps([{"password": "secret"}]), encoding="utf-8")
    return data


@pytest.fixture()
def imported(tmp_path):
    data = _write_legacy(tmp_path)
    before = sorted(p.name for p in data.rglob("*"))
    store = ModelStore(tmp_path / "new.sqlite3")
    report = import_legacy(data, store, as_tags={"DOCTORANT.ES": "doctorant·es"}, skip=["test", "tesfg"])
    yield store, report, data, before
    store.close()


def test_source_folder_is_left_untouched(imported):
    _store, _report, data, before = imported
    assert sorted(p.name for p in data.rglob("*")) == before


def test_hierarchy_becomes_spaces_projects_and_teams(imported):
    store, report, _data, _ = imported
    assert [s.name for s in store.list_spaces()] == ["FoReLLIS", "MIMMOC", "DEV", "À trier"]
    projects = {p.name: p for p in store.list_projects()}
    assert projects["DICODIACHRO"].team == "A"
    assert projects["PHOTO NON REPRODUCTIBLE"].team == "B"
    assert "Personnes : Martin Anne, Durand Paul" in (projects["PHOTO NON REPRODUCTIBLE"].description or "")
    assert projects["POR FAVOR"].parent_id == projects["PORTAIL DES REVUES"].id
    assert "test" not in projects and "tesfg" not in projects and "Numéros anciens" not in projects
    assert not any("UPoitiers" in p.name for p in projects.values())
    assert store.project_links(projects["DICODIACHRO"].id) == [("https://gitlab.example/dico", None)]
    assert any("fusionné" in w for w in report.warnings)
    assert any("agenda" in w for w in report.warnings)


def test_entries_cleaned_people_merged_tags_deduplicated(imported):
    store, _report, _data, _ = imported
    by_title = {e.title: e for e in store.timeline(limit=100)}
    assert by_title["Présentation de l'équipe A"].body == "## Notes\nAxes bilinguisme\n"
    assert by_title["Présentation de l'équipe A"].project_id is None  # container content -> space level
    assert by_title["Prise de contact"].body == ""
    assert (by_title["Prise de contact"].start_time, by_title["Prise de contact"].end_time) == ("10:30", "11:50")
    assert by_title["Planification"].decision_applied is True
    assert "Francoralité RDV" in by_title  # mojibake repaired, calendar icon dropped
    porfavor = next(p for p in store.list_projects() if p.name == "POR FAVOR")
    assert by_title["Bilan ancien"].project_id == porfavor.id  # merged from the too-deep project
    assert [t.name for t in store.entry_tags(by_title["Bilan ancien"].id)] == ["PPrim"]  # FoReLLIS dropped
    elodie = store.find_people("Elodie Peyrol Kleiber")
    assert len(elodie) == 1 and len(store.timeline(person_id=elodie[0].id)) == 1


def test_project_as_tag(imported):
    store, _report, _data, _ = imported
    by_title = {e.title: e for e in store.timeline(limit=100)}
    mareva = by_title["Brunet Maréva"]
    forellis = next(s for s in store.list_spaces() if s.name == "FoReLLIS")
    assert mareva.space_id == forellis.id and mareva.project_id is None
    assert [t.name for t in store.entry_tags(mareva.id)] == ["doctorant·es"]
    person = store.find_people("Maréva Brunet")[0]
    assert [t.name for t in store.person_tags(person.id)] == ["doctorant·es"]


def test_tasks_steps_status_dates_and_follow_ups(imported):
    store, _report, _data, _ = imported
    porfavor = next(p for p in store.list_projects() if p.name == "POR FAVOR")
    tasks = {t.title: t for t in store.tasks_for_project(porfavor.id, include_done=True)}
    planif = tasks["Planification: POR FAVOR"]
    assert planif.status == "in_progress" and planif.note == "3. Por Favor.\nObjectifs : valoriser."
    assert [(s.label, s.done) for s in store.steps(planif.id)] == [("Modifier les métadonnées", False), ("Choisir Quarto", True)]
    assert planif.origin_entry_id is not None
    reprendre = [t for t in tasks.values() if t.title.startswith("Reprendre")]
    assert len(reprendre) == 1 and reprendre[0].status == "in_progress"
    dico = next(p for p in store.list_projects() if p.name == "DICODIACHRO")
    [buchanan] = store.tasks_for_project(dico.id, include_done=True)
    assert buchanan.done_at == "2026-01-30T13:03:26.000000Z" and buchanan.due_date == "2026-02-28"
    inbox = next(s for s in store.list_spaces() if s.name == "À trier")
    assert [t.title for t in store.tasks_for_space(inbox.id)] == ["Rappeler la graphiste"]


def test_time_logs_become_blocks(imported):
    store, report, _data, _ = imported
    assert report.blocks == 1
    dico = next(p for p in store.list_projects() if p.name == "DICODIACHRO")
    assert store.last_activity(dico.id) is not None


def test_target_must_be_empty(tmp_path):
    data = _write_legacy(tmp_path)
    store = ModelStore(tmp_path / "new.sqlite3")
    store.create_space("Déjà là")
    with pytest.raises(InvalidOperationError):
        import_legacy(data, store)
    store.close()


def test_cli(tmp_path, capsys):
    data = _write_legacy(tmp_path)
    assert main([str(data), str(tmp_path / "cli.sqlite3"), "--as-tag", "DOCTORANT.ES=doctorant·es",
                 "--skip", "test", "--skip", "tesfg"]) == 0
    assert "Espaces : 4" in capsys.readouterr().out
    assert main([str(data), str(tmp_path / "cli.sqlite3")]) == 1  # second run refused: not empty
    assert main([str(tmp_path), str(tmp_path / "x.sqlite3")]) == 2


def test_text_helpers():
    assert clean_name("- FoReLLIS -") == "FoReLLIS"
    assert clean_name("Z- PERSO/ADMIN.") == "PERSO/ADMIN"
    assert clean_name("Z - DEV") == "DEV"
    assert fix_mojibake("ðŸ“… RDV") == "📅 RDV"
    assert fix_mojibake("Réunion") == "Réunion"
    assert clean_body("# \n\n**Date:** 1\n\n## Notes\n- \n\n## Next steps\n- \n") == ""
    assert split_note("a\n-[ ] b\n- [X] c") == ("a", [("b", False), ("c", True)])
