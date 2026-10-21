"""The code journal: what was pushed to a project's repository, day by day, summed up by
work item (the « chantiers » of pilote, read from the repository's ``pilotage/`` folder).

Nothing is copied from the repository but this summary: for each day, the work items whose
code appears in a commit subject, with their count, and the number of other commits. The
work items themselves (code, title, status, « Arrêté sur », open boxes) are shown on the
project page as read, never turned into tasks. GitHub only, read-only.
"""

from __future__ import annotations

import json
import logging
import re
import threading
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone
from typing import Any, Callable
from zoneinfo import ZoneInfo

from pige.model import ModelStore

logger = logging.getLogger(__name__)

API = "https://api.github.com"
TIMEOUT_SECONDS = 20
MAX_BYTES = 5 * 1024 * 1024
FIRST_WINDOW = timedelta(days=30)  # how far back the first sync of a repository looks
OVERLAP = timedelta(days=2)  # later syncs re-read a little before the last one
MAX_PAGES = 10  # 100 commits a page, per branch
# Read on its own twice a day (local time), else when asked (« Récupérer le code »).
SYNC_TIMES = ((12, 30), (19, 30))
RETRY_AFTER = timedelta(hours=1)  # a failed scheduled read is tried again an hour later, once
OPEN_STATUSES = {"à venir", "interrompu", "différé"}  # pilote: closed are clos, livré, abandonné


class CodeError(Exception):
    """A readable message (French), safe to show and to store."""


def normalize_repo(text: str) -> str:
    """« owner/name » from « owner/name », a github.com URL, or « git@github.com:owner/name.git »."""
    value = text.strip()
    value = re.sub(r"^(https?://)?(www\.)?github\.com[/:]", "", value)
    value = re.sub(r"^git@github\.com:", "", value)
    value = value.removesuffix(".git").strip("/")
    if not re.fullmatch(r"[A-Za-z0-9-]{1,39}/[A-Za-z0-9._-]{1,100}", value):
        raise CodeError("Indique le dépôt GitHub sous la forme propriétaire/nom (ex. Hsbtqemy/pilote).")
    return value


Fetcher = Callable[[str, dict[str, str]], tuple[Any, dict[str, str]]]


def github_fetcher(token: str) -> Fetcher:
    """GET a GitHub API path: (decoded JSON, response headers). The token is only ever sent
    to api.github.com, never logged."""

    def get(path: str, params: dict[str, str]) -> tuple[Any, dict[str, str]]:
        # « raw:owner/name/ref/path »: a file's text from raw.githubusercontent.com, which
        # does not count against the API's hourly limit.
        if path.startswith("raw:"):
            url = "https://raw.githubusercontent.com/" + urllib.parse.quote(path[4:])
            headers = {"User-Agent": "pige"}
            if token:
                headers["Authorization"] = f"Bearer {token}"
            try:
                with urllib.request.urlopen(urllib.request.Request(url, headers=headers), timeout=TIMEOUT_SECONDS) as r:
                    return r.read(MAX_BYTES).decode("utf-8", "replace"), {}
            except urllib.error.HTTPError as exc:
                raise CodeError(f"Fiche illisible ({exc.code}).") from exc
            except (urllib.error.URLError, TimeoutError, OSError) as exc:
                raise CodeError("GitHub injoignable.") from exc
        url = f"{API}{path}" + (f"?{urllib.parse.urlencode(params)}" if params else "")
        headers = {"Accept": "application/vnd.github+json", "X-GitHub-Api-Version": "2022-11-28",
                   "User-Agent": "pige"}
        if token:
            headers["Authorization"] = f"Bearer {token}"
        request = urllib.request.Request(url, headers=headers)
        try:
            with urllib.request.urlopen(request, timeout=TIMEOUT_SECONDS) as response:
                data = response.read(MAX_BYTES + 1)
                if len(data) > MAX_BYTES:
                    raise CodeError("Réponse de GitHub trop volumineuse.")
                return json.loads(data.decode("utf-8")), {k.lower(): v for k, v in response.headers.items()}
        except urllib.error.HTTPError as exc:
            if exc.code == 404:
                raise CodeError("Dépôt introuvable : vérifie son nom, ou le jeton GitHub s'il est privé.") from exc
            if exc.code in (401, 403):
                remaining = exc.headers.get("x-ratelimit-remaining") if exc.headers else None
                if remaining == "0":
                    reset = exc.headers.get("x-ratelimit-reset") if exc.headers else None
                    when = ""
                    if reset and reset.isdigit():
                        when = " après " + datetime.fromtimestamp(int(reset), timezone.utc).astimezone(
                            ZoneInfo("Europe/Paris")).strftime("%H h %M")
                    hint = "" if token else " Sans jeton, GitHub n'accorde que 60 requêtes par heure : ajoute PIGE_GITHUB_TOKEN."
                    raise CodeError(f"Limite de requêtes GitHub atteinte : réessaie{when or ' dans une heure'}.{hint}") from exc
                raise CodeError("GitHub refuse l'accès : vérifie le jeton (lecture du contenu de ce dépôt).") from exc
            raise CodeError(f"GitHub répond {exc.code}.") from exc
        except (urllib.error.URLError, TimeoutError, OSError, ValueError) as exc:
            logger.warning("GitHub: %s", type(exc).__name__)
            raise CodeError("GitHub injoignable.") from exc

    return get


# ---------------------------------------------------------------- pilote's work items

_FRONT = re.compile(r"\A---\n(.*?)\n---\n", re.S)
_TITLE = re.compile(r"^# (.+)$", re.M)
_ARRET = re.compile(r"^\*\*(Arrêté sur|Point de départ)\*\*\s*[—–-]?\s*(.+)$", re.M)
_OPEN_BOX = re.compile(r"^\s*- \[ \]", re.M)


def parse_fiche(text: str, filename: str) -> dict[str, Any] | None:
    """A pilote work item (pilotage/<CODE>.md): code, title, status, stopping point, open
    boxes of « Reste ». None for a QA pass or a file that is not a work item."""
    text = text.replace("\r\n", "\n")
    front: dict[str, str] = {}
    match = _FRONT.match(text)
    if match:
        for line in match.group(1).splitlines():
            if ":" in line:
                key, value = line.split(":", 1)
                front[key.strip()] = value.strip()
    if "passe" in front:
        return None
    code = front.get("chantier") or filename.removesuffix(".md")
    if not re.fullmatch(r"[A-Za-z][A-Za-z0-9]*(-[A-Za-z0-9]+)*", code) or code.startswith("_"):
        return None
    title_match = _TITLE.search(text)
    title = title_match.group(1).strip() if title_match else code
    title = re.sub(rf"^{re.escape(code)}\s*[—–:-]\s*", "", title)
    arret = _ARRET.search(text)
    reste = text.split("## Reste", 1)[1] if "## Reste" in text else ""
    reste = re.split(r"^## ", reste, maxsplit=1, flags=re.M)[0]
    return {
        "code": code,
        "title": title[:200],
        "status": front.get("statut") or "interrompu",
        "stopped": (arret.group(2).strip()[:300] if arret else ""),
        "stopped_label": (arret.group(1) if arret else ""),
        "open": len(_OPEN_BOX.findall(reste)),
        "path": f"pilotage/{filename}",
    }


def summarize(commits: list[dict[str, Any]], fiches: list[dict[str, Any]], *, recent: bool = True) -> dict[str, Any]:
    """A day's commits as work items: [{code, title, count, stopped}], plus the others.
    ``stopped`` (the work item's « Arrêté sur ») is today's: kept only for a recent day,
    where it says where that day's work stopped — not for days read afterwards."""
    known = sorted(fiches, key=lambda f: -len(f["code"]))
    by_code: dict[str, dict[str, Any]] = {}
    other = 0
    for commit in commits:
        subject = commit.get("subject", "")
        hits = [f for f in known if re.search(rf"(?<![A-Za-z0-9-]){re.escape(f['code'])}(?![A-Za-z0-9])", subject)]
        if not hits:
            other += 1
        for f in hits:
            item = by_code.setdefault(f["code"], {"code": f["code"], "title": f["title"], "count": 0,
                                                   "stopped": f["stopped"] if recent else "", "path": f["path"]})
            item["count"] += 1
    items = sorted(by_code.values(), key=lambda i: -i["count"])
    return {"total": len(commits), "chantiers": items, "other": other}


def day_title(repo: str, summary: dict[str, Any]) -> str:
    name = repo.split("/", 1)[-1]
    n = summary["total"]
    codes = ", ".join(i["code"] for i in summary["chantiers"][:4])
    more = "…" if len(summary["chantiers"]) > 4 else ""
    return f"Code — {name} · {n} commit{'s' if n > 1 else ''}" + (f" ({codes}{more})" if codes else "")


# ---------------------------------------------------------------- sync


class CodeJournal:
    """Reads the linked repositories (all pushed branches) and keeps one entry per day."""

    def __init__(self, store: ModelStore, zone: ZoneInfo, fetcher: Fetcher) -> None:
        self.store = store
        self.zone = zone
        self.get = fetcher
        self._lock = threading.Lock()
        self._stop = threading.Event()
        self._attempts: dict[str, datetime] = {}  # last scheduled attempt per project

    def _pages(self, path: str, params: dict[str, str]) -> list[Any]:
        out: list[Any] = []
        for page in range(1, MAX_PAGES + 1):
            data, _headers = self.get(path, {**params, "per_page": "100", "page": str(page)})
            if not isinstance(data, list):
                break
            out.extend(data)
            if len(data) < 100:
                break
        return out

    def _fiches(self, repo: str, branch: str, known_shas: dict[str, str],
                previous: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], dict[str, str]]:
        """The work items of the branch, re-reading only the files that changed."""
        try:
            listing, _ = self.get(f"/repos/{repo}/contents/pilotage", {"ref": branch})
        except CodeError:
            return [], {}  # no pilotage/ folder: no work items, commits still counted
        if not isinstance(listing, list):
            return [], {}
        by_path = {f["path"]: f for f in previous}
        fiches: list[dict[str, Any]] = []
        shas: dict[str, str] = {}
        for item in listing:
            name = item.get("name", "")
            if item.get("type") != "file" or not name.endswith(".md") or name.startswith("_"):
                continue
            path, sha = f"pilotage/{name}", item.get("sha", "")
            shas[path] = sha
            if known_shas.get(path) == sha and path in by_path:
                fiches.append(by_path[path])
                continue
            text, _ = self.get(f"raw:{repo}/{branch}/{path}", {})
            if not isinstance(text, str):
                text = ""
            fiche = parse_fiche(text, name)
            if fiche is not None:
                fiches.append(fiche)
        return sorted(fiches, key=lambda f: f["code"]), shas

    def sync(self, project_id: str, *, now: datetime | None = None) -> dict[str, Any]:
        moment = now or datetime.now(timezone.utc)
        with self._lock:
            link = self.store.project_repo(project_id)
            if link is None:
                raise CodeError("Ce projet n'est relié à aucun dépôt.")
            repo = link["repo"]
            try:
                last = (datetime.strptime(link["last_sync"], "%Y-%m-%dT%H:%M:%S.%fZ").replace(tzinfo=timezone.utc)
                        if link["last_sync"] else None)
                since = (last - OVERLAP) if last else (moment - FIRST_WINDOW)
                listed = self._pages(f"/repos/{repo}/branches", {})
                heads = {b["name"]: (b.get("commit") or {}).get("sha", "") for b in listed if "name" in b}
                branches = list(heads)
                # A branch whose last commit has not changed has nothing new: not read again.
                moved = [b for b in branches if not heads[b] or link["heads"].get(b) != heads[b]]
                commits: dict[str, dict[str, Any]] = {}
                latest_branch, latest_at = None, ""
                for branch in moved:
                    for c in self._pages(f"/repos/{repo}/commits",
                                         {"sha": branch, "since": since.strftime("%Y-%m-%dT%H:%M:%SZ")}):
                        sha = c.get("sha")
                        info = c.get("commit") or {}
                        at = ((info.get("committer") or {}).get("date") or (info.get("author") or {}).get("date") or "")
                        if not sha or not at:
                            continue
                        if at > latest_at:
                            latest_branch, latest_at = branch, at
                        commits[sha] = {"sha": sha, "at": at, "subject": (info.get("message") or "").split("\n", 1)[0][:200]}
                branch = latest_branch or link["branch"] or (branches[0] if branches else None)
                if branch and (moved or not link["last_sync"]):
                    fiches, shas = self._fiches(repo, branch, link["fiche_shas"], link["fiches"])
                else:
                    fiches, shas = link["fiches"], link["fiche_shas"]  # nothing moved: work items unchanged
                days: dict[str, list[dict[str, Any]]] = {}
                for c in commits.values():
                    when = datetime.strptime(c["at"], "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
                    days.setdefault(when.astimezone(self.zone).date().isoformat(), []).append(c)
                written = 0
                for day, found in sorted(days.items()):
                    previous = self.store.code_day(project_id, day)
                    merged = {c["sha"]: c for c in (previous["commits"] if previous else [])}
                    merged.update({c["sha"]: c for c in found})
                    all_commits = sorted(merged.values(), key=lambda c: c["at"])
                    recent = day >= (moment.astimezone(self.zone).date() - timedelta(days=1)).isoformat()
                    if previous and not recent:
                        # An older day read again: keep the stopping points it was written with.
                        stopped = {c["code"]: c["stopped"] for c in previous["summary"].get("chantiers", [])}
                        summary = summarize(all_commits, fiches, recent=False)
                        for item in summary["chantiers"]:
                            item["stopped"] = stopped.get(item["code"], "")
                    else:
                        summary = summarize(all_commits, fiches, recent=recent)
                    if previous and previous["summary"] == summary and previous["entry_id"]:
                        continue
                    self.store.save_code_day(project_id, day, commits=all_commits, summary=summary,
                                             title=day_title(repo, summary))
                    written += 1
            except CodeError as exc:
                self.store.repo_synced(project_id, error=str(exc))
                raise
            except Exception as exc:
                logger.warning("Code journal %s: unexpected %s", repo, type(exc).__name__)
                error = CodeError(f"Lecture du dépôt impossible ({type(exc).__name__}).")
                self.store.repo_synced(project_id, error=str(error))
                raise error from None
            self.store.repo_synced(project_id, branch=branch, fiches=fiches, fiche_shas=shas, heads=heads, at=moment)
            return {"commits": len(commits), "days": written, "fiches": len(fiches)}

    def last_slot(self, moment: datetime) -> datetime:
        """The latest scheduled reading time (12:30 or 19:30 local) at or before ``moment``."""
        local = moment.astimezone(self.zone)
        for days_back in (0, 1):
            day = local.date() - timedelta(days=days_back)
            for hour, minute in sorted(SYNC_TIMES, reverse=True):
                slot = datetime(day.year, day.month, day.day, hour, minute, tzinfo=self.zone)
                if slot <= local:
                    return slot.astimezone(timezone.utc)
        return moment - timedelta(days=1)

    def sync_due(self, now: datetime | None = None) -> None:
        """The scheduled reading: each linked repository not read since the last slot."""
        moment = now or datetime.now(timezone.utc)
        slot = self.last_slot(moment)
        for link in self.store.project_repos():
            last = link["last_sync"]
            if last and datetime.strptime(last, "%Y-%m-%dT%H:%M:%S.%fZ").replace(tzinfo=timezone.utc) >= slot:
                continue
            tried = self._attempts.get(link["project_id"])
            if tried and (tried >= slot + RETRY_AFTER or moment - tried < RETRY_AFTER):
                continue
            self._attempts[link["project_id"]] = moment
            try:
                self.sync(link["project_id"], now=moment)
            except CodeError:
                pass  # recorded on the link, shown on the project page

    def sync_all(self, now: datetime | None = None) -> dict[str, Any]:
        """« Récupérer le code »: every linked repository, now."""
        moment = now or datetime.now(timezone.utc)
        read, days, errors = 0, 0, []
        for link in self.store.project_repos():
            try:
                result = self.sync(link["project_id"], now=moment)
                read += 1
                days += result["days"]
            except CodeError as exc:
                errors.append({"repo": link["repo"], "error": str(exc)})
        return {"repos": read, "days": days, "errors": errors}

    def start(self) -> None:
        def loop() -> None:
            while not self._stop.wait(600):
                try:
                    self.sync_due()
                except Exception as exc:
                    logger.warning("Code loop: %s", type(exc).__name__)

        threading.Thread(target=loop, name="pige-code", daemon=True).start()

    def stop(self) -> None:
        self._stop.set()
