import os
import subprocess
import sys
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[1]


def _env() -> dict[str, str]:
    env = os.environ.copy()
    root = str(_repo_root())
    pythonpath = env.get("PYTHONPATH")
    env["PYTHONPATH"] = root if not pythonpath else root + os.pathsep + pythonpath
    return env


def _run_cli(args: list[str], cwd: Path, env: dict[str, str]) -> tuple[int, str, str]:
    result = subprocess.run(  # noqa: S603
        [sys.executable, "-m", "pige", *args],
        cwd=str(cwd),
        env=env,
        capture_output=True,
        text=True,
    )
    return result.returncode, result.stdout, result.stderr


def _init_and_project(cwd: Path, env: dict[str, str]) -> str:
    code, _out, _err = _run_cli(["init"], cwd, env)
    if code != 0:
        raise RuntimeError("init failed")
    code, out, err = _run_cli(["project", "add", "Alpha"], cwd, env)
    if code != 0:
        raise RuntimeError(f"project add failed: {err}")
    return out.strip().split(": ", 1)[1]


class TestCLI(unittest.TestCase):
    def test_export_narrative_succeeds(self) -> None:
        with TemporaryDirectory() as tmp:
            cwd = Path(tmp)
            env = _env()
            project_id = _init_and_project(cwd, env)
            code, out, err = _run_cli(
                ["export", "project", project_id, "--mode", "narrative"],
                cwd,
                env,
            )
            self.assertEqual(code, 0, err)
            self.assertIn("narrative", out)
            export_path = Path(out.strip())
            self.assertTrue(export_path.exists(), f"Export file should exist: {export_path}")

    def test_invalid_date_range_from_gt_to(self) -> None:
        with TemporaryDirectory() as tmp:
            cwd = Path(tmp)
            env = _env()
            project_id = _init_and_project(cwd, env)
            code, _out, err = _run_cli(
                [
                    "export",
                    "project",
                    project_id,
                    "--from",
                    "2024-02-10",
                    "--to",
                    "2024-02-01",
                ],
                cwd,
                env,
            )
            self.assertEqual(code, 1)
            self.assertIn("Invalid date range", err)

    def test_compact_succeeds(self) -> None:
        with TemporaryDirectory() as tmp:
            cwd = Path(tmp)
            env = _env()
            project_id = _init_and_project(cwd, env)
            code, out, err = _run_cli(
                ["entry", "add", project_id, "--type", "note", "--title", "T", "--body", "x"],
                cwd,
                env,
            )
            self.assertEqual(code, 0, err)
            code, out, err = _run_cli(["compact"], cwd, env)
            self.assertEqual(code, 0, err)
            self.assertIn("Compacted", out)
            self.assertIn("lines", out)
