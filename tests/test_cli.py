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

    def test_entry_add_with_all_parameters(self) -> None:
        """Test entry add with date, person, group, meeting times, and decision done."""
        with TemporaryDirectory() as tmp:
            cwd = Path(tmp)
            env = _env()
            project_id = _init_and_project(cwd, env)
            
            # Test with meeting entry including all parameters
            code, out, err = _run_cli(
                [
                    "entry", "add", project_id,
                    "--type", "meeting",
                    "--title", "Sprint Planning",
                    "--tags", "sprint,planning",
                    "--body", "Discussed sprint goals",
                    "--date", "2024-01-15",
                    "--person", "John Doe",
                    "--group", "Development Team",
                    "--meeting-start", "10:00",
                    "--meeting-end", "11:30"
                ],
                cwd,
                env,
            )
            self.assertEqual(code, 0, err)
            self.assertIn("Entry created:", out)
            
            # Test with decision entry
            code, out, err = _run_cli(
                [
                    "entry", "add", project_id,
                    "--type", "decision",
                    "--title", "Use PostgreSQL",
                    "--decision-done"
                ],
                cwd,
                env,
            )
            self.assertEqual(code, 0, err)
            self.assertIn("Entry created:", out)

    def test_entry_update_command(self) -> None:
        """Test entry update command."""
        with TemporaryDirectory() as tmp:
            cwd = Path(tmp)
            env = _env()
            project_id = _init_and_project(cwd, env)
            
            # Create an entry first
            code, out, err = _run_cli(
                ["entry", "add", project_id, "--type", "note", "--title", "Original Title"],
                cwd,
                env,
            )
            self.assertEqual(code, 0, err)
            entry_id = out.strip().split(": ")[1].split("\n")[0]
            
            # Update the entry
            code, out, err = _run_cli(
                [
                    "entry", "update", entry_id,
                    "--title", "Updated Title",
                    "--tags", "new,tags"
                ],
                cwd,
                env,
            )
            self.assertEqual(code, 0, err)
            self.assertIn("Entry updated:", out)

    def test_entry_list_command(self) -> None:
        """Test entry list command."""
        with TemporaryDirectory() as tmp:
            cwd = Path(tmp)
            env = _env()
            project_id = _init_and_project(cwd, env)
            
            # Add some entries
            for i in range(3):
                code, _out, err = _run_cli(
                    ["entry", "add", project_id, "--type", "note", "--title", f"Entry {i}"],
                    cwd,
                    env,
                )
                self.assertEqual(code, 0, err)
            
            # List entries
            code, out, err = _run_cli(
                ["entry", "list", project_id],
                cwd,
                env,
            )
            self.assertEqual(code, 0, err)
            self.assertIn("Entry 0", out)
            self.assertIn("Entry 1", out)
            self.assertIn("Entry 2", out)

    def test_entry_delete_command(self) -> None:
        """Test entry delete command with --yes flag."""
        with TemporaryDirectory() as tmp:
            cwd = Path(tmp)
            env = _env()
            project_id = _init_and_project(cwd, env)
            
            # Create an entry
            code, out, err = _run_cli(
                ["entry", "add", project_id, "--type", "note", "--title", "To Delete"],
                cwd,
                env,
            )
            self.assertEqual(code, 0, err)
            entry_id = out.strip().split(": ")[1].split("\n")[0]
            
            # Delete with --yes flag
            code, out, err = _run_cli(
                ["entry", "delete", entry_id, "--yes"],
                cwd,
                env,
            )
            self.assertEqual(code, 0, err)
            self.assertIn("Entry deleted:", out)

    def test_entry_move_command(self) -> None:
        """Test entry move command."""
        with TemporaryDirectory() as tmp:
            cwd = Path(tmp)
            env = _env()
            project_id1 = _init_and_project(cwd, env)
            
            # Create second project
            code, out, err = _run_cli(["project", "add", "Beta"], cwd, env)
            self.assertEqual(code, 0, err)
            project_id2 = out.strip().split(": ")[1]
            
            # Create entry in first project
            code, out, err = _run_cli(
                ["entry", "add", project_id1, "--type", "note", "--title", "Move Me", "--tags", "tag1"],
                cwd,
                env,
            )
            self.assertEqual(code, 0, err)
            entry_id = out.strip().split(": ")[1].split("\n")[0]
            
            # Move entry to second project with --keep-tags
            code, out, err = _run_cli(
                ["entry", "move", entry_id, project_id2, "--keep-tags"],
                cwd,
                env,
            )
            self.assertEqual(code, 0, err)
            self.assertIn("Entry moved to project:", out)
