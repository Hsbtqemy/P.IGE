"""The code journal: a project linked to a repository, one entry a day summed up by work item."""

from __future__ import annotations

import base64

import pytest

pytest.importorskip("fastapi")

from fastapi.testclient import TestClient  # noqa: E402

from pige.server.app import CSRF_HEADER, create_app  # noqa: E402
from pige.server.auth import hash_password, new_api_token  # noqa: E402
from pige.server.code import CodeError, day_title, normalize_repo, parse_fiche, summarize  # noqa: E402
from pige.server.config import Settings  # noqa: E402

PASSWORD = "correct horse battery staple"
_HASH = hash_password(PASSWORD)
_TOKEN, _TOKEN_HASH = new_api_token()
WEB = {CSRF_HEADER: "web"}

FICHE_P8 = """---
chantier: P-8
statut: interrompu
---

# P-8 — paragraphes manuels

**Arrêté sur** — geste ¶ par segment, commit `be36385`, 23 juillet.

## Reste

### Vérifications
- [ ] Vérifier la propagation
      sur deux lignes
- [x] Déjà fait
- [ ] Encore une

## QA
- [ ] pas compté
"""

FICHE_P1 = """---
chantier: P-1
statut: livré
---

# P-1 — fini
"""


def test_reading_work_items():
    p8 = parse_fiche(FICHE_P8, "P-8.md")
    assert p8 == {"code": "P-8", "title": "paragraphes manuels", "status": "interrompu",
                  "stopped": "geste ¶ par segment, commit `be36385`, 23 juillet.", "stopped_label": "Arrêté sur",
                  "open": 2, "path": "pilotage/P-8.md"}
    assert parse_fiche("---\npasse: rendu\n---\n# x", "rendu.md") is None
    assert parse_fiche("# R6 — sans en-tête\n**Point de départ** — rien encore", "R6.md")["stopped_label"] == "Point de départ"
    assert normalize_repo("https://github.com/Hsbtqemy/pilote.git") == "Hsbtqemy/pilote"
    assert normalize_repo("git@github.com:Hsbtqemy/pilote") == "Hsbtqemy/pilote"
    with pytest.raises(CodeError):
        normalize_repo("pas un dépôt")


def test_a_day_is_summed_up_by_work_item():
    fiches = [parse_fiche(FICHE_P8, "P-8.md"), {**parse_fiche(FICHE_P8, "P-8.md"), "code": "P-80", "title": "autre"}]
    commits = [{"sha": str(i), "at": "2026-10-21T09:00:00Z", "subject": s} for i, s in enumerate(
        ["P-8 : geste", "P-8 suite", "fix P-80", "P-8, P-80 ensemble", "typo", "P-81 inconnu"])]
    s = summarize(commits, fiches)
    assert s["total"] == 6 and s["other"] == 2
    assert [(c["code"], c["count"]) for c in s["chantiers"]] == [("P-8", 3), ("P-80", 2)]
    assert day_title("Hsbtqemy/pilote", s) == "Code — pilote · 6 commits (P-8, P-80)"


class FakeGitHub:
    def __init__(self):
        self.calls: list[str] = []
        self.commits = {
            "main": [self.c("a1", "2026-10-20T08:00:00Z", "P-8 : début")],
            "dev": [self.c("a1", "2026-10-20T08:00:00Z", "P-8 : début"),
                    self.c("b2", "2026-10-21T21:30:00Z", "P-8 : suite"),  # 23:30 in Paris: still the 21st
                    self.c("b3", "2026-10-21T22:30:00Z", "ménage")],  # 00:30 in Paris: the 22nd
        }
        self.files = {"P-8.md": FICHE_P8, "P-1.md": FICHE_P1, "_TEMPLATE.md": "# gabarit"}

    @staticmethod
    def c(sha, at, subject):
        return {"sha": sha, "commit": {"committer": {"date": at}, "message": f"{subject}\n\ncorps"}}

    def __call__(self, path, params):
        self.calls.append(path)
        if path.endswith("/branches"):
            return [{"name": "main"}, {"name": "dev"}], {}
        if path.endswith("/commits"):
            return self.commits[params["sha"]], {}
        if path.endswith("/contents/pilotage"):
            return [{"type": "file", "name": n, "path": f"pilotage/{n}", "sha": f"s-{n}"} for n in self.files], {}
        if "/contents/pilotage/" in path:
            name = path.rsplit("/", 1)[1]
            return {"content": base64.b64encode(self.files[name].encode()).decode()}, {}
        raise CodeError("Dépôt introuvable : vérifie son nom, ou le jeton GitHub s'il est privé.")


@pytest.fixture()
def app(tmp_path):
    settings = Settings(
        data_dir=tmp_path, password_hash=_HASH, session_secret="s" * 48, api_token_hashes=frozenset({_TOKEN_HASH}),
        cookie_secure=False, background_jobs=False, timezone="Europe/Paris",
    )
    application = create_app(settings)
    application.state.github = FakeGitHub()
    application.state.code_journal.get = application.state.github
    return application


def test_linking_a_project_writes_one_entry_a_day(app):
    c = TestClient(app)
    assert c.post("/api/login", json={"password": PASSWORD}).status_code == 200
    space = c.post("/api/v2/spaces", json={"name": "DEV"}, headers=WEB).json()
    project = c.post("/api/v2/projects", json={"space_id": space["id"], "name": "pilote"}, headers=WEB).json()
    pid = project["id"]
    assert c.put(f"/api/v2/projects/{pid}/repo", json={"repo": "pas un dépôt"}, headers=WEB).status_code == 400

    view = c.put(f"/api/v2/projects/{pid}/repo", json={"repo": "https://github.com/Hsbtqemy/pilote"}, headers=WEB).json()
    assert view["repo"] == "Hsbtqemy/pilote" and view["last_error"] is None and view["branch"] == "dev"
    assert [f["code"] for f in view["chantiers"]] == ["P-8"] and view["closed"] == 1  # P-1 livré
    assert view["chantiers"][0]["open"] == 2

    entries = sorted(c.get(f"/api/v2/timeline?project_id={pid}").json(), key=lambda e: e["entry_date"])
    assert [(e["entry_date"], e["title"]) for e in entries] == [
        ("2026-10-20", "Code — pilote · 1 commit (P-8)"),
        ("2026-10-21", "Code — pilote · 1 commit (P-8)"),
        ("2026-10-22", "Code — pilote · 1 commit"),
    ]
    assert entries[2]["code"] == {"total": 1, "chantiers": [], "other": 1, "repo": "Hsbtqemy/pilote", "branch": "dev"}

    # a synthesis written by hand is kept; a new commit that day updates the summary only
    e21 = entries[1]
    c.patch(f"/api/v2/entries/{e21['id']}", json={"expected_revision": e21["revision"], "body": "Bonne avancée"}, headers=WEB)
    app.state.github.commits["dev"].append(FakeGitHub.c("b4", "2026-10-21T10:00:00Z", "P-8 : fin"))
    files_read = app.state.github.calls.count("/repos/Hsbtqemy/pilote/contents/pilotage/P-8.md")
    c.post(f"/api/v2/projects/{pid}/code/sync", headers=WEB)
    again = c.get(f"/api/v2/entries/{e21['id']}").json()
    assert again["title"] == "Code — pilote · 2 commits (P-8)" and again["body"] == "Bonne avancée"
    assert again["code"]["chantiers"][0]["count"] == 2
    # unchanged work items are not read again
    assert app.state.github.calls.count("/repos/Hsbtqemy/pilote/contents/pilotage/P-8.md") == files_read

    # unlinking keeps the days already written
    assert c.put(f"/api/v2/projects/{pid}/repo", json={"repo": None}, headers=WEB).json()["repo"] is None
    assert len(c.get(f"/api/v2/timeline?project_id={pid}").json()) == 3


def test_errors_are_shown_and_tokens_cannot_link(app):
    c = TestClient(app)
    c.post("/api/login", json={"password": PASSWORD})
    space = c.post("/api/v2/spaces", json={"name": "DEV"}, headers=WEB).json()
    pid = c.post("/api/v2/projects", json={"space_id": space["id"], "name": "x"}, headers=WEB).json()["id"]
    def missing(path, params):
        raise CodeError("Dépôt introuvable : vérifie son nom, ou le jeton GitHub s'il est privé.")

    app.state.code_journal.get = missing
    view = c.put(f"/api/v2/projects/{pid}/repo", json={"repo": "Hsbtqemy/prive"}, headers=WEB).json()
    assert view["last_error"].startswith("Dépôt introuvable") and view["token"] is False
    token = TestClient(app, headers={"Authorization": f"Bearer {_TOKEN}"})
    assert token.put(f"/api/v2/projects/{pid}/repo", json={"repo": "a/b"}).status_code == 403
    assert token.get(f"/api/v2/projects/{pid}/code").status_code == 200


def test_the_stopping_point_is_kept_only_for_recent_days(app):
    from datetime import datetime, timezone

    store = app.state.code_journal.store
    space = store.create_space("DEV")
    pid = store.create_project(space.id, "pilote").id
    store.set_project_repo(pid, "Hsbtqemy/pilote")
    app.state.code_journal.sync(pid, now=datetime(2026, 10, 21, 20, 0, tzinfo=timezone.utc))
    by_day = {d: store.code_day(pid, d)["summary"] for d in ("2026-10-20", "2026-10-21")}
    assert by_day["2026-10-21"]["chantiers"][0]["stopped"].startswith("geste ¶")  # that day: where it stopped
    assert by_day["2026-10-20"]["chantiers"][0]["stopped"].startswith("geste ¶")  # yesterday too

    other = store.create_project(space.id, "relu plus tard").id
    store.set_project_repo(other, "Hsbtqemy/pilote")
    app.state.code_journal.sync(other, now=datetime(2026, 11, 5, 9, 0, tzinfo=timezone.utc))
    assert store.code_day(other, "2026-10-21")["summary"]["chantiers"][0]["stopped"] == ""  # read weeks later


def test_read_twice_a_day_or_when_asked(app):
    from datetime import datetime, timezone
    from zoneinfo import ZoneInfo

    journal = app.state.code_journal
    paris = ZoneInfo("Europe/Paris")
    at = lambda h, m: datetime(2026, 10, 21, h, m, tzinfo=paris).astimezone(timezone.utc)  # noqa: E731
    assert journal.last_slot(at(13, 0)) == at(12, 30)
    assert journal.last_slot(at(20, 0)) == at(19, 30)
    assert journal.last_slot(at(8, 0)) == datetime(2026, 10, 20, 19, 30, tzinfo=paris).astimezone(timezone.utc)

    store = journal.store
    space = store.create_space("DEV")
    pid = store.create_project(space.id, "pilote").id
    store.set_project_repo(pid, "Hsbtqemy/pilote")
    journal.sync_due(now=at(12, 40))
    first = store.project_repo(pid)["last_sync"]
    assert first is not None
    calls = len(app.state.github.calls)
    journal.sync_due(now=at(15, 0))  # nothing scheduled since 12:30
    assert len(app.state.github.calls) == calls
    journal.sync_due(now=at(19, 45))  # the evening reading
    assert len(app.state.github.calls) > calls

    c = TestClient(app)
    c.post("/api/login", json={"password": PASSWORD})
    assert [r["repo"] for r in c.get("/api/v2/code").json()] == ["Hsbtqemy/pilote"]
    result = c.post("/api/v2/code/sync", headers=WEB).json()
    assert result["repos"] == 1 and result["errors"] == []
