"""Archive/restore one PeachPOS event atomically, without deleting its master records.

Caller owns the writable DB transaction and commit/rollback. Lock the event
row FIRST, matching Edit Event lock ordering, before touching metadata or
deleting only this event's assignment children.
"""
from services.event_calendar_view_events import (
    ViewEventsError, ViewEventsArchiveConflict, set_event_view_archived,
)


def apply_event_archive_state(cur, *, spa_id, workspace_id, event_id,
                              actor_id, archive):
    if any(type(x) is not int or x <= 0 for x in
           (spa_id, workspace_id, event_id, actor_id)) or type(archive) is not bool:
        raise ViewEventsError("Invalid event archive identity or action.")

    scope = (spa_id, workspace_id, event_id)
    cur.execute(
        "SELECT event_revision FROM public.event_calendar_events "
        "WHERE spa_id = %s AND business_unit_id = %s AND event_id = %s "
        "FOR UPDATE", scope,
    )
    row = cur.fetchone()
    if row is None or type(row[0]) is not int or row[0] < 1:
        raise ViewEventsArchiveConflict("Event is unavailable in this workspace.")
    old_revision = int(row[0])

    # This must be in the SAME transaction and only after the event-row lock.
    # An already archived/restored event is a conflict, not a second destructive run.
    set_event_view_archived(
        cur, spa_id=spa_id, workspace_id=workspace_id,
        event_id=event_id, actor_id=actor_id, archive=archive,
    )

    employee_count = unit_count = 0
    if archive:
        # Employees can reference unit assignments. Delete children first.
        cur.execute(
            "DELETE FROM public.event_calendar_employee_assignments "
            "WHERE spa_id = %s AND business_unit_id = %s AND event_id = %s",
            scope,
        )
        employee_count = cur.rowcount
        cur.execute(
            "DELETE FROM public.event_calendar_unit_assignments "
            "WHERE spa_id = %s AND business_unit_id = %s AND event_id = %s",
            scope,
        )
        unit_count = cur.rowcount

    # is_public remains FALSE on RESTORE. A fresh admin action is required
    # to publish the restored event. Bump revision to reject stale edits.
    cur.execute(
        "UPDATE public.event_calendar_events "
        "SET is_public = FALSE, updated_by = %s, "
        "updated_at = CURRENT_TIMESTAMP, event_revision = event_revision + 1 "
        "WHERE spa_id = %s AND business_unit_id = %s AND event_id = %s "
        "AND event_revision = %s RETURNING event_revision",
        (actor_id, *scope, old_revision),
    )
    updated = cur.fetchone()
    if updated is None or int(updated[0]) != old_revision + 1:
        raise ViewEventsArchiveConflict("Event changed during Archive/Restore.")
    return {"archived": archive, "removed_employee_assignments": employee_count,
            "removed_unit_assignments": unit_count,
            "event_revision": int(updated[0])}
