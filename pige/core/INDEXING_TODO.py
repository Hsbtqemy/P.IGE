"""
⚠️ IMPORTANT: Auto-indexing is currently DISABLED

The automatic indexing feature in storage.py is disabled due to a 
PermissionError on Windows when running tests. The SQLite connection 
was not being closed properly, causing test cleanup to fail.

CURRENT STATE:
✅ FTS5 module fully functional (pige/core/indexing.py)
✅ CLI command works: python -m pige rebuild-index
✅ 12 FTS tests pass
❌ Auto-indexing on create/update/delete is disabled

WHY DISABLED:
- PermissionError when deleting temp .pige_index.db in tests
- Connection not closed in time (Python GC issue on Windows)
- 88 tests were failing with current implementation

SOLUTION TO IMPLEMENT:
Use context manager pattern for SearchIndex to guarantee connection closure.

See TODO_FTS5_INDEXATION_AUTO.md in project root for:
- Detailed problem analysis
- Multiple solution approaches
- Implementation checklist
- Performance benchmarks to run

PRIORITY: HIGH
Implement this before Phase 4 to enable real-time search for 10K+ entries.

LOCATIONS TO UPDATE:
- pige/core/indexing.py: Add __enter__ and __exit__
- pige/core/storage.py: Re-enable indexing in append_* methods
- Remove self._search_index cache (use with statement instead)

ESTIMATED TIME: 30-45 minutes
"""
