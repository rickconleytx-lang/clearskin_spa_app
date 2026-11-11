"""EC-063-3B: Copy draft endpoint contracts and isolated Flask HTTP tests."""
import ast
import json
from pathlib import Path
import unittest
from unittest.mock import Mock, patch

from flask import Flask, request, abort

from services.event_calendar_edit_read import EventEditReadError
from services.event_calendar_copy import EventCopyInvalid, SECTION_DEFAULTS

ROOT = Path(__file__).resolve().parents[1]
URL = "/events/12/copy-draft"


def source_event():
    return {
        "event_id": 12, "event_revision": 4,
        "event": {
            "name": "Original Event", "start_date": "2026-11-18",
            "end_date": "2026-11-18", "status": "confirmed",
            "street_address": "123 Main", "city": "Northlake",
            "state": "TX", "zip_code": "76247", "notes_2": "Private",
            "permits_obtained": True,
            "include_on_peachweb": True,
        },
        "days": [{
            "date": "2026-11-18", "operating": True,
            "opens": "10:00", "closes": "16:00",
            "closes_next_day": False, "setup": "09:00",
            "breakdown": "17:00", "notes": "Setup",
            "equipment_ids": [17],
            "shifts": [{"employee_id": 24, "starts": "10:00",
                        "ends": "16:00", "ends_next_day": False,
                        "equipment_id": 17, "role": "Cashier", "notes": ""}],
        }],
        "custom_values": {"1": "Value", "2": "", "3": ""},
    }


class CopyDraftEndpointTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        source = (ROOT / "app.py").read_text()
        tree = ast.parse(source)
        matches = [
            node for node in tree.body
            if isinstance(node, ast.FunctionDef)
            and node.name == "peachpos_event_copy_draft"
        ]
        if len(matches) != 1:
            raise AssertionError("Exactly one Copy Draft handler required.")
        node = matches[0]
        decorators = [
            ast.get_source_segment(source, deco) or ""
            for deco in node.decorator_list
        ]
        for fragment in (
            '/events/<int:event_id>/copy-draft',
            'login_required', 'spa_required',
            'require_subscription_feature("event_calendar")',
            'require_workspace_permission("can_manage_event_units")',
        ):
            if not any(fragment in decorator for decorator in decorators):
                raise AssertionError("Missing required decorator: " + fragment)
        if not any('methods=["POST"]' in decorator for decorator in decorators):
            raise AssertionError("Copy Draft must be POST-only.")
        cls.route_source = ast.get_source_segment(source, node)
        node.decorator_list = []
        module = ast.Module(body=[node], type_ignores=[])
        ast.fix_missing_locations(module)
        cls.route_code = compile(module, str(ROOT / "app.py"), "exec")

    def setUp(self):
        self.app = Flask(__name__)
        self.app.testing = True
        self.conn = Mock()
        self.role = "organization_admin"
        self.csrf_ok = True
        names = {
            "app": self.app,
            "request": request,
            "abort": abort,
            "current_business_unit_membership_role_code": lambda: self.role,
            "_security_form_csrf_valid": lambda value: self.csrf_ok and value == "csrf",
            "_event_unit_scope": lambda: (44, 41, 34),
            "get_db_connection": lambda: self.conn,
        }
        exec(self.route_code, names)
        self.app.add_url_rule(
            "/events/<int:event_id>/copy-draft",
            view_func=names["peachpos_event_copy_draft"],
            methods=["POST"],
        )
        self.client = self.app.test_client()
        self.source_patch = patch(
            "services.event_calendar_edit_read.load_event_edit_payload",
            return_value=source_event(),
        )
        self.reader = self.source_patch.start()
        self.addCleanup(self.source_patch.stop)

    def post(self, options=None, **extra):
        data = {"security_csrf_token": "csrf"}
        if options is not None:
            data["copy_options"] = json.dumps(options)
        data.update(extra)
        return self.client.post(URL, data=data)

    def test_default_returns_unsaved_next_week_create_payload(self):
        response = self.post()
        self.assertEqual(response.status_code, 200)
        body = response.get_json()
        self.assertEqual(body["ok"], True)
        self.assertFalse(body["saved"])
        self.assertEqual(body["source_event_id"], 12)
        self.assertEqual(body["source_event_revision"], 4)
        draft = body["draft"]
        self.assertEqual(set(draft), {"event", "custom_values", "days"})
        self.assertEqual(draft["event"]["start_date"], "2026-11-25")
        self.assertEqual(draft["event"]["end_date"], "2026-11-25")
        self.assertEqual(draft["days"][0]["date"], "2026-11-25")
        self.assertEqual(draft["days"][0]["equipment_ids"], [17])
        self.assertEqual(draft["days"][0]["shifts"], [])
        self.assertFalse(draft["event"]["permits_obtained"])
        self.assertFalse(draft["event"]["include_on_peachweb"])
        self.assertNotIn("event_id", draft)
        self.reader.assert_called_once_with(
            self.conn, event_id=12, spa_id=44, workspace_id=41
        )

    def test_custom_date_and_selected_employees(self):
        options = {
            "target_start_date": "2026-12-02",
            "sections": dict(SECTION_DEFAULTS, employees=True),
        }
        response = self.post(options)
        self.assertEqual(response.status_code, 200)
        draft = response.get_json()["draft"]
        self.assertEqual(draft["event"]["start_date"], "2026-12-02")
        self.assertEqual(draft["days"][0]["shifts"][0]["employee_id"], 24)

    def test_admin_only_before_database_connection(self):
        self.role = "employee"
        self.assertEqual(self.post().status_code, 403)
        self.reader.assert_not_called()
        self.conn.set_session.assert_not_called()

    def test_csrf_required_before_database(self):
        self.csrf_ok = False
        self.assertEqual(self.post().status_code, 400)
        self.reader.assert_not_called()

    def test_invalid_path_id(self):
        self.assertEqual(self.client.post("/events/0/copy-draft").status_code, 404)
        self.reader.assert_not_called()

    def test_payload_size_guard(self):
        response = self.post(copy_options="x" * 17000)
        self.assertEqual(response.status_code, 413)
        self.reader.assert_not_called()

    def test_invalid_json_rejected_before_database(self):
        response = self.post(copy_options="{not-json")
        self.assertEqual(response.status_code, 400)
        self.reader.assert_not_called()

    def test_unknown_copy_option_rejected_before_database(self):
        response = self.post({"spa_id": 999})
        self.assertEqual(response.status_code, 400)
        self.reader.assert_not_called()

    def test_non_object_options_rejected(self):
        response = self.post([1, 2, 3])
        self.assertEqual(response.status_code, 400)
        self.reader.assert_not_called()

    def test_foreign_or_missing_event_returns_404(self):
        self.reader.return_value = None
        response = self.post()
        self.assertEqual(response.status_code, 404)
        self.assertNotIn("Original Event", response.get_data(as_text=True))
        self.conn.rollback.assert_called_once()
        self.conn.close.assert_called_once()

    def test_corrupt_saved_event_returns_sanitized_409(self):
        self.reader.side_effect = EventEditReadError("Private DB detail")
        response = self.post()
        self.assertEqual(response.status_code, 409)
        self.assertNotIn("Private DB detail", response.get_data(as_text=True))
        self.conn.close.assert_called_once()

    def test_invalid_dates_return_422(self):
        response = self.post({"target_start_date": "2026-02-30"})
        self.assertEqual(response.status_code, 422)
        self.assertFalse(response.get_json()["ok"])
        self.conn.rollback.assert_called_once()

    def test_read_only_transaction_and_no_cache(self):
        response = self.post()
        self.assertEqual(response.status_code, 200)
        self.conn.set_session.assert_called_once_with(
            readonly=True, isolation_level="REPEATABLE READ", autocommit=False
        )
        self.conn.rollback.assert_called_once()
        self.conn.close.assert_called_once()
        self.conn.commit.assert_not_called()
        self.assertEqual(response.headers["Cache-Control"], "private, no-store")
        self.assertEqual(response.headers["X-Content-Type-Options"], "nosniff")

    def test_get_is_not_allowed(self):
        self.assertEqual(self.client.get(URL).status_code, 405)
        self.reader.assert_not_called()

    def test_copy_route_does_not_save_or_change_source(self):
        route = self.route_source
        self.assertNotIn("save_event_draft", route)
        self.assertNotIn("update_event_draft", route)
        self.assertNotIn("conn.commit(", route)
        self.assertIn("conn.rollback()", route)
        self.assertIn("build_event_copy_draft", route)


if __name__ == "__main__":
    unittest.main()
