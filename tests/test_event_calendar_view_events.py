"""EC-065-2A read-only View Events model and additive migration tests."""
import unittest
from datetime import date, datetime, timezone
from pathlib import Path
from services.event_calendar_view_events import (
    COLUMNS, ViewEventsError, list_view_events, validate_next_date_reference,
)

def sample_row(*, archived_at=None, next_date_reference="Oct 5-8"):
    return (21, "Keller Fall Festival", date(2026, 12, 4),
            date(2026, 12, 6), "Keller", "TX", "Keller Park",
            "Sample Coordinator", "555-0000", "sample@example.invalid",
            "scheduled", next_date_reference, archived_at)

class FakeCursor:
    def __init__(self, rows):
        self.rows = rows
        self.calls = []
        self.closed = False
    def execute(self, statement, params):
        self.calls.append((statement, params))
    def fetchall(self):
        return self.rows
    def close(self):
        self.closed = True

class FakeConn:
    def __init__(self, rows):
        self.cursor_obj = FakeCursor(rows)
    def cursor(self):
        return self.cursor_obj

class ViewEventsTests(unittest.TestCase):
    def test_single_row_per_event_and_values(self):
        conn = FakeConn([sample_row()])
        found = list_view_events(conn, 44, 41)
        self.assertEqual(len(found["events"]), 1)
        self.assertEqual(found["events"][0]["event_id"], 21)
        self.assertEqual(found["events"][0]["next_date_display"], "Oct 5-8")
        self.assertFalse(found["events"][0]["is_archived"])
    def test_missing_metadata_displays_not_scheduled(self):
        found = list_view_events(FakeConn([sample_row(next_date_reference="")]),44,41)
        self.assertEqual(found["events"][0]["next_date_display"], "Not Scheduled")
    def test_archived_status_mapping(self):
        now = datetime.now(timezone.utc)
        found = list_view_events(FakeConn([sample_row(archived_at=now)]),44,41,
                                 archive_mode="all")
        self.assertTrue(found["events"][0]["is_archived"])
    def test_workspace_scope_bound_not_injected(self):
        conn = FakeConn([])
        list_view_events(conn,44,41)
        sql, params = conn.cursor_obj.calls[0]
        self.assertIn("e.spa_id = %s AND e.business_unit_id = %s",sql)
        self.assertEqual(params[:2], (44,41))
        self.assertNotIn("44", sql)
        self.assertNotIn("41", sql)
    def test_metadata_join_scoped_to_event(self):
        conn = FakeConn([]);list_view_events(conn,44,41)
        sql = conn.cursor_obj.calls[0][0]
        self.assertIn("m.event_id = e.event_id",sql)
        self.assertIn("m.spa_id = e.spa_id",sql)
        self.assertIn("m.business_unit_id = e.business_unit_id",sql)
    def test_read_only_select_query(self):
        conn=FakeConn([]);list_view_events(conn,44,41)
        sql=conn.cursor_obj.calls[0][0]
        self.assertTrue(sql.strip().upper().startswith("SELECT"))
        self.assertNotIn("UPDATE ",sql.upper())
        self.assertNotIn("INSERT ",sql.upper())
        self.assertTrue(conn.cursor_obj.closed)
    def test_date_window_includes_overlapping_events(self):
        conn=FakeConn([])
        list_view_events(conn,44,41,start_date=date(2026,12,5),end_date=date(2026,12,6))
        sql,params=conn.cursor_obj.calls[0]
        self.assertIn("e.end_date >= %s",sql)
        self.assertIn("e.start_date <= %s",sql)
        self.assertIn(date(2026,12,5),params)
    def test_search_parameterized_literal(self):
        conn=FakeConn([])
        list_view_events(conn,44,41,search="Keller' OR 1=1 --")
        sql,params=conn.cursor_obj.calls[0]
        self.assertNotIn("OR 1=1",sql)
        self.assertIn("Keller' OR 1=1 --",params)
    def test_status_filter(self):
        conn=FakeConn([])
        list_view_events(conn,44,41,status="confirmed")
        self.assertIn("e.event_status = %s",conn.cursor_obj.calls[0][0])
        self.assertIn("confirmed",conn.cursor_obj.calls[0][1])
    def test_archive_filter_active(self):
        conn=FakeConn([]);list_view_events(conn,44,41)
        self.assertIn("m.archived_at IS NULL",conn.cursor_obj.calls[0][0])
    def test_archive_filter_archived(self):
        conn=FakeConn([]);list_view_events(conn,44,41,archive_mode="archived")
        self.assertIn("m.archived_at IS NOT NULL",conn.cursor_obj.calls[0][0])
    def test_archive_filter_all(self):
        conn=FakeConn([]);list_view_events(conn,44,41,archive_mode="all")
        sql=conn.cursor_obj.calls[0][0]
        self.assertNotIn("m.archived_at IS NULL",sql)
        self.assertNotIn("m.archived_at IS NOT NULL",sql)
    def test_pagination_has_more(self):
        conn=FakeConn([sample_row(),sample_row()])
        result=list_view_events(conn,44,41,limit=1,offset=5)
        self.assertTrue(result["has_more"])
        self.assertEqual(len(result["events"]),1)
        self.assertEqual(conn.cursor_obj.calls[0][1][-2:],(2,5))
    def test_invalid_business_scopes(self):
        for a,b in ((0,41),(44,0),(True,41),(44,"41"),(-1,41)):
            with self.subTest(a=a,b=b), self.assertRaises(ViewEventsError):
                list_view_events(FakeConn([]),a,b)
    def test_invalid_filters(self):
        bad = ({"status":"pending"},{"archive_mode":"private"},
               {"search":"a"*101},{"limit":0},{"offset":-1},
               {"limit":True},{"start_date":"2026-12-01"})
        for kw in bad:
            with self.subTest(kw=kw),self.assertRaises(ViewEventsError):
                list_view_events(FakeConn([]),44,41,**kw)
    def test_invalid_reversed_dates(self):
        with self.assertRaises(ViewEventsError):
            list_view_events(FakeConn([]),44,41,
                             start_date=date(2027,1,1),end_date=date(2026,1,1))
    def test_unknown_row_shape_rejected(self):
        with self.assertRaises(RuntimeError):
            list_view_events(FakeConn([(21,)]),44,41)
    def test_free_text_variants_preserved(self):
        for value in ("Oct 5","Oct 5-8","10/5-8","October 5–8, 2027"):
            self.assertEqual(validate_next_date_reference(value),value)
    def test_blank_reference(self):
        self.assertEqual(validate_next_date_reference(None),"")
        self.assertEqual(validate_next_date_reference("  "),"")
    def test_reject_long_or_multiline_reference(self):
        for value in ("x"*121,"Oct 5\nOct 6","\0date",123):
            with self.subTest(value=value),self.assertRaises(ViewEventsError):
                validate_next_date_reference(value)
    def test_migration_is_additive_separate_table(self):
        path=Path(__file__).resolve().parents[1]/"migrations/event_calendar_view_metadata_v1.sql"
        ddl=path.read_text()
        self.assertIn("CREATE TABLE IF NOT EXISTS event_calendar_view_metadata",ddl)
        self.assertIn("REFERENCES event_calendar_events(event_id) ON DELETE CASCADE",ddl)
        self.assertIn("next_date_reference VARCHAR(120)",ddl)
        self.assertIn("archived_at TIMESTAMPTZ",ddl)
        self.assertNotIn("ALTER TABLE event_calendar_events",ddl)
    def test_reference_does_not_schedule_anything(self):
        conn=FakeConn([sample_row()]);list_view_events(conn,44,41)
        sql=conn.cursor_obj.calls[0][0].upper()
        for term in ("EVENT_CALENDAR_UNIT_ASSIGNMENTS", "BUSINESS_SCHEDULE", "REMINDER_QUEUE"):
            self.assertNotIn(term,sql)

if __name__ == "__main__":
    unittest.main()
