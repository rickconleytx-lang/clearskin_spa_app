import re

from psycopg2 import IntegrityError
from psycopg2.extras import RealDictCursor

from db import get_db_connection
from services import square_service


class SquareClientSyncError(RuntimeError):
    """Raised when a PSP client cannot be synchronized safely."""


def normalize_client_email(value):
    return str(value or "").strip().lower()


def normalize_client_phone_for_square(value):
    """
    Normalize PSP client phone data conservatively for Square.

    PSP's existing duplicate logic treats a 10-digit US number,
    or 11 digits beginning with 1, as the same phone number.

    Square exact phone search expects E.164, so those numbers
    become +1XXXXXXXXXX.

    International numbers are accepted only when the stored
    value already includes a leading +. We do not guess a
    country code for ambiguous international numbers.
    """
    raw = str(value or "").strip()

    if not raw:
        return ""

    digits = re.sub(
        r"[^0-9]",
        "",
        raw
    )

    if (
        len(digits) == 10
    ):
        return "+1" + digits

    if (
        len(digits) == 11
        and digits.startswith("1")
    ):
        return "+" + digits

    if (
        raw.startswith("+")
        and 9 <= len(digits) <= 16
    ):
        return "+" + digits

    return ""


def build_psp_client_reference_id(
    spa_id,
    business_unit_id,
    client_id
):
    """
    Stable PSP identity written into Square Customer.reference_id.
    """
    reference_id = (
        f"psp-client-"
        f"{int(spa_id)}-"
        f"{int(business_unit_id)}-"
        f"{int(client_id)}"
    )

    if len(reference_id) > 100:
        raise SquareClientSyncError(
            "Generated Square customer reference ID is too long."
        )

    return reference_id


def _load_sync_context(
    spa_id,
    business_unit_id,
    client_id,
    environment
):
    environment = (
        square_service
        .normalize_square_environment(
            environment
        )
    )

    conn = get_db_connection()
    cur = conn.cursor(
        cursor_factory=RealDictCursor
    )

    try:
        cur.execute("""
            SELECT
                client_id,
                spa_id,
                business_unit_id,
                first_name,
                last_name,
                phone,
                email,
                active_client
            FROM clients
            WHERE client_id = %s
              AND spa_id = %s
              AND business_unit_id = %s
            LIMIT 1
        """, (
            client_id,
            spa_id,
            business_unit_id
        ))

        client = cur.fetchone()

        if not client:
            raise SquareClientSyncError(
                "PSP client was not found in the requested workspace."
            )

        cur.execute("""
            SELECT
                square_connection_id,
                spa_id,
                business_unit_id,
                environment,
                merchant_id,
                connection_status
            FROM square_connections
            WHERE spa_id = %s
              AND business_unit_id = %s
              AND environment = %s
              AND connection_status = 'connected'
            ORDER BY
                square_connection_id
            LIMIT 1
        """, (
            spa_id,
            business_unit_id,
            environment
        ))

        connection = cur.fetchone()

        if not connection:
            return {
                "client": dict(client),
                "connection": None,
                "mapping": None,
                "environment": environment,
            }

        cur.execute("""
            SELECT
                square_customer_mapping_id,
                square_connection_id,
                spa_id,
                business_unit_id,
                environment,
                square_customer_id,
                client_id,
                match_method,
                is_active,
                verified_by,
                verified_at
            FROM square_customer_mappings
            WHERE square_connection_id = %s
              AND spa_id = %s
              AND business_unit_id = %s
              AND environment = %s
              AND client_id = %s
              AND is_active = TRUE
            LIMIT 2
        """, (
            connection[
                "square_connection_id"
            ],
            spa_id,
            business_unit_id,
            environment,
            client_id
        ))

        mappings = cur.fetchall()

        if len(mappings) > 1:
            raise SquareClientSyncError(
                "PSP client has multiple active Square customer mappings."
            )

        mapping = (
            dict(mappings[0])
            if mappings
            else None
        )

        return {
            "client": dict(client),
            "connection": dict(connection),
            "mapping": mapping,
            "environment": environment,
        }

    finally:
        cur.close()
        conn.close()


def _resolve_access_token(
    environment
):
    """
    Sandbox currently uses the local environment token.

    Production seller OAuth/token decryption is intentionally
    not enabled here yet.
    """
    if environment == "sandbox":
        return (
            square_service
            .get_square_sandbox_access_token()
        )

    raise SquareClientSyncError(
        "Production Square customer sync is not enabled "
        "until seller OAuth token handling is implemented."
    )


def _customer_profile_values(
    client,
    reference_id
):
    email = normalize_client_email(
        client.get("email")
    )

    phone = normalize_client_phone_for_square(
        client.get("phone")
    )

    return {
        "given_name": str(
            client.get("first_name") or ""
        ).strip(),
        "family_name": str(
            client.get("last_name") or ""
        ).strip(),
        "email": email,
        "phone": phone,
        "reference_id": reference_id,
    }


def _build_create_payload(
    profile
):
    payload = {
        "given_name": profile[
            "given_name"
        ],
        "family_name": profile[
            "family_name"
        ],
        "reference_id": profile[
            "reference_id"
        ],
    }

    if profile["email"]:
        payload["email_address"] = (
            profile["email"]
        )

    if profile["phone"]:
        payload["phone_number"] = (
            profile["phone"]
        )

    return payload


def _build_update_payload(
    profile,
    *,
    version=None
):
    # PSP is authoritative. Empty strings intentionally clear
    # Square email/phone if those values were removed in PSP.
    payload = {
        "given_name": profile[
            "given_name"
        ],
        "family_name": profile[
            "family_name"
        ],
        "email_address": profile[
            "email"
        ],
        "phone_number": profile[
            "phone"
        ],
        "reference_id": profile[
            "reference_id"
        ],
    }

    if version is not None:
        payload["version"] = version

    return payload


def _is_square_invalid_phone_error(exc):
    """
    Identify only Square's specific invalid
    phone_number validation failure.

    Unrelated Square HTTP 400 responses must continue
    to fail normally.
    """
    if not isinstance(
        exc,
        square_service.SquareServiceError,
    ):
        return False

    message = str(
        exc or ""
    ).strip().lower()

    return (
        "http 400" in message
        and "phone_number" in message
        and "valid phone number" in message
    )


def _phone_omission_result_fields(
    phone_omitted
):
    """
    Add an audit note to a successful sync when Square
    rejected the PSP phone value.

    Peach Suite Pro's stored client phone is not changed.
    """
    if not phone_omitted:
        return {}

    return {
        "reason": "square_phone_omitted_invalid",
        "message": (
            "Square rejected the PSP phone number as "
            "invalid. The customer synchronized without "
            "that phone value; the PSP client record was "
            "not changed."
        ),
    }


def _update_customer_with_phone_fallback(
    customer_id,
    updates,
    *,
    access_token,
    environment,
):
    """
    Attempt the normal Square Customer update.

    If Square specifically rejects phone_number, retry
    once with an empty phone string so Square does not
    retain a stale phone value.

    Every unrelated Square error is re-raised.
    """
    payload = dict(
        updates or {}
    )

    try:
        updated = (
            square_service.update_customer(
                customer_id,
                payload,
                access_token=access_token,
                environment=environment,
            )
        )

        return updated, False

    except square_service.SquareServiceError as exc:
        if (
            "phone_number" not in payload
            or not _is_square_invalid_phone_error(
                exc
            )
        ):
            raise

        fallback_payload = dict(
            payload
        )

        fallback_payload[
            "phone_number"
        ] = ""

        updated = (
            square_service.update_customer(
                customer_id,
                fallback_payload,
                access_token=access_token,
                environment=environment,
            )
        )

        return updated, True


def _create_customer_with_phone_fallback(
    customer,
    *,
    idempotency_key,
    access_token,
    environment,
):
    """
    Attempt normal Square Customer creation.

    If Square specifically rejects phone_number, retry
    exactly once without phone_number.

    The fallback uses a separate deterministic
    idempotency key because the request body changed.
    """
    payload = dict(
        customer or {}
    )

    try:
        created = (
            square_service.create_customer(
                payload,
                idempotency_key=(
                    idempotency_key
                ),
                access_token=access_token,
                environment=environment,
            )
        )

        return created, False

    except square_service.SquareServiceError as exc:
        if (
            "phone_number" not in payload
            or not _is_square_invalid_phone_error(
                exc
            )
        ):
            raise

        fallback_payload = dict(
            payload
        )

        fallback_payload.pop(
            "phone_number",
            None,
        )

        fallback_key = (
            f"{idempotency_key}-no-phone"
        )

        created = (
            square_service.create_customer(
                fallback_payload,
                idempotency_key=fallback_key,
                access_token=access_token,
                environment=environment,
            )
        )

        return created, True


def _search_exact(
    field_name,
    value,
    *,
    access_token,
    environment
):
    if not value:
        return []

    result = square_service.search_customers(
        {
            "filter": {
                field_name: {
                    "exact": value
                }
            }
        },
        access_token=access_token,
        environment=environment,
        limit=100,
    )

    customers = []

    for customer in (
        result.get("customers")
        or []
    ):
        if (
            isinstance(customer, dict)
            and customer.get("id")
        ):
            customers.append(customer)

    return customers


def _unique_customers_by_id(
    customers
):
    by_id = {}

    for customer in customers:
        customer_id = str(
            customer.get("id") or ""
        ).strip()

        if customer_id:
            by_id[customer_id] = (
                customer
            )

    return by_id


def _find_existing_square_customer(
    profile,
    *,
    access_token,
    environment
):
    """
    Matching order:
      1. PSP reference_id
      2. exact email and/or exact E.164 phone

    Names are never used as an automatic identity match.
    """
    reference_matches = (
        _unique_customers_by_id(
            _search_exact(
                "reference_id",
                profile[
                    "reference_id"
                ],
                access_token=(
                    access_token
                ),
                environment=environment,
            )
        )
    )

    if len(reference_matches) > 1:
        return {
            "status": "needs_attention",
            "reason": (
                "multiple_reference_id_matches"
            ),
            "candidate_ids": sorted(
                reference_matches
            ),
        }

    if len(reference_matches) == 1:
        customer = next(
            iter(
                reference_matches.values()
            )
        )

        return {
            "status": "matched",
            "match_method": "reference_id",
            "customer": customer,
        }

    email_matches = {}
    phone_matches = {}

    if profile["email"]:
        email_matches = (
            _unique_customers_by_id(
                _search_exact(
                    "email_address",
                    profile["email"],
                    access_token=(
                        access_token
                    ),
                    environment=(
                        environment
                    ),
                )
            )
        )

    if profile["phone"]:
        try:
            phone_matches = (
                _unique_customers_by_id(
                    _search_exact(
                        "phone_number",
                        profile["phone"],
                        access_token=(
                            access_token
                        ),
                        environment=(
                            environment
                        ),
                    )
                )
            )

        except square_service.SquareServiceError as exc:
            if not _is_square_invalid_phone_error(
                exc
            ):
                raise

            # Square rejected the value itself. Do not
            # change PSP, but stop using the bad phone
            # for this synchronization attempt.
            profile["phone"] = ""

            profile[
                "_square_phone_omitted"
            ] = True

            phone_matches = {}

    candidates = dict(
        email_matches
    )

    candidates.update(
        phone_matches
    )

    if len(candidates) > 1:
        return {
            "status": "needs_attention",
            "reason": (
                "conflicting_contact_matches"
            ),
            "email_candidate_ids": sorted(
                email_matches
            ),
            "phone_candidate_ids": sorted(
                phone_matches
            ),
            "candidate_ids": sorted(
                candidates
            ),
        }

    if len(candidates) == 1:
        customer_id = next(
            iter(candidates)
        )

        if (
            customer_id
            in email_matches
            and customer_id
            in phone_matches
        ):
            match_method = (
                "email_phone"
            )

        elif (
            customer_id
            in email_matches
        ):
            match_method = "email"

        else:
            match_method = "phone"

        return {
            "status": "matched",
            "match_method": (
                match_method
            ),
            "customer": (
                candidates[
                    customer_id
                ]
            ),
        }

    return {
        "status": "not_found",
    }


def _persist_mapping(
    *,
    square_connection_id,
    spa_id,
    business_unit_id,
    environment,
    square_customer_id,
    client_id,
    match_method,
    actor_user_id
):
    conn = get_db_connection()
    cur = conn.cursor(
        cursor_factory=RealDictCursor
    )

    try:
        # Re-verify the Square connection itself belongs to this
        # exact workspace/environment before storing an external
        # identity against it.
        cur.execute("""
            SELECT square_connection_id
            FROM square_connections
            WHERE square_connection_id = %s
              AND spa_id = %s
              AND business_unit_id = %s
              AND environment = %s
            LIMIT 1
        """, (
            square_connection_id,
            spa_id,
            business_unit_id,
            environment
        ))

        if not cur.fetchone():
            raise SquareClientSyncError(
                "Square connection does not belong to this "
                "PSP workspace/environment."
            )

        # Re-verify the PSP client still belongs to this exact
        # workspace before storing the external identity.
        cur.execute("""
            SELECT client_id
            FROM clients
            WHERE client_id = %s
              AND spa_id = %s
              AND business_unit_id = %s
            LIMIT 1
        """, (
            client_id,
            spa_id,
            business_unit_id
        ))

        if not cur.fetchone():
            raise SquareClientSyncError(
                "PSP client workspace changed before "
                "Square mapping could be saved."
            )

        cur.execute("""
            SELECT
                square_customer_mapping_id,
                square_customer_id,
                client_id,
                match_method,
                is_active
            FROM square_customer_mappings
            WHERE square_connection_id = %s
              AND spa_id = %s
              AND business_unit_id = %s
              AND environment = %s
              AND client_id = %s
              AND is_active = TRUE
            LIMIT 1
            FOR UPDATE
        """, (
            square_connection_id,
            spa_id,
            business_unit_id,
            environment,
            client_id
        ))

        existing_for_client = (
            cur.fetchone()
        )

        if existing_for_client:
            if (
                existing_for_client[
                    "square_customer_id"
                ]
                != square_customer_id
            ):
                raise SquareClientSyncError(
                    "PSP client already has a different "
                    "active Square customer mapping."
                )

            cur.execute("""
                UPDATE square_customer_mappings
                SET
                    match_method = %s,
                    verified_by = %s,
                    verified_at = CURRENT_TIMESTAMP,
                    updated_at = CURRENT_TIMESTAMP
                WHERE square_customer_mapping_id = %s
                RETURNING
                    square_customer_mapping_id,
                    square_customer_id,
                    client_id,
                    match_method,
                    is_active
            """, (
                match_method,
                actor_user_id,
                existing_for_client[
                    "square_customer_mapping_id"
                ]
            ))

            row = cur.fetchone()
            conn.commit()

            return dict(row)

        cur.execute("""
            SELECT
                square_customer_mapping_id,
                client_id,
                is_active
            FROM square_customer_mappings
            WHERE square_connection_id = %s
              AND square_customer_id = %s
            LIMIT 1
            FOR UPDATE
        """, (
            square_connection_id,
            square_customer_id
        ))

        existing_for_square = (
            cur.fetchone()
        )

        if existing_for_square:
            raise SquareClientSyncError(
                "Square customer is already mapped "
                "to another PSP client."
            )

        cur.execute("""
            INSERT INTO square_customer_mappings (
                square_connection_id,
                spa_id,
                business_unit_id,
                environment,
                square_customer_id,
                client_id,
                match_method,
                is_active,
                verified_by,
                verified_at
            )
            VALUES (
                %s, %s, %s, %s, %s,
                %s, %s, TRUE, %s,
                CURRENT_TIMESTAMP
            )
            RETURNING
                square_customer_mapping_id,
                square_customer_id,
                client_id,
                match_method,
                is_active
        """, (
            square_connection_id,
            spa_id,
            business_unit_id,
            environment,
            square_customer_id,
            client_id,
            match_method,
            actor_user_id
        ))

        row = cur.fetchone()
        conn.commit()

        return dict(row)

    except IntegrityError as exc:
        conn.rollback()

        raise SquareClientSyncError(
            "Square customer mapping uniqueness guard "
            "blocked a conflicting identity."
        ) from exc

    except Exception:
        conn.rollback()
        raise

    finally:
        cur.close()
        conn.close()



def confirm_square_customer_mapping(
    *,
    square_connection_id,
    spa_id,
    business_unit_id,
    environment,
    square_customer_id,
    client_id,
    match_method,
    actor_user_id
):
    """
    Persist a human-confirmed Square Customer -> PSP Client
    identity mapping.

    This helper performs PSP database work only.

    It does NOT:
    - create a Square customer
    - update a Square customer
    - search Square
    - perform any PSP -> Square synchronization

    The underlying persistence helper re-verifies workspace
    ownership and enforces mapping collision guards.
    """

    environment = str(
        environment or ""
    ).strip().lower()

    if environment not in {
        "sandbox",
        "production",
    }:
        raise SquareClientSyncError(
            "Square environment must be sandbox or production."
        )

    square_customer_id = str(
        square_customer_id or ""
    ).strip()

    if not square_customer_id:
        raise SquareClientSyncError(
            "Square customer ID is required."
        )

    allowed_match_methods = {
        "confirmed_email",
        "confirmed_phone",
        "confirmed_email_phone",
        "confirmed_name",
        "manual_confirmed",
    }

    match_method = str(
        match_method or ""
    ).strip().lower()

    if match_method not in allowed_match_methods:
        raise SquareClientSyncError(
            "Invalid confirmed Square client match method."
        )

    try:
        square_connection_id = int(
            square_connection_id
        )
        spa_id = int(spa_id)
        business_unit_id = int(
            business_unit_id
        )
        client_id = int(client_id)
    except (TypeError, ValueError):
        raise SquareClientSyncError(
            "Square client mapping IDs must be valid integers."
        )

    if (
        square_connection_id <= 0
        or spa_id <= 0
        or business_unit_id <= 0
        or client_id <= 0
    ):
        raise SquareClientSyncError(
            "Square client mapping IDs must be positive."
        )

    mapping = _persist_mapping(
        square_connection_id=(
            square_connection_id
        ),
        spa_id=spa_id,
        business_unit_id=(
            business_unit_id
        ),
        environment=environment,
        square_customer_id=(
            square_customer_id
        ),
        client_id=client_id,
        match_method=match_method,
        actor_user_id=actor_user_id,
    )

    return {
        "status": "mapped",
        "action": "confirmed",
        **mapping,
    }


def _refresh_mapping_customer_id(
    mapping,
    canonical_square_customer_id
):
    """
    Square can return a new canonical customer ID after a
    seller/customer merge. Safely refresh our mapping only if
    the canonical ID is not already owned by another PSP client.
    """
    old_id = str(
        mapping.get(
            "square_customer_id"
        )
        or ""
    ).strip()

    new_id = str(
        canonical_square_customer_id
        or ""
    ).strip()

    if (
        not new_id
        or old_id == new_id
    ):
        return mapping

    conn = get_db_connection()
    cur = conn.cursor(
        cursor_factory=RealDictCursor
    )

    try:
        cur.execute("""
            SELECT
                square_customer_mapping_id,
                client_id
            FROM square_customer_mappings
            WHERE square_connection_id = %s
              AND square_customer_id = %s
            LIMIT 1
            FOR UPDATE
        """, (
            mapping[
                "square_connection_id"
            ],
            new_id
        ))

        conflict = cur.fetchone()

        if (
            conflict
            and conflict["client_id"]
            != mapping["client_id"]
        ):
            raise SquareClientSyncError(
                "Square canonical customer ID is already "
                "mapped to another PSP client."
            )

        cur.execute("""
            UPDATE square_customer_mappings
            SET
                square_customer_id = %s,
                updated_at = CURRENT_TIMESTAMP
            WHERE square_customer_mapping_id = %s
              AND spa_id = %s
              AND business_unit_id = %s
              AND is_active = TRUE
            RETURNING
                square_customer_mapping_id,
                square_connection_id,
                spa_id,
                business_unit_id,
                environment,
                square_customer_id,
                client_id,
                match_method,
                is_active,
                verified_by,
                verified_at
        """, (
            new_id,
            mapping[
                "square_customer_mapping_id"
            ],
            mapping["spa_id"],
            mapping[
                "business_unit_id"
            ]
        ))

        refreshed = cur.fetchone()

        if not refreshed:
            raise SquareClientSyncError(
                "Active Square customer mapping could not be refreshed."
            )

        conn.commit()

        return dict(refreshed)

    except IntegrityError as exc:
        conn.rollback()

        raise SquareClientSyncError(
            "Square customer merge created a mapping conflict."
        ) from exc

    except Exception:
        conn.rollback()
        raise

    finally:
        cur.close()
        conn.close()


def _touch_connection_sync_time(
    square_connection_id,
    spa_id,
    business_unit_id,
    environment
):
    conn = get_db_connection()
    cur = conn.cursor()

    try:
        cur.execute("""
            UPDATE square_connections
            SET
                last_sync_at = CURRENT_TIMESTAMP,
                updated_at = CURRENT_TIMESTAMP
            WHERE square_connection_id = %s
              AND spa_id = %s
              AND business_unit_id = %s
              AND environment = %s
        """, (
            square_connection_id,
            spa_id,
            business_unit_id,
            environment
        ))

        conn.commit()

    finally:
        cur.close()
        conn.close()


def sync_client_to_square(
    *,
    spa_id,
    business_unit_id,
    client_id,
    actor_user_id=None,
    environment="sandbox"
):
    """
    Synchronize one PSP client to Square.

    PSP is authoritative.

    Safety rules:
      - exact workspace identity required
      - existing mapping always wins
      - no automatic name-only matching
      - reference_id is strongest fallback identity
      - email/phone matches must resolve to one Square customer
      - conflicting candidates return needs_attention
      - no production sync until OAuth token handling is ready
    """
    context = _load_sync_context(
        spa_id,
        business_unit_id,
        client_id,
        environment
    )

    client = context["client"]
    connection = context[
        "connection"
    ]
    mapping = context["mapping"]
    environment = context[
        "environment"
    ]

    if not connection:
        return {
            "status": "skipped",
            "reason": "square_not_connected",
            "client_id": client_id,
            "spa_id": spa_id,
            "business_unit_id": (
                business_unit_id
            ),
            "environment": environment,
        }

    access_token = (
        _resolve_access_token(
            environment
        )
    )

    square_connection_id = (
        connection[
            "square_connection_id"
        ]
    )

    reference_id = (
        build_psp_client_reference_id(
            spa_id,
            business_unit_id,
            client_id
        )
    )

    profile = (
        _customer_profile_values(
            client,
            reference_id
        )
    )

    if (
        not profile["given_name"]
        or not profile[
            "family_name"
        ]
    ):
        raise SquareClientSyncError(
            "PSP client must have first and last name "
            "before Square synchronization."
        )

    phone_omitted = False

    # -----------------------------------------------------
    # Existing mapping: update exactly that Square profile.
    # -----------------------------------------------------

    if mapping:
        square_customer = (
            square_service
            .retrieve_customer(
                mapping[
                    "square_customer_id"
                ],
                access_token=(
                    access_token
                ),
                environment=environment,
            )
        )

        canonical_id = str(
            square_customer.get("id")
            or ""
        ).strip()

        if not canonical_id:
            raise SquareClientSyncError(
                "Mapped Square customer did not return an ID."
            )

        if (
            canonical_id
            != mapping[
                "square_customer_id"
            ]
        ):
            mapping = (
                _refresh_mapping_customer_id(
                    mapping,
                    canonical_id
                )
            )

        (
            updated,
            fallback_phone_omitted,
        ) = (
            _update_customer_with_phone_fallback(
                canonical_id,
                _build_update_payload(
                    profile,
                    version=(
                        square_customer
                        .get("version")
                    )
                ),
                access_token=(
                    access_token
                ),
                environment=environment,
            )
        )

        phone_omitted = (
            phone_omitted
            or fallback_phone_omitted
        )

        _persist_mapping(
            square_connection_id=(
                square_connection_id
            ),
            spa_id=spa_id,
            business_unit_id=(
                business_unit_id
            ),
            environment=environment,
            square_customer_id=(
                updated["id"]
            ),
            client_id=client_id,
            match_method=(
                mapping.get(
                    "match_method"
                )
                or "existing_mapping"
            ),
            actor_user_id=(
                actor_user_id
            ),
        )

        _touch_connection_sync_time(
            square_connection_id,
            spa_id,
            business_unit_id,
            environment
        )

        return {
            "status": "synced",
            "action": "updated",
            "client_id": client_id,
            "square_customer_id": (
                updated["id"]
            ),
            "square_connection_id": (
                square_connection_id
            ),
            "match_method": (
                mapping.get(
                    "match_method"
                )
                or "existing_mapping"
            ),
            "reference_id": (
                reference_id
            ),
            **_phone_omission_result_fields(
                phone_omitted
            ),
        }

    # -----------------------------------------------------
    # No mapping: search before create.
    # -----------------------------------------------------

    match_result = (
        _find_existing_square_customer(
            profile,
            access_token=(
                access_token
            ),
            environment=environment,
        )
    )

    phone_omitted = bool(
        profile.get(
            "_square_phone_omitted"
        )
    )

    if (
        match_result["status"]
        == "needs_attention"
    ):
        return {
            "status": "needs_attention",
            "client_id": client_id,
            "spa_id": spa_id,
            "business_unit_id": (
                business_unit_id
            ),
            "environment": environment,
            **match_result,
        }

    if (
        match_result["status"]
        == "matched"
    ):
        candidate = (
            match_result[
                "customer"
            ]
        )

        square_customer = (
            square_service
            .retrieve_customer(
                candidate["id"],
                access_token=(
                    access_token
                ),
                environment=environment,
            )
        )

        (
            updated,
            fallback_phone_omitted,
        ) = (
            _update_customer_with_phone_fallback(
                square_customer[
                    "id"
                ],
                _build_update_payload(
                    profile,
                    version=(
                        square_customer
                        .get("version")
                    )
                ),
                access_token=(
                    access_token
                ),
                environment=environment,
            )
        )

        phone_omitted = (
            phone_omitted
            or fallback_phone_omitted
        )

        mapping_row = (
            _persist_mapping(
                square_connection_id=(
                    square_connection_id
                ),
                spa_id=spa_id,
                business_unit_id=(
                    business_unit_id
                ),
                environment=(
                    environment
                ),
                square_customer_id=(
                    updated["id"]
                ),
                client_id=client_id,
                match_method=(
                    match_result[
                        "match_method"
                    ]
                ),
                actor_user_id=(
                    actor_user_id
                ),
            )
        )

        _touch_connection_sync_time(
            square_connection_id,
            spa_id,
            business_unit_id,
            environment
        )

        return {
            "status": "synced",
            "action": "matched_updated",
            "client_id": client_id,
            "square_customer_id": (
                updated["id"]
            ),
            "square_customer_mapping_id": (
                mapping_row[
                    "square_customer_mapping_id"
                ]
            ),
            "square_connection_id": (
                square_connection_id
            ),
            "match_method": (
                match_result[
                    "match_method"
                ]
            ),
            "reference_id": (
                reference_id
            ),
            **_phone_omission_result_fields(
                phone_omitted
            ),
        }

    # -----------------------------------------------------
    # No safe match: create a new Square profile.
    #
    # Stable idempotency key protects retries where Square
    # succeeds but the PSP mapping write is interrupted.
    # -----------------------------------------------------

    (
        created,
        fallback_phone_omitted,
    ) = (
        _create_customer_with_phone_fallback(
            _build_create_payload(
                profile
            ),
            idempotency_key=(
                f"psp-client-create-"
                f"{square_connection_id}-"
                f"{client_id}-v1"
            ),
            access_token=(
                access_token
            ),
            environment=environment,
        )
    )

    phone_omitted = (
        phone_omitted
        or fallback_phone_omitted
    )

    square_customer_id = str(
        created.get("id") or ""
    ).strip()

    if not square_customer_id:
        raise SquareClientSyncError(
            "Square did not return a customer ID after creation."
        )

    mapping_row = (
        _persist_mapping(
            square_connection_id=(
                square_connection_id
            ),
            spa_id=spa_id,
            business_unit_id=(
                business_unit_id
            ),
            environment=environment,
            square_customer_id=(
                square_customer_id
            ),
            client_id=client_id,
            match_method=(
                "psp_created"
            ),
            actor_user_id=(
                actor_user_id
            ),
        )
    )

    _touch_connection_sync_time(
        square_connection_id,
        spa_id,
        business_unit_id,
        environment
    )

    return {
        "status": "synced",
        "action": "created",
        "client_id": client_id,
        "square_customer_id": (
            square_customer_id
        ),
        "square_customer_mapping_id": (
            mapping_row[
                "square_customer_mapping_id"
            ]
        ),
        "square_connection_id": (
            square_connection_id
        ),
        "match_method": (
            "psp_created"
        ),
        "reference_id": (
            reference_id
        ),
        **_phone_omission_result_fields(
            phone_omitted
        ),
    }


def try_sync_client_to_square(
    **kwargs
):
    """
    Non-fatal wrapper intended for future Add/Edit Client routes.

    A Square failure must never roll back a PSP client that was
    already saved successfully.
    """
    try:
        return sync_client_to_square(
            **kwargs
        )

    except Exception as exc:
        return {
            "status": "error",
            "reason": (
                exc.__class__.__name__
            ),
            "message": str(exc),
            "client_id": kwargs.get(
                "client_id"
            ),
            "spa_id": kwargs.get(
                "spa_id"
            ),
            "business_unit_id": (
                kwargs.get(
                    "business_unit_id"
                )
            ),
            "environment": (
                kwargs.get(
                    "environment",
                    "sandbox"
                )
            ),
        }
