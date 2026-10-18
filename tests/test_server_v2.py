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
        cookie_secure=False,
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


def test_timeline_filters_and_paging(client, tree):
    pid = tree["porfavor"]["id"]
    for day in ("2026-01-13", "2026-01-23", "2026-01-29"):
        ok(client.post("/api/v2/entries", json={"entry_date": day, "project_id": pid, "title": day}), 201)
    page1 = ok(client.get(f"/api/v2/timeline?project_id={tree['portail']['id']}&limit=2"))
    page2 = ok(client.get(f"/api/v2/timeline?project_id={tree['portail']['id']}&limit=2&offset=2"))
    assert [e["title"] for e in page1 + page2] == ["2026-01-29", "2026-01-23", "2026-01-13"]
    assert [e["title"] for e in ok(client.get("/api/v2/timeline?day=2026-01-23"))] == ["2026-01-23"]


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


def test_search_endpoint(client, tree):
    ok(client.post("/api/v2/tasks", json={"title": "Définir les métadonnées", "project_id": tree["dico"]["id"]}), 201)
    hits = ok(client.get("/api/v2/search?q=metadonnees"))
    assert hits[0]["kind"] == "task"
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
