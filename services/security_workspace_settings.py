from psycopg2.extras import RealDictCursor

from db import get_db_connection


class SecurityWorkspaceSettingsError(RuntimeError):

    """Raised when workspace security settings cannot be handled safely."""


VALID_INACTIVITY_TIMEOUT_MINUTES = {
    30,
    45,
    60,
    90,
}

VALID_ABSOLUTE_SESSION_HOURS = {
    4,
    6,
    8,
    10,
}

DEFAULT_SECURITY_WORKSPACE_SETTINGS = {
    "inactivity_timeout_minutes": 60,
    "absolute_session_hours": 10,
}


def load_security_workspace_settings(
    cursor,
    *,
    spa_id,
    business_unit_id,
):
    """
    Read business-login security settings inside a caller-owned
    database transaction.

    This function does not commit, roll back, or close the
    caller's cursor. Missing settings use secure defaults.
    """

    if cursor is None:
        raise SecurityWorkspaceSettingsError(
            "A database cursor is required."
        )

    if not spa_id or not business_unit_id:
        raise SecurityWorkspaceSettingsError(
            "Security workspace context is incomplete."
        )

    cursor.execute("""
        SELECT
            security_workspace_setting_id,
            inactivity_timeout_minutes,
            absolute_session_hours
        FROM security_workspace_settings
        WHERE spa_id = %s
          AND business_unit_id = %s
        LIMIT 1
    """, (
        spa_id,
        business_unit_id,
    ))

    row = cursor.fetchone()

    if row is None:
        return {
            "security_workspace_setting_id": None,
            "spa_id": spa_id,
            "business_unit_id": business_unit_id,
            "inactivity_timeout_minutes": (
                DEFAULT_SECURITY_WORKSPACE_SETTINGS[
                    "inactivity_timeout_minutes"
                ]
            ),
            "absolute_session_hours": (
                DEFAULT_SECURITY_WORKSPACE_SETTINGS[
                    "absolute_session_hours"
                ]
            ),
            "is_persisted": False,
        }

    inactivity_timeout_minutes = int(row[1])
    absolute_session_hours = int(row[2])

    if (
        inactivity_timeout_minutes
        not in VALID_INACTIVITY_TIMEOUT_MINUTES
    ):
        raise SecurityWorkspaceSettingsError(
            "Stored inactivity timeout is invalid."
        )

    if (
        absolute_session_hours
        not in VALID_ABSOLUTE_SESSION_HOURS
    ):
        raise SecurityWorkspaceSettingsError(
            "Stored absolute session lifetime is invalid."
        )

    return {
        "security_workspace_setting_id": row[0],
        "spa_id": spa_id,
        "business_unit_id": business_unit_id,
        "inactivity_timeout_minutes": (
            inactivity_timeout_minutes
        ),
        "absolute_session_hours": (
            absolute_session_hours
        ),
        "is_persisted": True,
    }


def get_security_workspace_settings(
    *,
    spa_id,
    business_unit_id,
):
    """
    Return business-login security settings for one PSP workspace.

    A workspace with no persisted settings row receives secure
    defaults without creating a database record.
    """

    if not spa_id or not business_unit_id:
        raise SecurityWorkspaceSettingsError(
            "Security workspace context is incomplete."
        )

    conn = get_db_connection()
    cur = conn.cursor(
        cursor_factory=RealDictCursor
    )

    try:
        cur.execute("""
            SELECT
                security_workspace_setting_id,
                spa_id,
                business_unit_id,
                inactivity_timeout_minutes,
                absolute_session_hours,
                created_by,
                updated_by,
                created_at,
                updated_at
            FROM security_workspace_settings
            WHERE spa_id = %s
              AND business_unit_id = %s
        """, (
            spa_id,
            business_unit_id,
        ))

        row = cur.fetchone()

    finally:
        cur.close()
        conn.close()

    if row is None:
        return {
            "security_workspace_setting_id": None,
            "spa_id": spa_id,
            "business_unit_id": business_unit_id,
            "inactivity_timeout_minutes": (
                DEFAULT_SECURITY_WORKSPACE_SETTINGS[
                    "inactivity_timeout_minutes"
                ]
            ),
            "absolute_session_hours": (
                DEFAULT_SECURITY_WORKSPACE_SETTINGS[
                    "absolute_session_hours"
                ]
            ),
            "created_by": None,
            "updated_by": None,
            "created_at": None,
            "updated_at": None,
            "is_persisted": False,
        }

    result = dict(row)

    inactivity_timeout_minutes = int(
        result["inactivity_timeout_minutes"]
    )
    absolute_session_hours = int(
        result["absolute_session_hours"]
    )

    if (
        inactivity_timeout_minutes
        not in VALID_INACTIVITY_TIMEOUT_MINUTES
    ):
        raise SecurityWorkspaceSettingsError(
            "Stored inactivity timeout is invalid."
        )

    if (
        absolute_session_hours
        not in VALID_ABSOLUTE_SESSION_HOURS
    ):
        raise SecurityWorkspaceSettingsError(
            "Stored absolute session lifetime is invalid."
        )

    result["inactivity_timeout_minutes"] = (
        inactivity_timeout_minutes
    )
    result["absolute_session_hours"] = (
        absolute_session_hours
    )
    result["is_persisted"] = True

    return result


def save_security_workspace_settings(
    *,
    spa_id,
    business_unit_id,
    inactivity_timeout_minutes,
    absolute_session_hours,
    actor_user_id=None,
):
    """
    Create or update business-login security settings for one
    authenticated PSP workspace.
    """

    if not spa_id or not business_unit_id:
        raise SecurityWorkspaceSettingsError(
            "Security workspace context is incomplete."
        )

    try:
        inactivity_timeout_minutes = int(
            inactivity_timeout_minutes
        )
    except (TypeError, ValueError):
        raise SecurityWorkspaceSettingsError(
            "Inactivity timeout is invalid."
        )

    try:
        absolute_session_hours = int(
            absolute_session_hours
        )
    except (TypeError, ValueError):
        raise SecurityWorkspaceSettingsError(
            "Absolute session lifetime is invalid."
        )

    if (
        inactivity_timeout_minutes
        not in VALID_INACTIVITY_TIMEOUT_MINUTES
    ):
        raise SecurityWorkspaceSettingsError(
            "Inactivity timeout must be "
            "30, 45, 60, or 90 minutes."
        )

    if (
        absolute_session_hours
        not in VALID_ABSOLUTE_SESSION_HOURS
    ):
        raise SecurityWorkspaceSettingsError(
            "Absolute session lifetime must be "
            "4, 6, 8, or 10 hours."
        )

    conn = get_db_connection()
    cur = conn.cursor(
        cursor_factory=RealDictCursor
    )

    try:
        cur.execute("""
            INSERT INTO security_workspace_settings (
                spa_id,
                business_unit_id,
                inactivity_timeout_minutes,
                absolute_session_hours,
                created_by,
                updated_by
            )
            VALUES (
                %s,
                %s,
                %s,
                %s,
                %s,
                %s
            )
            ON CONFLICT (
                spa_id,
                business_unit_id
            )
            DO UPDATE SET
                inactivity_timeout_minutes = (
                    EXCLUDED.inactivity_timeout_minutes
                ),
                absolute_session_hours = (
                    EXCLUDED.absolute_session_hours
                ),
                updated_by = EXCLUDED.updated_by,
                updated_at = NOW()
            RETURNING
                security_workspace_setting_id,
                spa_id,
                business_unit_id,
                inactivity_timeout_minutes,
                absolute_session_hours,
                created_by,
                updated_by,
                created_at,
                updated_at
        """, (
            spa_id,
            business_unit_id,
            inactivity_timeout_minutes,
            absolute_session_hours,
            actor_user_id,
            actor_user_id,
        ))

        row = cur.fetchone()

        if row is None:
            raise SecurityWorkspaceSettingsError(
                "Security workspace settings were not saved."
            )

        conn.commit()

    except Exception:
        conn.rollback()
        raise

    finally:
        cur.close()
        conn.close()

    result = dict(row)
    result["is_persisted"] = True

    return result
