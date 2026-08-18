from datetime import datetime, timedelta, timezone

from psycopg2.extras import RealDictCursor

from db import get_db_connection
from services import square_oauth, square_service


class SquareSyncAuthError(RuntimeError):
    """Raised when Square sync credentials cannot be resolved safely."""


_REFRESH_INTERVAL = timedelta(days=7)
_REFRESH_BEFORE_EXPIRY = timedelta(days=7)
_VERIFY_INTERVAL = timedelta(days=1)


def _aware_datetime(value, field_name):
    if value is None:
        return None

    if value.tzinfo is None:
        raise SquareSyncAuthError(
            f"{field_name} must include timezone information."
        )

    return value.astimezone(timezone.utc)


def _should_refresh(
    *,
    connected_at,
    refreshed_at,
    expires_at,
    now,
):
    expires_at = _aware_datetime(
        expires_at,
        "Square OAuth expiration",
    )

    if expires_at is None:
        return True

    if expires_at <= now + _REFRESH_BEFORE_EXPIRY:
        return True

    refresh_reference = (
        _aware_datetime(
            refreshed_at,
            "Square OAuth refresh timestamp",
        )
        or _aware_datetime(
            connected_at,
            "Square connection timestamp",
        )
    )

    if refresh_reference is None:
        return True

    return (
        refresh_reference
        <= now - _REFRESH_INTERVAL
    )


def _should_verify(
    *,
    last_verified_at,
    now,
):
    last_verified_at = _aware_datetime(
        last_verified_at,
        "Square OAuth verification timestamp",
    )

    if last_verified_at is None:
        return True

    return (
        last_verified_at
        <= now - _VERIFY_INTERVAL
    )


def resolve_square_sync_access_token(
    *,
    spa_id,
    business_unit_id,
    environment,
):
    """
    Resolve the access token for one PSP -> Square write.

    Sandbox continues to use the existing Sandbox token.

    Production requires:
    - exact connected workspace/environment
    - live_sync_enabled = TRUE
    - encrypted workspace-bound OAuth credentials
    - merchant/application/scope verification
    - safe token refresh and encrypted persistence when due

    This helper does not enable live_sync_enabled.
    """

    environment = (
        square_service
        .normalize_square_environment(
            environment
        )
    )

    if environment == "sandbox":
        return (
            square_service
            .get_square_sandbox_access_token()
        )

    if environment != "production":
        raise SquareSyncAuthError(
            "Square sync environment must be "
            "sandbox or production."
        )

    conn = get_db_connection()
    cur = conn.cursor(
        cursor_factory=RealDictCursor
    )

    try:
        cur.execute("""
            SELECT
                square_connection_id,
                spa_id,
                business_unit_id,
                environment,
                merchant_id,
                connection_status,
                oauth_access_token_ciphertext,
                oauth_refresh_token_ciphertext,
                oauth_token_expires_at,
                oauth_token_refreshed_at,
                oauth_token_last_verified_at,
                connected_at,
                live_sync_enabled
            FROM square_connections
            WHERE spa_id = %s
              AND business_unit_id = %s
              AND environment = 'production'
              AND connection_status = 'connected'
            ORDER BY square_connection_id
            FOR UPDATE
        """, (
            spa_id,
            business_unit_id,
        ))

        connections = cur.fetchall()

        if len(connections) != 1:
            raise SquareSyncAuthError(
                "Exactly one connected Square Production "
                "connection is required for this workspace."
            )

        connection = connections[0]

        if not connection["live_sync_enabled"]:
            raise SquareSyncAuthError(
                "Live Square synchronization is disabled "
                "for this workspace."
            )

        merchant_id = str(
            connection["merchant_id"] or ""
        ).strip()

        if not merchant_id:
            raise SquareSyncAuthError(
                "The connected Square Production account "
                "is missing its merchant ID."
            )

        access_ciphertext = (
            connection[
                "oauth_access_token_ciphertext"
            ]
        )

        refresh_ciphertext = (
            connection[
                "oauth_refresh_token_ciphertext"
            ]
        )

        if not access_ciphertext:
            raise SquareSyncAuthError(
                "The connected Square Production account "
                "does not have a stored OAuth access token."
            )

        if not refresh_ciphertext:
            raise SquareSyncAuthError(
                "The connected Square Production account "
                "does not have a stored OAuth refresh token."
            )

        access_token = square_oauth.decrypt_token(
            access_ciphertext,
            spa_id=spa_id,
            business_unit_id=business_unit_id,
            environment="production",
            token_kind="access",
        )

        refresh_token = square_oauth.decrypt_token(
            refresh_ciphertext,
            spa_id=spa_id,
            business_unit_id=business_unit_id,
            environment="production",
            token_kind="refresh",
        )

        now = datetime.now(timezone.utc)

        refresh_due = _should_refresh(
            connected_at=connection["connected_at"],
            refreshed_at=connection[
                "oauth_token_refreshed_at"
            ],
            expires_at=connection[
                "oauth_token_expires_at"
            ],
            now=now,
        )

        verify_due = _should_verify(
            last_verified_at=connection[
                "oauth_token_last_verified_at"
            ],
            now=now,
        )

        if refresh_due:
            token_result = (
                square_oauth.refresh_access_token(
                    refresh_token
                )
            )

            if token_result["merchant_id"] != merchant_id:
                raise SquareSyncAuthError(
                    "Refreshed Square OAuth credentials "
                    "belong to a different merchant."
                )

            access_token = token_result[
                "access_token"
            ]

            refresh_token = token_result[
                "refresh_token"
            ]

            token_status = (
                square_oauth.retrieve_token_status(
                    access_token
                )
            )

            token_status = (
                square_oauth
                .validate_production_token_status(
                    token_status,
                    expected_application_id=(
                        square_oauth
                        .get_production_application_id()
                    ),
                    expected_merchant_id=merchant_id,
                )
            )

            access_ciphertext = (
                square_oauth.encrypt_token(
                    access_token,
                    spa_id=spa_id,
                    business_unit_id=(
                        business_unit_id
                    ),
                    environment="production",
                    token_kind="access",
                )
            )

            refresh_ciphertext = (
                square_oauth.encrypt_token(
                    refresh_token,
                    spa_id=spa_id,
                    business_unit_id=(
                        business_unit_id
                    ),
                    environment="production",
                    token_kind="refresh",
                )
            )

            cur.execute("""
                UPDATE square_connections
                SET
                    oauth_access_token_ciphertext = %s,
                    oauth_refresh_token_ciphertext = %s,
                    oauth_token_expires_at = %s,
                    oauth_scopes = %s,
                    oauth_token_refreshed_at =
                        CURRENT_TIMESTAMP,
                    oauth_token_last_verified_at =
                        CURRENT_TIMESTAMP,
                    updated_at = CURRENT_TIMESTAMP
                WHERE square_connection_id = %s
                  AND spa_id = %s
                  AND business_unit_id = %s
                  AND environment = 'production'
                  AND connection_status = 'connected'
                  AND live_sync_enabled = TRUE
            """, (
                access_ciphertext,
                refresh_ciphertext,
                token_result["expires_at"],
                " ".join(
                    token_status["scopes"]
                ),
                connection[
                    "square_connection_id"
                ],
                spa_id,
                business_unit_id,
            ))

            if cur.rowcount != 1:
                raise SquareSyncAuthError(
                    "Square Production connection changed "
                    "while refreshing OAuth credentials."
                )

            conn.commit()

            return access_token

        if verify_due:
            token_status = (
                square_oauth.retrieve_token_status(
                    access_token
                )
            )

            token_status = (
                square_oauth
                .validate_production_token_status(
                    token_status,
                    expected_application_id=(
                        square_oauth
                        .get_production_application_id()
                    ),
                    expected_merchant_id=merchant_id,
                )
            )

            cur.execute("""
                UPDATE square_connections
                SET
                    oauth_token_expires_at =
                        COALESCE(%s, oauth_token_expires_at),
                    oauth_scopes = %s,
                    oauth_token_last_verified_at =
                        CURRENT_TIMESTAMP,
                    updated_at = CURRENT_TIMESTAMP
                WHERE square_connection_id = %s
                  AND spa_id = %s
                  AND business_unit_id = %s
                  AND environment = 'production'
                  AND connection_status = 'connected'
                  AND live_sync_enabled = TRUE
            """, (
                token_status.get("expires_at"),
                " ".join(
                    token_status["scopes"]
                ),
                connection[
                    "square_connection_id"
                ],
                spa_id,
                business_unit_id,
            ))

            if cur.rowcount != 1:
                raise SquareSyncAuthError(
                    "Square Production connection changed "
                    "while verifying OAuth credentials."
                )

            conn.commit()

        return access_token

    except (
        square_oauth.SquareOAuthError,
        SquareSyncAuthError,
    ):
        conn.rollback()
        raise

    except Exception as exc:
        conn.rollback()

        raise SquareSyncAuthError(
            "Unable to resolve Square synchronization "
            "credentials safely."
        ) from exc

    finally:
        cur.close()
        conn.close()


def enable_square_production_live_sync(
    *,
    spa_id,
    business_unit_id,
):
    """
    Safely enable PSP -> Square Production synchronization.

    This performs no customer or Catalog writes.

    Requirements:
    - exactly one connected Production Square account
    - exactly one active default Square location
    - valid workspace-bound OAuth credentials
    - refreshed credentials when due
    - verified Square application, merchant, and scopes
    """

    conn = get_db_connection()
    cur = conn.cursor(
        cursor_factory=RealDictCursor
    )

    try:
        cur.execute("""
            SELECT
                square_connection_id,
                merchant_id,
                oauth_access_token_ciphertext,
                oauth_refresh_token_ciphertext,
                oauth_token_expires_at,
                oauth_token_refreshed_at,
                oauth_token_last_verified_at,
                connected_at,
                live_sync_enabled
            FROM square_connections
            WHERE spa_id = %s
              AND business_unit_id = %s
              AND environment = 'production'
              AND connection_status = 'connected'
            ORDER BY square_connection_id
            FOR UPDATE
        """, (
            spa_id,
            business_unit_id,
        ))

        connections = cur.fetchall()

        if len(connections) != 1:
            raise SquareSyncAuthError(
                "Exactly one connected Square Production "
                "connection is required for this workspace."
            )

        connection = connections[0]

        merchant_id = str(
            connection["merchant_id"] or ""
        ).strip()

        if not merchant_id:
            raise SquareSyncAuthError(
                "The connected Square Production account "
                "is missing its merchant ID."
            )

        cur.execute("""
            SELECT
                square_location_mapping_id,
                square_location_id,
                location_name
            FROM square_locations
            WHERE square_connection_id = %s
              AND spa_id = %s
              AND business_unit_id = %s
              AND environment = 'production'
              AND is_active = TRUE
              AND is_default = TRUE
            ORDER BY square_location_mapping_id
            LIMIT 2
        """, (
            connection["square_connection_id"],
            spa_id,
            business_unit_id,
        ))

        default_locations = cur.fetchall()

        if len(default_locations) != 1:
            raise SquareSyncAuthError(
                "Exactly one active default Square Production "
                "location is required before Live Sync can "
                "be enabled."
            )

        default_location = default_locations[0]

        access_ciphertext = (
            connection[
                "oauth_access_token_ciphertext"
            ]
        )

        refresh_ciphertext = (
            connection[
                "oauth_refresh_token_ciphertext"
            ]
        )

        if not access_ciphertext:
            raise SquareSyncAuthError(
                "The connected Square Production account "
                "does not have a stored OAuth access token."
            )

        if not refresh_ciphertext:
            raise SquareSyncAuthError(
                "The connected Square Production account "
                "does not have a stored OAuth refresh token."
            )

        access_token = square_oauth.decrypt_token(
            access_ciphertext,
            spa_id=spa_id,
            business_unit_id=business_unit_id,
            environment="production",
            token_kind="access",
        )

        refresh_token = square_oauth.decrypt_token(
            refresh_ciphertext,
            spa_id=spa_id,
            business_unit_id=business_unit_id,
            environment="production",
            token_kind="refresh",
        )

        now = datetime.now(timezone.utc)

        refresh_due = _should_refresh(
            connected_at=connection["connected_at"],
            refreshed_at=connection[
                "oauth_token_refreshed_at"
            ],
            expires_at=connection[
                "oauth_token_expires_at"
            ],
            now=now,
        )

        refreshed = False
        refreshed_expires_at = None
        new_access_ciphertext = None
        new_refresh_ciphertext = None

        if refresh_due:
            token_result = (
                square_oauth.refresh_access_token(
                    refresh_token
                )
            )

            if token_result["merchant_id"] != merchant_id:
                raise SquareSyncAuthError(
                    "Refreshed Square OAuth credentials "
                    "belong to a different merchant."
                )

            access_token = token_result[
                "access_token"
            ]

            refresh_token = token_result[
                "refresh_token"
            ]

            refreshed_expires_at = (
                token_result["expires_at"]
            )

            refreshed = True

        token_status = (
            square_oauth.retrieve_token_status(
                access_token
            )
        )

        token_status = (
            square_oauth
            .validate_production_token_status(
                token_status,
                expected_application_id=(
                    square_oauth
                    .get_production_application_id()
                ),
                expected_merchant_id=merchant_id,
            )
        )

        if refreshed:
            new_access_ciphertext = (
                square_oauth.encrypt_token(
                    access_token,
                    spa_id=spa_id,
                    business_unit_id=(
                        business_unit_id
                    ),
                    environment="production",
                    token_kind="access",
                )
            )

            new_refresh_ciphertext = (
                square_oauth.encrypt_token(
                    refresh_token,
                    spa_id=spa_id,
                    business_unit_id=(
                        business_unit_id
                    ),
                    environment="production",
                    token_kind="refresh",
                )
            )

        verified_expires_at = (
            token_status.get("expires_at")
            or refreshed_expires_at
        )

        cur.execute("""
            UPDATE square_connections
            SET
                oauth_access_token_ciphertext =
                    COALESCE(
                        %s,
                        oauth_access_token_ciphertext
                    ),
                oauth_refresh_token_ciphertext =
                    COALESCE(
                        %s,
                        oauth_refresh_token_ciphertext
                    ),
                oauth_token_expires_at =
                    COALESCE(
                        %s,
                        oauth_token_expires_at
                    ),
                oauth_scopes = %s,
                oauth_token_refreshed_at =
                    CASE
                        WHEN %s
                            THEN CURRENT_TIMESTAMP
                        ELSE oauth_token_refreshed_at
                    END,
                oauth_token_last_verified_at =
                    CURRENT_TIMESTAMP,
                live_sync_enabled = TRUE,
                updated_at = CURRENT_TIMESTAMP
            WHERE square_connection_id = %s
              AND spa_id = %s
              AND business_unit_id = %s
              AND environment = 'production'
              AND connection_status = 'connected'
        """, (
            new_access_ciphertext,
            new_refresh_ciphertext,
            verified_expires_at,
            " ".join(
                token_status["scopes"]
            ),
            refreshed,
            connection[
                "square_connection_id"
            ],
            spa_id,
            business_unit_id,
        ))

        if cur.rowcount != 1:
            raise SquareSyncAuthError(
                "Square Production connection changed "
                "while enabling Live Sync."
            )

        conn.commit()

        return {
            "square_connection_id": (
                connection[
                    "square_connection_id"
                ]
            ),
            "merchant_id": merchant_id,
            "square_location_id": (
                default_location[
                    "square_location_id"
                ]
            ),
            "location_name": (
                default_location[
                    "location_name"
                ]
            ),
            "scopes": token_status["scopes"],
            "refreshed": refreshed,
            "already_enabled": bool(
                connection["live_sync_enabled"]
            ),
        }

    except (
        square_oauth.SquareOAuthError,
        SquareSyncAuthError,
    ):
        conn.rollback()
        raise

    except Exception as exc:
        conn.rollback()

        raise SquareSyncAuthError(
            "Unable to enable Square Production "
            "Live Sync safely."
        ) from exc

    finally:
        cur.close()
        conn.close()


def disable_square_production_live_sync(
    *,
    spa_id,
    business_unit_id,
):
    """
    Immediately disable PSP -> Square Production synchronization
    for the exact workspace.

    Safety:
    - no Square API call
    - no OAuth verification required
    - no default-location requirement
    - does not disconnect Square
    - does not alter existing Square data
    """

    conn = get_db_connection()
    cur = conn.cursor()

    try:
        cur.execute("""
            UPDATE square_connections
            SET
                live_sync_enabled = FALSE,
                updated_at = CURRENT_TIMESTAMP
            WHERE spa_id = %s
              AND business_unit_id = %s
              AND environment = 'production'
              AND live_sync_enabled = TRUE
            RETURNING square_connection_id
        """, (
            spa_id,
            business_unit_id,
        ))

        disabled_rows = cur.fetchall()

        conn.commit()

        return {
            "disabled_count": len(
                disabled_rows
            ),
            "square_connection_ids": [
                row[0]
                for row in disabled_rows
            ],
        }

    except Exception as exc:
        conn.rollback()

        raise SquareSyncAuthError(
            "Unable to disable Square Production "
            "Live Sync safely."
        ) from exc

    finally:
        cur.close()
        conn.close()
