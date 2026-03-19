"""Tests pour le module de vérification des mises à jour (sans réseau)."""

from pige.utils import updates


def test_version_tuple_basic() -> None:
    assert updates._version_tuple("0.1.4") == (0, 1, 4)
    assert updates._version_tuple("v1.0.0") == (1, 0, 0)
    assert updates._version_tuple("2.3") == (2, 3, 0)


def test_update_result_flags() -> None:
    r = updates.UpdateCheckResult(current_version="0.1.0", latest_version="0.1.0")
    assert r.up_to_date
    assert not r.update_available

    r2 = updates.UpdateCheckResult(current_version="0.1.0", latest_version="0.2.0")
    assert not r2.up_to_date
    assert r2.update_available

    r3 = updates.UpdateCheckResult(current_version="0.2.0", latest_version="0.1.0")
    assert r3.up_to_date
    assert not r3.update_available


def test_pip_upgrade_spec() -> None:
    assert "github.com" in updates.pip_upgrade_spec("v0.1.4")
    assert updates.pip_upgrade_spec("v0.1.4").endswith("@v0.1.4")
    assert "@v1.0.0" in updates.pip_upgrade_spec("1.0.0")
