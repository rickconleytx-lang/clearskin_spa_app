"""Private building blocks for transactional Event Editing.

Not connected to Flask. A future save coordinator must acquire
and verify the exclusive editing lock, validate the complete
replacement, and perform every change in one transaction.
"""


def _delete_old_event_dependents(
    cur, *, spa_id, workspace_id, event_id
):
    """Delete existing children in foreign-key-safe order.

    PRECONDITION: The caller already holds the exclusive event
    row and edit-lease locks in the SAME transaction.

    This function does not commit, validate a new schedule,
    update the event, or release the editing lease.
    """
    if any(
        type(value) is not int or value <= 0
        for value in (spa_id, workspace_id, event_id)
    ):
        raise ValueError("Invalid event editing scope.")

    scope = (spa_id, workspace_id, event_id)

    # Employee assignments reference unit assignments and
    # daily schedules. They must be removed first.
    tables = (
        "event_calendar_employee_assignments",
        "event_calendar_unit_assignments",
        "event_calendar_daily_schedules",
        "event_calendar_custom_values",
    )

    for table in tables:
        cur.execute(
            "DELETE FROM public." + table
            + " WHERE spa_id = %s"
            + " AND business_unit_id = %s"
            + " AND event_id = %s",
            scope,
        )

class EventEditUpdateError(RuntimeError):
    """An event could not be safely updated."""


class EventEditUpdateConflict(EventEditUpdateError):
    """Event revision changed or the target is unavailable."""


_HEADER_FIELDS = (
    ("event_name", "name"),
    ("venue_name", "venue_name"),
    ("street_address", "street_address"),
    ("address_line2", "address_line2"),
    ("city", "city"),
    ("county", "county"),
    ("state", "state"),
    ("zip_code", "zip_code"),
    ("parking_setup_location", "parking_setup_location"),
    ("start_date", "start_date"),
    ("end_date", "end_date"),
    ("contact_name", "contact_name"),
    ("contact_phone", "contact_phone"),
    ("contact_email", "contact_email"),
    ("permits_obtained", "permits_obtained"),
    ("event_status", "status"),
    ("is_public", "include_on_peachweb"),
    ("public_description", "public_description"),
    ("notes_1", "notes_1"),
    ("notes_2", "notes_2"),
)


def _positive_id(value):
    return type(value) is int and value > 0


def _update_existing_event_header(
    cur, normalized, *, spa_id, workspace_id,
    event_id, actor_id, expected_revision
):
    """Update the SAME Event ID with optimistic revision protection.

    PRECONDITION: caller holds the verified edit lease and event
    row lock in this same transaction. Never call independently.
    """
    if not all(map(_positive_id, (
        spa_id, workspace_id, event_id,
        actor_id, expected_revision,
    ))):
        raise ValueError("Invalid Event Editing identity or revision.")

    event = normalized["event"]

    values = [
        event[key] for _column, key in _HEADER_FIELDS
    ]

    assignments = [
        column + " = %s"
        for column, _key in _HEADER_FIELDS
    ]

    assignments.extend((
        "timezone_name = %s",
        "updated_by = %s",
        "updated_at = CURRENT_TIMESTAMP",
        "event_revision = event_revision + 1",
    ))

    values.extend((
        normalized["timezone_name"],
        actor_id,
        spa_id,
        workspace_id,
        event_id,
        expected_revision,
    ))

    cur.execute(
        "UPDATE public.event_calendar_events SET "
        + ", ".join(assignments)
        + " WHERE spa_id = %s"
        + " AND business_unit_id = %s"
        + " AND event_id = %s"
        + " AND event_revision = %s"
        + " RETURNING event_revision",
        tuple(values),
    )

    row = cur.fetchone()

    if row is None:
        raise EventEditUpdateConflict(
            "Event was changed or is no longer available."
        )

    revision_after = int(row[0])

    if revision_after != expected_revision + 1:
        raise EventEditUpdateError(
            "Event revision increment was inconsistent."
        )

    return revision_after


def _event_edit_changes(before, after):
    """Compare two complete, JSON-ready event read snapshots.

    Record changed fields and operating days only. The caller
    must fetch both snapshots in the same update transaction.
    """
    if type(before) is not dict or type(after) is not dict:
        raise ValueError("Invalid event history snapshots.")

    changes = {}

    for section in ("event", "custom_values", "custom_labels"):
        old = before[section]
        new = after[section]

        differences = {}

        for key in sorted(set(old) | set(new)):
            if old.get(key) != new.get(key):
                differences[key] = {
                    "before": old.get(key),
                    "after": new.get(key),
                }

        if differences:
            changes[section] = differences

    old_days = {day["date"]: day for day in before["days"]}
    new_days = {day["date"]: day for day in after["days"]}

    differences = {}

    for key in sorted(set(old_days) | set(new_days)):
        if old_days.get(key) != new_days.get(key):
            differences[key] = {
                "before": old_days.get(key),
                "after": new_days.get(key),
            }

    if differences:
        changes["days"] = differences

    return changes


def _append_event_edit_history(
    cur, *, spa_id, workspace_id, event_id,
    actor_id, actor_display_name,
    revision_before, revision_after, changes
):
    """Write immutable history inside the event update transaction.

    Database constraints enforce one history row per new revision.
    Caller must retrieve the editor identity from authenticated
    server context, never from browser-supplied fields.
    """
    import json

    if not all(map(_positive_id, (
        spa_id, workspace_id, event_id,
        actor_id, revision_before,
    ))):
        raise ValueError("Invalid Event Edit history scope.")

    if (
        type(revision_after) is not int
        or revision_after != revision_before + 1
    ):
        raise ValueError("Invalid Event Edit history revision.")

    if (
        type(actor_display_name) is not str
        or not actor_display_name.strip()
        or len(actor_display_name.strip()) > 200
    ):
        raise ValueError("Invalid Event Edit editor display name.")

    if type(changes) is not dict:
        raise ValueError("Invalid Event Edit change record.")

    encoded = json.dumps(
        changes, ensure_ascii=False, allow_nan=False
    )

    cur.execute(
        """
        INSERT INTO public.event_calendar_edit_history (
            spa_id, business_unit_id, event_id,
            action_type, revision_before, revision_after,
            actor_user_id, actor_display_name, changes_json
        )
        VALUES (
            %s, %s, %s, 'edit', %s, %s,
            %s, %s, %s::jsonb
        )
        RETURNING history_id
        """,
        (
            spa_id, workspace_id, event_id,
            revision_before, revision_after,
            actor_id, actor_display_name.strip(), encoded,
        ),
    )

    row = cur.fetchone()

    if not row or not _positive_id(int(row[0])):
        raise EventEditUpdateError(
            "Event Edit history could not be recorded."
        )

    return int(row[0])


from services.event_calendar_edit_locks import (
    EventEditLockConflict, require_event_edit_lock_for_save,
)
from services.event_calendar_edit_read import load_event_edit_payload
from services.event_calendar_validation import (
    EventValidationError, validate_event_payload,
)
from services.event_calendar_resources import (
    EventResourceError, validate_event_resource_ownership,
)
from services.event_calendar_availability import (
    EventAvailabilityError, validate_existing_event_availability,
)
from services.event_calendar_save import _create_schedules, _create_custom_values


def update_event_draft(
    conn, payload, *, spa_id, workspace_id, event_id,
    actor_id, actor_display_name, lock_token, expected_revision,
):
    """Atomically edit one existing event using its exclusive lease.

    Call only after Flask authenticates and authorizes the administrator.
    All scope and actor values must be server-derived except for the event
    path identifier, lock token, and expected revision, which are verified.
    This service owns commit/rollback, but never connection close. It is
    intentionally NOT attached to an HTTP route until DB tests pass.
    """
    if not all(map(_positive_id, (
        spa_id, workspace_id, event_id, actor_id, expected_revision,
    ))):
        raise ValueError("Invalid Event Edit identity or revision.")

    if (
        type(actor_display_name) is not str
        or not actor_display_name.strip()
        or len(actor_display_name.strip()) > 200
    ):
        raise ValueError("Invalid Event Edit administrator display name.")

    if type(lock_token) is not str or not lock_token.strip():
        raise ValueError("Invalid Event Edit session token.")

    if conn.autocommit:
        raise EventEditUpdateError(
            "Editing requires one database transaction."
        )

    try:
        with conn.cursor() as cur:
            # Row-lock both the event and lease for the entire transaction.
            require_event_edit_lock_for_save(
                cur, spa_id=spa_id, workspace_id=workspace_id,
                event_id=event_id, actor_id=actor_id,
                lock_token=lock_token, expected_revision=expected_revision,
            )

            before = load_event_edit_payload(
                conn, event_id=event_id,
                spa_id=spa_id, workspace_id=workspace_id,
            )
            if before is None:
                raise EventEditUpdateConflict(
                    "Event is no longer available for editing."
                )
            if before["event_revision"] != expected_revision:
                raise EventEditUpdateConflict(
                    "Event revision changed during editing."
                )

            # Same trusted business timezone source as Create Event.
            cur.execute(
                "SELECT timezone_name FROM public.spas "
                "WHERE spa_id = %s FOR SHARE",
                (spa_id,),
            )
            zone_row = cur.fetchone()
            if not zone_row or not zone_row[0]:
                raise EventEditUpdateInvalid(
                    "Business time zone is not configured."
                )
            normalized = validate_event_payload(payload, zone_row[0])
            validate_event_resource_ownership(
                cur, normalized, spa_id, workspace_id,
            )
            if normalized["event"]["status"] != "cancelled":
                validate_existing_event_availability(
                    cur, normalized, spa_id,
                    excluded_event=(workspace_id, event_id),
                )

            # Everything below is protected by the lease and one transaction.
            revision_after = _update_existing_event_header(
                cur, normalized, spa_id=spa_id,
                workspace_id=workspace_id, event_id=event_id,
                actor_id=actor_id, expected_revision=expected_revision,
            )
            _delete_old_event_dependents(
                cur, spa_id=spa_id, workspace_id=workspace_id,
                event_id=event_id,
            )
            counts = _create_schedules(
                cur, normalized, spa_id, workspace_id, actor_id, event_id,
            )
            counts["custom_values"] = _create_custom_values(
                cur, normalized, spa_id, workspace_id, event_id,
            )

            after = load_event_edit_payload(
                conn, event_id=event_id,
                spa_id=spa_id, workspace_id=workspace_id,
            )
            if after is None or after["event_revision"] != revision_after:
                raise EventEditUpdateError(
                    "Updated event could not be verified."
                )
            changes = _event_edit_changes(before, after)
            if not changes:
                raise EventEditUpdateInvalid(
                    "No event changes were detected."
                )

            history_id = _append_event_edit_history(
                cur, spa_id=spa_id, workspace_id=workspace_id,
                event_id=event_id, actor_id=actor_id,
                actor_display_name=actor_display_name,
                revision_before=expected_revision,
                revision_after=revision_after, changes=changes,
            )

            # Consume the very same lease only after all writes succeeded.
            # Recheck expiration against DB clock; failure rolls back all.
            cur.execute(
                "DELETE FROM public.event_calendar_edit_locks "
                "WHERE spa_id = %s AND business_unit_id = %s "
                "AND event_id = %s AND editor_user_id = %s "
                "AND lock_token = %s::uuid "
                "AND expires_at > clock_timestamp() "
                "RETURNING event_id",
                (spa_id, workspace_id, event_id, actor_id, lock_token),
            )
            released = cur.fetchone()
            if released is None or int(released[0]) != event_id:
                raise EventEditUpdateConflict(
                    "Editing session expired before save completed."
                )

        conn.commit()
        return {
            "event_id": event_id,
            "revision_before": expected_revision,
            "revision_after": revision_after,
            "history_id": history_id,
            "updated": True,
            **counts,
        }

    except (EventValidationError, EventResourceError) as exc:
        conn.rollback()
        raise EventEditUpdateInvalid(str(exc)) from exc
    except (EventAvailabilityError, EventEditLockConflict) as exc:
        conn.rollback()
        raise EventEditUpdateConflict(str(exc)) from exc
    except Exception as exc:
        conn.rollback()
        code = getattr(exc, "pgcode", None) or getattr(exc, "sqlstate", None)
        if code == "23P01":
            raise EventEditUpdateConflict(
                "Equipment or employee is already reserved "
                "during the proposed time."
            ) from exc
        raise


class EventEditUpdateInvalid(EventEditUpdateError):
    """Edit payload or selected resources are invalid."""
