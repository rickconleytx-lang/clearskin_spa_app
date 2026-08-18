from copy import deepcopy
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from difflib import SequenceMatcher
import hashlib
import json

from psycopg2 import IntegrityError
from psycopg2.extras import RealDictCursor

from db import get_db_connection
from services import square_service, square_sync_auth


class SquareInventorySyncError(Exception):
    """Raised when PSP -> Square inventory catalog sync cannot proceed."""


def _money_to_cents(value):
    try:
        amount = Decimal(str(value or 0))
    except (InvalidOperation, TypeError, ValueError) as exc:
        raise SquareInventorySyncError(
            "PSP product retail price is invalid."
        ) from exc

    if amount < 0:
        raise SquareInventorySyncError(
            "PSP product retail price cannot be negative."
        )

    return int(
        (amount * Decimal("100"))
        .quantize(
            Decimal("1"),
            rounding=ROUND_HALF_UP,
        )
    )


def _load_sync_context(
    spa_id,
    business_unit_id,
    inventory_product_id,
    environment,
):
    environment = str(
        environment or "sandbox"
    ).strip().lower()

    if environment not in (
        "sandbox",
        "production",
    ):
        raise SquareInventorySyncError(
            "Square environment must be sandbox or production."
        )

    conn = get_db_connection()
    cur = conn.cursor(
        cursor_factory=RealDictCursor
    )

    try:
        cur.execute("""
            SELECT
                product_id,
                spa_id,
                business_unit_id,
                sku,
                product_name,
                wholesale_cost,
                suggested_retail,
                active
            FROM inventory_products
            WHERE product_id = %s
              AND spa_id = %s
              AND business_unit_id = %s
            LIMIT 1
        """, (
            inventory_product_id,
            spa_id,
            business_unit_id,
        ))

        product = cur.fetchone()

        if not product:
            raise SquareInventorySyncError(
                "PSP inventory product could not be found "
                "in the selected workspace."
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
            ORDER BY square_connection_id DESC
            LIMIT 2
        """, (
            spa_id,
            business_unit_id,
            environment,
        ))

        connections = cur.fetchall()

        if len(connections) > 1:
            raise SquareInventorySyncError(
                "More than one active Square connection "
                "exists for this workspace/environment."
            )

        connection = (
            connections[0]
            if connections
            else None
        )

        mapping = None

        if connection:
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
                    inventory_product_id,
                    is_active
                FROM square_catalog_mappings
                WHERE square_connection_id = %s
                  AND spa_id = %s
                  AND business_unit_id = %s
                  AND environment = %s
                  AND mapping_type = 'inventory_product'
                  AND inventory_product_id = %s
                  AND is_active = TRUE
                ORDER BY square_catalog_mapping_id
                LIMIT 2
            """, (
                connection[
                    "square_connection_id"
                ],
                spa_id,
                business_unit_id,
                environment,
                inventory_product_id,
            ))

            mappings = cur.fetchall()

            if len(mappings) > 1:
                raise SquareInventorySyncError(
                    "PSP inventory product has more than one "
                    "active Square Catalog mapping."
                )

            if mappings:
                mapping = mappings[0]

        return {
            "product": dict(product),
            "connection": (
                dict(connection)
                if connection
                else None
            ),
            "mapping": (
                dict(mapping)
                if mapping
                else None
            ),
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
        raise SquareInventorySyncError(
            str(exc)
        ) from exc


def _product_profile(product):
    name = str(
        product.get("product_name") or ""
    ).strip()

    sku = str(
        product.get("sku") or ""
    ).strip()

    if not name:
        raise SquareInventorySyncError(
            "PSP inventory product name is required."
        )

    if not sku:
        raise SquareInventorySyncError(
            "PSP inventory product SKU is required."
        )

    return {
        "name": name,
        "sku": sku,
        "price_cents": _money_to_cents(
            product.get("suggested_retail")
        ),
        "is_active": bool(
            product.get("active")
        ),
    }


def _find_existing_square_product_candidate(
    profile,
    *,
    access_token,
    environment,
):
    """
    Conservatively detect an existing Square Catalog product
    before creating an unmapped PSP inventory product.

    Exact SKU is the strongest signal. Exact names and very
    close name variants also require human review. This helper
    never writes to Square or PSP.
    """
    target_name = (
        square_service
        .normalize_catalog_match_text(
            profile["name"]
        )
    )

    target_sku = str(
        profile["sku"]
        or ""
    ).strip().casefold()

    sku_matches = []
    exact_name_matches = []
    similar_name_matches = []

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

        if not square_item_id:
            continue

        all_skus = []
        matching_variation_ids = []

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

            variation_data = (
                variation.get(
                    "item_variation_data"
                )
                or {}
            )

            square_sku = str(
                variation_data.get("sku")
                or ""
            ).strip()

            if square_sku:
                all_skus.append(
                    square_sku
                )

            if (
                target_sku
                and square_sku.casefold()
                == target_sku
                and variation_id
            ):
                matching_variation_ids.append(
                    variation_id
                )

        candidate = {
            "square_item_id": (
                square_item_id
            ),
            "square_name": square_name,
            "square_product_type": str(
                item_data.get(
                    "product_type"
                )
                or ""
            ).strip(),
            "square_skus": all_skus,
        }

        if matching_variation_ids:
            candidate[
                "matching_variation_ids"
            ] = matching_variation_ids

            sku_matches.append(
                candidate
            )
            continue

        if (
            target_name
            and normalized_name
            == target_name
        ):
            exact_name_matches.append(
                candidate
            )
            continue

        if (
            target_name
            and normalized_name
        ):
            similarity = SequenceMatcher(
                None,
                target_name,
                normalized_name,
            ).ratio()

            # Product names are intentionally held to a
            # much higher similarity threshold than service
            # names because SKU is the stronger identity.
            if similarity >= 0.92:
                candidate[
                    "similarity"
                ] = round(
                    similarity,
                    3,
                )

                similar_name_matches.append(
                    candidate
                )

    if sku_matches:
        return {
            "status": "needs_attention",
            "reason": (
                "existing_square_product_sku_match"
                if len(sku_matches) == 1
                else "multiple_square_product_sku_matches"
            ),
            "candidate_count": (
                len(sku_matches)
            ),
            "candidates": sku_matches,
        }

    if exact_name_matches:
        return {
            "status": "needs_attention",
            "reason": (
                "existing_square_product_name_match"
                if len(exact_name_matches) == 1
                else "multiple_square_product_name_matches"
            ),
            "candidate_count": (
                len(exact_name_matches)
            ),
            "candidates": (
                exact_name_matches
            ),
        }

    if similar_name_matches:
        similar_name_matches.sort(
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
                "similar_square_product_candidate"
            ),
            "candidate_count": (
                len(similar_name_matches)
            ),
            "candidates": (
                similar_name_matches
            ),
        }

    return {
        "status": "no_match",
    }


def _build_create_payload(
    inventory_product_id,
    profile,
):
    return {
        "type": "ITEM",
        "id": (
            f"#psp-product-item-"
            f"{inventory_product_id}"
        ),
        "present_at_all_locations": True,
        "item_data": {
            "name": profile["name"],
            "is_archived": (
                not profile["is_active"]
            ),
            "variations": [
                {
                    "type": "ITEM_VARIATION",
                    "id": (
                        f"#psp-product-variation-"
                        f"{inventory_product_id}"
                    ),
                    "present_at_all_locations": True,
                    "item_variation_data": {
                        "name": "Regular",
                        "sku": profile["sku"],
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
                    },
                }
            ],
        },
    }


def _extract_single_variation(catalog_item):
    variations = (
        catalog_item
        .get("item_data", {})
        .get("variations", [])
    )

    if len(variations) != 1:
        raise SquareInventorySyncError(
            "Square product item must contain exactly "
            "one PSP-managed variation."
        )

    variation = variations[0]

    variation_id = str(
        variation.get("id") or ""
    ).strip()

    if not variation_id:
        raise SquareInventorySyncError(
            "Square product variation ID is missing."
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
        raise SquareInventorySyncError(
            "Mapped Square parent object is not an ITEM."
        )

    item_data = updated_parent.setdefault(
        "item_data",
        {}
    )

    item_data["name"] = profile["name"]
    item_data["is_archived"] = (
        not profile["is_active"]
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
        raise SquareInventorySyncError(
            "Mapped Square product variation was not found "
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
    variation_data["sku"] = profile["sku"]
    variation_data["pricing_type"] = (
        "FIXED_PRICING"
    )
    variation_data["price_money"] = {
        "amount": profile["price_cents"],
        "currency": "USD",
    }

    return updated_parent


def _create_idempotency_key(
    square_connection_id,
    inventory_product_id,
):
    return (
        f"psp-inv-c-"
        f"{square_connection_id}-"
        f"{inventory_product_id}-v1"
    )


def _update_idempotency_key(
    square_connection_id,
    inventory_product_id,
    parent_version,
    profile,
    payload,
):
    raw = "|".join([
        str(square_connection_id),
        str(inventory_product_id),
        str(parent_version or ""),
        profile["name"],
        profile["sku"],
        str(profile["price_cents"]),
        str(profile["is_active"]),
    ])

    # Include the complete request body so the same Square
    # idempotency key is reused only for the same exact update.
    raw += "|" + json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
    )

    digest = hashlib.sha256(
        raw.encode("utf-8")
    ).hexdigest()[:20]

    return (
        f"psp-inv-u-"
        f"{square_connection_id}-"
        f"{inventory_product_id}-"
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
    square_sku,
    inventory_product_id,
    actor_user_id,
):
    conn = get_db_connection()
    cur = conn.cursor(
        cursor_factory=RealDictCursor
    )

    try:
        cur.execute("""
            SELECT product_id
            FROM inventory_products
            WHERE product_id = %s
              AND spa_id = %s
              AND business_unit_id = %s
            LIMIT 1
        """, (
            inventory_product_id,
            spa_id,
            business_unit_id,
        ))

        if not cur.fetchone():
            raise SquareInventorySyncError(
                "PSP inventory product changed before "
                "the Square mapping could be saved."
            )

        cur.execute("""
            SELECT
                square_catalog_mapping_id,
                square_catalog_object_id,
                square_item_id,
                inventory_product_id,
                is_active
            FROM square_catalog_mappings
            WHERE square_connection_id = %s
              AND spa_id = %s
              AND business_unit_id = %s
              AND environment = %s
              AND mapping_type = 'inventory_product'
              AND inventory_product_id = %s
              AND is_active = TRUE
            LIMIT 1
            FOR UPDATE
        """, (
            square_connection_id,
            spa_id,
            business_unit_id,
            environment,
            inventory_product_id,
        ))

        existing_for_product = (
            cur.fetchone()
        )

        if existing_for_product:
            if (
                existing_for_product[
                    "square_catalog_object_id"
                ]
                != square_catalog_object_id
            ):
                raise SquareInventorySyncError(
                    "PSP inventory product already has a "
                    "different active Square Catalog mapping."
                )

            if (
                existing_for_product[
                    "square_item_id"
                ]
                and existing_for_product[
                    "square_item_id"
                ] != square_item_id
            ):
                raise SquareInventorySyncError(
                    "PSP inventory mapping points to a "
                    "different Square parent item."
                )

            cur.execute("""
                UPDATE square_catalog_mappings
                SET
                    square_item_id = %s,
                    square_name = %s,
                    square_sku = %s,
                    verified_by = %s,
                    verified_at = CURRENT_TIMESTAMP,
                    updated_at = CURRENT_TIMESTAMP
                WHERE square_catalog_mapping_id = %s
                RETURNING
                    square_catalog_mapping_id,
                    square_catalog_object_id,
                    square_item_id,
                    square_name,
                    square_sku,
                    inventory_product_id,
                    is_active
            """, (
                square_item_id,
                square_name,
                square_sku,
                actor_user_id,
                existing_for_product[
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
            raise SquareInventorySyncError(
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
                %s, %s, %s, 'inventory_product',
                %s, NULL, TRUE, %s,
                CURRENT_TIMESTAMP
            )
            RETURNING
                square_catalog_mapping_id,
                square_catalog_object_id,
                square_item_id,
                square_name,
                square_sku,
                inventory_product_id,
                is_active
        """, (
            square_connection_id,
            spa_id,
            business_unit_id,
            environment,
            square_catalog_object_id,
            square_item_id,
            square_name,
            square_sku,
            inventory_product_id,
            actor_user_id,
        ))

        row = cur.fetchone()
        conn.commit()

        return dict(row)

    except IntegrityError as exc:
        conn.rollback()

        raise SquareInventorySyncError(
            "Square inventory mapping conflicted with an "
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


def sync_inventory_product_to_square(
    *,
    spa_id,
    business_unit_id,
    inventory_product_id,
    actor_user_id=None,
    environment="sandbox",
):
    """
    Synchronize one PSP inventory product to Square Catalog.

    PSP is authoritative for product master data.

    This function intentionally does NOT synchronize physical
    stock counts. inventory_movements remains untouched.

    Identity rules:
      - PSP inventory product belongs to one exact workspace.
      - Square mapping is workspace/environment specific.
      - mapped variation ID is the chargeable Catalog identity.
      - mapped parent ITEM ID is retained separately.
      - existing mappings always update the same Square objects.
      - inactive PSP products archive, rather than delete, the
        Square ITEM so Catalog identity is preserved.
      - production sync requires the explicit workspace Live Sync gate.
    """
    context = _load_sync_context(
        spa_id,
        business_unit_id,
        inventory_product_id,
        environment,
    )

    product = context["product"]
    connection = context["connection"]
    mapping = context["mapping"]
    environment = context["environment"]

    if not connection:
        return {
            "status": "skipped",
            "reason": "square_not_connected",
            "inventory_product_id": (
                inventory_product_id
            ),
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

    profile = _product_profile(
        product
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
            raise SquareInventorySyncError(
                "Mapped PSP inventory product is missing "
                "its Square parent item ID."
            )

        if not square_variation_id:
            raise SquareInventorySyncError(
                "Mapped PSP inventory product is missing "
                "its Square variation ID."
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
                        inventory_product_id,
                        parent_version,
                        profile,
                        updated_parent,
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
            raise SquareInventorySyncError(
                "Square inventory update did not return "
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
            square_sku=profile["sku"],
            inventory_product_id=(
                inventory_product_id
            ),
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
            "inventory_product_id": (
                inventory_product_id
            ),
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
            "square_sku": profile["sku"],
            "price_cents": (
                profile["price_cents"]
            ),
            "is_archived": (
                not profile["is_active"]
            ),
        }

    # -----------------------------------------------------
    # No mapping: inspect the existing Square Catalog before
    # creating anything. A possible duplicate requires human
    # review and causes no Square write.
    # -----------------------------------------------------
    catalog_guard = (
        _find_existing_square_product_candidate(
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
            "inventory_product_id": (
                inventory_product_id
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
                inventory_product_id,
                profile,
            ),
            idempotency_key=(
                _create_idempotency_key(
                    square_connection_id,
                    inventory_product_id,
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
        raise SquareInventorySyncError(
            "Square did not return a parent product item ID."
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
        square_sku=profile["sku"],
        inventory_product_id=(
            inventory_product_id
        ),
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
        "inventory_product_id": (
            inventory_product_id
        ),
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
        "square_sku": profile["sku"],
        "price_cents": profile["price_cents"],
        "is_archived": (
            not profile["is_active"]
        ),
    }


def try_sync_inventory_product_to_square(
    **kwargs
):
    """
    Non-fatal wrapper for future Inventory routes.

    A Square failure must never roll back a PSP inventory
    product that was already saved successfully.
    """
    try:
        return sync_inventory_product_to_square(
            **kwargs
        )

    except Exception as exc:
        return {
            "status": "error",
            "reason": (
                exc.__class__.__name__
            ),
            "message": str(exc),
            "inventory_product_id": kwargs.get(
                "inventory_product_id"
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
