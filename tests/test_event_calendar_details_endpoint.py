"""Read-only Event Details endpoint and modal contracts."""

import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


class EventDetailsEndpointTests(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        source = (ROOT / "app.py").read_text()
        start = source.index(
            '@app.route("/events/<int:event_id>/details", '
            'methods=["GET"])'
        )
        end = source.index(
            '@app.route("/events/validate", methods=["POST"])',
            start,
        )
        cls.route = source[start:end]
        cls.template = (
            ROOT / "templates/event_calendar_month.html"
        ).read_text()

    def test_endpoint_requires_auth_and_event_feature(self):
        for marker in (
            "@login_required",
            "@spa_required",
            '@require_subscription_feature("event_calendar")',
            '@require_workspace_permission("can_manage_event_units")',
        ):
            with self.subTest(marker=marker):
                self.assertIn(marker, self.route)

    def test_endpoint_requires_organization_admin(self):
        self.assertIn(
            'current_business_unit_membership_role_code() '
            '!= "organization_admin"',
            self.route
        )
        self.assertIn("abort(403)", self.route)

    def test_event_scope_comes_from_authenticated_context(self):
        self.assertIn("_event_unit_scope()", self.route)
        self.assertIn(
            "workspace_id=workspace_id",
            self.route
        )
        self.assertIn("spa_id=spa_id", self.route)
        self.assertIn("event_id=event_id", self.route)
        self.assertIn("abort(404)", self.route)

    def test_database_transaction_is_read_only_and_closed(self):
        self.assertIn(
            'cur.execute("SET TRANSACTION READ ONLY")',
            self.route
        )
        self.assertIn("conn.rollback()", self.route)
        self.assertIn("conn.close()", self.route)
        self.assertNotIn("conn.commit()", self.route)

    def test_response_disallows_caching(self):
        self.assertIn(
            '"Cache-Control"] = "private, no-store"',
            self.route
        )
        self.assertIn(
            'jsonify({"ok": True, "event": details})',
            self.route
        )

    def test_calendar_entries_are_clickable_buttons(self):
        self.assertIn(
            '<button type="button" class="ec-month-event"',
            self.template
        )
        self.assertIn(
            "url_for('peachpos_event_calendar_details', "
            "event_id=item.event_id)",
            self.template
        )

    def test_modal_is_read_only_and_accessible(self):
        self.assertIn(
            '<dialog id="ec-detail-dialog"',
            self.template
        )
        self.assertIn(
            'aria-labelledby="ec-detail-name"',
            self.template
        )
        self.assertIn(
            'id="ec-detail-close"',
            self.template
        )
        self.assertIn("dialog.showModal()", self.template)
        self.assertIn("dialog.close()", self.template)
        self.assertIn('method: "GET"', self.template)
        self.assertNotIn("innerHTML", self.template)

    def test_clicking_outside_modal_closes_it(self):
        for marker in (
            'dialog.addEventListener("click", function (event) {',
            "event.target !== dialog",
            "dialog.getBoundingClientRect()",
            "event.clientX < bounds.left",
            "event.clientX > bounds.right",
            "event.clientY < bounds.top",
            "event.clientY > bounds.bottom",
            "if (outside) {",
            "dialog.close();",
        ):
            with self.subTest(marker=marker):
                self.assertIn(marker, self.template)

        self.assertIn(
            'dialog.addEventListener("close"',
            self.template
        )

    def test_modal_includes_schedule_and_employees(self):
        for label in (
            "Venue & Location",
            "Event Dates",
            "Daily Operating Schedule",
            "Employee Assignments",
            "Event Notes",
            "No employees scheduled for this day.",
        ):
            with self.subTest(label=label):
                self.assertIn(label, self.template)


if __name__ == "__main__":
    unittest.main()
