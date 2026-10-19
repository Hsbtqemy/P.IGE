"""Tests of the new SQLite model (pige.model)."""

from __future__ import annotations

import sqlite3
import threading
from datetime import date, datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import pytest

from pige.model import InvalidOperationError, ModelStore, NotFoundError, SchemaTooNewError, connect
from pige.model.schema import SCHEMA_VERSION
from pige.model.text import fold, name_key, split_people
from pige.model.timecount import Span, counted_seconds, presence_seconds

PARIS = ZoneInfo("Europe/Paris")


@pytest.fixture()
def store(tmp_path):
    s = ModelStore(tmp_path / "pige.sqlite3")
    yield s
    s.close()


@pytest.fixture()
def tree(store):
    """FoReLLIS / MIMMOC with the real-looking hierarchy from docs/modele.md."""
    forellis = store.create_space("FoReLLIS")
    mimmoc = store.create_space("MIMMOC")
    dico = store.create_project(forellis.id, "DICODIACHRO", team="A")
    portail = store.create_project(mimmoc.id, "Portail des revues")
    porfavor = store.create_project(mimmoc.id, "POR FAVOR", parent_id=portail.id)
    return {"forellis": forellis, "mimmoc": mimmoc, "dico": dico, "portail": portail, "porfavor": porfavor}


def at(hour: float, day: date = date(2026, 10, 15)) -> datetime:
    h = int(hour)
    m = round((hour - h) * 60)
    return datetime(day.year, day.month, day.day, h, m, tzinfo=PARIS)


# ---------------------------------------------------------------- schema


def test_schema_created_and_reopen_is_idempotent(tmp_path):
    path = tmp_path / "db.sqlite3"
    conn = connect(path)
    assert conn.execute("PRAGMA user_version").fetchone()[0] == SCHEMA_VERSION
    assert conn.execute("PRAGMA foreign_keys").fetchone()[0] == 1
    conn.close()
    conn = connect(path)
    assert conn.execute("PRAGMA user_version").fetchone()[0] == SCHEMA_VERSION
    conn.close()


def test_newer_schema_is_refused(tmp_path):
    path = tmp_path / "db.sqlite3"
    connect(path).close()
    raw = sqlite3.connect(path)
    raw.execute(f"PRAGMA user_version = {SCHEMA_VERSION + 1}")
    raw.close()
    with pytest.raises(SchemaTooNewError):
        connect(path)


def test_two_processes_creating_the_database_at_once(tmp_path):
    path = tmp_path / "db.sqlite3"
    errors: list[BaseException] = []

    def open_it():
        try:
            connect(path).close()
        except BaseException as exc:  # pragma: no cover - reported below
            errors.append(exc)

    threads = [threading.Thread(target=open_it) for _ in range(4)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert errors == []


# ---------------------------------------------------------------- text


def test_name_matching_ignores_order_case_accents_and_hyphens():
    assert name_key("PEYROL-KLEIBER Elodie") == name_key("Élodie Peyrol Kleiber")
    assert name_key("Thouverez Ludivine") == name_key("ludivine THOUVEREZ")
    assert fold("  Anne-Cécile  ") == "anne cecile"
    assert split_people("Magord André\nLabau Marion, Belly Marlène;") == ["Magord André", "Labau Marion", "Belly Marlène"]


# ---------------------------------------------------------------- projects


def test_one_level_of_subprojects_only(store, tree):
    with pytest.raises(InvalidOperationError):
        store.create_project(tree["mimmoc"].id, "Trop profond", parent_id=tree["porfavor"].id)
    with pytest.raises(InvalidOperationError):
        store.create_project(tree["forellis"].id, "Ailleurs", parent_id=tree["portail"].id)
    with pytest.raises(InvalidOperationError):  # a parent cannot become a sub-project
        store.move_project(tree["portail"].id, space_id=tree["mimmoc"].id, parent_id=tree["dico"].id)


def test_projects_listed_parent_then_children_in_space_order(store, tree):
    names = [p.name for p in store.list_projects()]
    assert names == ["DICODIACHRO", "Portail des revues", "POR FAVOR"]
    store.move_space(tree["mimmoc"].id, before=tree["forellis"].id)
    assert [p.name for p in store.list_projects()] == ["Portail des revues", "POR FAVOR", "DICODIACHRO"]


def test_moving_a_project_carries_children_and_attached_rows(store, tree):
    task = store.create_task("Inventaire", project_id=tree["porfavor"].id)
    entry = store.create_entry(entry_date="2026-01-13", project_id=tree["porfavor"].id, title="Prise de contact")
    block = store.add_block(at(9), at(10), project_id=tree["porfavor"].id)
    store.move_project(tree["portail"].id, space_id=tree["forellis"].id, parent_id=None)
    assert store.get_project(tree["porfavor"].id).space_id == tree["forellis"].id
    assert store.get_task(task.id).space_id == tree["forellis"].id
    assert store.get_entry(entry.id).space_id == tree["forellis"].id
    assert store.get_block(block.id).space_id == tree["forellis"].id


def test_a_subproject_cannot_leave_its_parent_space_alone(store, tree):
    with pytest.raises(InvalidOperationError):
        store.move_project(tree["porfavor"].id, space_id=tree["forellis"].id, parent_id=tree["portail"].id)


def test_project_links_keep_order_and_drop_duplicates(store, tree):
    store.set_project_links(tree["porfavor"].id, [("https://a", "A"), ("https://b", None), ("https://a", "dup")])
    assert store.project_links(tree["porfavor"].id) == [("https://a", "A"), ("https://b", None)]


# ---------------------------------------------------------------- tasks


def test_tasks_keep_manual_order_and_can_be_reordered(store, tree):
    pid = tree["dico"].id
    titles = ["1. Buchanan", "2. Dyche", "3. Dyche", "4. Newbery"]
    tasks = [store.create_task(t, project_id=pid) for t in titles]
    store.reorder_task(tasks[3].id, before=tasks[0].id)
    store.reorder_task(tasks[0].id, after=tasks[2].id)
    assert [t.title for t in store.tasks_for_project(pid)] == ["4. Newbery", "2. Dyche", "3. Dyche", "1. Buchanan"]


def test_reorder_survives_exhausted_gaps(store, tree):
    pid = tree["dico"].id
    a = store.create_task("a", project_id=pid)
    b = store.create_task("b", project_id=pid)
    for i in range(80):  # halve the gap between a and b far beyond float precision
        c = store.create_task(f"c{i}", project_id=pid)
        store.reorder_task(c.id, before=b.id)
        b = c
    order = [t.title for t in store.tasks_for_project(pid)]
    assert order[0] == "a" and order[-1] == "b" and len(order) == len(set(order)) == 82
    assert a.id == store.tasks_for_project(pid)[0].id


def test_reorder_rejects_rows_from_another_list(store, tree):
    t1 = store.create_task("ici", project_id=tree["dico"].id)
    t2 = store.create_task("ailleurs", project_id=tree["porfavor"].id)
    with pytest.raises(InvalidOperationError):
        store.reorder_task(t1.id, before=t2.id)


def test_waiting_needs_a_person_and_lists_by_person(store, tree):
    task = store.create_task("Articles déjà publiés", project_id=tree["porfavor"].id)
    with pytest.raises(InvalidOperationError):
        store.set_task_status(task.id, "waiting")
    ludivine = store.get_or_create_person("Thouverez Ludivine")
    store.set_task_status(task.id, "waiting", waiting_on=ludivine.id)
    with pytest.raises(NotFoundError):  # an id, never a name to create
        store.set_task_status(task.id, "waiting", waiting_on="Quelqu'un d'autre")
    assert [t.id for t in store.waiting_on(ludivine.id)] == [task.id]
    done = store.set_task_status(task.id, "done")
    assert done.done_at is not None and done.waiting_on is None
    assert store.waiting_on(ludivine.id) == []


def test_status_since_only_moves_when_status_changes(store, tree):
    task = store.create_task("3. Dyche", project_id=tree["dico"].id)
    first = store.set_task_status(task.id, "in_progress")
    again = store.set_task_status(task.id, "in_progress")
    assert again.status_since == first.status_since
    assert [t.id for t in store.in_progress_tasks()] == [task.id]


def test_in_progress_skips_sleeping_places_newest_first(store, tree):
    old = store.set_task_status(store.create_task("ancienne", project_id=tree["dico"].id).id, "in_progress")
    new = store.set_task_status(store.create_task("récente", space_id=tree["mimmoc"].id).id, "in_progress")
    asleep = store.set_task_status(store.create_task("dort", project_id=tree["porfavor"].id).id, "in_progress")
    ids = [t.id for t in store.in_progress_tasks()]
    assert set(ids) == {old.id, new.id, asleep.id} and ids.index(new.id) < ids.index(old.id)
    store.update_project(tree["portail"].id, state="dormant")  # the parent sleeps: its sub-project too
    store.update_project(tree["dico"].id, state="closed")
    assert [t.id for t in store.in_progress_tasks()] == [new.id]
    assert {t.id for t in store.open_tasks(living=True)} == {new.id}
    assert {old.id, new.id, asleep.id} <= {t.id for t in store.open_tasks()}
    store.set_space_archived(tree["mimmoc"].id, True)
    assert store.in_progress_tasks() == []


def test_steps_progress(store, tree):
    task = store.create_task("Site Por Favor", project_id=tree["porfavor"].id,
                             steps=["Métadonnées", "Migrer vers Quarto", "Relier les notices"])
    assert (task.steps_done, task.steps_total) == (0, 3)
    store.set_step_done(store.steps(task.id)[1].id, True)
    assert store.get_task(task.id).steps_done == 1


def test_space_level_tasks_and_space_consistency(store, tree):
    t = store.create_task("Note générale", space_id=tree["forellis"].id)
    assert t.project_id is None and store.tasks_for_space(tree["forellis"].id)[0].id == t.id
    with pytest.raises(InvalidOperationError):
        store.create_task("Incohérente", project_id=tree["dico"].id, space_id=tree["mimmoc"].id)


def test_invalid_due_date_rejected(store, tree):
    with pytest.raises(InvalidOperationError):
        store.create_task("x", project_id=tree["dico"].id, due_date="19/01/2026")


# ---------------------------------------------------------------- people and tags


def test_people_are_recognised_whatever_the_spelling(store):
    a = store.get_or_create_person("PEYROL-KLEIBER Elodie")
    b = store.get_or_create_person("Elodie Peyrol Kleiber")
    c = store.get_or_create_person("@peyrol kleiber élodie")
    assert a.id == b.id == c.id


def test_email_is_unique_across_people(store):
    a = store.get_or_create_person("Sophie Stokes")
    b = store.get_or_create_person("Anne Cousson")
    store.update_person(a.id, email="s.stokes@example.org")
    with pytest.raises(InvalidOperationError):
        store.update_person(b.id, email="S.Stokes@example.org")


def test_tags_case_insensitive_and_pinned_counts(store, tree):
    t1 = store.get_or_create_tag("#doctorant·es")
    t2 = store.get_or_create_tag("Doctorant·es")
    assert t1.id == t2.id
    maréva = store.get_or_create_person("Brunet Maréva")
    store.tag_person(maréva.id, ["doctorant·es"])
    store.create_entry(entry_date="2026-01-15", space_id=tree["forellis"].id, title="Café", tags=["doctorant·es"])
    store.set_tag_pinned(t1.id, True)
    [(tag, uses)] = store.pinned_tags()
    assert tag.name == "doctorant·es" and uses == 2


# ---------------------------------------------------------------- entries


def test_text_change_keeps_previous_version(store, tree):
    e = store.create_entry(entry_date="2026-10-15", project_id=tree["dico"].id, title="CR", body="v1")
    e2 = store.update_entry(e.id, body="v2", expected_revision=1)
    assert (e2.version, e2.revision) == (2, 2)
    e3 = store.update_entry(e.id, start_time="10:30")  # metadata only: no new text version
    assert (e3.version, e3.revision) == (2, 3)
    [old] = store.entry_versions(e.id)
    assert (old.version, old.body) == (1, "v1")
    # another device still holding revision 2 cannot overwrite the metadata change
    with pytest.raises(InvalidOperationError):
        store.update_entry(e.id, kind="meeting", expected_revision=2)


def test_decisions_can_be_applied_others_cannot(store, tree):
    d = store.create_entry(entry_date="2026-01-15", project_id=tree["porfavor"].id, kind="decision", title="Planif")
    assert d.decision_applied is False
    assert store.update_entry(d.id, decision_applied=True).decision_applied is True
    n = store.create_entry(entry_date="2026-01-15", project_id=tree["porfavor"].id, title="note")
    with pytest.raises(InvalidOperationError):
        store.update_entry(n.id, decision_applied=True)
    assert store.update_entry(d.id, kind="note").decision_applied is None


def test_timeline_filters(store, tree):
    pf = tree["porfavor"].id
    task = store.create_task("Site", project_id=pf)
    e1 = store.create_entry(entry_date="2026-01-13", project_id=pf, kind="meeting", title="Prise de contact",
                            start_time="10:30", people=["Thouverez Ludivine"])
    e2 = store.create_entry(entry_date="2026-01-26", task_id=task.id, title="Collection Maximo")
    e3 = store.create_entry(entry_date="2026-01-26", space_id=tree["forellis"].id, title="Ailleurs")
    ludivine = store.find_people("Ludivine Thouverez")[0]
    # project journal includes sub-projects
    assert [e.id for e in store.timeline(project_id=tree["portail"].id)] == [e2.id, e1.id]
    assert [e.id for e in store.timeline(person_id=ludivine.id)] == [e1.id]
    assert [e.id for e in store.timeline(task_id=task.id)] == [e2.id]
    assert {e.id for e in store.timeline(day="2026-01-26")} == {e2.id, e3.id}
    assert store.last_exchange(ludivine.id) == "2026-01-13"


def test_tag_page_includes_entries_of_tagged_people(store, tree):
    tag = store.get_or_create_tag("doctorant·es")
    lola = store.get_or_create_person("Geiger Lola")
    store.tag_person(lola.id, ["doctorant·es"])
    e = store.create_entry(entry_date="2026-01-19", space_id=tree["forellis"].id, title="Geiger Lola", person_ids=[lola.id])
    assert [x.id for x in store.timeline(tag_id=tag.id)] == [e.id]


def test_mail_message_id_is_unique(store, tree):
    store.create_entry(entry_date="2026-01-16", project_id=tree["porfavor"].id, source="mail", mail_message_id="<a@b>")
    assert store.entry_by_mail("<a@b>") is not None
    with pytest.raises(InvalidOperationError):
        store.create_entry(entry_date="2026-01-16", project_id=tree["porfavor"].id, mail_message_id="<a@b>")


def test_entry_task_must_belong_to_the_project(store, tree):
    task = store.create_task("ici", project_id=tree["dico"].id)
    with pytest.raises(InvalidOperationError):
        store.create_entry(entry_date="2026-01-16", project_id=tree["porfavor"].id, task_id=task.id)


# ---------------------------------------------------------------- search


def test_search_ignores_accents_and_matches_prefix(store, tree):
    e = store.create_entry(entry_date="2026-10-15", project_id=tree["dico"].id, title="Réunion",
                           body="Arborescence ShareDocs validée, métadonnées à définir")
    t = store.create_task("Définir les métadonnées pertinentes", project_id=tree["dico"].id)
    hits = store.search("metadonn")
    assert {(h.kind, h.id) for h in hits} == {("entry", e.id), ("task", t.id)}
    store.update_entry(e.id, body="autre chose")
    assert {h.kind for h in store.search("metadonnees")} == {"task"}


@pytest.mark.parametrize("query", ['"', "OR", "a AND", "NEAR(", "*", "title:x", ")"])
def test_search_is_safe_against_fts_syntax(store, tree, query):
    store.create_entry(entry_date="2026-10-15", project_id=tree["dico"].id, title="x", body="OR title near")
    store.search(query)  # must not raise


# ---------------------------------------------------------------- time


def test_counting_rules():
    a, b = at(9), at(10)
    shared = counted_seconds([Span("x", a, b), Span("y", a + timedelta(minutes=30), b)])
    assert shared == {"x": 45 * 60, "y": 15 * 60}
    both = counted_seconds([Span("x", a, b), Span("y", a, b, "both")])
    assert both == {"x": 3600, "y": 3600}
    excl = counted_seconds([Span("x", a, b), Span("y", a, b, "exclusive")])
    assert excl == {"x": 0, "y": 3600}
    assert presence_seconds([Span("x", a, b), Span("y", a + timedelta(minutes=30), at(11))]) == 2 * 3600
    with pytest.raises(ValueError):
        counted_seconds([Span("x", b, a)])


def test_day_report_matches_the_ma_journee_mockup(store, tree):
    """The day shown in the « Ma journée » mockup: 6 h 30 present, FoReLLIS 4 h 40, MIMMOC 1 h 50."""
    dico, pf = tree["dico"].id, tree["porfavor"].id
    photo = store.create_project(tree["forellis"].id, "Photo non reproductible", team="B").id
    b1 = store.add_block(at(8.75), at(10.25), project_id=dico, source="timer")
    b2 = store.add_block(at(9 + 35 / 60), at(10.25), project_id=pf, source="timer")
    b3 = store.add_block(at(10.5), at(12), space_id=tree["forellis"].id, source="agenda")
    b4 = store.add_block(at(13.5), at(15.5), project_id=pf, source="timer")
    b5 = store.add_block(at(14), at(15), project_id=dico, source="timer")
    b6 = store.add_block(at(15.75), at(17.25), project_id=photo)
    report = store.day_report(date(2026, 10, 15), PARIS)
    minutes = {c.block.id: c.counted_seconds // 60 for c in report.blocks}
    assert [minutes[b.id] for b in (b1, b2, b3, b4, b5, b6)] == [70, 20, 90, 90, 30, 90]
    assert report.presence_seconds == 390 * 60
    assert report.by_space[tree["forellis"].id] == 280 * 60
    assert report.by_space[tree["mimmoc"].id] == 110 * 60
    # « compter pour les deux » on the afternoon overlap
    store.update_block(b5.id, overlap_mode="both")
    report = store.day_report(date(2026, 10, 15), PARIS)
    minutes = {c.block.id: c.counted_seconds // 60 for c in report.blocks}
    assert (minutes[b4.id], minutes[b5.id]) == (120, 60)


def test_day_report_clips_at_local_midnight_and_counts_running_timers(store, tree):
    late = store.add_block(at(23), at(1, date(2026, 10, 16)), project_id=tree["dico"].id)
    report = store.day_report(date(2026, 10, 15), PARIS)
    assert report.blocks[0].block.id == late.id and report.blocks[0].counted_seconds == 3600
    running = store.start_timer(task_id=store.create_task("t", project_id=tree["dico"].id).id, at=at(9, date(2026, 10, 17)))
    assert store.running_timers()[0].id == running.id
    report = store.day_report(date(2026, 10, 17), PARIS, now=at(9.5, date(2026, 10, 17)))
    assert report.blocks[0].counted_seconds == 1800
    stopped = store.stop_timer(running.id, at=at(10, date(2026, 10, 17)))
    assert stopped.end_at is not None and store.running_timers() == []
    with pytest.raises(InvalidOperationError):
        store.stop_timer(running.id)


def test_validate_day_and_edits_reset_validation(store, tree):
    b = store.add_block(at(9), at(10), project_id=tree["dico"].id)
    assert store.validate_day(date(2026, 10, 15), PARIS) == 1
    assert store.get_block(b.id).validated
    assert not store.update_block(b.id, end=at(10.5)).validated


def test_naive_datetimes_rejected(store, tree):
    with pytest.raises(ValueError):
        store.add_block(datetime(2026, 10, 15, 9), datetime(2026, 10, 15, 10), project_id=tree["dico"].id)


# ---------------------------------------------------------------- staleness and errors


def test_stale_projects(store, tree):
    store.create_entry(entry_date="2026-01-29", project_id=tree["porfavor"].id, title="Travail")
    future = datetime.now(timezone.utc) + timedelta(days=40)
    stale = {p.name for p, _ in store.stale_projects(days=30, now=future)}
    assert {"POR FAVOR", "DICODIACHRO", "Portail des revues"} <= stale
    assert store.stale_projects(days=30) == []


def test_unknown_ids_raise_not_found(store):
    with pytest.raises(NotFoundError):
        store.get_task("nope")
    with pytest.raises(NotFoundError):
        store.create_project("nope", "x")


def test_failed_operation_leaves_nothing_behind(store, tree):
    before = store.conn.execute("SELECT count(*) FROM people").fetchone()[0]
    with pytest.raises(InvalidOperationError):
        store.create_entry(entry_date="2026-10-15", project_id=tree["dico"].id, people=["Nouvelle Personne"], tags=["#"])
    assert store.conn.execute("SELECT count(*) FROM people").fetchone()[0] == before


# ---------------------------------------------------------------- review follow-ups


def test_day_report_on_clock_change_days(store, tree):
    pid = tree["dico"].id
    store.add_block(datetime(2026, 10, 24, 23, tzinfo=PARIS), datetime(2026, 10, 25, 22, tzinfo=PARIS), project_id=pid)
    store.add_block(datetime(2026, 10, 25, 22, tzinfo=PARIS), datetime(2026, 10, 26, 2, tzinfo=PARIS), project_id=pid)
    report = store.day_report(date(2026, 10, 25), PARIS)  # 25-hour day
    assert report.presence_seconds == 25 * 3600
    assert sum(c.counted_seconds for c in report.blocks) == 25 * 3600
    store.add_block(datetime(2026, 3, 28, 23, tzinfo=PARIS), datetime(2026, 3, 29, 22, tzinfo=PARIS), project_id=pid)
    store.add_block(datetime(2026, 3, 29, 22, tzinfo=PARIS), datetime(2026, 3, 30, 1, tzinfo=PARIS), project_id=pid)
    assert store.day_report(date(2026, 3, 29), PARIS).presence_seconds == 23 * 3600
    spans = [Span("x", datetime(2026, 10, 25, 0, tzinfo=PARIS), datetime(2026, 10, 26, 0, tzinfo=PARIS))]
    assert counted_seconds(spans) == {"x": 25 * 3600}


def test_threads_never_share_a_transaction(store, tree):
    """A failing operation in one thread must not roll back another thread's write."""
    barrier = threading.Barrier(2)
    results: dict[str, object] = {}

    def failing():
        try:
            with store._tx():
                store.conn.execute("INSERT INTO spaces(id, name, created_at) VALUES ('a', 'A', 'x')")
                barrier.wait(timeout=5)
                raise RuntimeError("boom")
        except RuntimeError:
            results["a"] = "rolled back"

    def writer():
        barrier.wait(timeout=5)
        results["b"] = store.create_space("B").id

    threads = [threading.Thread(target=failing), threading.Thread(target=writer)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=20)
    names = {s.name for s in store.list_spaces()}
    assert "B" in names and "A" not in names


def test_nested_failure_is_rolled_back_to_its_savepoint(store, tree):
    with store._tx():
        store.create_space("Gardé")
        with pytest.raises(InvalidOperationError):
            store.create_task("Sans place")  # nested operation fails: no project, no space
        with pytest.raises(InvalidOperationError):
            store.get_or_create_person("-")
    assert "Gardé" in {s.name for s in store.list_spaces()}


def test_accented_tags_are_case_insensitive(store):
    a = store.get_or_create_tag("Été")
    b = store.get_or_create_tag("été")
    c = store.get_or_create_tag("été")  # decomposed accents
    d = store.get_or_create_tag("ete")
    assert a.id == b.id == c.id and d.id != a.id


@pytest.mark.parametrize("call", [
    lambda s, t: s.create_space("  "),
    lambda s, t: s.rename_space(t["forellis"].id, ""),
    lambda s, t: s.create_project(t["forellis"].id, " "),
    lambda s, t: s.create_task(" ", project_id=t["dico"].id),
    lambda s, t: s.add_step(s.create_task("x", project_id=t["dico"].id).id, " "),
    lambda s, t: s.get_or_create_person("- '"),
    lambda s, t: s.get_or_create_tag("#"),
])
def test_empty_names_raise_invalid_operation(store, tree, call):
    with pytest.raises(InvalidOperationError):
        call(store, tree)


def test_done_again_keeps_completion_date(store, tree):
    task = store.create_task("x", project_id=tree["dico"].id)
    first = store.set_task_status(task.id, "done")
    assert store.set_task_status(task.id, "done").done_at == first.done_at


def test_waiting_task_always_has_a_person_in_the_database(store, tree):
    task = store.create_task("x", project_id=tree["dico"].id)
    with pytest.raises(sqlite3.IntegrityError):
        store.conn.execute("UPDATE tasks SET status = 'waiting' WHERE id = ?", (task.id,))


def test_moving_a_task_takes_its_thread_and_time(store, tree):
    task = store.create_task("Site", project_id=tree["dico"].id)
    entry = store.create_entry(entry_date="2026-01-26", task_id=task.id, title="avancée")
    block = store.add_block(at(9), at(10), task_id=task.id)
    store.move_task(task.id, project_id=tree["porfavor"].id)
    assert store.get_entry(entry.id).project_id == tree["porfavor"].id
    assert store.get_block(block.id).project_id == tree["porfavor"].id
    assert store.get_block(block.id).space_id == tree["mimmoc"].id
    pos = store.get_task(task.id).position
    assert store.move_task(task.id, project_id=tree["porfavor"].id).position == pos  # same place: unchanged


def test_moving_a_parent_carries_rows_attached_to_its_subprojects(store, tree):
    task = store.create_task("t", project_id=tree["porfavor"].id)
    parent_task = store.create_task("p", project_id=tree["portail"].id)
    store.move_project(tree["portail"].id, space_id=tree["forellis"].id, parent_id=None)
    assert store.get_task(task.id).space_id == tree["forellis"].id
    assert store.get_task(parent_task.id).space_id == tree["forellis"].id


def test_unknown_person_ids_are_refused_not_created(store, tree):
    before = len(store.list_people())
    with pytest.raises(NotFoundError):
        store.create_entry(entry_date="2026-01-01", project_id=tree["dico"].id, person_ids=["deadbeef"])
    assert len(store.list_people()) == before


def test_fts_index_stays_consistent(store, tree):
    e = store.create_entry(entry_date="2026-10-15", project_id=tree["dico"].id, title="Réunion", body="métadonnées")
    t = store.create_task("Métadonnées", project_id=tree["dico"].id)
    store.update_entry(e.id, body="autre")
    store.update_task(t.id, note="notes")
    store.conn.execute("DELETE FROM entries WHERE id = ?", (e.id,))
    store.conn.execute("INSERT INTO entries_fts(entries_fts) VALUES ('integrity-check')")
    store.conn.execute("INSERT INTO tasks_fts(tasks_fts) VALUES ('integrity-check')")
    store.conn.execute("VACUUM")
    assert [h.id for h in store.search("metadonnees")] == [t.id]


def test_search_snippet_from_title_and_done_tasks_hidden(store, tree):
    t = store.create_task("Zotero pour Maréva", project_id=tree["dico"].id)
    [hit] = store.search("zotero")
    assert "[Zotero]" in hit.snippet
    store.set_task_status(t.id, "done")
    assert store.search("zotero") == []
    assert len(store.search("zotero", include_done_tasks=True)) == 1


def test_reorder_spaces_and_steps(store, tree):
    task = store.create_task("t", project_id=tree["dico"].id, steps=["a", "b", "c"])
    a, b, c = store.steps(task.id)
    store.reorder_step(c.id, before=a.id)
    assert [x.label for x in store.steps(task.id)] == ["c", "a", "b"]
    perso = store.create_space("Perso")
    store.move_space(perso.id, before=tree["forellis"].id)
    assert store.list_spaces()[0].name == "Perso"


def test_long_running_timer_is_capped_and_flagged(store, tree):
    t = store.start_timer(project_id=tree["dico"].id, at=at(8, date(2026, 10, 20)))
    report = store.day_report(date(2026, 10, 21), PARIS, now=at(12, date(2026, 10, 21)))
    assert [b.id for b in report.stale_timers] == [t.id]
    assert report.blocks == []  # capped at 16 h: ended 20 Oct at midnight
    with pytest.raises(InvalidOperationError):
        store.add_block(at(8), at(9, date(2026, 10, 17)), project_id=tree["dico"].id)  # > 24 h


def test_naive_datetimes_rejected_before_comparisons(store, tree):
    t = store.start_timer(project_id=tree["dico"].id, at=at(8))
    with pytest.raises(ValueError):
        store.stop_timer(t.id, at=datetime(2026, 10, 15, 9))
    with pytest.raises(ValueError):
        store.start_timer(project_id=tree["dico"].id, at=datetime(2026, 10, 15, 9))


def test_migration_splitter_handles_comments_and_one_line_statements():
    from pige.model.db import _statements

    assert _statements("CREATE TABLE a(x); CREATE TABLE b(y);\n-- trailing comment\n") == [
        "CREATE TABLE a(x);", "CREATE TABLE b(y);",
    ]
    with pytest.raises(ValueError):
        _statements("CREATE TABLE c(")


def test_stale_projects_see_activity_in_subprojects(store, tree):
    future = datetime.now(timezone.utc) + timedelta(days=40)
    store.create_entry(entry_date="2026-10-15", project_id=tree["porfavor"].id, title="récent")
    stale = {p.name for p, _ in store.stale_projects(days=30, now=future - timedelta(days=20))}
    assert "Portail des revues" not in stale


# ---------------------------------------------------------------- API follow-ups


def test_failed_commit_leaves_the_connection_usable(tmp_path):
    store = ModelStore(tmp_path / "db.sqlite3")  # no WAL: a reader blocks the commit
    store.conn.execute("PRAGMA busy_timeout = 100")
    reader = sqlite3.connect(tmp_path / "db.sqlite3")
    reader.execute("BEGIN")
    reader.execute("SELECT count(*) FROM spaces").fetchone()  # holds a shared lock
    with pytest.raises(sqlite3.OperationalError):
        store.create_space("Bloquée")
    assert not store.conn.in_transaction
    reader.rollback()
    reader.close()
    assert store.create_space("Ensuite").name == "Ensuite"
    assert [s.name for s in store.list_spaces()] == ["Ensuite"]
    store.close()


def test_deletes_refuse_non_empty_containers_and_detach_history(store, tree):
    task = store.create_task("t", project_id=tree["dico"].id, steps=["a"])
    entry = store.create_entry(entry_date="2026-10-15", task_id=task.id, title="fil")
    block = store.add_block(at(9), at(10), task_id=task.id)
    with pytest.raises(InvalidOperationError):
        store.delete_project(tree["dico"].id)
    store.delete_task(task.id)
    assert store.get_entry(entry.id).task_id is None
    assert store.get_block(block.id).task_id is None
    person = store.get_or_create_person("Quelqu'un")
    waiting = store.create_task("w", project_id=tree["porfavor"].id)
    store.set_task_status(waiting.id, "waiting", waiting_on=person.id)
    with pytest.raises(InvalidOperationError):
        store.delete_person(person.id)
    store.delete_entry(entry.id)
    store.delete_block(block.id)
    store.delete_project(tree["dico"].id)
    with pytest.raises(NotFoundError):
        store.get_project(tree["dico"].id)


def test_counts_and_timeline_paging(store, tree):
    pid = tree["dico"].id
    store.create_task("a", project_id=pid)
    done = store.create_task("b", project_id=pid)
    store.set_task_status(done.id, "done")
    assert store.open_task_counts() == {pid: 1} and store.open_task_count(pid) == 1
    for d in ("2026-01-01", "2026-01-02", "2026-01-03"):
        store.create_entry(entry_date=d, project_id=pid, title=d)
    assert [e.title for e in store.timeline(project_id=pid, limit=2, offset=1)] == ["2026-01-02", "2026-01-01"]


def test_autosave_keeps_versions_only_after_a_pause_or_every_quarter_hour(store, tree, monkeypatch):
    import pige.model.store as model_store
    from datetime import datetime, timedelta, timezone

    clock = [datetime(2026, 10, 18, 9, 0, tzinfo=timezone.utc)]
    monkeypatch.setattr(model_store, "_now", lambda: clock[0])

    def at(minutes: float) -> None:
        clock[0] = datetime(2026, 10, 18, 9, 0, tzinfo=timezone.utc) + timedelta(minutes=minutes)

    e = store.create_entry(entry_date="2026-10-18", project_id=tree["dico"].id, body="v1", source="writing")
    for i, minute in enumerate([0.5, 1, 1.5, 2], start=2):  # typing on: replaced, no version
        at(minute)
        e = store.update_entry(e.id, body=f"v{i}", autosave=True, expected_revision=e.revision)
    assert store.entry_versions(e.id) == [] and e.body == "v5"
    at(8)  # after a pause of more than 5 minutes: the text before the pause is kept
    e = store.update_entry(e.id, body="v6", autosave=True, expected_revision=e.revision)
    assert [v.body for v in store.entry_versions(e.id)] == ["v5"]
    for minute in range(9, 17):  # typing on: still one version (kept text dates from 9:02)
        at(minute)
        e = store.update_entry(e.id, body=f"w{minute}", autosave=True, expected_revision=e.revision)
    assert len(store.entry_versions(e.id)) == 1
    at(17.5)  # 15 minutes after the kept text: one more, even without a pause
    e = store.update_entry(e.id, body="x", autosave=True, expected_revision=e.revision)
    assert [v.body for v in store.entry_versions(e.id)] == ["w16", "v5"]
    at(24)  # an explicit save always keeps a version
    e = store.update_entry(e.id, body="y", expected_revision=e.revision)
    assert store.entry_versions(e.id)[0].body == "x"


def test_timeline_filters_by_source(store, tree):
    store.create_entry(entry_date="2026-10-18", project_id=tree["dico"].id, body="note", source="journal")
    long = store.create_entry(entry_date="2026-10-18", project_id=tree["dico"].id, title="CR", source="writing")
    assert [e.id for e in store.timeline(source="writing")] == [long.id]
