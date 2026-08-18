from copy import deepcopy
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from difflib import SequenceMatcher
import hashlib

from psycopg2 import IntegrityError
from psycopg2.extras import RealDictCursor

from db import get_db_connection
from services import square_service, square_sync_auth


class SquareServiceSyncError(Exception):
    pass


def _money_to_cents(value):
    try:
        amount = Decimal(str(value or "0"))
    except (InvalidOperation, TypeError, ValueError) as exc:
        raise SquareServiceSyncError(
            "PSP service price is invalid."
        ) from exc

    if amount < 0:
        raise SquareServiceSyncError(
            "PSP service price cannot be negative."
        )

    return int(
        (amount * Decimal("100")).quantize(
            Decimal("1"),
            rounding=ROUND_HALF_UP,
        )
    )


def _duration_to_milliseconds(value):
    try:
        minutes = int(value)
    except (TypeError, ValueError) as exc:
        raise SquareServiceSyncError(
            "PSP service duration is invalid."
        ) from exc

    if minutes <= 0:
        raise SquareServiceSyncError(
            "PSP service duration must be greater than zero."
        )

    return minutes * 60 * 1000


def _load_sync_context(
    spa_id,
    business_unit_id,
    service_type_id,
    environment,
):
    environment = (
        square_service.normalize_square_environment(
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
                service_type_id,
                spa_id,
                service_name,
                default_duration_minutes,
                default_price,
                is_active
            FROM service_name_types
            WHERE service_type_id = %s
              AND spa_id = %s
            LIMIT 1
        """, (
            service_type_id,
            spa_id,
        ))

        service = cur.fetchone()

        if not service:
            raise SquareServiceSyncError(
                "PSP service was not found for the requested spa."
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
            ORDER BY square_connection_id
            LIMIT 1
        """, (
            spa_id,
            business_unit_id,
            environment,
        ))

        connection = cur.fetchone()

        if not connection:
            return {
                "service": dict(service),
                "connection": None,
                "mapping": None,
                "environment": environment,
            }

        cur.execute("""
            SELECT
                square_catalog_mapping_id,
                square_connection_id,
                spa_id,
                business_unit_id,
                environment,
                square_catalog_object_id,
                square_item_id,
                square_name,
                square_sku,
                mapping_type,
                inventory_product_id,
                service_type_id,
                is_active,
                verified_by,
                verified_at
            FROM square_catalog_mappings
            WHERE square_connection_id = %s
              AND spa_id = %s
              AND business_unit_id = %s
              AND environment = %s
              AND mapping_type = 'service_type'
              AND service_type_id = %s
              AND is_active = TRUE
            LIMIT 2
        """, (
            connection["square_connection_id"],
            spa_id,
            business_unit_id,
            environment,
            service_type_id,
        ))

        mappings = cur.fetchall()

        if len(mappings) > 1:
            raise SquareServiceSyncError(
                "PSP service has multiple active Square Catalog mappings."
            )

        mapping = (
            dict(mappings[0])
            if mappings
            else None
        )

        return {
            "service": dict(service),
            "connection": dict(connection),
            "mapping": mapping,
            "environment": environment,
        }

    finally:
        cur.close()
        conn.close()


def _resolve_access_token(
    environment,
    *,
    spa_id,
    business_unit_id,
):
    """
    Resolve the workspace-scoped Square write credential.

    Production remains guarded by the shared sync-auth
    live_sync_enabled and OAuth verification requirements.
    """
    try:
        return (
            square_sync_auth
            .resolve_square_sync_access_token(
                spa_id=spa_id,
                business_unit_id=business_unit_id,
                environment=environment,
            )
        )

    except square_sync_auth.SquareSyncAuthError as exc:
        raise SquareServiceSyncError(
            str(exc)
        ) from exc


def _service_profile(service):
    name = str(
        service.get("service_name") or ""
    ).strip()

    if not name:
        raise SquareServiceSyncError(
            "PSP service name is required."
        )

    return {
        "name": name,
        "price_cents": _money_to_cents(
            service.get("default_price")
        ),
        "duration_ms": (
            _duration_to_milliseconds(
                service.get(
                    "default_duration_minutes"
                )
            )
        ),
        "is_active": bool(
            service.get("is_active")
        ),
    }


def _find_existing_square_service_candidate(
    profile,
    *,
    access_token,
    environment,
):
    """
    Conservatively detect an existing Square service before
    creating an unmapped PSP service.

    Exact or sufficiently similar candidates require human
    review. This helper never writes to Square or PSP.
    """
    target_name = (
        square_service
        .normalize_catalog_match_text(
            profile["name"]
        )
    )

    target_tokens = set(
        target_name.split()
    )

    exact_matches = []
    similar_matches = []

    catalog_objects = (
        square_service
        .list_catalog_objects(
            access_token=access_token,
            environment=environment,
            object_types=("ITEM",),
        )
    )

    for catalog_object in (
        catalog_objects
    ):
        if (
            catalog_object.get("type")
            != "ITEM"
            or catalog_object.get(
                "is_deleted"
            )
        ):
            continue

        item_data = (
            catalog_object.get(
                "item_data"
            )
            or {}
        )

        product_type = str(
            item_data.get(
                "product_type"
            )
            or ""
        ).strip().upper()

        # PSP service sync creates and manages
        # APPOINTMENTS_SERVICE items. Do not silently
        # adopt unrelated retail/legacy Catalog objects.
        if (
            product_type
            != "APPOINTMENTS_SERVICE"
        ):
            continue

        square_item_id = str(
            catalog_object.get("id")
            or ""
        ).strip()

        square_name = str(
            item_data.get("name")
            or ""
        ).strip()

        normalized_name = (
            square_service
            .normalize_catalog_match_text(
                square_name
            )
        )

        if (
            not square_item_id
            or not normalized_name
        ):
            continue

        variation_ids = []

        for variation in (
            item_data.get(
                "variations"
            )
            or []
        ):
            variation_id = str(
                variation.get("id")
                or ""
            ).strip()

            if variation_id:
                variation_ids.append(
                    variation_id
                )

        candidate = {
            "square_item_id": (
                square_item_id
            ),
            "square_name": square_name,
            "square_product_type": (
                product_type
            ),
            "square_variation_ids": (
                variation_ids
            ),
        }

        if (
            normalized_name
            == target_name
        ):
            exact_matches.append(
                candidate
            )
            continue

        similarity = SequenceMatcher(
            None,
            target_name,
            normalized_name,
        ).ratio()

        candidate_tokens = set(
            normalized_name.split()
        )

        token_subset_match = (
            len(target_tokens) >= 2
            and len(candidate_tokens) >= 2
            and (
                target_tokens.issubset(
                    candidate_tokens
                )
                or candidate_tokens.issubset(
                    target_tokens
                )
            )
        )

        shared_tokens = (
            target_tokens
            .intersection(
                candidate_tokens
            )
        )

        token_prefix_match = (
            bool(shared_tokens)
            and any(
                target_token
                != candidate_token
                and len(target_token) >= 5
                and len(candidate_token) >= 5
                and (
                    target_token.startswith(
                        candidate_token
                    )
                    or candidate_token.startswith(
                        target_token
                    )
                )
                for target_token in target_tokens
                for candidate_token in candidate_tokens
            )
        )

        if (
            similarity >= 0.88
            or token_subset_match
            or token_prefix_match
        ):
            candidate["similarity"] = (
                round(
                    similarity,
                    3,
                )
            )

            similar_matches.append(
                candidate
            )

    if exact_matches:
        return {
            "status": "needs_attention",
            "reason": (
                "existing_square_service_exact_match"
                if len(exact_matches) == 1
                else "multiple_square_service_exact_matches"
            ),
            "candidate_count": (
                len(exact_matches)
            ),
            "candidates": exact_matches,
        }

    if similar_matches:
        similar_matches.sort(
            key=lambda candidate: (
                -candidate.get(
                    "similarity",
                    0,
                ),
                candidate.get(
                    "square_name",
                    "",
                ).lower(),
                candidate.get(
                    "square_item_id",
                    "",
                ),
            )
        )

        return {
            "status": "needs_attention",
            "reason": (
                "similar_square_service_candidate"
            ),
            "candidate_count": (
                len(similar_matches)
            ),
            "candidates": (
                similar_matches
            ),
        }

    return {
        "status": "no_match",
    }


def _build_create_payload(
    service_type_id,
    profile,
):
    return {
        "type": "ITEM",
        "id": (
            f"#psp-service-item-"
            f"{service_type_id}"
        ),
        "present_at_all_locations": True,
        "item_data": {
            "name": profile["name"],
            "product_type": (
                "APPOINTMENTS_SERVICE"
            ),
            "variations": [
                {
                    "type": "ITEM_VARIATION",
                    "id": (
                        f"#psp-service-variation-"
                        f"{service_type_id}"
                    ),
                    "present_at_all_locations": True,
                    "item_variation_data": {
                        "name": "Regular",
                        "pricing_type": (
                            "FIXED_PRICING"
                        ),
                        "price_money": {
                            "amount": (
                                profile[
                                    "price_cents"
                                ]
                            ),
                            "currency": "USD",
                        },
                        "service_duration": (
                            profile["duration_ms"]
                        ),
                        "available_for_booking": (
                            profile["is_active"]
                        ),
                    },
                }
            ],
        },
    }


def _extract_single_variation(
    catalog_item,
):
    variations = (
        catalog_item
        .get("item_data", {})
        .get("variations", [])
    )

    if len(variations) != 1:
        raise SquareServiceSyncError(
            "Square service item must contain exactly "
            "one PSP-managed variation."
        )

    variation = variations[0]

    variation_id = str(
        variation.get("id") or ""
    ).strip()

    if not variation_id:
        raise SquareServiceSyncError(
            "Square service variation ID is missing."
        )

    return variation


def _build_update_payload(
    parent_item,
    mapped_variation_id,
    profile,
):
    updated_parent = deepcopy(
        parent_item
    )

    if updated_parent.get("type") != "ITEM":
        raise SquareServiceSyncError(
            "Mapped Square parent object is not an ITEM."
        )

    item_data = updated_parent.setdefault(
        "item_data",
        {}
    )

    item_data["name"] = profile["name"]
    item_data["product_type"] = (
        "APPOINTMENTS_SERVICE"
    )

    variations = (
        item_data.get("variations")
        or []
    )

    matches = [
        variation
        for variation in variations
        if str(
            variation.get("id") or ""
        ).strip() == mapped_variation_id
    ]

    if len(matches) != 1:
        raise SquareServiceSyncError(
            "Mapped Square service variation was not found "
            "exactly once in its parent item."
        )

    variation = matches[0]

    variation["type"] = "ITEM_VARIATION"

    variation_data = (
        variation.setdefault(
            "item_variation_data",
            {}
        )
    )

    variation_data["name"] = "Regular"
    variation_data["pricing_type"] = (
        "FIXED_PRICING"
    )
    variation_data["price_money"] = {
        "amount": profile["price_cents"],
        "currency": "USD",
    }
    variation_data["service_duration"] = (
        profile["duration_ms"]
    )
    variation_data["available_for_booking"] = (
        profile["is_active"]
    )

    return updated_parent


def _create_idempotency_key(
    square_connection_id,
    service_type_id,
):
    return (
        f"psp-svc-c-"
        f"{square_connection_id}-"
        f"{service_type_id}-v1"
    )


def _update_idempotency_key(
    square_connection_id,
    service_type_id,
    parent_version,
    profile,
):
    raw = "|".join([
        str(square_connection_id),
        str(service_type_id),
        str(parent_version or ""),
        profile["name"],
        str(profile["price_cents"]),
        str(profile["duration_ms"]),
        str(profile["is_active"]),
    ])

    digest = hashlib.sha256(
        raw.encode("utf-8")
    ).hexdigest()[:20]

    return (
        f"psp-svc-u-"
        f"{square_connection_id}-"
        f"{service_type_id}-"
        f"{digest}"
    )


def _persist_mapping(
    *,
    square_connection_id,
    spa_id,
    business_unit_id,
    environment,
    square_catalog_object_id,
    square_item_id,
    square_name,
    service_type_id,
    actor_user_id,
):
    conn = get_db_connection()
    cur = conn.cursor(
        cursor_factory=RealDictCursor
    )

    try:
        cur.execute("""
            SELECT service_type_id
            FROM service_name_types
            WHERE service_type_id = %s
              AND spa_id = %s
            LIMIT 1
        """, (
            service_type_id,
            spa_id,
        ))

        if not cur.fetchone():
            raise SquareServiceSyncError(
                "PSP service changed before the Square "
                "mapping could be saved."
            )

        cur.execute("""
            SELECT
                square_catalog_mapping_id,
                square_catalog_object_id,
                square_item_id,
                service_type_id,
                is_active
            FROM square_catalog_mappings
            WHERE square_connection_id = %s
              AND spa_id = %s
              AND business_unit_id = %s
              AND environment = %s
              AND mapping_type = 'service_type'
              AND service_type_id = %s
              AND is_active = TRUE
            LIMIT 1
            FOR UPDATE
        """, (
            square_connection_id,
            spa_id,
            business_unit_id,
            environment,
            service_type_id,
        ))

        existing_for_service = (
            cur.fetchone()
        )

        if existing_for_service:
            if (
                existing_for_service[
                    "square_catalog_object_id"
                ]
                != square_catalog_object_id
            ):
                raise SquareServiceSyncError(
                    "PSP service already has a different "
                    "active Square Catalog mapping."
                )

            if (
                existing_for_service[
                    "square_item_id"
                ]
                and existing_for_service[
                    "square_item_id"
                ] != square_item_id
            ):
                raise SquareServiceSyncError(
                    "PSP service mapping points to a "
                    "different Square parent item."
                )

            cur.execute("""
                UPDATE square_catalog_mappings
                SET
                    square_item_id = %s,
                    square_name = %s,
                    square_sku = NULL,
                    verified_by = %s,
                    verified_at = CURRENT_TIMESTAMP,
                    updated_at = CURRENT_TIMESTAMP
                WHERE square_catalog_mapping_id = %s
                RETURNING
                    square_catalog_mapping_id,
                    square_catalog_object_id,
                    square_item_id,
                    square_name,
                    service_type_id,
                    is_active
            """, (
                square_item_id,
                square_name,
                actor_user_id,
                existing_for_service[
                    "square_catalog_mapping_id"
                ],
            ))

            row = cur.fetchone()
            conn.commit()

            return dict(row)

        cur.execute("""
            SELECT
                square_catalog_mapping_id,
                mapping_type,
                inventory_product_id,
                service_type_id,
                is_active
            FROM square_catalog_mappings
            WHERE square_connection_id = %s
              AND square_catalog_object_id = %s
            LIMIT 1
            FOR UPDATE
        """, (
            square_connection_id,
            square_catalog_object_id,
        ))

        existing_for_square = (
            cur.fetchone()
        )

        if existing_for_square:
            raise SquareServiceSyncError(
                "Square Catalog variation is already mapped "
                "to another PSP record."
            )

        cur.execute("""
            INSERT INTO square_catalog_mappings (
                square_connection_id,
                spa_id,
                business_unit_id,
                environment,
                square_catalog_object_id,
                square_item_id,
                square_name,
                square_sku,
                mapping_type,
                inventory_product_id,
                service_type_id,
                is_active,
                verified_by,
                verified_at
            )
            VALUES (
                %s, %s, %s, %s, %s,
                %s, %s, NULL, 'service_type',
                NULL, %s, TRUE, %s,
                CURRENT_TIMESTAMP
            )
            RETURNING
                square_catalog_mapping_id,
                square_catalog_object_id,
                square_item_id,
                square_name,
                service_type_id,
                is_active
        """, (
            square_connection_id,
            spa_id,
            business_unit_id,
            environment,
            square_catalog_object_id,
            square_item_id,
            square_name,
            service_type_id,
            actor_user_id,
        ))

        row = cur.fetchone()
        conn.commit()

        return dict(row)

    except IntegrityError as exc:
        conn.rollback()

        raise SquareServiceSyncError(
            "Square service mapping conflicted with an "
            "existing active mapping."
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
    environment,
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
            environment,
        ))

        conn.commit()

    finally:
        cur.close()
        conn.close()


def sync_service_to_square(
    *,
    spa_id,
    business_unit_id,
    service_type_id,
    actor_user_id=None,
    environment="sandbox",
):
    """
    Synchronize one PSP service to Square Catalog.

    PSP is authoritative.

    Identity rules:
      - PSP service is spa-level master data.
      - Square mapping is workspace/environment specific.
      - mapped variation ID is the chargeable Catalog identity.
      - mapped parent ITEM ID is retained separately.
      - existing mappings always update the same Square objects.
      - production sync requires the explicit workspace Live Sync gate.
    """
    context = _load_sync_context(
        spa_id,
        business_unit_id,
        service_type_id,
        environment,
    )

    service = context["service"]
    connection = context["connection"]
    mapping = context["mapping"]
    environment = context["environment"]

    if not connection:
        return {
            "status": "skipped",
            "reason": "square_not_connected",
            "service_type_id": service_type_id,
            "spa_id": spa_id,
            "business_unit_id": business_unit_id,
            "environment": environment,
        }

    access_token = _resolve_access_token(
        environment,
        spa_id=spa_id,
        business_unit_id=business_unit_id,
    )

    square_connection_id = (
        connection["square_connection_id"]
    )

    profile = _service_profile(
        service
    )

    if mapping:
        square_item_id = str(
            mapping.get("square_item_id") or ""
        ).strip()

        square_variation_id = str(
            mapping.get(
                "square_catalog_object_id"
            ) or ""
        ).strip()

        if not square_item_id:
            raise SquareServiceSyncError(
                "Mapped PSP service is missing its "
                "Square parent item ID."
            )

        if not square_variation_id:
            raise SquareServiceSyncError(
                "Mapped PSP service is missing its "
                "Square variation ID."
            )

        parent_item = (
            square_service
            .retrieve_catalog_object(
                square_item_id,
                access_token=access_token,
                environment=environment,
            )
        )

        parent_version = (
            parent_item.get("version")
        )

        updated_parent = (
            _build_update_payload(
                parent_item,
                square_variation_id,
                profile,
            )
        )

        result = (
            square_service
            .upsert_catalog_object(
                updated_parent,
                idempotency_key=(
                    _update_idempotency_key(
                        square_connection_id,
                        service_type_id,
                        parent_version,
                        profile,
                    )
                ),
                access_token=access_token,
                environment=environment,
            )
        )

        updated_item = result[
            "catalog_object"
        ]

        updated_variations = (
            updated_item
            .get("item_data", {})
            .get("variations", [])
        )

        matching_variations = [
            variation
            for variation in updated_variations
            if str(
                variation.get("id") or ""
            ).strip() == square_variation_id
        ]

        if len(matching_variations) != 1:
            raise SquareServiceSyncError(
                "Square service update did not return "
                "the mapped variation."
            )

        persisted = _persist_mapping(
            square_connection_id=(
                square_connection_id
            ),
            spa_id=spa_id,
            business_unit_id=(
                business_unit_id
            ),
            environment=environment,
            square_catalog_object_id=(
                square_variation_id
            ),
            square_item_id=square_item_id,
            square_name=profile["name"],
            service_type_id=service_type_id,
            actor_user_id=actor_user_id,
        )

        _touch_connection_sync_time(
            square_connection_id,
            spa_id,
            business_unit_id,
            environment,
        )

        return {
            "status": "synced",
            "action": "updated",
            "service_type_id": service_type_id,
            "square_catalog_mapping_id": (
                persisted[
                    "square_catalog_mapping_id"
                ]
            ),
            "square_connection_id": (
                square_connection_id
            ),
            "square_item_id": square_item_id,
            "square_catalog_object_id": (
                square_variation_id
            ),
            "square_name": profile["name"],
            "price_cents": (
                profile["price_cents"]
            ),
            "duration_ms": (
                profile["duration_ms"]
            ),
            "available_for_booking": (
                profile["is_active"]
            ),
        }

    # -----------------------------------------------------
    # No mapping: inspect the existing Square Catalog before
    # creating anything. A possible duplicate requires human
    # review and causes no Square write.
    # -----------------------------------------------------
    catalog_guard = (
        _find_existing_square_service_candidate(
            profile,
            access_token=access_token,
            environment=environment,
        )
    )

    if (
        catalog_guard["status"]
        == "needs_attention"
    ):
        return {
            "status": "needs_attention",
            "service_type_id": (
                service_type_id
            ),
            "spa_id": spa_id,
            "business_unit_id": (
                business_unit_id
            ),
            "environment": environment,
            **catalog_guard,
        }

    create_result = (
        square_service
        .upsert_catalog_object(
            _build_create_payload(
                service_type_id,
                profile,
            ),
            idempotency_key=(
                _create_idempotency_key(
                    square_connection_id,
                    service_type_id,
                )
            ),
            access_token=access_token,
            environment=environment,
        )
    )

    created_item = create_result[
        "catalog_object"
    ]

    square_item_id = str(
        created_item.get("id") or ""
    ).strip()

    if not square_item_id:
        raise SquareServiceSyncError(
            "Square did not return a parent service item ID."
        )

    created_variation = (
        _extract_single_variation(
            created_item
        )
    )

    square_variation_id = str(
        created_variation.get("id") or ""
    ).strip()

    persisted = _persist_mapping(
        square_connection_id=(
            square_connection_id
        ),
        spa_id=spa_id,
        business_unit_id=(
            business_unit_id
        ),
        environment=environment,
        square_catalog_object_id=(
            square_variation_id
        ),
        square_item_id=square_item_id,
        square_name=profile["name"],
        service_type_id=service_type_id,
        actor_user_id=actor_user_id,
    )

    _touch_connection_sync_time(
        square_connection_id,
        spa_id,
        business_unit_id,
        environment,
    )

    return {
        "status": "synced",
        "action": "created",
        "service_type_id": service_type_id,
        "square_catalog_mapping_id": (
            persisted[
                "square_catalog_mapping_id"
            ]
        ),
        "square_connection_id": (
            square_connection_id
        ),
        "square_item_id": square_item_id,
        "square_catalog_object_id": (
            square_variation_id
        ),
        "square_name": profile["name"],
        "price_cents": profile["price_cents"],
        "duration_ms": profile["duration_ms"],
        "available_for_booking": (
            profile["is_active"]
        ),
    }


def try_sync_service_to_square(
    **kwargs
):
    """
    Non-fatal wrapper for future Service Catalog routes.

    A Square failure must never roll back a PSP service that
    was already saved successfully.
    """
    try:
        return sync_service_to_square(
            **kwargs
        )

    except Exception as exc:
        return {
            "status": "error",
            "reason": (
                exc.__class__.__name__
            ),
            "message": str(exc),
            "service_type_id": kwargs.get(
                "service_type_id"
            ),
            "spa_id": kwargs.get(
                "spa_id"
            ),
            "business_unit_id": kwargs.get(
                "business_unit_id"
            ),
            "environment": kwargs.get(
                "environment",
                "sandbox"
            ),
        }
