"""Counting time when blocks overlap (two things done at once).

Rules, applied to each stretch of time where the same blocks are running:

* one block alone counts in full;
* if one of the overlapping blocks is ``exclusive`` ("ne compter qu'ici"), the
  stretch goes to the exclusive block(s), split equally, and the others get nothing;
* otherwise, if one of them is ``both`` ("compter pour les deux"), every block
  counts the stretch in full;
* otherwise (``shared``, the default) the stretch is split equally, so the day's
  total matches the time actually present.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from fractions import Fraction
from typing import Iterable, Literal

OverlapMode = Literal["shared", "both", "exclusive"]


@dataclass(frozen=True)
class Span:
    id: str
    start: datetime
    end: datetime
    mode: OverlapMode = "shared"


def counted_seconds(spans: Iterable[Span]) -> dict[str, int]:
    """Seconds credited to each span, following the module rules."""
    items = list(spans)
    if len({s.id for s in items}) != len(items):
        raise ValueError("span ids must be unique")
    for s in items:
        if s.end <= s.start:
            raise ValueError(f"span {s.id} ends before it starts")
        if s.mode not in ("shared", "both", "exclusive"):
            raise ValueError(f"span {s.id} has unknown mode {s.mode!r}")
    credit: dict[str, Fraction] = {s.id: Fraction(0) for s in items}
    bounds = sorted({t for s in items for t in (s.start, s.end)})
    for a, b in zip(bounds, bounds[1:]):
        active = [s for s in items if s.start <= a and s.end >= b]
        if not active:
            continue
        length = _seconds(b - a)
        exclusive = [s for s in active if s.mode == "exclusive"]
        if exclusive:
            for s in exclusive:
                credit[s.id] += length / len(exclusive)
        elif any(s.mode == "both" for s in active):
            for s in active:
                credit[s.id] += length
        else:
            for s in active:
                credit[s.id] += length / len(active)
    return {key: round(value) for key, value in credit.items()}


def _seconds(delta: timedelta) -> Fraction:
    return Fraction(delta // timedelta(microseconds=1), 1_000_000)


def presence_seconds(spans: Iterable[Span]) -> int:
    """Wall-clock time covered by at least one span (overlaps counted once)."""
    total = Fraction(0)
    current_start: datetime | None = None
    current_end: datetime | None = None
    for s in sorted(spans, key=lambda x: x.start):
        if current_end is None or s.start > current_end:
            if current_start is not None and current_end is not None:
                total += _seconds(current_end - current_start)
            current_start, current_end = s.start, s.end
        elif s.end > current_end:
            current_end = s.end
    if current_start is not None and current_end is not None:
        total += _seconds(current_end - current_start)
    return round(total)
