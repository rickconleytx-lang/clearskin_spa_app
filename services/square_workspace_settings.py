from psycopg2.extras import RealDictCursor

from db import get_db_connection


class SquareWorkspaceSettingsError(RuntimeError):
    """Raised when Square workspace settings cannot be saved safely."""


PROCESSING_MODE_APPOINTMENT_SERVICE = "appointment_service"
PROCESSING_MODE_POS_DAILY_SALES = "pos_daily_sales"

VALID_PROCESSING_MODES = {
    PROCESSING_MODE_APPOINTMENT_SERVICE,
    PROCESSING_MODE_POS_DAILY_SALES,
}

DEFAULT_SQUARE_WORKSPACE_SETTINGS = {
    "processing_mode": PROCESSING_MODE_APPOINTMENT_SERVICE,
    "track_inventory_sales": True,
}


def load_square_workspace_settings(
    cursor,
    *,
    spa_id,
    business_unit_id,
):
    """
    Read Square operating settings inside a caller-owned
    database transaction.

    This function does not commit, roll back, or close the
    caller's cursor. Missing settings use safe legacy defaults.
    """

    if cursor is None:
        raise SquareWorkspaceSettingsError(
            "A database cursor is required."
        )

    if not spa_id or not business_unit_id:
        raise SquareWorkspaceSettingsError(
            "Square workspace context is incomplete."
        )

    cursor.execute("""
        SELECT
            square_workspace_setting_id,
            processing_mode,
            track_inventory_sales
        FROM square_workspace_settings
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
            "square_workspace_setting_id": None,
            "spa_id": spa_id,
            "business_unit_id": business_unit_id,
            "processing_mode": (
                DEFAULT_SQUARE_WORKSPACE_SETTINGS[
                    "processing_mode"
                ]
            ),
            "track_inventory_sales": (
                DEFAULT_SQUARE_WORKSPACE_SETTINGS[
                    "track_inventory_sales"
                ]
            ),
            "is_persisted": False,
        }

    processing_mode = str(
        row[1] or ""
    ).strip().lower()

    if processing_mode not in VALID_PROCESSING_MODES:
        raise SquareWorkspaceSettingsError(
            "Stored Square operating mode is invalid."
        )

    return {
        "square_workspace_setting_id": row[0],
        "spa_id": spa_id,
        "business_unit_id": business_unit_id,
        "processing_mode": processing_mode,
        "track_inventory_sales": bool(row[2]),
        "is_persisted": True,
    }


def get_square_workspace_settings(
    *,
    spa_id,
    business_unit_id,
):
    """
    Return Square operating settings for one PSP workspace.

    A workspace with no persisted settings row receives the
    safe legacy defaults without creating a database record.
    """

    if not spa_id or not business_unit_id:
        raise SquareWorkspaceSettingsError(
            "Square workspace context is incomplete."
        )

    conn = get_db_connection()
    cur = conn.cursor(
        cursor_factory=RealDictCursor
    )

    try:
        cur.execute("""
            SELECT
                square_workspace_setting_id,
                spa_id,
                business_unit_id,
                processing_mode,
                track_inventory_sales,
                created_by,
                updated_by,
                created_at,
                updated_at
            FROM square_workspace_settings
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
            "square_workspace_setting_id": None,
            "spa_id": spa_id,
            "business_unit_id": business_unit_id,
            "processing_mode": (
                DEFAULT_SQUARE_WORKSPACE_SETTINGS[
                    "processing_mode"
                ]
            ),
            "track_inventory_sales": (
                DEFAULT_SQUARE_WORKSPACE_SETTINGS[
                    "track_inventory_sales"
                ]
            ),
            "created_by": None,
            "updated_by": None,
            "created_at": None,
            "updated_at": None,
            "is_persisted": False,
        }

    result = dict(row)
    result["track_inventory_sales"] = bool(
        result["track_inventory_sales"]
    )
    result["is_persisted"] = True

    return result


def save_square_workspace_settings(
    *,
    spa_id,
    business_unit_id,
    processing_mode,
    track_inventory_sales,
    actor_user_id=None,
):
    """
    Create or update Square operating settings for one
    authenticated PSP workspace.
    """

    if not spa_id or not business_unit_id:
        raise SquareWorkspaceSettingsError(
            "Square workspace context is incomplete."
        )

    processing_mode = str(
        processing_mode or ""
    ).strip().lower()

    if processing_mode not in VALID_PROCESSING_MODES:
        raise SquareWorkspaceSettingsError(
            "Square operating mode must be "
            "Appointment / Service Business or "
            "PeachPOS — Daily Sales Mode."
        )

    if not isinstance(track_inventory_sales, bool):
        raise SquareWorkspaceSettingsError(
            "Square inventory tracking setting is invalid."
        )

    conn = get_db_connection()
    cur = conn.cursor(
        cursor_factory=RealDictCursor
    )

    try:
        cur.execute("""
            INSERT INTO square_workspace_settings (
                spa_id,
                business_unit_id,
                processing_mode,
                track_inventory_sales,
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
                processing_mode = EXCLUDED.processing_mode,
                track_inventory_sales = (
                    EXCLUDED.track_inventory_sales
                ),
                updated_by = EXCLUDED.updated_by,
                updated_at = NOW()
            RETURNING
                square_workspace_setting_id,
                spa_id,
                business_unit_id,
                processing_mode,
                track_inventory_sales,
                created_by,
                updated_by,
                created_at,
                updated_at
        """, (
            spa_id,
            business_unit_id,
            processing_mode,
            track_inventory_sales,
            actor_user_id,
            actor_user_id,
        ))

        row = cur.fetchone()

        if row is None:
            raise SquareWorkspaceSettingsError(
                "Square workspace settings were not saved."
            )

        conn.commit()

    except Exception:
        conn.rollback()
        raise

    finally:
        cur.close()
        conn.close()

    result = dict(row)
    result["track_inventory_sales"] = bool(
        result["track_inventory_sales"]
    )
    result["is_persisted"] = True

    return result
