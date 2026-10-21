"""HTTP tests of the /api/v2 routes (new model)."""

from __future__ import annotations

import pytest

fastapi = pytest.importorskip("fastapi")

from fastapi.testclient import TestClient  # noqa: E402

from pige.server.app import CSRF_HEADER, create_app  # noqa: E402
from pige.server.auth import hash_password, new_api_token  # noqa: E402
from pige.server.config import ConfigError, Settings  # noqa: E402

PASSWORD = "correct horse battery staple"
_HASH = hash_password(PASSWORD)
_TOKEN, _TOKEN_HASH = new_api_token()


@pytest.fixture()
def client(tmp_path):
    settings = Settings(
        data_dir=tmp_path,
        password_hash=_HASH,
        session_secret="s" * 48,
        api_token_hashes=frozenset({_TOKEN_HASH}),
        cookie_secure=False, background_jobs=False,
    )
    with TestClient(create_app(settings)) as c:
        c.headers.update({"Authorization": f"Bearer {_TOKEN}"})
        yield c


def ok(response, code=200):
    assert response.status_code == code, response.text
    return response.json() if response.content else None


@pytest.fixture()
def tree(client):
    forellis = ok(client.post("/api/v2/spaces", json={"name": "FoReLLIS"}), 201)
    mimmoc = ok(client.post("/api/v2/spaces", json={"name": "MIMMOC"}), 201)
    dico = ok(client.post("/api/v2/projects", json={"space_id": forellis["id"], "name": "DICODIACHRO", "team": "A"}), 201)
    portail = ok(client.post("/api/v2/projects", json={"space_id": mimmoc["id"], "name": "Portail des revues"}), 201)
    porfavor = ok(client.post("/api/v2/projects", json={
        "space_id": mimmoc["id"], "name": "POR FAVOR", "parent_id": portail["id"]}), 201)
    return {"forellis": forellis, "mimmoc": mimmoc, "dico": dico, "portail": portail, "porfavor": porfavor}


def test_v2_requires_auth_and_csrf_for_cookie_writes(client):
    anonymous = TestClient(client.app)
    assert anonymous.get("/api/v2/tree").status_code == 401
    ok(anonymous.post("/api/login", json={"password": PASSWORD}))
    assert anonymous.get("/api/v2/tree").status_code == 200
    assert anonymous.post("/api/v2/spaces", json={"name": "x"}).status_code == 403
    assert anonymous.post("/api/v2/spaces", json={"name": "x"}, headers={CSRF_HEADER: "web"}).status_code == 201


def test_tree_lists_spaces_projects_counts_and_pinned_tags(client, tree):
    ok(client.post("/api/v2/tasks", json={"title": "4. Newbery", "project_id": tree["dico"]["id"],
                                           "tags": ["PPrim"]}), 201)
    data = ok(client.get("/api/v2/tree"))
    assert [s["name"] for s in data["spaces"]] == ["FoReLLIS", "MIMMOC"]
    assert [p["name"] for p in data["spaces"][1]["projects"]] == ["Portail des revues", "POR FAVOR"]
    assert data["spaces"][0]["projects"][0]["open_tasks"] == 1
    assert data["pinned_tags"] == []


def test_task_lifecycle_with_steps_order_and_waiting(client, tree):
    pid = tree["porfavor"]["id"]
    t1 = ok(client.post("/api/v2/tasks", json={"title": "Inventaire", "project_id": pid}), 201)
    t2 = ok(client.post("/api/v2/tasks", json={"title": "Site", "project_id": pid,
                                                "steps": ["Métadonnées", "Quarto"]}), 201)
    assert [s["label"] for s in t2["steps"]] == ["Métadonnées", "Quarto"]
    ok(client.post(f"/api/v2/tasks/{t2['id']}/place", json={"before": t1["id"]}), 204)
    assert [t["title"] for t in ok(client.get(f"/api/v2/projects/{pid}/tasks"))] == ["Site", "Inventaire"]
    ok(client.patch(f"/api/v2/steps/{t2['steps'][0]['id']}", json={"done": True}))
    assert ok(client.get(f"/api/v2/tasks/{t2['id']}"))["steps_done"] == 1
    person = ok(client.post("/api/v2/people", json={"name": "Thouverez Ludivine"}), 201)
    again = ok(client.post("/api/v2/people", json={"name": "Ludivine THOUVEREZ"}))
    assert again["id"] == person["id"]
    waiting = ok(client.patch(f"/api/v2/tasks/{t1['id']}", json={"status": "waiting", "waiting_on": person["id"]}))
    assert waiting["waiting_on"] == person["id"]
    fiche = ok(client.get(f"/api/v2/people/{person['id']}"))
    assert [t["id"] for t in fiche["waiting_on"]] == [t1["id"]]
    assert client.patch(f"/api/v2/tasks/{t1['id']}", json={"status": "waiting"}).status_code == 400
    assert client.patch(f"/api/v2/tasks/{t1['id']}", json={"waiting_on": person["id"]}).status_code == 400
    cleared = ok(client.patch(f"/api/v2/tasks/{t2['id']}", json={"due_date": "2026-11-03"}))
    assert cleared["due_date"] == "2026-11-03"
    assert ok(client.patch(f"/api/v2/tasks/{t2['id']}", json={"due_date": ""}))["due_date"] is None


def test_entry_editing_with_revisions_and_conflicts(client, tree):
    pid = tree["porfavor"]["id"]
    e = ok(client.post("/api/v2/entries", json={
        "entry_date": "2026-10-15", "project_id": pid, "kind": "meeting", "title": "Équipe B",
        "body": "v1", "start_time": "10:30", "end_time": "12:00", "people": ["Guilbard Anne-Cécile"],
        "tags": ["PPrim"]}), 201)
    assert [p["display_name"] for p in e["people"]] == ["Guilbard Anne-Cécile"]
    e2 = ok(client.patch(f"/api/v2/entries/{e['id']}", json={"expected_revision": e["revision"], "body": "v2"}))
    assert (e2["version"], e2["revision"]) == (2, 2)
    stale = client.patch(f"/api/v2/entries/{e['id']}", json={"expected_revision": 1, "kind": "note"})
    assert stale.status_code == 409
    assert client.patch(f"/api/v2/entries/{e['id']}", json={"body": "no revision"}).status_code == 422
    versions = ok(client.get(f"/api/v2/entries/{e['id']}/versions"))
    assert [v["body"] for v in versions] == ["v1"]
    cleared = ok(client.patch(f"/api/v2/entries/{e['id']}", json={"expected_revision": 2, "start_time": ""}))
    assert cleared["start_time"] is None


def test_mail_entries_are_idempotent(client, tree):
    body = {"entry_date": "2026-01-16", "project_id": tree["porfavor"]["id"], "source": "mail",
            "mail_message_id": "<abc@univ>", "title": "Re: chantiers"}
    first = ok(client.post("/api/v2/entries", json=body), 201)
    second = ok(client.post("/api/v2/entries", json=body), 200)
    assert first["id"] == second["id"]


def test_mail_filed_again_brings_its_full_text(client, tree):
    """An entry from the old extension (short excerpt) is completed by a newer one; edited text is kept."""
    short = {"id": "a" * 32, "entry_date": "2026-01-16", "space_id": tree["porfavor"]["space_id"], "source": "mail",
             "mail_message_id": "<long@univ>", "title": "Devis", "body": "Mail de Anne\n\nBonjour, voici…"}
    first = ok(client.post("/api/v2/entries", json=short), 201)
    full = "Mail de Anne\n\nBonjour, voici le devis complet.\n\nPièces jointes : devis.pdf (12 Ko)"
    again = ok(client.post("/api/v2/entries", json={**short, "body": full}), 200)
    assert again["id"] == first["id"] and again["body"] == full
    ok(client.patch(f"/api/v2/entries/{first['id']}", json={"expected_revision": again["revision"],
                                                               "body": "Mes notes à moi"}))
    kept = ok(client.post("/api/v2/entries", json={**short, "id": "b" * 32, "body": full + " encore"}), 200)
    assert kept["body"] == "Mes notes à moi"
    shorter = ok(client.post("/api/v2/entries", json={**short, "mail_message_id": "<x@y>", "id": "f" * 32}), 201)
    assert ok(client.post("/api/v2/entries", json={**short, "mail_message_id": "<x@y>", "id": "f" * 32,
                                                     "body": "Mail de Anne"}), 200)["body"] == shorter["body"]


def test_timeline_filters_and_paging(client, tree):
    pid = tree["porfavor"]["id"]
    for day in ("2026-01-13", "2026-01-23", "2026-01-29"):
        ok(client.post("/api/v2/entries", json={"entry_date": day, "project_id": pid, "title": day}), 201)
    page1 = ok(client.get(f"/api/v2/timeline?project_id={tree['portail']['id']}&limit=2"))
    page2 = ok(client.get(f"/api/v2/timeline?project_id={tree['portail']['id']}&limit=2&offset=2"))
    assert [e["title"] for e in page1 + page2] == ["2026-01-29", "2026-01-23", "2026-01-13"]
    assert [e["title"] for e in ok(client.get("/api/v2/timeline?day=2026-01-23"))] == ["2026-01-23"]
    space = tree["porfavor"]["space_id"]
    ok(client.post("/api/v2/entries", json={"entry_date": "2026-01-24", "space_id": space, "title": "hors projet"}), 201)
    loose = ok(client.get(f"/api/v2/timeline?space_id={space}&without_project=true"))
    assert [e["title"] for e in loose] == ["hors projet"]


def test_time_day_report_and_timers(client, tree):
    dico = tree["dico"]["id"]
    ok(client.post("/api/v2/blocks", json={"start": "2026-10-15T08:45:00+02:00", "end": "2026-10-15T10:15:00+02:00",
                                            "project_id": dico}), 201)
    b2 = ok(client.post("/api/v2/blocks", json={"start": "2026-10-15T09:35:00+02:00",
                                                 "end": "2026-10-15T10:15:00+02:00",
                                                 "project_id": tree["porfavor"]["id"]}), 201)
    report = ok(client.get("/api/v2/days/2026-10-15"))
    assert report["presence_seconds"] == 90 * 60
    assert sorted(b["counted_seconds"] // 60 for b in report["blocks"]) == [20, 70]
    ok(client.patch(f"/api/v2/blocks/{b2['id']}", json={"overlap_mode": "both"}))
    report = ok(client.get("/api/v2/days/2026-10-15?tz=Europe/Paris"))
    assert sorted(b["counted_seconds"] // 60 for b in report["blocks"]) == [40, 90]
    assert client.get("/api/v2/days/2026-10-15?tz=Mars/Olympus").status_code == 400
    assert client.post("/api/v2/blocks", json={"start": "2026-10-15T08:00:00", "end": "2026-10-15T09:00:00",
                                                "project_id": dico}).status_code == 400  # no time zone
    timer = ok(client.post("/api/v2/timers", json={"project_id": dico}), 201)
    assert [t["id"] for t in ok(client.get("/api/v2/timers"))] == [timer["id"]]
    stopped = ok(client.post(f"/api/v2/timers/{timer['id']}/stop", json={}))
    assert stopped["end_at"] is not None
    assert ok(client.post("/api/v2/days/2026-10-15/validate"))["validated"] == 2


def test_errors_map_to_http_codes(client, tree):
    assert client.get("/api/v2/tasks/" + "0" * 32).status_code == 404
    assert client.post("/api/v2/projects", json={
        "space_id": tree["mimmoc"]["id"], "name": "Trop profond", "parent_id": tree["porfavor"]["id"]}).status_code == 400
    web = TestClient(client.app, headers={CSRF_HEADER: "web"})
    ok(web.post("/api/login", json={"password": PASSWORD}))
    assert web.delete(f"/api/v2/projects/{tree['portail']['id']}").status_code == 409  # has a sub-project
    assert web.delete(f"/api/v2/projects/{tree['porfavor']['id']}").status_code == 204
    assert client.post("/api/v2/spaces", json={"name": "x", "extra": 1}).status_code == 422
    assert client.post("/api/v2/projects/" + tree["dico"]["id"] + "/place", json={}).status_code == 400


def test_people_tags_and_pinning(client, tree):
    p = ok(client.post("/api/v2/people", json={"name": "Brunet Maréva"}), 201)
    fiche = ok(client.patch(f"/api/v2/people/{p['id']}", json={"tags": ["doctorant·es"], "email": "m.b@univ.fr"}))
    tag_id = fiche["tags"][0]["id"]
    ok(client.patch(f"/api/v2/tags/{tag_id}", json={"pinned": True}))
    pinned = ok(client.get("/api/v2/tree"))["pinned_tags"]
    assert pinned[0]["name"] == "doctorant·es" and pinned[0]["uses"] == 1
    assert [x["id"] for x in ok(client.get(f"/api/v2/people?tag_id={tag_id}"))] == [p["id"]]


def test_tag_list_and_tag_page(client, tree):
    p = ok(client.post("/api/v2/people", json={"name": "Brunet Maréva"}), 201)
    ok(client.patch(f"/api/v2/people/{p['id']}", json={"tags": ["doctorant·es"]}))
    task = ok(client.post("/api/v2/tasks", json={
        "title": "Relire", "project_id": tree["dico"]["id"], "tags": ["doctorant·es", "Urgent"]}), 201)
    done = ok(client.post("/api/v2/tasks", json={"title": "Fait", "project_id": tree["dico"]["id"], "tags": ["Urgent"]}), 201)
    ok(client.patch(f"/api/v2/tasks/{done['id']}", json={"status": "done"}))
    tags = ok(client.get("/api/v2/tags"))
    by_name = {t["name"]: t for t in tags}
    assert by_name["doctorant·es"]["uses"] == 2 and by_name["Urgent"]["uses"] == 1  # done tasks are not counted
    ok(client.patch(f"/api/v2/tags/{by_name['Urgent']['id']}", json={"pinned": True}))
    assert ok(client.get("/api/v2/tags"))[0]["name"] == "Urgent"  # pinned first
    page = ok(client.get(f"/api/v2/tags/{by_name['doctorant·es']['id']}"))
    assert [x["id"] for x in page["people"]] == [p["id"]]
    assert [x["id"] for x in page["tasks"]] == [task["id"]]
    assert client.get("/api/v2/tags/" + "0" * 32).status_code == 404


def test_search_endpoint(client, tree):
    ok(client.post("/api/v2/tasks", json={"title": "Définir les métadonnées", "project_id": tree["dico"]["id"]}), 201)
    hits = ok(client.get("/api/v2/search?q=metadonnees"))
    assert hits[0]["kind"] == "task"
    assert hits[0]["project_id"] == tree["dico"]["id"] and hits[0]["status"] == "open"
    ok(client.post("/api/v2/entries", json={
        "entry_date": "2026-03-12", "project_id": tree["dico"]["id"], "body": "Réunion sur les métadonnées"}), 201)
    entry = next(h for h in ok(client.get("/api/v2/search?q=metadonnees")) if h["kind"] == "entry")
    assert entry["entry_date"] == "2026-03-12"
    assert client.get("/api/v2/search?q=").status_code == 422


def test_legacy_poc_routes_still_work(client):
    created = ok(client.post("/api/tasks", json={"title": "Depuis Thunderbird"}), 201)
    assert created["title"] == "Depuis Thunderbird"


def test_timezone_setting_is_validated():
    base = {"PIGE_DATA_DIR": "/tmp/x", "PIGE_PASSWORD_HASH": _HASH, "PIGE_SESSION_SECRET": "s" * 48}
    assert Settings.from_env(base).timezone == "Europe/Paris"
    with pytest.raises(ConfigError):
        Settings.from_env({**base, "PIGE_TIMEZONE": "Nowhere/Land"})



# ---------------------------------------------------------------- review follow-ups


def test_tokens_cannot_delete_but_the_web_app_can(client, tree):
    pid = tree["dico"]["id"]
    task = ok(client.post("/api/v2/tasks", json={"title": "x", "project_id": pid}), 201)
    assert client.delete(f"/api/v2/tasks/{task['id']}").status_code == 403
    web = TestClient(client.app)
    ok(web.post("/api/login", json={"password": PASSWORD}))
    assert web.delete(f"/api/v2/tasks/{task['id']}").status_code == 403  # cookie without the client header
    assert web.patch(f"/api/v2/tasks/{task['id']}", json={"title": "y"}).status_code == 403
    assert web.delete(f"/api/v2/tasks/{task['id']}", headers={CSRF_HEADER: "web"}).status_code == 204


def test_task_view_includes_people_and_tags_and_space_tasks(client, tree):
    t = ok(client.post("/api/v2/tasks", json={"title": "Zotero", "space_id": tree["forellis"]["id"],
                                               "people": ["Brunet Maréva"], "tags": ["doctorant·es"]}), 201)
    assert [p["display_name"] for p in t["people"]] == ["Brunet Maréva"]
    assert [x["name"] for x in t["tags"]] == ["doctorant·es"]
    assert [x["id"] for x in ok(client.get(f"/api/v2/spaces/{tree['forellis']['id']}/tasks"))] == [t["id"]]


def test_archived_spaces_and_closed_projects_can_be_found_again(client, tree):
    ok(client.patch(f"/api/v2/spaces/{tree['mimmoc']['id']}", json={"archived": True}))
    ok(client.patch(f"/api/v2/projects/{tree['dico']['id']}", json={"state": "closed"}))
    plain = ok(client.get("/api/v2/tree"))
    assert [s["name"] for s in plain["spaces"]] == ["FoReLLIS"] and plain["spaces"][0]["projects"] == []
    full = ok(client.get("/api/v2/tree?include_archived=true"))
    assert [s["name"] for s in full["spaces"]] == ["FoReLLIS", "MIMMOC"]
    assert full["spaces"][0]["projects"][0]["state"] == "closed"


def test_people_or_tags_change_bumps_the_revision(client, tree):
    e = ok(client.post("/api/v2/entries", json={"entry_date": "2026-10-15", "project_id": tree["dico"]["id"]}), 201)
    first = ok(client.patch(f"/api/v2/entries/{e['id']}", json={"expected_revision": 1, "tags": ["PPrim"]}))
    assert first["revision"] == 2
    assert client.patch(f"/api/v2/entries/{e['id']}", json={"expected_revision": 1, "tags": ["HCERES"]}).status_code == 409


def test_null_clears_optional_fields_and_is_refused_for_required_ones(client, tree):
    pid = tree["dico"]["id"]
    t = ok(client.post("/api/v2/tasks", json={"title": "x", "project_id": pid, "note": "n", "due_date": "2026-11-03"}), 201)
    t = ok(client.patch(f"/api/v2/tasks/{t['id']}", json={"note": None, "due_date": None}))
    assert t["note"] is None and t["due_date"] is None
    assert client.patch(f"/api/v2/tasks/{t['id']}", json={"title": None}).status_code == 400
    proj = ok(client.patch(f"/api/v2/projects/{pid}", json={"team": None}))
    assert proj["team"] is None
    e = ok(client.post("/api/v2/entries", json={"entry_date": "2026-10-15", "project_id": pid, "start_time": "10:00"}), 201)
    e = ok(client.patch(f"/api/v2/entries/{e['id']}", json={"expected_revision": 1, "start_time": None}))
    assert e["start_time"] is None


def test_block_patch_keeps_unsent_attachments(client, tree):
    pid = tree["dico"]["id"]
    task = ok(client.post("/api/v2/tasks", json={"title": "t", "project_id": pid}), 201)
    b = ok(client.post("/api/v2/blocks", json={"start": "2026-10-15T09:00:00+02:00", "end": "2026-10-15T10:00:00+02:00",
                                                "task_id": task["id"]}), 201)
    b = ok(client.patch(f"/api/v2/blocks/{b['id']}", json={"note": "relu"}))
    assert b["task_id"] == task["id"]
    b = ok(client.patch(f"/api/v2/blocks/{b['id']}", json={"project_id": pid}))
    assert b["task_id"] == task["id"] and b["project_id"] == pid
    assert b["start_at"].endswith("Z")


def test_bad_inputs_are_4xx_not_500(client, tree):
    pid = tree["dico"]["id"]
    assert client.get("/api/v2/days/9999-12-31").status_code == 400
    assert client.post("/api/v2/days/0001-01-01/validate").status_code == 400
    assert client.post("/api/v2/timers", json={"project_id": pid, "at": "0001-01-01T00:00:00+05:00"}).status_code == 400
    assert client.post("/api/v2/tasks", json={"title": "x", "project_id": pid,
                                               "origin_entry_id": "0" * 32}).status_code == 404
    assert client.post("/api/v2/tasks", json={"title": "x", "project_id": pid, "tags": ["t" * 1000]}).status_code == 422
    links = [{"url": f"https://x/{i}"} for i in range(51)]
    assert client.put(f"/api/v2/projects/{pid}/links", json=links).status_code == 422
    assert client.get("/api/v2/tasks/not-an-id").status_code == 422
    detail = client.get("/api/v2/tasks/" + "0" * 32).json()["detail"]
    assert "0000" not in detail


def test_find_or_create_person_status_and_view(client):
    created = client.post("/api/v2/people", json={"name": "Bob Martin"})
    assert created.status_code == 201
    again = client.post("/api/v2/people", json={"name": "@martin bob"})
    assert again.status_code == 200 and again.json()["id"] == created.json()["id"]
    assert "waiting_on" in again.json()


def test_journal_days(client, tree):
    for d in ("2026-10-01", "2026-10-15", "2026-10-15", "2026-11-02"):
        ok(client.post("/api/v2/entries", json={"entry_date": d, "project_id": tree["dico"]["id"]}), 201)
    assert ok(client.get("/api/v2/journal/days?month=2026-10")) == ["2026-10-01", "2026-10-15"]
    assert client.get("/api/v2/journal/days?month=octobre").status_code == 422


def test_interface_routes_fall_back_to_the_app_shell(tmp_path):
    web = tmp_path / "web"
    web.mkdir()
    (web / "index.html").write_text("<p>accueil</p>")
    (web / "200.html").write_text("<p>appli</p>")
    (web / "app.js").write_text("ok")
    settings = Settings(data_dir=tmp_path, password_hash=_HASH, session_secret="s" * 48,
                        api_token_hashes=frozenset(), cookie_secure=False, web_dir=web, background_jobs=False)
    with TestClient(create_app(settings)) as c:
        assert c.get("/").text == "<p>accueil</p>"
        page = c.get("/journal/2026-10-15")
        assert page.status_code == 200 and page.text == "<p>appli</p>"
        assert page.headers["cache-control"] == "no-cache"
        assert c.get("/missing.js").status_code == 404
        assert c.get("/app.js").text == "ok"
        assert c.get("/api/nope").status_code == 404
        assert c.get("/api").status_code == 404
        assert c.head("/api/v2/tree").status_code == 404  # never the HTML shell, never data
        assert c.head("/api/nope").status_code == 404
        assert c.get("/_app/immutable/missing").status_code == 404


def test_device_chosen_ids_make_resends_harmless(client, tree):
    eid, tid = "a" * 32, "b" * 32
    body = {"id": eid, "entry_date": "2026-10-18", "project_id": tree["dico"]["id"], "body": "Noté hors ligne"}
    first = ok(client.post("/api/v2/entries", json=body), 201)
    again = ok(client.post("/api/v2/entries", json=body), 200)  # the reply was lost: same entry
    assert first["id"] == again["id"] == eid
    assert len(ok(client.get(f"/api/v2/timeline?project_id={tree['dico']['id']}"))) == 1
    task = {"id": tid, "title": "Rappeler", "project_id": tree["dico"]["id"], "origin_entry_id": eid}
    assert ok(client.post("/api/v2/tasks", json=task), 201)["id"] == tid
    assert ok(client.post("/api/v2/tasks", json=task), 200)["id"] == tid
    assert len(ok(client.get(f"/api/v2/projects/{tree['dico']['id']}/tasks"))) == 1
    assert client.post("/api/v2/entries", json={**body, "id": "XYZ"}).status_code == 422


def test_thunderbird_files_a_mail_as_entry_and_task(client, tree):
    """What the extension sends (token auth): idempotent by ids and by Message-ID."""
    person = ok(client.post("/api/v2/people", json={"name": "Martin Anne"}), 201)
    ok(client.patch(f"/api/v2/people/{person['id']}", json={"email": "anne@univ.fr"}))
    entry = {"id": "c" * 32, "entry_date": "2026-03-12", "project_id": tree["dico"]["id"], "kind": "note",
             "title": "Devis", "body": "Mail de Anne", "source": "mail", "mail_message_id": "<abc@mail>",
             "person_ids": [person["id"]]}
    first = ok(client.post("/api/v2/entries", json=entry), 201)
    assert first["mail_message_id"] == "<abc@mail>" and [p["id"] for p in first["people"]] == [person["id"]]
    assert ok(client.post("/api/v2/entries", json=entry), 200)["id"] == first["id"]
    # same mail filed again from another computer (other id): still the same entry
    assert ok(client.post("/api/v2/entries", json={**entry, "id": "d" * 32}), 200)["id"] == first["id"]
    task = {"id": "e" * 32, "title": "Devis", "project_id": tree["dico"]["id"], "origin_entry_id": first["id"],
            "person_ids": [person["id"]]}
    created = ok(client.post("/api/v2/tasks", json=task), 201)
    assert created["origin_entry_id"] == first["id"]
    assert ok(client.post("/api/v2/tasks", json=task), 200)["id"] == created["id"]
    waiting = ok(client.get(f"/api/v2/people/{person['id']}"))
    assert [t["id"] for t in waiting["involved_in"]] == [created["id"]]


def test_all_open_tasks(client, tree):
    a = ok(client.post("/api/v2/tasks", json={"title": "A", "project_id": tree["dico"]["id"]}), 201)
    b = ok(client.post("/api/v2/tasks", json={"title": "B", "space_id": tree["mimmoc"]["id"]}), 201)
    c = ok(client.post("/api/v2/tasks", json={"title": "C", "project_id": tree["porfavor"]["id"]}), 201)
    ok(client.patch(f"/api/v2/tasks/{c['id']}", json={"status": "done"}))
    assert {t["id"] for t in ok(client.get("/api/v2/tasks"))} == {a["id"], b["id"]}


def test_people_of_projects_and_tasks(client, tree):
    anne = ok(client.post("/api/v2/people", json={"name": "Martin Anne"}), 201)
    paul = ok(client.post("/api/v2/people", json={"name": "Durand Paul"}), 201)
    portail, porfavor = tree["portail"]["id"], tree["porfavor"]["id"]  # porfavor is a sub-project of portail
    view = ok(client.put(f"/api/v2/projects/{portail}/people/{anne['id']}", json={"role": "responsable"}))
    assert [(p["id"], p["project_role"], p["inherited"]) for p in view["people"]] == [(anne["id"], "responsable", False)]
    ok(client.put(f"/api/v2/projects/{portail}/people/{anne['id']}", json={"role": " co-responsable "}))
    sub = ok(client.put(f"/api/v2/projects/{porfavor}/people/{paul['id']}", json={}))
    assert [(p["display_name"], p["inherited"]) for p in sub["people"]] == [("Durand Paul", False), ("Martin Anne", True)]
    person = ok(client.get(f"/api/v2/people/{anne['id']}"))
    assert [(p["id"], p["project_role"]) for p in person["projects"]] == [(portail, "co-responsable")]
    # a task's people, set by hand
    task = ok(client.post("/api/v2/tasks", json={"title": "Relire", "project_id": porfavor}), 201)
    ok(client.patch(f"/api/v2/tasks/{task['id']}", json={"person_ids": [anne["id"], paul["id"]]}))
    assert {p["id"] for p in ok(client.get(f"/api/v2/tasks/{task['id']}"))["people"]} == {anne["id"], paul["id"]}
    assert [t["id"] for t in ok(client.get(f"/api/v2/people/{paul['id']}"))["involved_in"]] == [task["id"]]
    web = TestClient(client.app)
    ok(web.post("/api/login", json={"password": PASSWORD}))
    ok(web.delete(f"/api/v2/projects/{portail}/people/{anne['id']}", headers={CSRF_HEADER: "web"}))
    assert ok(client.get(f"/api/v2/people/{anne['id']}"))["projects"] == []


def test_tasks_done_since_a_moment(client, tree):
    task = ok(client.post("/api/v2/tasks", json={"title": "Cochée par erreur", "project_id": tree["dico"]["id"]}), 201)
    ok(client.patch(f"/api/v2/tasks/{task['id']}", json={"status": "done"}))
    done = ok(client.get("/api/v2/tasks/done?since=2000-01-01T00:00:00%2B02:00"))
    assert [t["id"] for t in done] == [task["id"]]
    assert ok(client.get("/api/v2/tasks/done?since=2090-01-01T00:00:00Z")) == []
    assert client.get("/api/v2/tasks/done?since=2026-01-01T00:00:00").status_code == 400
    ok(client.patch(f"/api/v2/tasks/{task['id']}", json={"status": "open"}))
    assert ok(client.get("/api/v2/tasks/done?since=2000-01-01T00:00:00Z")) == []


def test_task_follow_up_from_thunderbird_and_by_hand(client, tree):
    """Replies sent about a mail a task came from go into its follow-up, one entry per day."""
    pid = tree["dico"]["id"]
    entry = ok(client.post("/api/v2/entries", json={"entry_date": "2026-10-20", "project_id": pid, "source": "mail",
                                                     "mail_message_id": "<orig@univ>", "title": "Devis"}), 201)
    task = ok(client.post("/api/v2/tasks", json={"title": "Devis", "project_id": pid, "origin_entry_id": entry["id"]}), 201)

    def mail(mid, refs, direction="sent", at="2026-10-21T09:00:00+02:00", day="2026-10-21"):
        return client.post("/api/v2/mail-followups", json={
            "message_id": mid, "references": refs, "direction": direction, "sent_at": at, "day": day,
            "author": "moi", "recipients": "Anne Martin", "subject": "Re: Devis", "body": f"texte {mid}"})

    first = ok(mail("<r1@me>", ["<orig@univ>"]), 201)
    assert first["task"]["id"] == task["id"] and first["created"]
    assert ok(mail("<r1@me>", ["<orig@univ>"]), 200)["created"] is False  # sent twice: once
    ok(mail("<in2@univ>", ["<orig@univ>", "<r1@me>"], "received", "2026-10-21T10:00:00+02:00"), 201)
    ok(mail("<r3@me>", ["<in2@univ>"], at="2026-10-21T11:00:00+02:00"), 201)  # found through the follow-up
    ok(mail("<r4@me>", ["<r3@me>"], at="2026-10-22T08:00:00+02:00", day="2026-10-22"), 201)
    assert mail("<x@me>", ["<unknown@nowhere>"]).status_code == 404

    mails = ok(client.get(f"/api/v2/tasks/{task['id']}/mails"))
    assert [m["message_id"] for m in mails] == ["<r1@me>", "<in2@univ>", "<r3@me>", "<r4@me>"]
    thread = ok(client.get(f"/api/v2/timeline?task_id={task['id']}"))
    titles = sorted(e["title"] for e in thread)
    assert titles == ["Échange du 21 oct. — 2 réponses envoyées, 1 mail reçu", "Échange du 22 oct. — 1 réponse envoyée"]
    assert all(e["project_id"] == pid for e in thread)

    # by hand
    note = ok(client.post(f"/api/v2/tasks/{task['id']}/followups", json={"entry_date": "2026-10-22", "body": "Accord trouvé"}), 201)
    assert note["task_id"] == task["id"]

    # removing a useless mail; the last one of a day takes its empty entry along
    web = TestClient(client.app)
    ok(web.post("/api/login", json={"password": PASSWORD}))
    h = {CSRF_HEADER: "web"}
    assert web.delete(f"/api/v2/task-mails/{mails[1]['id']}", headers=h).status_code == 204
    assert web.delete(f"/api/v2/task-mails/{mails[3]['id']}", headers=h).status_code == 204
    titles = sorted(e["title"] for e in ok(client.get(f"/api/v2/timeline?task_id={task['id']}")))
    assert titles == ["", "Échange du 21 oct. — 2 réponses envoyées"]
