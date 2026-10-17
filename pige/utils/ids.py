import re
import uuid

_ID_RE = re.compile(r"^[0-9a-f]{32}$")


def new_id() -> str:
    return uuid.uuid4().hex


def is_valid_id(value: object) -> bool:
    """True for ids in the format produced by :func:`new_id` (32 lowercase hex)."""
    return isinstance(value, str) and bool(_ID_RE.match(value))


_SAFE_RE = re.compile(r"^[A-Za-z0-9_-]{1,64}$")


def is_safe_id(value: object) -> bool:
    """True for ids usable as a file name: letters, digits, '-' and '_' only.

    Looser than :func:`is_valid_id` (older data and tests use other shapes) but
    rules out path separators and '..'.
    """
    return isinstance(value, str) and bool(_SAFE_RE.match(value))
