import decimal

from psycopg2.extras import Json


class SquareIncomePostingError(Exception):
    """Raised when Square Income posting cannot complete safely."""


class SquareInventoryLinkError(SquareIncomePostingError):
    """Raised when an inventory movement cannot be linked safely."""


class SquarePaymentLinkError(SquareIncomePostingError):
    """Raised when a Square payment cannot be linked to Income."""


def stage_square_payment_line_items(
    cursor,
    *,
    spa_id,
    business_unit_id,
    square_payment_record_id,
    preview,
    catalog_mapping_details,
):
    """
    Stage authoritative Square order lines without creating
    Income or inventory movements.

    The caller owns transaction control. Returned staging
    context can be used by the full Income/inventory posting
    path after the line records are safely upserted.
    """

    staged_lines = []

    for line in preview["line_items"]:
        raw_line = line.get("raw") or {}

        catalog_object_id = (
            line.get("catalog_object_id")
        )

        mapping = (
            catalog_mapping_details.get(
                catalog_object_id
            )
            if catalog_object_id
            else None
        )

        classification = str(
            line.get("classification") or "unknown"
        ).strip().lower()

        mapping_is_compatible = bool(
            mapping
            and (
                (
                    mapping["mapping_type"]
                    == "service_type"
                    and classification == "service"
                )
                or
                (
                    mapping["mapping_type"]
                    == "inventory_product"
                    and classification == "retail"
                )
            )
        )

        square_catalog_mapping_id = (
            mapping[
                "square_catalog_mapping_id"
            ]
            if mapping_is_compatible
            else None
        )

        quantity_text = str(
            line.get("quantity") or ""
        ).strip()

        quantity_numeric = None

        if quantity_text:
            try:
                candidate_quantity = (
                    decimal.Decimal(
                        quantity_text
                    )
                )

                if candidate_quantity.is_finite():
                    quantity_numeric = (
                        candidate_quantity
                    )

            except decimal.InvalidOperation:
                quantity_numeric = None

        inventory_quantity = None

        if (
            quantity_numeric is not None
            and quantity_numeric > 0
            and quantity_numeric
                == quantity_numeric.to_integral_value()
        ):
            inventory_quantity = int(
                quantity_numeric
            )

        retail_inventory_candidate = bool(
            mapping_is_compatible
            and classification == "retail"
            and mapping["mapping_type"]
                == "inventory_product"
            and mapping[
                "inventory_product_id"
            ] is not None
        )

        line_status = (
            "mapped"
            if mapping_is_compatible
            else "review"
        )

        if (
            retail_inventory_candidate
            and inventory_quantity is None
        ):
            line_status = "review"

        def square_line_money_cents(field_name):
            money = (
                raw_line.get(field_name)
                or {}
            )

            try:
                return int(
                    money.get("amount") or 0
                )
            except (
                TypeError,
                ValueError,
            ):
                return 0

        cursor.execute("""
            INSERT INTO square_payment_line_items (
                square_payment_record_id,
                spa_id,
                business_unit_id,
                line_sequence,
                square_order_line_item_uid,
                square_catalog_object_id,
                square_item_id,
                item_name,
                sku,
                quantity_text,
                quantity_numeric,
                base_price_cents,
                gross_amount_cents,
                discount_amount_cents,
                tax_amount_cents,
                total_amount_cents,
                item_classification,
                square_catalog_mapping_id,
                reconciliation_status,
                raw_line_item
            )
            VALUES (
                %s, %s, %s, %s, %s,
                %s, %s, %s, %s, %s,
                %s, %s, %s, %s, %s,
                %s, %s, %s, %s, %s
            )
            ON CONFLICT (
                square_payment_record_id,
                line_sequence
            )
            DO UPDATE SET
                square_order_line_item_uid =
                    EXCLUDED.square_order_line_item_uid,
                square_catalog_object_id =
                    EXCLUDED.square_catalog_object_id,
                square_item_id = COALESCE(
                    EXCLUDED.square_item_id,
                    square_payment_line_items.square_item_id
                ),
                item_name = EXCLUDED.item_name,
                sku = COALESCE(
                    EXCLUDED.sku,
                    square_payment_line_items.sku
                ),
                quantity_text =
                    EXCLUDED.quantity_text,
                quantity_numeric =
                    EXCLUDED.quantity_numeric,
                base_price_cents =
                    EXCLUDED.base_price_cents,
                gross_amount_cents =
                    EXCLUDED.gross_amount_cents,
                discount_amount_cents =
                    EXCLUDED.discount_amount_cents,
                tax_amount_cents =
                    EXCLUDED.tax_amount_cents,
                total_amount_cents =
                    EXCLUDED.total_amount_cents,
                item_classification =
                    EXCLUDED.item_classification,
                square_catalog_mapping_id =
                    COALESCE(
                        EXCLUDED.square_catalog_mapping_id,
                        square_payment_line_items
                            .square_catalog_mapping_id
                    ),
                reconciliation_status =
                    CASE
                        WHEN square_payment_line_items
                            .inventory_movement_id
                            IS NOT NULL
                        THEN 'posted'
                        ELSE EXCLUDED
                            .reconciliation_status
                    END,
                raw_line_item =
                    EXCLUDED.raw_line_item,
                updated_at = CURRENT_TIMESTAMP
            RETURNING
                square_payment_line_item_id,
                inventory_movement_id
        """, (
            square_payment_record_id,
            spa_id,
            business_unit_id,
            line["sequence"],
            line.get("line_uid"),
            catalog_object_id,
            (
                mapping["square_item_id"]
                if mapping_is_compatible
                else None
            ),
            line.get("name"),
            (
                mapping["square_sku"]
                if mapping_is_compatible
                else None
            ),
            quantity_text or None,
            quantity_numeric,
            square_line_money_cents(
                "base_price_money"
            ),
            square_line_money_cents(
                "gross_sales_money"
            ),
            square_line_money_cents(
                "total_discount_money"
            ),
            line.get("tax_cents"),
            line.get("total_cents"),
            classification,
            square_catalog_mapping_id,
            line_status,
            Json(raw_line),
        ))

        (
            square_payment_line_item_id,
            existing_inventory_movement_id,
        ) = cursor.fetchone()

        staged_lines.append({
            "line": line,
            "mapping": mapping,
            "retail_inventory_candidate":
                retail_inventory_candidate,
            "inventory_quantity": inventory_quantity,
            "square_payment_line_item_id":
                square_payment_line_item_id,
            "existing_inventory_movement_id":
                existing_inventory_movement_id,
        })

    return staged_lines


def finalize_square_payment_income_link(
    cursor,
    *,
    spa_id,
    business_unit_id,
    income_id,
    square_payment_record_id,
):
    """
    Link one reserved Square payment to PSP Income and mark
    its financial reconciliation complete.

    The caller owns transaction control.
    """

    cursor.execute("""
        UPDATE square_payments
        SET
            income_id = %s,
            reconciliation_status = 'reconciled',
            reconciled_at = CURRENT_TIMESTAMP,
            last_synced_at = CURRENT_TIMESTAMP,
            updated_at = CURRENT_TIMESTAMP
        WHERE square_payment_record_id = %s
          AND spa_id = %s
          AND business_unit_id = %s
          AND income_id IS NULL
    """, (
        income_id,
        square_payment_record_id,
        spa_id,
        business_unit_id,
    ))

    if cursor.rowcount != 1:
        raise SquarePaymentLinkError(
            "Square payment reconciliation could not "
            "be linked to Income."
        )


def ignore_square_payment_line_items(
    cursor,
    *,
    spa_id,
    business_unit_id,
    square_payment_record_id,
):
    """
    Mark previously staged Square item detail as intentionally
    not tracked when item-level PSP Inventory tracking is off.

    Existing posted inventory movements are never changed.
    The caller owns transaction control.
    """

    cursor.execute("""
        UPDATE square_payment_line_items
        SET
            reconciliation_status = 'ignored',
            updated_at = CURRENT_TIMESTAMP
        WHERE square_payment_record_id = %s
          AND spa_id = %s
          AND business_unit_id = %s
          AND inventory_movement_id IS NULL
          AND reconciliation_status <> 'posted'
    """, (
        square_payment_record_id,
        spa_id,
        business_unit_id,
    ))

    return cursor.rowcount


def post_square_income_lines_and_inventory(
    cursor,
    *,
    spa_id,
    business_unit_id,
    income_id,
    square_payment_record_id,
    square_payment_id,
    preview,
    catalog_mapping_details,
):
    """
    Stage Square order lines, post mapped retail inventory
    movements, and link the Square payment to Income.

    The caller owns transaction control.
    """

    staged_lines = stage_square_payment_line_items(
        cursor,
        spa_id=spa_id,
        business_unit_id=business_unit_id,
        square_payment_record_id=square_payment_record_id,
        preview=preview,
        catalog_mapping_details=catalog_mapping_details,
    )

    for staged_line in staged_lines:
        line = staged_line["line"]
        mapping = staged_line["mapping"]
        retail_inventory_candidate = staged_line[
            "retail_inventory_candidate"
        ]
        inventory_quantity = staged_line[
            "inventory_quantity"
        ]
        square_payment_line_item_id = staged_line[
            "square_payment_line_item_id"
        ]
        existing_inventory_movement_id = staged_line[
            "existing_inventory_movement_id"
        ]

        if (
            retail_inventory_candidate
            and inventory_quantity is not None
            and existing_inventory_movement_id
                is None
        ):
            inventory_product_id = (
                mapping[
                    "inventory_product_id"
                ]
            )

            cursor.execute("""
                SELECT
                    product_id,
                    product_name
                FROM inventory_products
                WHERE product_id = %s
                  AND spa_id = %s
                  AND business_unit_id = %s
                  AND active = TRUE
                LIMIT 1
            """, (
                inventory_product_id,
                spa_id,
                business_unit_id,
            ))

            inventory_product = (
                cursor.fetchone()
            )

            if inventory_product:
                cursor.execute("""
                    INSERT INTO inventory_movements (
                        spa_id,
                        business_unit_id,
                        product_id,
                        movement_type,
                        quantity,
                        note,
                        income_id
                    )
                    VALUES (
                        %s, %s, %s,
                        'sold',
                        %s, %s, %s
                    )
                    RETURNING movement_id
                """, (
                    spa_id,
                    business_unit_id,
                    inventory_product_id,
                    inventory_quantity,
                    (
                        "Square sale — "
                        f"{line.get('name') or inventory_product[1]} "
                        "— Payment "
                        f"{square_payment_id}"
                    ),
                    income_id,
                ))

                inventory_movement_id = (
                    cursor.fetchone()[0]
                )

                cursor.execute("""
                    UPDATE square_payment_line_items
                    SET
                        inventory_movement_id = %s,
                        reconciliation_status = 'posted',
                        updated_at = CURRENT_TIMESTAMP
                    WHERE square_payment_line_item_id = %s
                      AND spa_id = %s
                      AND business_unit_id = %s
                      AND inventory_movement_id IS NULL
                """, (
                    inventory_movement_id,
                    square_payment_line_item_id,
                    spa_id,
                    business_unit_id,
                ))

                if cursor.rowcount != 1:
                    raise SquareInventoryLinkError(
                        "Square inventory movement "
                        "could not be linked to its "
                        "payment line."
                    )

            else:
                cursor.execute("""
                    UPDATE square_payment_line_items
                    SET
                        reconciliation_status = 'review',
                        updated_at = CURRENT_TIMESTAMP
                    WHERE square_payment_line_item_id = %s
                      AND spa_id = %s
                      AND business_unit_id = %s
                """, (
                    square_payment_line_item_id,
                    spa_id,
                    business_unit_id,
                ))

    # Financial reconciliation is complete even when one or
    # more catalog/inventory lines still require review.
    finalize_square_payment_income_link(
        cursor,
        spa_id=spa_id,
        business_unit_id=business_unit_id,
        income_id=income_id,
        square_payment_record_id=(
            square_payment_record_id
        ),
    )
