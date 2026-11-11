"""Exclusive editing leases for PeachPOS Event Calendar.

Flask must authenticate the administrator and derive all scope IDs
from the server-side session and workspace membership.

Acquisition, renewal, and release own their transactions.
The save guard uses the caller's existing transaction.
"""

import uuid


LEASE_INTERVAL_SQL = "INTERVAL '15 minutes'"


class EventEditLockError(Exception):
    """Invalid editing-lock operation or connection."""


class EventEditLockConflict(EventEditLockError):
    """Lock missing, expired, or revision no longer current."""


def _scope(spa_id, workspace_id, event_id, actor_id):
    for name, value in (
        ("spa_id", spa_id),
        ("workspace_id", workspace_id),
        ("event_id", event_id),
        ("actor_id", actor_id),
    ):
        if type(value) is not int or value <= 0:
            raise EventEditLockError(f"Invalid {name}.")


def _revision(value):
    if type(value) is not int or value < 1:
        raise EventEditLockError("Invalid event revision.")
    return value


def _token(value):
    try:
        parsed = uuid.UUID(str(value))
    except (TypeError, ValueError, AttributeError):
        raise EventEditLockError("Invalid edit-session token.") from None

    if parsed.version != 4:
        raise EventEditLockError("Invalid edit-session token.")

    return str(parsed)


def _transaction_connection(conn):
    if getattr(conn, "autocommit", None) is not False:
        raise EventEditLockError(
            "Editing-lock operations require a database transaction."
        )


def acquire_event_edit_lock(
    conn, *, spa_id, workspace_id, event_id, actor_id
):
    """Acquire a new exclusive session lease or identify its holder.

    A second tab, even for the same administrator, cannot replace
    an unexpired lease. Expired leases may be replaced atomically.
    """
    _scope(spa_id, workspace_id, event_id, actor_id)
    _transaction_connection(conn)

    with conn:
        with conn.cursor() as cur:
            # Serialize against other acquisitions and future saves.
            cur.execute(
                """
                SELECT event_revision
                FROM public.event_calendar_events
                WHERE spa_id = %s
                  AND business_unit_id = %s
                  AND event_id = %s
                FOR UPDATE
                """,
                (spa_id, workspace_id, event_id),
            )
            event = cur.fetchone()

            if event is None:
                return {"status": "not_found"}

            current_revision = int(event[0])
            new_token = str(uuid.uuid4())

            cur.execute(
                """
                WITH tick AS MATERIALIZED (
                    SELECT clock_timestamp() AS now
                )
                INSERT INTO public.event_calendar_edit_locks AS held (
                    spa_id, business_unit_id, event_id,
                    editor_user_id, lock_token, base_revision,
                    acquired_at, last_activity_at, expires_at
                )
                SELECT
                    %s, %s, %s, %s, %s::uuid, %s,
                    tick.now, tick.now,
                    tick.now + INTERVAL '15 minutes'
                FROM tick
                WHERE TRUE
                ON CONFLICT (spa_id, business_unit_id, event_id)
                DO UPDATE SET
                    editor_user_id = EXCLUDED.editor_user_id,
                    lock_token = EXCLUDED.lock_token,
                    base_revision = EXCLUDED.base_revision,
                    acquired_at = EXCLUDED.acquired_at,
                    last_activity_at = EXCLUDED.last_activity_at,
                    expires_at = EXCLUDED.expires_at
                WHERE held.expires_at <= EXCLUDED.acquired_at
                RETURNING lock_token, base_revision, expires_at
                """,
                (
                    spa_id, workspace_id, event_id,
                    actor_id, new_token, current_revision,
                ),
            )

            acquired = cur.fetchone()

            if acquired is not None:
                return {
                    "status": "acquired",
                    "lock_token": str(acquired[0]),
                    "event_revision": int(acquired[1]),
                    "expires_at": acquired[2].isoformat(),
                }

            # Never expose the other editor's email address.
            cur.execute(
                """
                SELECT
                    COALESCE(
                        NULLIF(
                            BTRIM(
                                CONCAT_WS(
                                    ' ', u.first_name, u.last_name
                                )
                            ),
                            ''
                        ),
                        'Another administrator'
                    ),
                    l.expires_at
                FROM public.event_calendar_edit_locks AS l
                LEFT JOIN public.users AS u
                    ON u.user_id = l.editor_user_id
                WHERE l.spa_id = %s
                  AND l.business_unit_id = %s
                  AND l.event_id = %s
                """,
                (spa_id, workspace_id, event_id),
            )

            holder = cur.fetchone()

            return {
                "status": "busy",
                "editor_display_name": (
                    holder[0] if holder
                    else "Another administrator"
                ),
                "expires_at": (
                    holder[1].isoformat()
                    if holder and holder[1] else None
                ),
            }


def renew_event_edit_lock(
    conn, *, spa_id, workspace_id, event_id,
    actor_id, lock_token
):
    """Extend a valid lease only following actual editing activity.

    The future HTTP handler must not use an unconditional heartbeat.
    """
    _scope(spa_id, workspace_id, event_id, actor_id)
    token = _token(lock_token)
    _transaction_connection(conn)

    with conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                WITH tick AS MATERIALIZED (
                    SELECT clock_timestamp() AS now
                )
                UPDATE public.event_calendar_edit_locks AS l
                SET
                    last_activity_at = tick.now,
                    expires_at = tick.now + INTERVAL '15 minutes'
                FROM tick, public.event_calendar_events AS e
                WHERE l.spa_id = %s
                  AND l.business_unit_id = %s
                  AND l.event_id = %s
                  AND l.editor_user_id = %s
                  AND l.lock_token = %s::uuid
                  AND e.spa_id = l.spa_id
                  AND e.business_unit_id = l.business_unit_id
                  AND e.event_id = l.event_id
                  AND e.event_revision = l.base_revision
                  AND l.expires_at > tick.now
                  AND l.last_activity_at <= tick.now
                RETURNING l.expires_at, l.base_revision
                """,
                (
                    spa_id, workspace_id, event_id,
                    actor_id, token,
                ),
            )

            renewed = cur.fetchone()

            if renewed is None:
                return {"status": "lost"}

            return {
                "status": "renewed",
                "expires_at": renewed[0].isoformat(),
                "event_revision": int(renewed[1]),
            }


def release_event_edit_lock(
    conn, *, spa_id, workspace_id, event_id,
    actor_id, lock_token
):
    """Release only the exact editor/session lock."""
    _scope(spa_id, workspace_id, event_id, actor_id)
    token = _token(lock_token)
    _transaction_connection(conn)

    with conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                DELETE FROM public.event_calendar_edit_locks
                WHERE spa_id = %s
                  AND business_unit_id = %s
                  AND event_id = %s
                  AND editor_user_id = %s
                  AND lock_token = %s::uuid
                RETURNING event_id
                """,
                (
                    spa_id, workspace_id, event_id,
                    actor_id, token,
                ),
            )

            return {"released": cur.fetchone() is not None}


def require_event_edit_lock_for_save(
    cur, *, spa_id, workspace_id, event_id,
    actor_id, lock_token, expected_revision
):
    """Guard an edit in the SAME transaction as its eventual save.

    Keeps both the event and its lease row locked until the caller
    commits or rolls back. It does not perform the edit itself.
    """
    _scope(spa_id, workspace_id, event_id, actor_id)
    token = _token(lock_token)
    revision = _revision(expected_revision)

    cur.execute(
        """
        SELECT
            e.event_revision,
            l.base_revision,
            l.expires_at
        FROM public.event_calendar_events AS e
        JOIN public.event_calendar_edit_locks AS l
          ON l.spa_id = e.spa_id
         AND l.business_unit_id = e.business_unit_id
         AND l.event_id = e.event_id
        WHERE e.spa_id = %s
          AND e.business_unit_id = %s
          AND e.event_id = %s
          AND l.editor_user_id = %s
          AND l.lock_token = %s::uuid
        FOR UPDATE OF e, l
        """,
        (
            spa_id, workspace_id, event_id,
            actor_id, token,
        ),
    )

    row = cur.fetchone()

    if row is None:
        raise EventEditLockConflict(
            "Editing session is no longer valid."
        )

    cur.execute("SELECT clock_timestamp()")
    now = cur.fetchone()[0]

    event_revision, base_revision, expires_at = row

    if (
        int(event_revision) != revision
        or int(base_revision) != revision
        or expires_at <= now
    ):
        raise EventEditLockConflict(
            "Editing lease expired or event revision changed."
        )

    return revision


def require_event_edit_lock_for_read(
    cur, *, spa_id, workspace_id, event_id,
    actor_id, lock_token
):
    """Verify an active editing session without modifying the database.

    Caller must use a REPEATABLE READ, READ ONLY transaction and
    load the event draft within that same transaction.

    This check does not renew the lease. The eventual save still
    requires require_event_edit_lock_for_save(), which locks rows
    and rechecks the revision in the save transaction.
    """
    _scope(spa_id, workspace_id, event_id, actor_id)
    token = _token(lock_token)

    cur.execute(
        """
        SELECT
            e.event_revision,
            l.base_revision,
            l.expires_at > clock_timestamp() AS lease_active
        FROM public.event_calendar_events AS e
        JOIN public.event_calendar_edit_locks AS l
          ON l.spa_id = e.spa_id
         AND l.business_unit_id = e.business_unit_id
         AND l.event_id = e.event_id
        WHERE e.spa_id = %s
          AND e.business_unit_id = %s
          AND e.event_id = %s
          AND l.editor_user_id = %s
          AND l.lock_token = %s::uuid
        """,
        (
            spa_id, workspace_id, event_id,
            actor_id, token,
        ),
    )

    row = cur.fetchone()

    if row is None:
        raise EventEditLockConflict(
            "Editing session is no longer available."
        )

    event_revision, base_revision, active = row

    if (
        not active
        or int(event_revision) != int(base_revision)
    ):
        raise EventEditLockConflict(
            "Editing session expired or event revision changed."
        )

    return int(event_revision)
