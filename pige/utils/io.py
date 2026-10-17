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


def _copy_mode(path: Path, tmp_name: str) -> None:
    """Give the new file the permissions of the one it replaces (mkstemp creates 0600),
    or the usual umask-based mode for a new file."""
    if sys.platform.startswith("win"):
        return
    try:
        mode = path.stat().st_mode & 0o777
    except OSError:
        umask = os.umask(0)
        os.umask(umask)
        mode = 0o666 & ~umask
    os.chmod(tmp_name, mode)


def _atomic_write(path: Path, write: Any) -> None:
    ensure_parent(path)
    fd, tmp_name = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
    try:
        _copy_mode(path, tmp_name)
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
    """Append one JSON line and flush it to disk before returning.

    If a previous crash left a torn last line (no final newline), that fragment
    is moved to ``<file>.torn`` and cut off first, so the log stays readable.
    """
    ensure_parent(path)
    line = (json.dumps(obj, ensure_ascii=False) + "\n").encode("utf-8")
    with open(path, "ab+") as handle:
        _repair_torn_tail(path, handle)
        handle.seek(0, os.SEEK_END)
        handle.write(line)
        handle.flush()
        os.fsync(handle.fileno())


def _repair_torn_tail(path: Path, handle: Any) -> None:
    size = handle.seek(0, os.SEEK_END)
    if size == 0:
        return
    handle.seek(size - 1)
    if handle.read(1) == b"\n":
        return
    # Find the last newline, scanning backwards in blocks.
    end = size
    keep = 0
    while end > 0:
        start = max(0, end - 65536)
        handle.seek(start)
        block = handle.read(end - start)
        index = block.rfind(b"\n")
        if index != -1:
            keep = start + index + 1
            break
        end = start
    handle.seek(keep)
    fragment = handle.read()
    with open(Path(str(path) + ".torn"), "ab") as torn:
        torn.write(fragment + b"\n")
    handle.truncate(keep)
    logger.warning("Removed a torn last line from %s (saved to %s.torn)", path, path.name)


def read_jsonl(path: Path) -> list[Any]:
    """Read a JSONL file.

    A corrupt *last* line (a write interrupted by a crash or power loss, possibly
    cut inside a multi-byte character) is skipped with a warning; the next
    :func:`append_jsonl` removes it. Corruption anywhere else raises.
    """
    if not path.exists():
        return []
    raw_lines = path.read_bytes().split(b"\n")
    numbered = [(num, raw) for num, raw in enumerate(raw_lines, start=1) if raw.strip()]
    items: list[Any] = []
    for index, (line_num, raw) in enumerate(numbered):
        try:
            items.append(json.loads(raw.decode("utf-8")))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            if index == len(numbered) - 1:
                logger.warning("Ignoring torn last line %d of %s (interrupted write?)", line_num, path)
                continue
            raise ValueError(f"Error: Corrupt JSONL at {path} line {line_num}: {exc}") from exc
    return items


# --------------------------------------------------------------------- locking


class _ProcessLock:
    """The actual lock on one file, shared by every FileLock for that path in this process.

    flock/LockFileEx locks belong to an open file, so two independent opens of
    the same lock file in one process would block each other. Sharing one
    object per path avoids that (re-entrant within a thread).
    """

    def __init__(self, path: Path) -> None:
        self.path = path
        self.thread_lock = threading.RLock()
        self.depth = 0
        self.handle: Any = None

    def acquire(self) -> None:
        ensure_parent(self.path)
        handle = open(self.path, "a+b")
        try:
            if sys.platform.startswith("win"):
                _windows_lock(handle, self.path)
            else:
                import fcntl

                fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
        except BaseException:
            handle.close()
            raise
        self.handle = handle

    def release(self) -> None:
        handle, self.handle = self.handle, None
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


def _windows_lock(handle: Any, path: Path, warn_after: float = 30.0) -> None:
    if sys.platform == "win32":
        import errno
        import msvcrt
        import time

        started = time.monotonic()
        warned = False
        handle.seek(0)
        while True:
            try:
                msvcrt.locking(handle.fileno(), msvcrt.LK_LOCK, 1)  # retries ~10 s itself
                return
            except OSError as exc:
                if exc.errno not in (errno.EDEADLK, errno.EACCES):
                    raise
                if not warned and time.monotonic() - started > warn_after:
                    logger.warning("Waiting: another P.IGE process is using %s", path.parent)
                    warned = True


_PROCESS_LOCKS: dict[str, _ProcessLock] = {}
_PROCESS_LOCKS_GUARD = threading.Lock()


class FileLock:
    """Exclusive lock shared by every process using the same data directory.

    Re-entrant within a thread, so nested service calls do not deadlock, and
    shared by all FileLock objects for the same path in one process. Uses
    ``fcntl.flock`` on POSIX and ``msvcrt.locking`` on Windows; the OS releases
    the lock if the process dies.
    """

    def __init__(self, path: Path) -> None:
        self.path = path
        key = os.path.normcase(os.path.abspath(path))
        with _PROCESS_LOCKS_GUARD:
            self._shared = _PROCESS_LOCKS.setdefault(key, _ProcessLock(path))

    @contextmanager
    def hold(self) -> Iterator[None]:
        shared = self._shared
        with shared.thread_lock:
            if shared.depth == 0:
                shared.acquire()
            shared.depth += 1
            try:
                yield
            finally:
                shared.depth -= 1
                if shared.depth == 0:
                    shared.release()


def file_signature(path: Path) -> tuple[int, int] | None:
    """(mtime_ns, size) of ``path``, or None if missing: detects changes by other processes."""
    try:
        stat = path.stat()
    except OSError:
        return None
    return (stat.st_mtime_ns, stat.st_size)
