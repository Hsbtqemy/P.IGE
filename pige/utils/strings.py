import re
from typing import Iterable


def parse_tags(raw: str | None) -> list[str]:
    if not raw:
        return []
    tags: list[str] = []
    for part in raw.split(","):
        tag = part.strip()
        if tag:
            tags.append(tag)
    return tags


def format_tags(tags: Iterable[str]) -> str:
    tags_list = list(tags)
    return ", ".join(tags_list) if tags_list else "-"


def sanitize_project_name(name: str) -> str:
    sanitized = re.sub(r"[^\w\s-]", "", name).strip().replace(" ", "_").lower()
    return sanitized[:50]


def split_people(text: str | None) -> list[str]:
    if not text:
        return []
    seen: set[str] = set()
    people: list[str] = []
    for line in str(text).splitlines():
        name = line.strip()
        if not name:
            continue
        key = name.lower()
        if key in seen:
            continue
        seen.add(key)
        people.append(name)
    return people


def join_people_storage(people: Iterable[str]) -> str:
    return "\n".join(list(people))


def format_people_inline(text: str | None, max_items: int = 3) -> str:
    people = split_people(text)
    if not people:
        return ""
    label = ", ".join(people[:max_items])
    if len(people) > max_items:
        label = f"{label}..."
    return label
