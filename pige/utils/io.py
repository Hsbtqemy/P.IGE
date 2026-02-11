from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any


def ensure_parent(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)


def safe_write_json(path: Path, data: Any) -> None:
    ensure_parent(path)
    tmp_path = Path(str(path) + ".tmp")
    with open(tmp_path, "w", encoding="utf-8") as handle:
        json.dump(data, handle, indent=2, ensure_ascii=False)
        handle.write("\n")
    os.replace(tmp_path, path)


def safe_write_text(path: Path, content: str) -> None:
    """Write text to path atomically (write to .tmp then rename)."""
    ensure_parent(path)
    tmp_path = Path(str(path) + ".tmp")
    with open(tmp_path, "w", encoding="utf-8") as handle:
        handle.write(content)
    os.replace(tmp_path, path)


def read_json(path: Path, default: Any | None = None) -> Any:
    if not path.exists():
        if default is not None:
            return default
        raise FileNotFoundError(path)
    with open(path, "r", encoding="utf-8") as handle:
        return json.load(handle)


def append_jsonl(path: Path, obj: Any) -> None:
    ensure_parent(path)
    line = json.dumps(obj, ensure_ascii=False)
    with open(path, "a", encoding="utf-8") as handle:
        handle.write(line + "\n")
        handle.flush()


def safe_write_jsonl(path: Path, items: Any) -> None:
    ensure_parent(path)
    tmp_path = Path(str(path) + ".tmp")
    with open(tmp_path, "w", encoding="utf-8") as handle:
        for item in items:
            line = json.dumps(item, ensure_ascii=False)
            handle.write(line + "\n")
    os.replace(tmp_path, path)


def read_jsonl(path: Path) -> list[Any]:
    if not path.exists():
        return []
    items: list[Any] = []
    with open(path, "r", encoding="utf-8") as handle:
        for line_num, line in enumerate(handle, start=1):
            payload = line.strip()
            try:
                items.append(json.loads(payload))
            except Exception as exc:  # pragma: no cover - line capture matters
                raise ValueError(
                    f"Error: Corrupt JSONL at {path} line {line_num}: {exc}"
                ) from exc
    return items
