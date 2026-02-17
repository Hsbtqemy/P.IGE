"""Advanced search query parser for PIGE entries.

Supports search queries with field-specific filters:
- tag:value - Filter by tag
- person:value - Filter by person
- group:value - Filter by group
- type:value - Filter by entry type (note, meeting, decision, log)
- date:value - Filter by entry date (YYYY-MM-DD)
- date:>=value - Filter entries on or after date
- date:<=value - Filter entries on or before date
- status:value - Filter by context status (created, actual, treated)
- title:value - Filter by title (case-insensitive substring)

Examples:
    >>> query = "tag:alpha person:John type:meeting"
    >>> filters = parse_search_query(query)
    >>> filters['tags']
    ['alpha']
    >>> filters['person']
    'John'
    
    >>> query = 'person:"Jane Doe" date:>=2024-01-01'
    >>> filters = parse_search_query(query)
    >>> filters['person']
    'Jane Doe'
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date
from typing import Any

from pige.core.models import EntryMeta
from pige.utils import dates


@dataclass
class SearchFilters:
    """Parsed search filters."""
    tags: list[str] = field(default_factory=list)
    person: str | None = None
    group: str | None = None
    entry_type: str | None = None
    entry_date: date | None = None
    entry_date_gte: date | None = None  # Greater than or equal
    entry_date_lte: date | None = None  # Less than or equal
    context_status: str | None = None
    title: str | None = None
    free_text: str | None = None  # Any remaining text not part of filters


def parse_search_query(query: str) -> SearchFilters:
    """Parse a search query string into structured filters.
    
    Args:
        query: Search query string with field:value patterns
        
    Returns:
        SearchFilters object with parsed filters
        
    Examples:
        >>> parse_search_query("tag:alpha person:John")
        SearchFilters(tags=['alpha'], person='John', ...)
        
        >>> parse_search_query('person:"Jane Doe" type:meeting')
        SearchFilters(person='Jane Doe', entry_type='meeting', ...)
    """
    filters = SearchFilters()
    
    if not query or not query.strip():
        return filters
    
    # Pattern to match field:value or field:"quoted value"
    # Supports: field:value, field:"quoted value", field:>=value, field:<=value
    pattern = r'(\w+):(>=|<=|>|<)?(?:"([^"]*)"|(\S+))'
    
    matches = re.finditer(pattern, query)
    matched_positions = []
    
    for match in matches:
        matched_positions.append((match.start(), match.end()))
        field = match.group(1).lower()
        operator = match.group(2)  # Can be None, '>=', '<=', '>', '<'
        quoted_value = match.group(3)  # Value in quotes
        unquoted_value = match.group(4)  # Value without quotes
        value = quoted_value if quoted_value is not None else unquoted_value
        
        if not value:
            continue
        
        # Process field-specific filters
        if field == "tag":
            filters.tags.append(value)
        elif field == "person":
            filters.person = value
        elif field == "group":
            filters.group = value
        elif field == "type":
            filters.entry_type = value
        elif field == "date":
            try:
                parsed_date = dates.parse_date(value)
                if operator == ">=":
                    filters.entry_date_gte = parsed_date
                elif operator == "<=":
                    filters.entry_date_lte = parsed_date
                elif operator in (">", "<"):
                    # For now, treat > as >= and < as <=
                    if operator == ">":
                        filters.entry_date_gte = parsed_date
                    else:
                        filters.entry_date_lte = parsed_date
                else:
                    filters.entry_date = parsed_date
            except ValueError:
                # Invalid date, skip
                pass
        elif field == "status":
            if value.lower() in ("created", "actual", "treated"):
                filters.context_status = value.lower()
        elif field == "title":
            filters.title = value
    
    # Extract free text (anything not matched by field:value patterns)
    free_text_parts = []
    last_end = 0
    for start, end in matched_positions:
        if start > last_end:
            free_text_parts.append(query[last_end:start])
        last_end = end
    if last_end < len(query):
        free_text_parts.append(query[last_end:])
    
    free_text = " ".join(part.strip() for part in free_text_parts if part.strip())
    if free_text:
        filters.free_text = free_text
    
    return filters


def apply_search_filters(entries: list[EntryMeta], filters: SearchFilters) -> list[EntryMeta]:
    """Apply search filters to a list of entries.
    
    Args:
        entries: List of entry metadata to filter
        filters: Parsed search filters
        
    Returns:
        Filtered list of entries
    """
    if not filters:
        return entries
    
    result = []
    
    for entry in entries:
        # Check tags filter (all specified tags must be present)
        if filters.tags:
            entry_tags_lower = [t.lower() for t in entry.tags]
            if not all(tag.lower() in entry_tags_lower for tag in filters.tags):
                continue
        
        # Check person filter
        if filters.person:
            if not entry.person or filters.person.lower() not in entry.person.lower():
                continue
        
        # Check group filter
        if filters.group:
            if not entry.group or filters.group.lower() not in entry.group.lower():
                continue
        
        # Check entry type filter
        if filters.entry_type:
            if entry.type != filters.entry_type.lower():
                continue
        
        # Check exact date filter
        if filters.entry_date:
            if entry.entry_date != filters.entry_date:
                continue
        
        # Check date >= filter
        if filters.entry_date_gte:
            if entry.entry_date < filters.entry_date_gte:
                continue
        
        # Check date <= filter
        if filters.entry_date_lte:
            if entry.entry_date > filters.entry_date_lte:
                continue
        
        # Check context status filter
        if filters.context_status:
            if entry.context_status != filters.context_status:
                continue
        
        # Check title filter (case-insensitive substring)
        if filters.title:
            if filters.title.lower() not in entry.title.lower():
                continue
        
        # Check free text (searches in title)
        if filters.free_text:
            if filters.free_text.lower() not in entry.title.lower():
                continue
        
        # Entry passed all filters
        result.append(entry)
    
    return result


def format_search_query_help() -> str:
    """Return help text for search query syntax.
    
    Returns:
        Multi-line help text string
    """
    return """
Search Query Syntax:

  field:value           - Search by field
  field:"quoted value"  - Value with spaces
  
Available Fields:
  tag:VALUE            - Filter by tag (can specify multiple)
  person:VALUE         - Filter by person (substring match)
  group:VALUE          - Filter by group (substring match)
  type:VALUE           - Filter by type (note, meeting, decision, log)
  date:YYYY-MM-DD      - Filter by exact date
  date:>=YYYY-MM-DD    - Filter entries on or after date
  date:<=YYYY-MM-DD    - Filter entries on or before date
  status:VALUE         - Filter by status (created, actual, treated)
  title:VALUE          - Filter by title (substring match)

Examples:
  tag:alpha person:John type:meeting
  person:"Jane Doe" date:>=2024-01-01
  type:decision date:<=2024-12-31 tag:urgent
  title:sprint date:>=2024-01-01 date:<=2024-01-31

Any text not matching field:value is treated as free text and searches in titles.
""".strip()
