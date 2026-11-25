"""Workspace-scoped, read-only Event Details history display.

Query execution is owned by the caller's existing read-only transaction.
Saved edit authors are historical snapshots from the append-only audit table.
"""

from datetime import datetime


class EventHistoryDisplayError(RuntimeError):
    """History display unavailable without disclosing private details."""


_HISTORY_SQL = """
SELECT
    e.created_at AT TIME ZONE s.timezone_name,
    h.changed_at AT TIME ZONE s.timezone_name,
    h.actor_display_name
FROM public.event_calendar_events AS e
JOIN public.spas AS s
  ON s.spa_id = e.spa_id
LEFT JOIN LATERAL (
    SELECT changed_at, actor_display_name
    FROM public.event_calendar_edit_history AS h
    WHERE h.spa_id = e.spa_id
      AND h.business_unit_id = e.business_unit_id
      AND h.event_id = e.event_id
    ORDER BY h.revision_after DESC
    LIMIT 1
) AS h ON TRUE
WHERE e.spa_id = %s
  AND e.business_unit_id = %s
  AND e.event_id = %s
"""


def _day_label(value):
    if not isinstance(value, datetime):
        raise EventHistoryDisplayError("Invalid Event Details timestamp.")
    return f"{value.strftime('%B')} {value.day}, {value.year}"


def load_event_history_text(cur, *, spa_id, workspace_id, event_id):
    """Return Created on... or previously edited... in business time.

    Call only after the authenticated, authorized, scoped Event Details
    lookup succeeds, from that same read-only transaction. The displayed
    name comes from the database history, never from the browser.
    """
    if any(
        type(value) is not int or value <= 0
        for value in (spa_id, workspace_id, event_id)
    ):
        raise EventHistoryDisplayError("Invalid Event Details scope.")

    cur.execute(_HISTORY_SQL, (spa_id, workspace_id, event_id))
    row = cur.fetchone()
    if row is None or len(row) != 3:
        raise EventHistoryDisplayError("Event history is unavailable.")

    created_at, changed_at, actor = row
    if changed_at is None:
        return "Created on " + _day_label(created_at)

    if not isinstance(actor, str) or not actor.strip():
        raise EventHistoryDisplayError("Saved editor information unavailable.")

    clock = changed_at.strftime("%I:%M %p").lstrip("0") if isinstance(changed_at, datetime) else None
    if not clock:
        raise EventHistoryDisplayError("Invalid Event Edit timestamp.")

    return (
        "This event was previously edited on "
        + _day_label(changed_at)
        + " at " + clock
        + " by " + actor.strip()
    )
