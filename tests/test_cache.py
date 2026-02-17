import unittest

from pige.core.cache import EntryCache
from pige.core.models import EntryMeta


class TestEntryCache(unittest.TestCase):
    def _create_entry(self, entry_id: str = "test123") -> EntryMeta:
        return EntryMeta(
            id=entry_id,
            project_id="proj123",
            type="note",
            title="Test Entry",
            tags=[],
            ts="2024-01-15T10:00:00Z",
            entry_date="2024-01-15",
            content_path="entries/test123.md",
        )

    def test_cache_initially_empty(self) -> None:
        cache = EntryCache()
        self.assertIsNone(cache.get_entries())
        self.assertFalse(cache.is_valid())

    def test_set_and_get_entries(self) -> None:
        cache = EntryCache()
        entries = [self._create_entry("e1"), self._create_entry("e2")]
        cache.set_entries(entries)
        
        cached = cache.get_entries()
        self.assertIsNotNone(cached)
        self.assertEqual(len(cached), 2)
        self.assertTrue(cache.is_valid())

    def test_invalidate_clears_cache(self) -> None:
        cache = EntryCache()
        entries = [self._create_entry()]
        cache.set_entries(entries)
        self.assertTrue(cache.is_valid())
        
        cache.invalidate()
        self.assertIsNone(cache.get_entries())
        self.assertFalse(cache.is_valid())

    def test_disable_cache(self) -> None:
        cache = EntryCache()
        entries = [self._create_entry()]
        cache.set_entries(entries)
        
        cache.disable()
        self.assertIsNone(cache.get_entries())
        self.assertFalse(cache.is_valid())
        
        # Setting entries while disabled should not cache
        cache.set_entries(entries)
        self.assertIsNone(cache.get_entries())

    def test_enable_cache(self) -> None:
        cache = EntryCache()
        cache.disable()
        
        cache.enable()
        entries = [self._create_entry()]
        cache.set_entries(entries)
        self.assertIsNotNone(cache.get_entries())

    def test_cache_returns_same_list(self) -> None:
        """Test that cache returns the same list for performance."""
        cache = EntryCache()
        entries = [self._create_entry("e1")]
        cache.set_entries(entries)
        
        cached1 = cache.get_entries()
        cached2 = cache.get_entries()
        
        # Both should have same content
        self.assertEqual(len(cached1), len(cached2))
        self.assertEqual(cached1[0].id, cached2[0].id)

    def test_get_stats(self) -> None:
        cache = EntryCache()
        stats = cache.get_stats()
        self.assertTrue(stats["enabled"])
        self.assertFalse(stats["has_data"])
        self.assertEqual(stats["entry_count"], 0)
        self.assertIsNone(stats["timestamp"])
        
        entries = [self._create_entry("e1"), self._create_entry("e2")]
        cache.set_entries(entries)
        
        stats = cache.get_stats()
        self.assertTrue(stats["enabled"])
        self.assertTrue(stats["has_data"])
        self.assertEqual(stats["entry_count"], 2)
        self.assertIsNotNone(stats["timestamp"])
