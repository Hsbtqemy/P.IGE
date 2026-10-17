"""Simple in-memory cache for PIGE entries with intelligent invalidation.

This cache improves performance by avoiding repeated reads of entries.jsonl,
especially useful for large projects with 1000+ entries.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any

from pige.core.models import EntryMeta


@dataclass
class CacheEntry:
    """Cached data with timestamp."""
    data: Any
    timestamp: datetime


class EntryCache:
    """In-memory cache for entry metadata with intelligent invalidation."""
    
    def __init__(self) -> None:
        self._entries: list[EntryMeta] | None = None
        self._timestamp: datetime | None = None
        self._signature: object = None
        self._enabled = True
    
    def get_entries(self, signature: object = None) -> list[EntryMeta] | None:
        """Get cached entries if available and valid.
        
        Returns:
            List of cached entries or None if cache is empty/invalid
        """
        if not self._enabled:
            return None
        if signature is not None and signature != self._signature:
            # The file changed on disk since it was cached (possibly another process).
            return None
        return self._entries
    
    def set_entries(self, entries: list[EntryMeta], signature: object = None) -> None:
        """Store entries in cache.
        
        Args:
            entries: List of entry metadata to cache
        """
        if not self._enabled:
            return
        self._entries = entries  # Store reference (no copy for performance)
        self._timestamp = datetime.now()
        self._signature = signature
    
    def invalidate(self) -> None:
        """Invalidate the cache (clear all cached data)."""
        self._entries = None
        self._timestamp = None
    
    def is_valid(self) -> bool:
        """Check if cache contains valid data.
        
        Returns:
            True if cache has data, False otherwise
        """
        return self._entries is not None and self._enabled
    
    def enable(self) -> None:
        """Enable the cache."""
        self._enabled = True
    
    def disable(self) -> None:
        """Disable the cache and clear data."""
        self._enabled = False
        self.invalidate()
    
    def get_stats(self) -> dict[str, Any]:
        """Get cache statistics.
        
        Returns:
            Dictionary with cache stats (size, timestamp, enabled)
        """
        return {
            "enabled": self._enabled,
            "has_data": self._entries is not None,
            "entry_count": len(self._entries) if self._entries else 0,
            "timestamp": self._timestamp.isoformat() if self._timestamp else None,
        }
