"""File helpers: crash-safe writes, tolerant JSONL reads, inter-process locking.

Every whole-file write goes to a unique temporary file in the same directory,
is flushed to disk (fsync), then atomically renamed over the target. A crash at
any point leaves either the old file or the new one, never a half-written one.
"""

from __future__ import annotations

import json
import logging
import os
import sys
import tempfile
import threading
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterable, Iterator

logger = logging.getLogger(__name__)


def ensure_parent(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)


def _fsync_dir(directory: Path) -> None:
    """Persist a rename on POSIX (the directory entry must reach the disk too)."""
    if sys.platform.startswith("win"):
        return
    try:
        fd = os.open(directory, os.O_RDONLY)
    except OSError:
        return
    try:
        os.fsync(fd)
    except OSError:
        pass
    finally:
        os.close(fd)


def _atomic_write(path: Path, write: Any) -> None:
    ensure_parent(path)
    fd, tmp_name = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as handle:
            write(handle)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp_name, path)
    except BaseException:
        try:
            os.unlink(tmp_name)
        except OSError:
            pass
        raise
    _fsync_dir(path.parent)


def safe_write_json(path: Path, data: Any) -> None:
    def write(handle: Any) -> None:
        json.dump(data, handle, indent=2, ensure_ascii=False)
        handle.write("\n")

    _atomic_write(path, write)


def safe_write_text(path: Path, content: str) -> None:
    """Write text to ``path`` atomically and durably."""
    _atomic_write(path, lambda handle: handle.write(content))


def safe_write_jsonl(path: Path, items: Iterable[Any]) -> None:
    def write(handle: Any) -> None:
        for item in items:
            handle.write(json.dumps(item, ensure_ascii=False) + "\n")

    _atomic_write(path, write)


def read_json(path: Path, default: Any | None = None) -> Any:
    if not path.exists():
        if default is not None:
            return default
        raise FileNotFoundError(path)
    with open(path, "r", encoding="utf-8") as handle:
        return json.load(handle)


def append_jsonl(path: Path, obj: Any) -> None:
    """Append one JSON line and flush it to disk before returning."""
    ensure_parent(path)
    line = json.dumps(obj, ensure_ascii=False)
    with open(path, "a+", encoding="utf-8", newline="\n") as handle:
        # If a previous crash left a line without its newline, start a fresh line
        # so the new record is not glued to the broken one.
        handle.seek(0, os.SEEK_END)
        if handle.tell() > 0:
            handle.seek(handle.tell() - 1)
            if handle.read(1) != "\n":
                handle.write("\n")
        handle.write(line + "\n")
        handle.flush()
        os.fsync(handle.fileno())


def read_jsonl(path: Path) -> list[Any]:
    """Read a JSONL file.

    A corrupt *last* line (typically a write interrupted by a crash or power
    loss) is skipped with a warning, so one torn record never makes the whole
    file unreadable. Corruption anywhere else is a real problem and raises.
    """
    if not path.exists():
        return []
    with open(path, "r", encoding="utf-8") as handle:
        lines = handle.read().split("\n")
    numbered = [(num, line.strip()) for num, line in enumerate(lines, start=1) if line.strip()]
    items: list[Any] = []
    for index, (line_num, payload) in enumerate(numbered):
        try:
            items.append(json.loads(payload))
        except json.JSONDecodeError as exc:
            if index == len(numbered) - 1:
                logger.warning(
                    "Ignoring truncated last line %d of %s (interrupted write?): %s",
                    line_num, path, exc,
                )
                continue
            raise ValueError(f"Error: Corrupt JSONL at {path} line {line_num}: {exc}") from exc
    return items


# --------------------------------------------------------------------- locking


class FileLock:
    """Exclusive lock shared by every process using the same data directory.

    Re-entrant within a thread, so nested service calls do not deadlock. Uses
    ``fcntl.flock`` on POSIX and ``msvcrt.locking`` on Windows; both locks are
    released by the OS if the process dies.
    """

    def __init__(self, path: Path) -> None:
        self.path = path
        self._thread_lock = threading.RLock()
        self._depth = 0
        self._handle: Any = None

    @contextmanager
    def hold(self) -> Iterator[None]:
        with self._thread_lock:
            if self._depth == 0:
                self._acquire()
            self._depth += 1
            try:
                yield
            finally:
                self._depth -= 1
                if self._depth == 0:
                    self._release()

    def _acquire(self) -> None:
        ensure_parent(self.path)
        handle = open(self.path, "a+b")
        try:
            if sys.platform.startswith("win"):
                import msvcrt

                handle.seek(0)
                while True:
                    try:
                        msvcrt.locking(handle.fileno(), msvcrt.LK_LOCK, 1)
                        break
                    except OSError:
                        continue  # LK_LOCK gives up after ~10 s; keep waiting
            else:
                import fcntl

                fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
        except BaseException:
            handle.close()
            raise
        self._handle = handle

    def _release(self) -> None:
        handle, self._handle = self._handle, None
        if handle is None:
            return
        try:
            if sys.platform.startswith("win"):
                import msvcrt

                handle.seek(0)
                msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                import fcntl

                fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
        finally:
            handle.close()


def file_signature(path: Path) -> tuple[int, int] | None:
    """(mtime_ns, size) of ``path``, or None if missing: detects changes by other processes."""
    try:
        stat = path.stat()
    except OSError:
        return None
    return (stat.st_mtime_ns, stat.st_size)
