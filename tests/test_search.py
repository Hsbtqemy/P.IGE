import unittest
from datetime import date

from pige.core.models import EntryMeta
from pige.core.search import (
    SearchFilters,
    apply_search_filters,
    parse_search_query,
)


class TestSearchParser(unittest.TestCase):
    def test_parse_empty_query(self) -> None:
        filters = parse_search_query("")
        self.assertEqual(filters.tags, [])
        self.assertIsNone(filters.person)
        self.assertIsNone(filters.entry_type)

    def test_parse_single_tag(self) -> None:
        filters = parse_search_query("tag:alpha")
        self.assertEqual(filters.tags, ["alpha"])

    def test_parse_multiple_tags(self) -> None:
        filters = parse_search_query("tag:alpha tag:beta tag:gamma")
        self.assertEqual(filters.tags, ["alpha", "beta", "gamma"])

    def test_parse_person(self) -> None:
        filters = parse_search_query("person:John")
        self.assertEqual(filters.person, "John")

    def test_parse_person_quoted(self) -> None:
        filters = parse_search_query('person:"Jane Doe"')
        self.assertEqual(filters.person, "Jane Doe")

    def test_parse_group(self) -> None:
        filters = parse_search_query("group:DevTeam")
        self.assertEqual(filters.group, "DevTeam")

    def test_parse_type(self) -> None:
        filters = parse_search_query("type:meeting")
        self.assertEqual(filters.entry_type, "meeting")

    def test_parse_exact_date(self) -> None:
        filters = parse_search_query("date:2024-01-15")
        self.assertEqual(filters.entry_date, date(2024, 1, 15))

    def test_parse_date_gte(self) -> None:
        filters = parse_search_query("date:>=2024-01-01")
        self.assertEqual(filters.entry_date_gte, date(2024, 1, 1))
        self.assertIsNone(filters.entry_date)

    def test_parse_date_lte(self) -> None:
        filters = parse_search_query("date:<=2024-12-31")
        self.assertEqual(filters.entry_date_lte, date(2024, 12, 31))
        self.assertIsNone(filters.entry_date)

    def test_parse_date_range(self) -> None:
        filters = parse_search_query("date:>=2024-01-01 date:<=2024-12-31")
        self.assertEqual(filters.entry_date_gte, date(2024, 1, 1))
        self.assertEqual(filters.entry_date_lte, date(2024, 12, 31))

    def test_parse_status(self) -> None:
        filters = parse_search_query("status:actual")
        self.assertEqual(filters.context_status, "actual")

    def test_parse_title(self) -> None:
        filters = parse_search_query("title:sprint")
        self.assertEqual(filters.title, "sprint")

    def test_parse_complex_query(self) -> None:
        query = 'tag:alpha tag:beta person:"John Doe" type:meeting date:>=2024-01-01'
        filters = parse_search_query(query)
        self.assertEqual(filters.tags, ["alpha", "beta"])
        self.assertEqual(filters.person, "John Doe")
        self.assertEqual(filters.entry_type, "meeting")
        self.assertEqual(filters.entry_date_gte, date(2024, 1, 1))

    def test_parse_with_free_text(self) -> None:
        filters = parse_search_query("tag:alpha important meeting type:meeting")
        self.assertEqual(filters.tags, ["alpha"])
        self.assertEqual(filters.entry_type, "meeting")
        self.assertEqual(filters.free_text, "important meeting")

    def test_parse_invalid_date_ignored(self) -> None:
        filters = parse_search_query("date:invalid")
        self.assertIsNone(filters.entry_date)


class TestSearchFilters(unittest.TestCase):
    def _create_entry(
        self,
        entry_id: str = "test123",
        title: str = "Test Entry",
        entry_type: str = "note",
        tags: list[str] | None = None,
        person: str | None = None,
        group: str | None = None,
        entry_date: date | None = None,
        context_status: str = "created",
    ) -> EntryMeta:
        return EntryMeta(
            id=entry_id,
            project_id="proj123",
            type=entry_type,
            title=title,
            tags=tags or [],
            ts="2024-01-15T10:00:00Z",
            entry_date=entry_date or date(2024, 1, 15),
            content_path="",
            person=person,
            group=group,
            context_status=context_status,
        )

    def test_filter_by_single_tag(self) -> None:
        entries = [
            self._create_entry("e1", tags=["alpha", "beta"]),
            self._create_entry("e2", tags=["beta", "gamma"]),
            self._create_entry("e3", tags=["gamma"]),
        ]
        filters = SearchFilters(tags=["alpha"])
        result = apply_search_filters(entries, filters)
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0].id, "e1")

    def test_filter_by_multiple_tags_all_required(self) -> None:
        entries = [
            self._create_entry("e1", tags=["alpha", "beta"]),
            self._create_entry("e2", tags=["beta", "gamma"]),
            self._create_entry("e3", tags=["alpha"]),
        ]
        filters = SearchFilters(tags=["alpha", "beta"])
        result = apply_search_filters(entries, filters)
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0].id, "e1")

    def test_filter_by_person(self) -> None:
        entries = [
            self._create_entry("e1", person="John Doe"),
            self._create_entry("e2", person="Jane Smith"),
            self._create_entry("e3", person=None),
        ]
        filters = SearchFilters(person="John")
        result = apply_search_filters(entries, filters)
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0].id, "e1")

    def test_filter_by_type(self) -> None:
        entries = [
            self._create_entry("e1", entry_type="note"),
            self._create_entry("e2", entry_type="meeting"),
            self._create_entry("e3", entry_type="decision"),
        ]
        filters = SearchFilters(entry_type="meeting")
        result = apply_search_filters(entries, filters)
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0].id, "e2")

    def test_filter_by_exact_date(self) -> None:
        entries = [
            self._create_entry("e1", entry_date=date(2024, 1, 10)),
            self._create_entry("e2", entry_date=date(2024, 1, 15)),
            self._create_entry("e3", entry_date=date(2024, 1, 20)),
        ]
        filters = SearchFilters(entry_date=date(2024, 1, 15))
        result = apply_search_filters(entries, filters)
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0].id, "e2")

    def test_filter_by_date_gte(self) -> None:
        entries = [
            self._create_entry("e1", entry_date=date(2024, 1, 10)),
            self._create_entry("e2", entry_date=date(2024, 1, 15)),
            self._create_entry("e3", entry_date=date(2024, 1, 20)),
        ]
        filters = SearchFilters(entry_date_gte=date(2024, 1, 15))
        result = apply_search_filters(entries, filters)
        self.assertEqual(len(result), 2)
        self.assertIn("e2", [e.id for e in result])
        self.assertIn("e3", [e.id for e in result])

    def test_filter_by_date_lte(self) -> None:
        entries = [
            self._create_entry("e1", entry_date=date(2024, 1, 10)),
            self._create_entry("e2", entry_date=date(2024, 1, 15)),
            self._create_entry("e3", entry_date=date(2024, 1, 20)),
        ]
        filters = SearchFilters(entry_date_lte=date(2024, 1, 15))
        result = apply_search_filters(entries, filters)
        self.assertEqual(len(result), 2)
        self.assertIn("e1", [e.id for e in result])
        self.assertIn("e2", [e.id for e in result])

    def test_filter_by_date_range(self) -> None:
        entries = [
            self._create_entry("e1", entry_date=date(2024, 1, 5)),
            self._create_entry("e2", entry_date=date(2024, 1, 15)),
            self._create_entry("e3", entry_date=date(2024, 1, 25)),
        ]
        filters = SearchFilters(
            entry_date_gte=date(2024, 1, 10),
            entry_date_lte=date(2024, 1, 20),
        )
        result = apply_search_filters(entries, filters)
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0].id, "e2")

    def test_filter_by_title(self) -> None:
        entries = [
            self._create_entry("e1", title="Sprint Planning"),
            self._create_entry("e2", title="Daily Standup"),
            self._create_entry("e3", title="Sprint Review"),
        ]
        filters = SearchFilters(title="sprint")
        result = apply_search_filters(entries, filters)
        self.assertEqual(len(result), 2)
        self.assertIn("e1", [e.id for e in result])
        self.assertIn("e3", [e.id for e in result])

    def test_filter_combined(self) -> None:
        entries = [
            self._create_entry(
                "e1",
                entry_type="meeting",
                tags=["sprint"],
                person="John",
                entry_date=date(2024, 1, 15),
            ),
            self._create_entry(
                "e2",
                entry_type="note",
                tags=["sprint"],
                person="John",
                entry_date=date(2024, 1, 15),
            ),
            self._create_entry(
                "e3",
                entry_type="meeting",
                tags=["daily"],
                person="John",
                entry_date=date(2024, 1, 15),
            ),
        ]
        filters = SearchFilters(
            tags=["sprint"],
            entry_type="meeting",
            person="John",
        )
        result = apply_search_filters(entries, filters)
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0].id, "e1")

    def test_no_filters_returns_all(self) -> None:
        entries = [
            self._create_entry("e1"),
            self._create_entry("e2"),
            self._create_entry("e3"),
        ]
        filters = SearchFilters()
        result = apply_search_filters(entries, filters)
        self.assertEqual(len(result), 3)
