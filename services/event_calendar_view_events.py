"""EC-065: read-only, workspace-scoped View Events list foundation.

Archive and Next Date are administrative reference metadata, not event status,
event scheduling, equipment allocation, or reminders. Schema migration must be
separately reviewed/applied before the reader can be used against PostgreSQL.
"""

from datetime import date, datetime


class ViewEventsError(ValueError):
    """Invalid View Events request parameters."""


COLUMNS = (
    "event_id", "event_name", "start_date", "end_date", "city",
    "state", "venue_name", "contact_name", "contact_phone",
    "contact_email", "event_status", "next_date_reference", "archived_at",
)

STATUSES = frozenset({"scheduled", "confirmed", "cancelled", "completed"})
ARCHIVE_MODES = frozenset({"active", "archived", "all"})

BASE_QUERY = """
SELECT
    e.event_id, e.event_name, e.start_date, e.end_date,
    e.city, e.state, e.venue_name,
    e.contact_name, e.contact_phone, e.contact_email, e.event_status,
    COALESCE(m.next_date_reference, '') AS next_date_reference,
    m.archived_at
FROM event_calendar_events e
LEFT JOIN event_calendar_view_metadata m
  ON m.event_id = e.event_id
 AND m.spa_id = e.spa_id
 AND m.business_unit_id = e.business_unit_id
WHERE e.spa_id = %s AND e.business_unit_id = %s
"""


def validate_next_date_reference(value):
    """Accept flexible human-entered text, never parse it as a booking date."""
    if value is None:
        return ""
    if not isinstance(value, str):
        raise ViewEventsError("Next Date must be text.")
    value = value.strip()
    if len(value) > 120:
        raise ViewEventsError("Next Date must be 120 characters or fewer.")
    if any(ord(char) < 32 or ord(char) == 127 for char in value):
        raise ViewEventsError("Next Date must be a single line.")
    return value


def upsert_next_occurrence(cur, *, spa_id, workspace_id, event_id, reference):
    """Store a reference in the caller's existing event-save transaction.

    Does not commit or modify event scheduling. The event must belong to
    the authenticated business and workspace. Existing archive data remains.
    """
    for value in (spa_id, workspace_id, event_id):
        if type(value) is not int or value <= 0:
            raise ViewEventsError("Invalid Next Occurrence event scope.")
    reference = validate_next_date_reference(reference)
    cur.execute(
        """
        INSERT INTO public.event_calendar_view_metadata
            (event_id, spa_id, business_unit_id, next_date_reference)
        SELECT e.event_id, e.spa_id, e.business_unit_id, %s
          FROM public.event_calendar_events AS e
         WHERE e.spa_id = %s
           AND e.business_unit_id = %s
           AND e.event_id = %s
        ON CONFLICT (event_id) DO UPDATE SET
            next_date_reference = EXCLUDED.next_date_reference,
            updated_at = NOW()
        WHERE event_calendar_view_metadata.spa_id = EXCLUDED.spa_id
          AND event_calendar_view_metadata.business_unit_id = EXCLUDED.business_unit_id
        RETURNING event_id
        """,
        (reference, spa_id, workspace_id, event_id),
    )
    row = cur.fetchone()
    if row is None or int(row[0]) != event_id:
        raise ViewEventsError("Next Occurrence could not be saved in this workspace.")
    return reference


class ViewEventsArchiveConflict(ViewEventsError):
    """Requested list archive state changed, or event is outside scope."""


def set_event_view_archived(cur, *, spa_id, workspace_id, event_id,
                            actor_id, archive):
    """Change only View Events list metadata in caller's transaction.

    Does not change event status, event/calendar allocations, publication,
    employee shifts, Next Occurrence, or Business Schedule. Server must
    derive scope/actor from the current authenticated session.
    """
    if any(type(v) is not int or v <= 0 for v in
           (spa_id, workspace_id, event_id, actor_id)):
        raise ViewEventsError("Invalid View Events archive scope.")
    if type(archive) is not bool:
        raise ViewEventsError("Invalid archive action.")

    if archive:
        cur.execute(
            """
            INSERT INTO public.event_calendar_view_metadata
              (event_id, spa_id, business_unit_id, archived_at,
               archived_by_user_id)
            SELECT e.event_id, e.spa_id, e.business_unit_id,
                   NOW(), %s
            FROM public.event_calendar_events AS e
            WHERE e.spa_id = %s AND e.business_unit_id = %s
              AND e.event_id = %s
            ON CONFLICT (event_id) DO UPDATE SET
              archived_at = NOW(),
              archived_by_user_id = EXCLUDED.archived_by_user_id,
              updated_at = NOW()
            WHERE event_calendar_view_metadata.spa_id = EXCLUDED.spa_id
              AND event_calendar_view_metadata.business_unit_id =
                  EXCLUDED.business_unit_id
              AND event_calendar_view_metadata.archived_at IS NULL
            RETURNING event_id
            """,
            (actor_id, spa_id, workspace_id, event_id),
        )
    else:
        cur.execute(
            """
            UPDATE public.event_calendar_view_metadata AS m
               SET archived_at = NULL,
                   archived_by_user_id = NULL,
                   updated_at = NOW()
             WHERE m.spa_id = %s AND m.business_unit_id = %s
               AND m.event_id = %s AND m.archived_at IS NOT NULL
               AND EXISTS (
                   SELECT 1 FROM public.event_calendar_events AS e
                   WHERE e.event_id = m.event_id
                     AND e.spa_id = m.spa_id
                     AND e.business_unit_id = m.business_unit_id
               )
            RETURNING m.event_id
            """,
            (spa_id, workspace_id, event_id),
        )
    result = cur.fetchone()
    if result is None or int(result[0]) != event_id:
        raise ViewEventsArchiveConflict(
            "This event's archive state changed or it is unavailable."
        )
    return archive


def _validated_date(value, field):
    if value is None:
        return None
    if not isinstance(value, date) or isinstance(value, datetime):
        raise ViewEventsError(f"{field} must be a date object.")
    if not 2000 <= value.year <= 2100:
        raise ViewEventsError(f"{field} outside supported calendar years.")
    return value


def list_view_events(
    conn, spa_id, workspace_id, *, start_date=None, end_date=None,
    status="", search="", archive_mode="active", limit=50, offset=0,
):
    """List each event once, with optional View Events metadata.

    The supplied scope must come from authenticated request context.
    All query parameters are bound. The caller owns a READ ONLY transaction.
    No automatic event booking, email/SMS, or reminder writes occur here.
    """
    if type(spa_id) is not int or spa_id <= 0:
        raise ViewEventsError("Valid business required.")
    if type(workspace_id) is not int or workspace_id <= 0:
        raise ViewEventsError("Valid workspace required.")
    start_date = _validated_date(start_date, "From")
    end_date = _validated_date(end_date, "To")
    if start_date and end_date and start_date > end_date:
        raise ViewEventsError("From date must not follow To date.")
    if not isinstance(status, str) or status not in STATUSES | {""}:
        raise ViewEventsError("Invalid event status.")
    if not isinstance(search, str) or len(search.strip()) > 100:
        raise ViewEventsError("Search must be 100 characters or fewer.")
    search = search.strip()
    if archive_mode not in ARCHIVE_MODES:
        raise ViewEventsError("Invalid archive filter.")
    if type(limit) is not int or not 1 <= limit <= 100:
        raise ViewEventsError("Invalid page size.")
    if type(offset) is not int or not 0 <= offset <= 100000:
        raise ViewEventsError("Invalid page offset.")

    parts = [BASE_QUERY]
    params = [spa_id, workspace_id]
    if start_date is not None:
        parts.append("AND e.end_date >= %s")
        params.append(start_date)
    if end_date is not None:
        parts.append("AND e.start_date <= %s")
        params.append(end_date)
    if status:
        parts.append("AND e.event_status = %s")
        params.append(status)
    if search:
        parts.append("""AND POSITION(LOWER(%s) IN LOWER(CONCAT_WS(' ',
            e.event_name, e.venue_name, e.city, e.contact_name))) > 0""")
        params.append(search)
    if archive_mode == "active":
        parts.append("AND m.archived_at IS NULL")
    elif archive_mode == "archived":
        parts.append("AND m.archived_at IS NOT NULL")
    parts.append("ORDER BY e.start_date DESC, e.event_id DESC LIMIT %s OFFSET %s")
    params.extend((limit + 1, offset))
    cursor = conn.cursor()
    try:
        cursor.execute("\n".join(parts), tuple(params))
        rows = cursor.fetchall()
    finally:
        cursor.close()

    if any(len(row) != len(COLUMNS) for row in rows):
        raise RuntimeError("Unexpected View Events query result.")
    events = [dict(zip(COLUMNS, row)) for row in rows[:limit]]
    for event in events:
        event["next_date_reference"] = event["next_date_reference"] or ""
        event["next_date_display"] = (
            event["next_date_reference"] or "Not Scheduled"
        )
        event["is_archived"] = event["archived_at"] is not None
    return {"events": events, "has_more": len(rows) > limit,
            "limit": limit, "offset": offset}
