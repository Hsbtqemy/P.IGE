from __future__ import annotations

from datetime import date, timedelta
from types import SimpleNamespace
import unittest

from pige.core.models import EntryMeta, Task
from pige.interfaces.gui.panels.calendar_panel import CalendarPanel


class TestCalendarPanelHelpers(unittest.TestCase):
    def _panel(self) -> CalendarPanel:
        # Bypass Tk construction: helper methods tested here are pure.
        return object.__new__(CalendarPanel)

    def test_sort_day_tasks_prioritizes_overdue_then_due_today_then_done(self) -> None:
        panel = self._panel()
        today = date.today()

        overdue_open = Task(
            id="t1",
            project_id="p1",
            title="Overdue open",
            status="open",
            created_at="",
            due_date=(today - timedelta(days=1)).isoformat(),
        )
        due_today_in_progress = Task(
            id="t2",
            project_id="p1",
            title="Due today in progress",
            status="in_progress",
            created_at="",
            due_date=today.isoformat(),
        )
        due_today_done = Task(
            id="t3",
            project_id="p1",
            title="Done today",
            status="done",
            created_at="",
            due_date=today.isoformat(),
        )

        result = panel._sort_day_tasks([due_today_done, due_today_in_progress, overdue_open])
        self.assertEqual([task.id for task in result], ["t1", "t2", "t3"])

    def test_sort_day_entries_meeting_before_decision_before_note(self) -> None:
        panel = self._panel()

        note = EntryMeta(
            id="e1",
            ts="2026-01-01T09:00:00Z",
            project_id="p1",
            type="note",
            title="Note",
            tags=[],
            content_path="entries/e1.md",
            entry_date="2026-01-01",
            priority=3,
        )
        decision = EntryMeta(
            id="e2",
            ts="2026-01-01T08:00:00Z",
            project_id="p1",
            type="decision",
            title="Decision",
            tags=[],
            content_path="entries/e2.md",
            entry_date="2026-01-01",
            priority=3,
        )
        meeting = EntryMeta(
            id="e3",
            ts="2026-01-01T07:00:00Z",
            project_id="p1",
            type="meeting",
            title="Meeting",
            tags=[],
            content_path="entries/e3.md",
            entry_date="2026-01-01",
            start_time="09:30",
            priority=3,
        )

        result = panel._sort_day_entries([note, decision, meeting])
        self.assertEqual([entry.id for entry in result], ["e3", "e2", "e1"])

    def test_sort_day_events_orders_by_time_then_title(self) -> None:
        panel = self._panel()

        event_a = SimpleNamespace(id="a", title="Alpha", start_time="10:00:00")
        event_b = SimpleNamespace(id="b", title="Beta", start_time="09:00:00")
        event_c = SimpleNamespace(id="c", title="Gamma", start_time="09:00:00")

        result = panel._sort_day_events([event_a, event_c, event_b])
        self.assertEqual([event.id for event in result], ["b", "c", "a"])


if __name__ == "__main__":
    unittest.main()
