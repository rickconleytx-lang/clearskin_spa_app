"""Foreign-key-safe Event Editing replacement contracts."""

import unittest

from services.event_calendar_edit_update import (
    _delete_old_event_dependents,
)


class FakeCursor:
    def __init__(self):
        self.calls = []

    def execute(self, sql, params):
        self.calls.append((sql, params))


class EventEditUpdateTests(unittest.TestCase):

    def test_dependencies_deleted_in_safe_order(self):
        cur = FakeCursor()

        _delete_old_event_dependents(
            cur,
            spa_id=44,
            workspace_id=41,
            event_id=12,
        )

        expected = [
            "event_calendar_employee_assignments",
            "event_calendar_unit_assignments",
            "event_calendar_daily_schedules",
            "event_calendar_custom_values",
        ]

        self.assertEqual(len(cur.calls), 4)

        for (sql, params), table in zip(
            cur.calls, expected
        ):
            self.assertIn(
                "DELETE FROM public." + table,
                sql,
            )
            self.assertEqual(params, (44, 41, 12))

    def test_every_delete_requires_workspace_scope(self):
        cur = FakeCursor()

        _delete_old_event_dependents(
            cur,
            spa_id=44,
            workspace_id=41,
            event_id=12,
        )

        for sql, _params in cur.calls:
            self.assertIn("spa_id = %s", sql)
            self.assertIn(
                "business_unit_id = %s", sql
            )
            self.assertIn("event_id = %s", sql)

    def test_invalid_event_id_rejected_before_sql(self):
        cur = FakeCursor()

        with self.assertRaises(ValueError):
            _delete_old_event_dependents(
                cur,
                spa_id=44,
                workspace_id=41,
                event_id=0,
            )

        self.assertEqual(cur.calls, [])

    def test_boolean_scope_rejected(self):
        cur = FakeCursor()

        with self.assertRaises(ValueError):
            _delete_old_event_dependents(
                cur,
                spa_id=44,
                workspace_id=True,
                event_id=12,
            )

        self.assertEqual(cur.calls, [])

    def test_helper_does_not_update_event_or_commit(self):
        cur = FakeCursor()

        _delete_old_event_dependents(
            cur,
            spa_id=44,
            workspace_id=41,
            event_id=12,
        )

        for sql, _params in cur.calls:
            self.assertNotIn(
                "UPDATE event_calendar_events",
                sql,
            )
            self.assertNotIn(
                "COMMIT",
                sql.upper(),
            )

    def test_helper_does_not_touch_edit_history(self):
        cur = FakeCursor()

        _delete_old_event_dependents(
            cur,
            spa_id=44,
            workspace_id=41,
            event_id=12,
        )

        for sql, _params in cur.calls:
            self.assertNotIn(
                "event_calendar_edit_history",
                sql,
            )
            self.assertNotIn(
                "event_calendar_edit_locks",
                sql,
            )




from services.event_calendar_edit_update import (
    EventEditUpdateConflict,
    EventEditUpdateError,
    _update_existing_event_header,
    _event_edit_changes,
    _append_event_edit_history,
)


def normalized_fixture():
    from datetime import date

    fields = {
        key: "Saved value"
        for _column, key in __import__(
            "services.event_calendar_edit_update",
            fromlist=["_HEADER_FIELDS"],
        )._HEADER_FIELDS
    }

    fields.update({
        "name": "Updated Event",
        "start_date": date(2026, 11, 18),
        "end_date": date(2026, 11, 18),
        "status": "confirmed",
        "permits_obtained": False,
        "include_on_peachweb": True,
    })

    return {
        "event": fields,
        "timezone_name": "America/Chicago",
    }


class ReturningCursor(FakeCursor):
    def __init__(self, result):
        super().__init__()
        self.result = result

    def fetchone(self):
        return self.result


class EventEditHeaderAndHistoryTests(unittest.TestCase):

    def test_header_preserves_identity_and_increments_revision(self):
        cur = ReturningCursor((2,))

        revision = _update_existing_event_header(
            cur, normalized_fixture(),
            spa_id=44, workspace_id=41,
            event_id=12, actor_id=34,
            expected_revision=1,
        )

        self.assertEqual(revision, 2)
        sql, params = cur.calls[0]

        self.assertIn(
            "UPDATE public.event_calendar_events SET", sql
        )
        self.assertIn("event_revision = event_revision + 1", sql)
        self.assertIn("updated_at = CURRENT_TIMESTAMP", sql)
        self.assertIn("updated_by = %s", sql)
        self.assertIn("AND event_revision = %s", sql)
        self.assertEqual(params[-4:], (44, 41, 12, 1))

    def test_header_rejects_stale_revision(self):
        cur = ReturningCursor(None)

        with self.assertRaises(EventEditUpdateConflict):
            _update_existing_event_header(
                cur, normalized_fixture(),
                spa_id=44, workspace_id=41,
                event_id=12, actor_id=34,
                expected_revision=1,
            )

    def test_header_rejects_wrong_returned_revision(self):
        cur = ReturningCursor((4,))

        with self.assertRaises(EventEditUpdateError):
            _update_existing_event_header(
                cur, normalized_fixture(),
                spa_id=44, workspace_id=41,
                event_id=12, actor_id=34,
                expected_revision=1,
            )

    def test_invalid_header_scope_rejected_before_sql(self):
        cur = ReturningCursor((2,))

        with self.assertRaises(ValueError):
            _update_existing_event_header(
                cur, normalized_fixture(),
                spa_id=44, workspace_id=True,
                event_id=12, actor_id=34,
                expected_revision=1,
            )

        self.assertEqual(cur.calls, [])

    def test_header_does_not_change_original_event_id(self):
        cur = ReturningCursor((2,))

        _update_existing_event_header(
            cur, normalized_fixture(),
            spa_id=44, workspace_id=41,
            event_id=12, actor_id=34,
            expected_revision=1,
        )

        sql, _params = cur.calls[0]
        self.assertNotIn("SET event_id =", sql)
        self.assertIn("AND event_id = %s", sql)

    def test_history_writes_bound_json_and_revision(self):
        import json

        cur = ReturningCursor((55,))
        changes = {
            "event": {
                "name": {
                    "before": "Old",
                    "after": "New",
                }
            }
        }

        history_id = _append_event_edit_history(
            cur,
            spa_id=44, workspace_id=41, event_id=12,
            actor_id=34, actor_display_name="Jane Admin",
            revision_before=1, revision_after=2,
            changes=changes,
        )

        self.assertEqual(history_id, 55)

        sql, params = cur.calls[0]
        self.assertIn("INSERT INTO public.event_calendar_edit_history", sql)
        self.assertIn("%s::jsonb", sql)
        self.assertEqual(params[:7], (
            44, 41, 12, 1, 2, 34, "Jane Admin"
        ))
        self.assertEqual(json.loads(params[7]), changes)

    def test_history_rejects_blank_editor(self):
        cur = ReturningCursor((55,))

        with self.assertRaises(ValueError):
            _append_event_edit_history(
                cur,
                spa_id=44, workspace_id=41, event_id=12,
                actor_id=34, actor_display_name=" ",
                revision_before=1, revision_after=2,
                changes={},
            )

        self.assertEqual(cur.calls, [])

    def test_history_rejects_nonsequential_revision(self):
        cur = ReturningCursor((55,))

        with self.assertRaises(ValueError):
            _append_event_edit_history(
                cur,
                spa_id=44, workspace_id=41, event_id=12,
                actor_id=34, actor_display_name="Jane Admin",
                revision_before=1, revision_after=3,
                changes={},
            )

        self.assertEqual(cur.calls, [])

    def test_field_level_changes_only(self):
        before = {
            "event": {"name": "Old", "city": "Keller"},
            "custom_values": {"1": "Code A"},
            "custom_labels": {"1": "Event Code"},
            "days": [],
        }

        after = {
            **before,
            "event": {"name": "New", "city": "Keller"},
        }

        changes = _event_edit_changes(before, after)

        self.assertEqual(
            changes["event"]["name"],
            {"before": "Old", "after": "New"},
        )
        self.assertNotIn("city", changes["event"])
        self.assertNotIn("days", changes)

    def test_operating_day_changes_tracked(self):
        before = {
            "event": {},
            "custom_values": {},
            "custom_labels": {},
            "days": [{
                "date": "2026-11-18",
                "opens": "11:00",
            }],
        }

        after = {
            **before,
            "days": [{
                "date": "2026-11-18",
                "opens": "12:00",
            }],
        }

        changes = _event_edit_changes(before, after)

        self.assertIn("2026-11-18", changes["days"])

    def test_unchanged_snapshots_produce_empty_diff(self):
        snapshot = {
            "event": {"name": "Same"},
            "custom_values": {},
            "custom_labels": {},
            "days": [],
        }

        self.assertEqual(
            _event_edit_changes(snapshot, snapshot),
            {},
        )




from contextlib import ExitStack
from unittest.mock import patch
from services.event_calendar_edit_update import (
    EventEditUpdateInvalid, update_event_draft,
)


class _EditTransactionCursor:
    def __init__(self):
        self.calls = []
        self.row = None
        self.release_result = (12,)

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def execute(self, sql, params=None):
        self.calls.append((sql, params))
        if "SELECT timezone_name FROM public.spas" in sql:
            self.row = ("America/Chicago",)
        elif "DELETE FROM public.event_calendar_edit_locks" in sql:
            self.row = self.release_result
        else:
            raise AssertionError("Unexpected SQL in mocked coordinator.")

    def fetchone(self):
        return self.row


class _EditTransactionConnection:
    autocommit = False

    def __init__(self):
        self.cur = _EditTransactionCursor()
        self.commits = 0
        self.rollbacks = 0

    def cursor(self):
        return self.cur

    def commit(self):
        self.commits += 1

    def rollback(self):
        self.rollbacks += 1


def _edit_before():
    return {
        "event_id": 12,
        "event_revision": 1,
        "event": {"name": "Old Name"},
        "custom_values": {},
        "custom_labels": {},
        "days": [],
    }


def _edit_after():
    return {
        **_edit_before(),
        "event_revision": 2,
        "event": {"name": "New Name"},
    }


class EventEditCoordinatorTests(unittest.TestCase):

    @staticmethod
    def _run(conn, **overrides):
        args = dict(
            spa_id=44, workspace_id=41, event_id=12,
            actor_id=34, actor_display_name="Jane Admin",
            lock_token="d65f743f-343c-411c-8522-3caef1d00001",
            expected_revision=1,
        )
        args.update(overrides)
        return update_event_draft(conn, {"payload": True}, **args)

    def _mock_dependencies(self, stack, *, reads=None, order=None):
        order = [] if order is None else order
        before, after = _edit_before(), _edit_after()
        read_values = [before, after] if reads is None else reads
        target = "services.event_calendar_edit_update"

        def spy(name, value=None):
            def cb(*args, **kwargs):
                order.append(name)
                return value
            return cb

        mocks = {}
        for name, side_effect in (
            ("load_event_edit_payload", None),
            ("require_event_edit_lock_for_save", spy("lock", 1)),
            ("validate_event_payload", spy("validate", normalized_fixture())),
            ("validate_event_resource_ownership", spy("ownership")),
            ("validate_existing_event_availability", spy("availability")),
            ("_update_existing_event_header", spy("header", 2)),
            ("_delete_old_event_dependents", spy("delete")),
            ("_create_schedules", spy("schedules", {"operating_days": 1})),
            ("_create_custom_values", spy("custom", 0)),
            ("_append_event_edit_history", spy("history", 55)),
        ):
            p = stack.enter_context(patch(target + "." + name))
            if side_effect is not None:
                p.side_effect = side_effect
            mocks[name] = p
        reads_iter = iter(read_values)
        def next_read(*args, **kwargs):
            order.append("read")
            return next(reads_iter)
        mocks["load_event_edit_payload"].side_effect = next_read
        return mocks, order

    def test_success_preserves_id_revision_and_history(self):
        conn = _EditTransactionConnection()
        with ExitStack() as stack:
            mocks, order = self._mock_dependencies(stack)
            result = self._run(conn)
            self.assertEqual(result["event_id"], 12)
            self.assertEqual(result["revision_after"], 2)
            self.assertEqual(result["history_id"], 55)
            self.assertEqual(conn.commits, 1)
            self.assertEqual(conn.rollbacks, 0)
            for stage in ("lock", "validate", "ownership", "availability",
                          "header", "delete", "schedules", "custom", "history"):
                self.assertIn(stage, order)
            self.assertLess(order.index("ownership"), order.index("delete"))
            self.assertLess(order.index("availability"), order.index("header"))
            self.assertLess(order.index("delete"), order.index("schedules"))
            self.assertLess(order.index("schedules"), order.index("history"))
            mocks["validate_existing_event_availability"].assert_called_once()
            self.assertEqual(
                mocks["validate_existing_event_availability"].call_args.kwargs,
                {"excluded_event": (41, 12)},
            )
            release_sql, release_params = conn.cur.calls[-1]
            self.assertIn("DELETE FROM public.event_calendar_edit_locks", release_sql)
            self.assertIn("expires_at > clock_timestamp()", release_sql)
            self.assertEqual(release_params[:4], (44, 41, 12, 34))

    def test_stale_lease_rolls_back_before_other_work(self):
        from services.event_calendar_edit_locks import EventEditLockConflict
        conn = _EditTransactionConnection()
        with ExitStack() as stack:
            mocks, _ = self._mock_dependencies(stack)
            mocks["require_event_edit_lock_for_save"].side_effect = (
                EventEditLockConflict("Expired")
            )
            with self.assertRaises(EventEditUpdateConflict):
                self._run(conn)
            self.assertEqual(conn.commits, 0)
            self.assertEqual(conn.rollbacks, 1)
            mocks["load_event_edit_payload"].assert_not_called()

    def test_stale_revision_from_snapshot_rolls_back(self):
        conn = _EditTransactionConnection()
        stale = {**_edit_before(), "event_revision": 4}
        with ExitStack() as stack:
            mocks, _ = self._mock_dependencies(stack, reads=[stale, _edit_after()])
            with self.assertRaises(EventEditUpdateConflict):
                self._run(conn)
            self.assertEqual(conn.commits, 0)
            self.assertEqual(conn.rollbacks, 1)
            mocks["validate_event_payload"].assert_not_called()

    def test_failed_ownership_rolls_back_without_deleting(self):
        from services.event_calendar_resources import EventResourceError
        conn = _EditTransactionConnection()
        with ExitStack() as stack:
            mocks, _ = self._mock_dependencies(stack)
            mocks["validate_event_resource_ownership"].side_effect = (
                EventResourceError("Unavailable")
            )
            with self.assertRaises(EventEditUpdateInvalid):
                self._run(conn)
            self.assertEqual(conn.rollbacks, 1)
            self.assertEqual(conn.commits, 0)
            mocks["_delete_old_event_dependents"].assert_not_called()

    def test_availability_conflict_rolls_back_before_deleting(self):
        from services.event_calendar_availability import EventAvailabilityError
        conn = _EditTransactionConnection()
        with ExitStack() as stack:
            mocks, _ = self._mock_dependencies(stack)
            mocks["validate_existing_event_availability"].side_effect = (
                EventAvailabilityError("Truck busy")
            )
            with self.assertRaises(EventEditUpdateConflict):
                self._run(conn)
            self.assertEqual(conn.commits, 0)
            self.assertEqual(conn.rollbacks, 1)
            mocks["_delete_old_event_dependents"].assert_not_called()

    def test_failure_after_delete_rolls_back_entire_update(self):
        conn = _EditTransactionConnection()
        with ExitStack() as stack:
            mocks, _ = self._mock_dependencies(stack)
            mocks["_create_schedules"].side_effect = RuntimeError("Failed insert")
            with self.assertRaisesRegex(RuntimeError, "Failed insert"):
                self._run(conn)
            mocks["_delete_old_event_dependents"].assert_called_once()
            self.assertEqual(conn.rollbacks, 1)
            self.assertEqual(conn.commits, 0)
            mocks["_append_event_edit_history"].assert_not_called()

    def test_history_failure_rolls_back_all(self):
        conn = _EditTransactionConnection()
        with ExitStack() as stack:
            mocks, _ = self._mock_dependencies(stack)
            mocks["_append_event_edit_history"].side_effect = RuntimeError("History insert")
            with self.assertRaisesRegex(RuntimeError, "History insert"):
                self._run(conn)
            self.assertEqual(conn.rollbacks, 1)
            self.assertEqual(conn.commits, 0)

    def test_expired_lease_at_completion_rolls_back_everything(self):
        conn = _EditTransactionConnection()
        conn.cur.release_result = None
        with ExitStack() as stack:
            self._mock_dependencies(stack)
            with self.assertRaises(EventEditUpdateConflict):
                self._run(conn)
            self.assertEqual(conn.rollbacks, 1)
            self.assertEqual(conn.commits, 0)

    def test_no_real_changes_rollback_instead_of_logging(self):
        conn = _EditTransactionConnection()
        before = _edit_before()
        after = {**before, "event_revision": 2}
        with ExitStack() as stack:
            mocks, _ = self._mock_dependencies(stack, reads=[before, after])
            with self.assertRaises(EventEditUpdateInvalid):
                self._run(conn)
            self.assertEqual(conn.rollbacks, 1)
            self.assertEqual(conn.commits, 0)
            mocks["_append_event_edit_history"].assert_not_called()

    def test_invalid_identity_rejected_without_db(self):
        conn = _EditTransactionConnection()
        with self.assertRaises(ValueError):
            self._run(conn, workspace_id=True)
        self.assertEqual(conn.cur.calls, [])
        self.assertEqual(conn.commits, 0)

    def test_autocommit_connection_rejected(self):
        conn = _EditTransactionConnection()
        conn.autocommit = True
        with self.assertRaises(EventEditUpdateError):
            self._run(conn)
        self.assertEqual(conn.cur.calls, [])
        self.assertEqual(conn.commits, 0)


if __name__ == "__main__":
    unittest.main()
