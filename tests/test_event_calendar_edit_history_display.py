"""Event Details history and Edit Event-only presentation contracts."""

import ast
import unittest
from datetime import datetime
from pathlib import Path

from services.event_calendar_edit_history_view import (
    EventHistoryDisplayError,
    load_event_history_text,
)

ROOT = Path(__file__).resolve().parents[1]


class FakeCursor:
    def __init__(self, row):
        self.row = row
        self.calls = []

    def execute(self, sql, params):
        self.calls.append((sql, params))

    def fetchone(self):
        return self.row


class EventHistoryDisplayTests(unittest.TestCase):
    def test_never_edited_created_date_only(self):
        cur = FakeCursor((datetime(2026, 11, 7, 12, 1), None, None))
        text = load_event_history_text(cur, spa_id=44, workspace_id=41, event_id=14)
        self.assertEqual(text, "Created on November 7, 2026")

    def test_edited_in_business_local_timezone(self):
        cur = FakeCursor((
            datetime(2026, 11, 7, 12, 1),
            datetime(2026, 11, 10, 22, 52, 33),
            "Rick Conley",
        ))
        text = load_event_history_text(cur, spa_id=44, workspace_id=41, event_id=12)
        self.assertEqual(
            text,
            "This event was previously edited on November 10, 2026 at 10:52 PM by Rick Conley",
        )

    def test_latest_revision_and_business_timezone_selected(self):
        cur = FakeCursor((datetime(2026, 11, 1), None, None))
        load_event_history_text(cur, spa_id=44, workspace_id=41, event_id=12)
        sql, params = cur.calls[0]
        self.assertIn("ORDER BY h.revision_after DESC", sql)
        self.assertIn("LIMIT 1", sql)
        self.assertIn("AT TIME ZONE s.timezone_name", sql)
        self.assertIn("h.business_unit_id = e.business_unit_id", sql)
        self.assertEqual(params, (44, 41, 12))

    def test_reject_invalid_scope_before_database(self):
        for scope in ((44, True, 12), (44, 41, 0), ("44", 41, 12)):
            cur = FakeCursor(None)
            with self.subTest(scope=scope), self.assertRaises(EventHistoryDisplayError):
                load_event_history_text(
                    cur, spa_id=scope[0], workspace_id=scope[1], event_id=scope[2],
                )
            self.assertEqual(cur.calls, [])

    def test_missing_event_is_not_fabricated(self):
        cur = FakeCursor(None)
        with self.assertRaises(EventHistoryDisplayError):
            load_event_history_text(cur, spa_id=44, workspace_id=41, event_id=12)

    def test_invalid_missing_editor_rejected(self):
        cur = FakeCursor((datetime(2026, 11, 7), datetime(2026, 11, 10), " "))
        with self.assertRaises(EventHistoryDisplayError):
            load_event_history_text(cur, spa_id=44, workspace_id=41, event_id=12)

    def test_database_user_name_is_trimmed(self):
        cur = FakeCursor((datetime(2026, 11, 7), datetime(2026, 11, 10, 9, 5), "  Admin  "))
        result = load_event_history_text(cur, spa_id=44, workspace_id=41, event_id=12)
        self.assertTrue(result.endswith("at 9:05 AM by Admin"))

    def test_event_details_route_keeps_read_only_scope(self):
        code = (ROOT / "app.py").read_text()
        tree = ast.parse(code)
        func = next(n for n in tree.body if isinstance(n, ast.FunctionDef)
                    and n.name == "peachpos_event_calendar_details")
        block = "\n".join(code.splitlines()[func.lineno - 1:func.end_lineno])
        for text in (
            'cur.execute("SET TRANSACTION READ ONLY")',
            'details = get_event_details(',
            'details["history_text"] = load_event_history_text(',
            'spa_id=spa_id', 'workspace_id=workspace_id', 'event_id=event_id',
            'conn.rollback()', 'conn.close()',
        ):
            self.assertIn(text, block)
        self.assertNotIn('conn.commit()', block)

    def test_modal_uses_safe_text_injection(self):
        code = (ROOT / "templates/event_calendar_month.html").read_text()
        self.assertIn('const history = section("Event History");', code)
        self.assertIn('line(history, event.history_text', code)
        self.assertNotIn("innerHTML", code)

    def test_navigation_is_edit_only(self):
        code = (ROOT / "templates/event_new.html").read_text()
        self.assertIn("url_for('peachpos_event_calendar_month')", code)
        self.assertIn("Back to Event Calendar", code)
        self.assertIn("url_for('admin')", code)
        self.assertIn("Back to Calendar Settings", code)
        self.assertIn("{% if event_edit_id %}", code)

    def test_save_labels_change_without_affecting_create(self):
        code = (ROOT / "templates/event_new.html").read_text()
        self.assertIn("'Save Changes' if event_edit_id else 'Save Event'", code)
        self.assertIn('Save Changes updates this existing event', code)
        self.assertIn('Save Event records event details', code)
        self.assertIn("Step 2 — Save Your Changes", code)
        self.assertIn("Step 2 — Save Your Event", code)


if __name__ == "__main__":
    unittest.main()
