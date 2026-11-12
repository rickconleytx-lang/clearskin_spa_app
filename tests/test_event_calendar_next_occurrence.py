"""EC-065-3C Next Occurrence Add/Edit/Copy/metadata safety contracts."""
import ast
import unittest
from pathlib import Path
from jinja2 import Environment
from services.event_calendar_view_events import (
    ViewEventsError, upsert_next_occurrence, validate_next_date_reference,
)

ROOT = Path(__file__).resolve().parents[1]
def read(path): return (ROOT / path).read_text()


class Cursor:
    def __init__(self, row=(21,)):
        self.row, self.calls = row, []
    def execute(self, sql, args):
        self.calls.append((sql, args))
    def fetchone(self): return self.row


class NextOccurrenceTests(unittest.TestCase):
    def test_flexible_text_variants(self):
        for example in ('Oct 5', 'Oct 5-8', '10/5-8', 'October 5–8, 2027'):
            self.assertEqual(validate_next_date_reference(example), example)
    def test_clear_reference(self):
        self.assertEqual(validate_next_date_reference('  '), '')
    def test_multiline_reference_rejected(self):
        with self.assertRaises(ViewEventsError):
            validate_next_date_reference('Oct 5\nOct 6')
    def test_overlength_rejected(self):
        with self.assertRaises(ViewEventsError):
            validate_next_date_reference('x' * 121)
    def test_scope_in_metadata_write(self):
        cur = Cursor()
        self.assertEqual(upsert_next_occurrence(cur, spa_id=44, workspace_id=41,
                                               event_id=21, reference='Oct 5-8'), 'Oct 5-8')
        sql, args = cur.calls[0]
        self.assertEqual(args, ('Oct 5-8', 44, 41, 21))
        self.assertIn('e.spa_id = %s', sql)
        self.assertIn('e.business_unit_id = %s', sql)
        self.assertIn('e.event_id = %s', sql)
        self.assertIn('ON CONFLICT (event_id)', sql)
        self.assertNotIn('DELETE ', sql.upper())
    def test_write_uses_bound_parameters(self):
        cur = Cursor()
        upsert_next_occurrence(cur, spa_id=44, workspace_id=41,
                               event_id=21, reference="Oct 5'); DROP TABLE x; --")
        sql, args = cur.calls[0]
        self.assertNotIn('DROP TABLE', sql)
        self.assertIn('DROP TABLE', args[0])
    def test_scope_rejects_wrong_identity_shapes(self):
        for arguments in ((0, 41, 21), (44, 0, 21), (44, 41, True)):
            with self.subTest(arguments=arguments), self.assertRaises(ViewEventsError):
                upsert_next_occurrence(Cursor(), spa_id=arguments[0],
                                       workspace_id=arguments[1], event_id=arguments[2], reference='Oct 5')
    def test_absent_event_refuses_write(self):
        with self.assertRaises(ViewEventsError):
            upsert_next_occurrence(Cursor(row=None), spa_id=44, workspace_id=41,
                                   event_id=21, reference='Oct 5')
    def test_metadata_does_not_change_calendar_reservations(self):
        sql = read('services/event_calendar_view_events.py')
        part = sql.split('def upsert_next_occurrence', 1)[1].split('def _validated_date', 1)[0]
        for forbidden in ('UPDATE event_calendar_events', 'INSERT INTO event_calendar_events',
                          'event_calendar_unit_assignments', 'business_schedule'):
            self.assertNotIn(forbidden, part.lower())
    def test_event_field_and_phrase_present(self):
        template = read('templates/event_new.html')
        self.assertIn('id="next_occurrence"', template)
        self.assertIn('Next Occurrence (Optional)', template)
        self.assertIn('Enter it when you know it. Update it when you learn it.', template)
        Environment().parse(template)
    def test_add_event_payload_contains_occurrence(self):
        self.assertIn('next_occurrence: fieldValue("next_occurrence")',
                      read('templates/event_new.html'))
    def test_copy_explicitly_blanks_future_occurrence(self):
        template = read('templates/event_new.html')
        copy_section = template.split('if (isCopyMode) {', 1)[1].split('if (isEditMode) {', 1)[0]
        self.assertIn('next_occurrence: ""', copy_section)
    def test_edit_form_populates_occurrence(self):
        template = read('templates/event_new.html')
        edit_section = template.split('if (isEditMode) {', 1)[1]
        self.assertIn('next_occurrence: eventData.next_occurrence || ""', edit_section)
    def test_view_events_heading_updated(self):
        self.assertIn('Next Occurrence</th>', read('templates/event_view_events.html'))
    def test_validator_preserves_legacy_payloads(self):
        text = read('services/event_calendar_validation.py')
        self.assertIn('if "next_occurrence" in raw_event:', text)
        self.assertIn('validate_next_date_reference(', text)
    def test_create_save_same_transaction(self):
        text = read('services/event_calendar_save.py')
        self.assertIn('upsert_next_occurrence(', text)
        self.assertLess(text.index('upsert_next_occurrence('), text.index('conn.commit()', text.index('def save_event_draft(')))
    def test_edit_save_same_transaction_and_history(self):
        text = read('services/event_calendar_edit_update.py')
        self.assertIn('has_next_occurrence', text)
        body = text.split('def update_event_draft(', 1)[1]
        self.assertLess(body.index('upsert_next_occurrence('),
                        body.index('changes = _event_edit_changes('))
        self.assertIn('include_next_occurrence', body)
    def test_read_is_opt_in_for_legacy_copy(self):
        text = read('services/event_calendar_edit_read.py')
        self.assertIn('include_next_occurrence=False', text)
        self.assertIn('result["event"]["next_occurrence"] = next_occurrence', text)
    def test_editor_route_asks_for_reference(self):
        tree = ast.parse(read('app.py'))
        routes = [n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == 'peachpos_event_edit_draft']
        self.assertEqual(len(routes), 1)
        segment = ast.get_source_segment(read('app.py'), routes[0])
        self.assertIn('include_next_occurrence=True', segment)

if __name__ == '__main__': unittest.main()
