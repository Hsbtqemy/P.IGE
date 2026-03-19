"""Vérification des mises à jour via les releases GitHub."""

from __future__ import annotations

import json
import logging
import re
import urllib.error
import urllib.request
from dataclasses import dataclass

logger = logging.getLogger(__name__)

# Dépôt officiel (releases GitHub + installation pip depuis git)
GITHUB_OWNER = "Hsbtqemy"
GITHUB_REPO = "P.IGE"
GITHUB_LATEST_API = f"https://api.github.com/repos/{GITHUB_OWNER}/{GITHUB_REPO}/releases/latest"
PIP_GIT_BASE = f"git+https://github.com/{GITHUB_OWNER}/{GITHUB_REPO}.git"


@dataclass
class UpdateCheckResult:
    """Résultat d'une vérification de mise à jour."""

    current_version: str
    latest_version: str | None = None
    release_title: str | None = None
    release_url: str | None = None
    release_notes: str | None = None
    error: str | None = None

    @property
    def up_to_date(self) -> bool:
        if self.error or not self.latest_version:
            return False
        return _version_tuple(self.latest_version) <= _version_tuple(self.current_version)

    @property
    def update_available(self) -> bool:
        if self.error or not self.latest_version:
            return False
        return _version_tuple(self.latest_version) > _version_tuple(self.current_version)


def get_installed_version() -> str:
    """Version du paquet `pige` (métadonnées d’installation)."""
    try:
        from importlib.metadata import version

        return version("pige").strip()
    except Exception as e:
        logger.debug("get_installed_version: %s", e)
        return "0.0.0"


def _version_tuple(v: str) -> tuple[int, int, int]:
    """Parse une version type 0.1.4 ou v0.1.4 en (major, minor, patch)."""
    raw = (v or "").strip().lstrip("vV")
    parts = raw.split(".")
    nums: list[int] = []
    for p in parts[:3]:
        m = re.match(r"^(\d+)", p.strip())
        nums.append(int(m.group(1)) if m else 0)
    while len(nums) < 3:
        nums.append(0)
    return (nums[0], nums[1], nums[2])


def fetch_latest_release(timeout: float = 15.0) -> dict:
    """Appelle l’API GitHub `releases/latest`. Lève urllib.error.URLError en cas d’échec."""
    req = urllib.request.Request(
        GITHUB_LATEST_API,
        headers={
            "Accept": "application/vnd.github+json",
            "User-Agent": f"pige-updates/{get_installed_version()}",
            "X-GitHub-Api-Version": "2022-11-28",
        },
        method="GET",
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        data = resp.read().decode("utf-8")
    return json.loads(data)


def check_for_updates() -> UpdateCheckResult:
    """
    Compare la version installée à la dernière release GitHub.
    Ne nécessite pas de dépendance HTTP externe (urllib).
    """
    current = get_installed_version()
    try:
        payload = fetch_latest_release()
    except urllib.error.HTTPError as e:
        return UpdateCheckResult(
            current_version=current,
            error=f"Erreur HTTP {e.code} lors de la lecture de GitHub.",
        )
    except urllib.error.URLError as e:
        return UpdateCheckResult(
            current_version=current,
            error=f"Réseau indisponible ou délai dépassé : {e.reason!s}",
        )
    except Exception as e:
        logger.exception("check_for_updates")
        return UpdateCheckResult(current_version=current, error=str(e))

    tag = (payload.get("tag_name") or "").strip()
    if not tag:
        return UpdateCheckResult(
            current_version=current,
            error="Réponse GitHub sans tag de version.",
        )
    latest = tag.lstrip("vV")
    notes = payload.get("body") or ""
    if len(notes) > 4000:
        notes = notes[:3997] + "…"

    return UpdateCheckResult(
        current_version=current,
        latest_version=latest,
        release_title=(payload.get("name") or "").strip() or tag,
        release_url=payload.get("html_url"),
        release_notes=notes.strip() or None,
    )


def pip_upgrade_spec(tag: str) -> str:
    """Spécification pip pour installer la release donnée (ex. v0.1.4)."""
    t = tag.strip()
    if not t.startswith("v"):
        t = f"v{t}"
    return f"{PIP_GIT_BASE}@{t}"
