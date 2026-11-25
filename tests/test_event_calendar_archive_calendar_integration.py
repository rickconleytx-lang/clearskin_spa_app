"""Archive state must affect only this event and calendar display, safely."""
import ast
import unittest
from pathlib import Path
from datetime import date
from jinja2 import Environment
from unittest.mock import patch

from services.event_calendar_archive_actions import apply_event_archive_state
from services.event_calendar_archive_read import (
    overlay_archived_month, overlay_archived_week, overlay_archived_year,
    list_archived_event_spans,
)
from services.event_calendar_read import CALENDAR_QUERY
from services.event_calendar_year_read import YEAR_SQL

ROOT = Path(__file__).resolve().parents[1]


class Cursor:
    def __init__(self):
        self.calls=[];self.results=[(4,), (5,)];self.rowcount=2
    def execute(self, sql, params): self.calls.append((sql,params))
    def fetchone(self): return self.results.pop(0)


class ArchiveCalendarTests(unittest.TestCase):
    def test_archive_scopes_deletions_and_unpublishes(self):
        cur=Cursor()
        with patch('services.event_calendar_archive_actions.set_event_view_archived') as meta:
            result=apply_event_archive_state(cur,spa_id=44,workspace_id=41,
                                             event_id=21,actor_id=9,archive=True)
        self.assertEqual([p for _,p in cur.calls[:3]],
                         [(44,41,21),(44,41,21),(44,41,21)])
        self.assertIn('FOR UPDATE',cur.calls[0][0])
        self.assertIn('event_calendar_employee_assignments',cur.calls[1][0])
        self.assertIn('event_calendar_unit_assignments',cur.calls[2][0])
        self.assertIn('is_public = FALSE',cur.calls[3][0])
        self.assertIn('event_revision = event_revision + 1',cur.calls[3][0])
        self.assertEqual(cur.calls[3][1],(9,44,41,21,4))
        self.assertTrue(result['archived'])
        meta.assert_called_once()

    def test_restore_does_not_reassign_or_republish(self):
        cur=Cursor()
        with patch('services.event_calendar_archive_actions.set_event_view_archived'):
            result=apply_event_archive_state(cur,spa_id=44,workspace_id=41,
                                             event_id=21,actor_id=9,archive=False)
        self.assertEqual(len(cur.calls),2)
        self.assertIn('is_public = FALSE',cur.calls[1][0])
        self.assertFalse(result['archived'])
        self.assertEqual(result['removed_employee_assignments'],0)

    def test_guard_bad_scope_before_sql(self):
        c=Cursor()
        with self.assertRaises(ValueError):
            apply_event_archive_state(c,spa_id=44,workspace_id=0,
                                      event_id=21,actor_id=9,archive=True)
        self.assertEqual(c.calls,[])

    def test_normal_calendar_sql_excludes_archives(self):
        for sql in (CALENDAR_QUERY,YEAR_SQL):
            self.assertIn('event_calendar_view_metadata',sql)
            self.assertIn('archive.archived_at IS NOT NULL',sql)
            self.assertIn('NOT EXISTS',sql)

    def test_archived_reader_uses_dates_not_equipment(self):
        class ReaderCursor:
            def __init__(self): self.calls=[]
            def execute(self,*args): self.calls.append(args)
            def fetchall(self): return [(21,'Winter Fest',date(2027,2,19),date(2027,2,21))]
            def close(self): pass
        class Conn:
            def __init__(self): self.cur=ReaderCursor()
            def cursor(self): return self.cur
        c=Conn()
        result=list_archived_event_spans(c,44,41,date(2027,2,1),date(2027,2,28))
        self.assertEqual(len(result),1)
        self.assertIn('m.archived_at IS NOT NULL',c.cur.calls[0][0])
        self.assertNotIn('event_calendar_unit_assignments',c.cur.calls[0][0])
        self.assertEqual(c.cur.calls[0][1],(44,41,date(2027,2,28),date(2027,2,1)))

    def test_calendar_overlay_uses_name_and_archive_only(self):
        spans=[{'event_id':21,'name':'Winter Fest','start':date(2027,2,19),
                'end':date(2027,2,21)}]
        month={'weeks':[[{'date':date(2027,2,19),'entries':[]}]]}
        week={'days':[{'date':date(2027,2,19),'entries':[]}]}
        year={'months':[{'weeks':[[{'date':date(2027,2,19),'in_month':True}]]}]}
        m=overlay_archived_month(month,spans)['weeks'][0][0]['entries'][0]
        w=overlay_archived_week(week,spans)['days'][0]['entries'][0]
        y=overlay_archived_year(year,spans)['months'][0]['weeks'][0][0]
        self.assertEqual(m,{'event_id':21,'name':'Winter Fest','is_archived':True})
        self.assertEqual(w,m)
        self.assertEqual(y['archive_names'],['Winter Fest'])

    def test_templates_render_archived_name_not_resource(self):
        for name in ('month','week','year'):
            source=(ROOT/f'templates/event_calendar_{name}.html').read_text()
            Environment().parse(source)
            self.assertIn('Show Archived',source)
            self.assertIn('Hide Archived',source)
            self.assertIn('ec-archived-event' if name!='year' else 'ec-year-date is-archived',source)
            self.assertIn('show_archived=',source)

    def test_app_post_calls_atomic_coordinator(self):
        source=(ROOT/'app.py').read_text()
        tree=ast.parse(source)
        node=next(n for n in tree.body if isinstance(n,ast.FunctionDef)
                  and n.name=='_ec_set_view_events_archive_state')
        segment=ast.get_source_segment(source,node)
        self.assertIn('apply_event_archive_state(',segment)
        self.assertIn('archive_acknowledged',segment)
        self.assertIn('conn.commit()',segment)
        self.assertIn('conn.rollback()',segment)

    def test_edit_save_blocks_archived_events(self):
        source=(ROOT/'services/event_calendar_edit_update.py').read_text()
        self.assertIn('event_calendar_view_metadata',source)
        self.assertIn('m.archived_at IS NOT NULL',source)

    def test_archive_form_warns_without_changing_list_controls(self):
        html=(ROOT/'templates/event_view_events.html').read_text()
        self.assertEqual(html.count('method="POST"'),2)
        self.assertIn('archive_acknowledged',html)
        self.assertIn('Next Occurrence',html)
        self.assertIn('Archived</option>',html)
        self.assertIn('Go To Month',html)
        self.assertIn('>Restore</button>',html)
