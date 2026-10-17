import re
import uuid

_ID_RE = re.compile(r"^[0-9a-f]{32}$")


def new_id() -> str:
    return uuid.uuid4().hex


def is_valid_id(value: object) -> bool:
    """True for ids in the format produced by :func:`new_id` (32 lowercase hex)."""
    return isinstance(value, str) and bool(_ID_RE.match(value))
