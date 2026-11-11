"""EC-062-14D-1: isolated tests for no-lease HTTP endpoints."""
import ast
import copy
import json
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
from flask import Flask, request, abort

from services.event_calendar_edit_update import (
    EventEditUpdateConflict, EventEditUpdateInvalid,
)

APP_SOURCE = Path(__file__).resolve().parents[1].joinpath("app.py").read_text()
TREE = ast.parse(APP_SOURCE)
NAMES = ("peachpos_event_edit_draft", "peachpos_event_edit_save_unlocked")


class Cursor:
    def __init__(self):
        self.calls = []

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def execute(self, sql, args):
        self.calls.append((sql, args))
        if "FROM public.users AS u" not in sql:
            raise AssertionError("Unexpected DB query")

    def fetchone(self):
        return ("Jane Administrator",)


class Connection:
    def __init__(self):
        self.cur = Cursor()
        self.sessions = []
        self.rollbacks = 0
        self.closed = False

    def cursor(self):
        return self.cur

    def set_session(self, **kwargs):
        self.sessions.append(kwargs)

    def rollback(self):
        self.rollbacks += 1

    def close(self):
        self.closed = True


class OptimisticHttpTests(unittest.TestCase):
    def setUp(self):
        self.flask_app = Flask(__name__)
        self.flask_app.secret_key = "offline-only"
        self.conn = Connection()
        self.scope_calls = []
        self.namespace = {
            "current_business_unit_membership_role_code": lambda: "organization_admin",
            "_security_form_csrf_valid": lambda x: x == "valid-csrf",
            "_event_unit_scope": lambda: (44, 41, 34),
            "get_db_connection": lambda: self.conn,
            "request": request,
            "abort": abort,
            "app": SimpleNamespace(logger=SimpleNamespace(
                error=lambda *a, **kw: None,
                exception=lambda *a, **kw: None,
            )),
        }
        for name in NAMES:
            nodes = [n for n in TREE.body
                     if isinstance(n, ast.FunctionDef) and n.name == name]
            self.assertEqual(len(nodes), 1)
            node = nodes[0]
            decorators = [ast.unparse(d) for d in node.decorator_list]
            self.assertIn("login_required", decorators)
            self.assertIn("spa_required", decorators)
            self.assertIn("require_subscription_feature('event_calendar')", decorators)
            self.assertIn("require_workspace_permission('can_manage_event_units')", decorators)
            self.assertTrue(any('edit-draft' in d or 'edit-save-unlocked' in d
                                for d in decorators))
            prepared = copy.deepcopy(node)
            prepared.decorator_list = []
            code = compile(ast.fix_missing_locations(
                ast.Module(body=[prepared], type_ignores=[])), 'app.py', 'exec')
            exec(code, self.namespace)
        self.load = self.namespace["peachpos_event_edit_draft"]
        self.save = self.namespace["peachpos_event_edit_save_unlocked"]

    def invoke_load(self, event_id=12, **overrides):
        data = {"security_csrf_token": "valid-csrf"}
        data.update(overrides)
        with self.flask_app.test_request_context(
            f"/events/{event_id}/edit-draft", method="POST", data=data,
        ):
            response, status = self.load(event_id)
            return response.get_json(), status, response.headers

    def invoke_save(self, event_id=12, **overrides):
        data = {
            "security_csrf_token": "valid-csrf",
            "event_payload": json.dumps({"event": {}, "days": [], "custom_values": {}}),
            "expected_revision": "2",
        }
        data.update(overrides)
        with self.flask_app.test_request_context(
            f"/events/{event_id}/edit-save-unlocked", method="POST", data=data,
        ):
            response, status = self.save(event_id)
            return response.get_json(), status, response.headers

    @staticmethod
    def draft():
        return {"event_id": 12, "event_revision": 2,
                "event": {"name": "Test"}, "days": [{"date": "2026-11-18"}]}

    def test_read_without_lease_uses_readonly_transaction_and_scope(self):
        with patch('services.event_calendar_edit_read.load_event_edit_payload',
                   return_value=self.draft()) as loader:
            data, status, headers = self.invoke_load()
        self.assertEqual(status, 200)
        self.assertTrue(data["ok"])
        self.assertEqual(data["event"]["event_revision"], 2)
        loader.assert_called_once_with(self.conn, event_id=12, spa_id=44,
                                       workspace_id=41)
        self.assertEqual(self.conn.sessions[0], {
            "readonly": True, "isolation_level": "REPEATABLE READ",
            "autocommit": False,
        })
        self.assertEqual(self.conn.rollbacks, 1)
        self.assertTrue(self.conn.closed)
        self.assertIn("no-store", headers["Cache-Control"])

    def test_read_missing_event_is_404(self):
        with patch('services.event_calendar_edit_read.load_event_edit_payload',
                   return_value=None):
            _data, status, _headers = self.invoke_load()
        self.assertEqual(status, 404)
        self.assertTrue(self.conn.closed)

    def test_read_does_not_need_or_use_token(self):
        with patch('services.event_calendar_edit_read.load_event_edit_payload',
                   return_value=self.draft()):
            _data, status, _headers = self.invoke_load(lock_token='malicious-old-token')
        self.assertEqual(status, 200)
        src = ast.unparse(next(n for n in TREE.body if isinstance(n, ast.FunctionDef)
                               and n.name == NAMES[0]))
        self.assertNotIn('edit_locks', src)
        self.assertNotIn('lock_token', src)

    def test_read_csrf_blocked_before_connection(self):
        with self.assertRaises(Exception) as caught:
            self.invoke_load(security_csrf_token='wrong')
        self.assertEqual(getattr(caught.exception, 'code', None), 400)
        self.assertFalse(self.conn.closed)

    def test_save_uses_only_server_actor_and_no_lease(self):
        captured = []
        def saving(conn, payload, **kw):
            captured.append((conn, payload, kw))
            return {'event_id': 12, 'revision_after': 3}
        with patch('services.event_calendar_edit_update.update_event_draft',
                   side_effect=saving):
            data, status, headers = self.invoke_save(
                actor_id='999', spa_id='999', workspace_id='999',
                lock_token='ignored-old-token', actor_display_name='Pretender',
            )
        self.assertEqual(status, 200)
        self.assertTrue(data['saved'])
        self.assertEqual(data['event_revision'], 3)
        self.assertIn('no-store', headers['Cache-Control'])
        self.assertEqual(len(captured), 1)
        conn, payload, kw = captured[0]
        self.assertIs(conn, self.conn)
        self.assertEqual(kw, {
            'spa_id': 44, 'workspace_id': 41, 'event_id': 12,
            'actor_id': 34, 'actor_display_name': 'Jane Administrator',
            'expected_revision': 2,
        })
        self.assertEqual(self.conn.cur.calls[0][1], (34,))
        self.assertTrue(self.conn.closed)

    def test_save_stale_revision_is_409_and_does_not_claim_success(self):
        with patch('services.event_calendar_edit_update.update_event_draft',
                   side_effect=EventEditUpdateConflict('This event has changed')):
            data, status, _headers = self.invoke_save()
        self.assertEqual(status, 409)
        self.assertFalse(data['saved'])
        self.assertIn('changed', data['error'])
        self.assertTrue(self.conn.closed)

    def test_save_validation_conflict_is_422(self):
        with patch('services.event_calendar_edit_update.update_event_draft',
                   side_effect=EventEditUpdateInvalid('Invalid schedule')):
            data, status, _headers = self.invoke_save()
        self.assertEqual(status, 422)
        self.assertFalse(data['saved'])

    def test_save_revision_validation_is_400_before_connection(self):
        for invalid in ('', '0', '-1', '1x', '9'*22):
            with self.subTest(invalid=invalid):
                data, status, _headers = self.invoke_save(expected_revision=invalid)
                self.assertEqual(status, 400)
                self.assertFalse(data['saved'])
        self.assertFalse(self.conn.closed)

    def test_save_csrf_blocks_before_connection(self):
        with self.assertRaises(Exception) as caught:
            self.invoke_save(security_csrf_token='wrong')
        self.assertEqual(getattr(caught.exception, 'code', None), 400)
        self.assertFalse(self.conn.closed)

    def test_no_new_endpoints_call_create_event_or_lease(self):
        for name in NAMES:
            fn = next(n for n in TREE.body
                      if isinstance(n, ast.FunctionDef) and n.name == name)
            src = ast.unparse(fn)
            self.assertNotIn('event_calendar_edit_locks', src)
            self.assertNotIn('acquire_event_edit_lock', src)
            self.assertNotIn('save_event_draft', src)
            self.assertNotIn('require_event_edit_lock', src)


if __name__ == '__main__':
    unittest.main()
