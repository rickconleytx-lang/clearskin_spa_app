"""Atomic PeachPOS Event Calendar creation.

This service is intentionally disconnected from Flask until
transaction, idempotency, conflict, and authorization tests pass.

The caller supplies an authenticated business/workspace/user
scope and owns closing the database connection.
"""

import hashlib
import json
import uuid

from services.event_calendar_validation import (
    EventValidationError,
    validate_event_payload,
)
from services.event_calendar_resources import (
    EventResourceError,
    validate_event_resource_ownership,
)
from services.event_calendar_availability import (
    EventAvailabilityError,
    validate_existing_event_availability,
)


class EventSaveError(ValueError):
    """An event could not be saved safely."""


class EventSaveConflict(EventSaveError):
    """A submitted reservation conflicts with another booking."""


class EventSaveInvalid(EventSaveError):
    """The submitted data or submission identity is invalid."""


def event_request_fingerprint(payload):
    """Stable SHA-256 of the event request, excluding the token.

    The caller supplies the event payload, not the surrounding
    form. This lets identical retries share the same fingerprint.
    """
    if type(payload) is not dict:
        raise EventSaveInvalid("Invalid event submission.")

    try:
        encoded = json.dumps(
            payload,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
            allow_nan=False,
        ).encode("utf-8")
    except (TypeError, ValueError, OverflowError) as exc:
        raise EventSaveInvalid(
            "Invalid event submission format."
        ) from exc

    return hashlib.sha256(encoded).hexdigest()


def _submission_uuid(value):
    if not isinstance(value, (str, uuid.UUID)):
        raise EventSaveInvalid("Invalid submission token.")

    try:
        token = uuid.UUID(str(value))
    except (ValueError, AttributeError) as exc:
        raise EventSaveInvalid(
            "Invalid submission token."
        ) from exc

    if token.version != 4:
        raise EventSaveInvalid(
            "A version 4 submission token is required."
        )

    return str(token)


def _assert_scope(spa_id, workspace_id, actor_id):
    for value in (spa_id, workspace_id, actor_id):
        if type(value) is not int or value <= 0:
            raise EventSaveInvalid(
                "Invalid authenticated event scope."
            )


def _claim_submission(
    cur, token, spa_id, workspace_id, actor_id, fingerprint
):
    """Claim token atomically or return the prior saved event.

    PostgreSQL's unique token constraint serializes simultaneous
    requests for the same token. Completion and event creation
    must occur in this same transaction.
    """

    cur.execute(
        """
        INSERT INTO event_calendar_save_submissions (
            submission_token,
            spa_id,
            business_unit_id,
            request_sha256,
            created_by
        )
        VALUES (%s::uuid, %s, %s, %s, %s)
        ON CONFLICT (submission_token) DO NOTHING
        RETURNING submission_token
        """,
        (
            token,
            spa_id,
            workspace_id,
            fingerprint,
            actor_id,
        ),
    )

    if cur.fetchone() is not None:
        return None

    cur.execute(
        """
        SELECT spa_id,
               business_unit_id,
               request_sha256,
               event_id,
               completed_at
        FROM event_calendar_save_submissions
        WHERE submission_token = %s::uuid
        FOR UPDATE
        """,
        (token,),
    )

    existing = cur.fetchone()

    if not existing:
        raise EventSaveInvalid(
            "Submission identity could not be verified."
        )

    prior_spa, prior_workspace, prior_hash, event_id, completed = (
        existing
    )

    if (
        prior_spa != spa_id
        or prior_workspace != workspace_id
    ):
        raise EventSaveInvalid(
            "Submission token is unavailable."
        )

    if prior_hash != fingerprint:
        raise EventSaveInvalid(
            "Submission token was reused with different data."
        )

    if event_id is None or completed is None:
        raise EventSaveInvalid(
            "Submission is incomplete."
        )

    return int(event_id)


def _create_event(cur, normalized, spa_id, workspace_id, actor_id):
    event = normalized["event"]

    columns = (
        "spa_id",
        "business_unit_id",
        "event_name",
        "venue_name",
        "street_address",
        "address_line2",
        "city",
        "county",
        "state",
        "zip_code",
        "parking_setup_location",
        "start_date",
        "end_date",
        "timezone_name",
        "contact_name",
        "contact_phone",
        "contact_email",
        "permits_obtained",
        "event_status",
        "is_public",
        "public_description",
        "notes_1",
        "notes_2",
        "created_by",
    )

    values = (
        spa_id,
        workspace_id,
        event["name"],
        event["venue_name"],
        event["street_address"],
        event["address_line2"],
        event["city"],
        event["county"],
        event["state"],
        event["zip_code"],
        event["parking_setup_location"],
        event["start_date"],
        event["end_date"],
        normalized["timezone_name"],
        event["contact_name"],
        event["contact_phone"],
        event["contact_email"],
        event["permits_obtained"],
        event["status"],
        event["include_on_peachweb"],
        event["public_description"],
        event["notes_1"],
        event["notes_2"],
        actor_id,
    )

    if len(columns) != len(values):
        raise EventSaveError(
            "Event persistence mapping is inconsistent."
        )

    placeholders = ", ".join(["%s"] * len(columns))

    cur.execute(
        "INSERT INTO event_calendar_events ("
        + ", ".join(columns)
        + ") VALUES ("
        + placeholders
        + ") RETURNING event_id",
        values,
    )

    return int(cur.fetchone()[0])


def _create_schedules(
    cur, normalized, spa_id, workspace_id, actor_id, event_id
):
    counts = {
        "operating_days": 0,
        "equipment_assignments": 0,
        "employee_shifts": 0,
    }

    # Cancelled events may retain scheduling information, but
    # must not hold active equipment or employee reservations.
    active_reservations = (
        normalized["event"]["status"] != "cancelled"
    )

    for day in normalized["days"]:
        if not day["operating"]:
            continue

        cur.execute(
            """
            INSERT INTO event_calendar_daily_schedules (
                spa_id, business_unit_id, event_id,
                operating_date, opens_at, closes_at,
                setup_at, breakdown_at, daily_notes, created_by
            )
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            RETURNING daily_schedule_id
            """,
            (
                spa_id, workspace_id, event_id,
                day["date"],
                day["opens_at"], day["closes_at"],
                day["setup_at"], day["breakdown_at"],
                day["notes"], actor_id,
            ),
        )

        day_id = int(cur.fetchone()[0])
        counts["operating_days"] += 1

        assignments = {}

        for unit_id in day["equipment_ids"]:
            cur.execute(
                """
                INSERT INTO event_calendar_unit_assignments (
                    spa_id, business_unit_id, event_id,
                    daily_schedule_id, event_unit_id,
                    assigned_start_at, assigned_end_at,
                    is_active, created_by
                )
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
                RETURNING unit_assignment_id
                """,
                (
                    spa_id, workspace_id, event_id, day_id,
                    unit_id,
                    day["occupancy_start"],
                    day["occupancy_end"],
                    active_reservations,
                    actor_id,
                ),
            )

            assignments[unit_id] = int(cur.fetchone()[0])
            counts["equipment_assignments"] += 1

        for shift in day["shifts"]:
            unit_id = shift["unit_id"]

            if unit_id is not None and unit_id not in assignments:
                raise EventSaveInvalid(
                    "Employee shift references equipment "
                    "not assigned to that operating day."
                )

            unit_assignment_id = (
                assignments[unit_id]
                if unit_id is not None
                else None
            )

            cur.execute(
                """
                INSERT INTO event_calendar_employee_assignments (
                    spa_id, business_unit_id, event_id,
                    daily_schedule_id, employee_id,
                    unit_assignment_id, shift_start_at,
                    shift_end_at, shift_role, shift_notes,
                    is_active, created_by
                )
                VALUES (
                    %s, %s, %s, %s, %s, %s,
                    %s, %s, %s, %s, %s, %s
                )
                """,
                (
                    spa_id, workspace_id, event_id, day_id,
                    shift["employee_id"],
                    unit_assignment_id,
                    shift["starts_at"], shift["ends_at"],
                    shift["role"], shift["notes"],
                    active_reservations, actor_id,
                ),
            )

            counts["employee_shifts"] += 1

    if not counts["operating_days"]:
        raise EventSaveInvalid(
            "At least one operating day is required."
        )

    return counts


def _create_custom_values(
    cur, normalized, spa_id, workspace_id, event_id
):
    cur.execute(
        """
        SELECT slot_number, field_label
        FROM event_calendar_custom_labels
        WHERE spa_id = %s
        ORDER BY slot_number
        FOR SHARE
        """,
        (spa_id,),
    )

    labels = {
        int(slot): label
        for slot, label in cur.fetchall()
    }

    count = 0

    for slot in (1, 2, 3):
        value = normalized["custom_values"][str(slot)]

        if not value:
            continue

        label = labels.get(slot, f"Default {slot}")

        cur.execute(
            """
            INSERT INTO event_calendar_custom_values (
                spa_id, business_unit_id, event_id,
                slot_number, field_label_snapshot, field_value
            )
            VALUES (%s, %s, %s, %s, %s, %s)
            """,
            (
                spa_id, workspace_id, event_id,
                slot, label, value,
            ),
        )

        count += 1

    return count


def save_event_draft(
    conn, payload, spa_id, workspace_id, actor_id,
    submission_token
):
    """Save one event, or return the event from an exact retry.

    Owns commit/rollback, but not connection close.

    IMPORTANT: Authenticate and authorize the actor in Flask.
    Do not take spa_id, workspace_id, or actor_id from the
    browser payload. This function must remain disconnected
    from HTTP until its transactional tests have passed.
    """

    _assert_scope(spa_id, workspace_id, actor_id)
    token = _submission_uuid(submission_token)
    fingerprint = event_request_fingerprint(payload)

    if conn.autocommit:
        raise EventSaveError(
            "Event saving requires a database transaction."
        )

    try:
        with conn.cursor() as cur:
            previous_id = _claim_submission(
                cur, token, spa_id, workspace_id,
                actor_id, fingerprint,
            )

            if previous_id is not None:
                conn.rollback()
                return {
                    "event_id": previous_id,
                    "created": False,
                    "duplicate": True,
                }

            cur.execute(
                """
                SELECT timezone_name
                FROM spas
                WHERE spa_id = %s
                FOR SHARE
                """,
                (spa_id,),
            )

            row = cur.fetchone()

            if not row or not row[0]:
                raise EventSaveInvalid(
                    "Business time zone is not configured."
                )

            normalized = validate_event_payload(
                payload, row[0]
            )

            validate_event_resource_ownership(
                cur, normalized, spa_id, workspace_id
            )

            # Cancelled events do not reserve active resources.
            if normalized["event"]["status"] != "cancelled":
                validate_existing_event_availability(
                    cur, normalized, spa_id
                )

            event_id = _create_event(
                cur, normalized, spa_id, workspace_id, actor_id
            )

            # Reference metadata is in the SAME idempotent creation transaction.
            # Blank/omitted references need no metadata row.
            next_occurrence = normalized["event"].get("next_occurrence", "")
            if next_occurrence:
                from services.event_calendar_view_events import upsert_next_occurrence
                upsert_next_occurrence(
                    cur, spa_id=spa_id, workspace_id=workspace_id,
                    event_id=event_id, reference=next_occurrence,
                )

            counts = _create_schedules(
                cur, normalized, spa_id, workspace_id,
                actor_id, event_id,
            )

            counts["custom_values"] = _create_custom_values(
                cur, normalized, spa_id, workspace_id, event_id
            )

            cur.execute(
                """
                UPDATE event_calendar_save_submissions
                SET event_id = %s,
                    completed_at = CURRENT_TIMESTAMP
                WHERE submission_token = %s::uuid
                  AND spa_id = %s
                  AND business_unit_id = %s
                  AND event_id IS NULL
                RETURNING event_id
                """,
                (event_id, token, spa_id, workspace_id),
            )

            completed = cur.fetchone()

            if not completed or int(completed[0]) != event_id:
                raise EventSaveError(
                    "Event submission completion failed."
                )

        # The only success commit for a newly created event.
        conn.commit()

        return {
            "event_id": event_id,
            "created": True,
            "duplicate": False,
            **counts,
        }

    except (EventValidationError, EventResourceError) as exc:
        conn.rollback()
        raise EventSaveInvalid(str(exc)) from exc

    except EventAvailabilityError as exc:
        conn.rollback()
        raise EventSaveConflict(str(exc)) from exc

    except Exception as exc:
        conn.rollback()

        code = (
            getattr(exc, "pgcode", None)
            or getattr(exc, "sqlstate", None)
        )

        if code == "23P01":
            raise EventSaveConflict(
                "Equipment or employee is already reserved "
                "during the proposed time."
            ) from exc

        raise
