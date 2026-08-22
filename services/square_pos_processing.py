from datetime import datetime, timezone
from zoneinfo import ZoneInfo

from psycopg2.extras import Json

from services.square_income_posting import (
    finalize_square_payment_income_link,
    ignore_square_payment_line_items,
    post_square_income_lines_and_inventory,
    stage_square_payment_line_items,
)


class SquarePosProcessingError(Exception):
    """Raised when a PeachPOS Square payment cannot be posted safely."""


def _square_payment_income_date(
    cursor,
    *,
    spa_id,
    created_at,
):
    """
    Convert Square RFC-3339 created_at into the spa's local
    calendar date using the established Add Income rule.
    """

    value = str(created_at or "").strip()

    if not value:
        raise SquarePosProcessingError(
            "Square payment date is unavailable."
        )

    try:
        parsed = datetime.fromisoformat(
            value.replace("Z", "+00:00")
        )
    except ValueError as exc:
        raise SquarePosProcessingError(
            "Square payment date is invalid."
        ) from exc

    if parsed.tzinfo is None:
        parsed = parsed.replace(
            tzinfo=timezone.utc
        )

    cursor.execute("""
        SELECT timezone_name
        FROM spas
        WHERE spa_id = %s
        LIMIT 1
    """, (spa_id,))

    row = cursor.fetchone()

    timezone_name = (
        str(row[0] or "").strip()
        if row
        else ""
    ) or "UTC"

    try:
        spa_zone = ZoneInfo(timezone_name)
    except Exception:
        spa_zone = ZoneInfo("UTC")

    return parsed.astimezone(
        spa_zone
    ).date()


def _mapped_square_client_id(
    cursor,
    *,
    square_connection_id,
    spa_id,
    business_unit_id,
    environment,
    square_customer_id,
):
    """
    Resolve an optional PSP client only through an existing
    active Square customer mapping in this exact workspace.
    """

    customer_id = str(
        square_customer_id or ""
    ).strip()

    if not customer_id:
        return None

    cursor.execute("""
        SELECT scm.client_id
        FROM square_customer_mappings scm
        JOIN clients c
          ON c.client_id = scm.client_id
         AND c.spa_id = scm.spa_id
         AND c.business_unit_id =
                scm.business_unit_id
        WHERE scm.square_connection_id = %s
          AND scm.spa_id = %s
          AND scm.business_unit_id = %s
          AND scm.environment = %s
          AND scm.square_customer_id = %s
          AND scm.is_active = TRUE
        ORDER BY
            scm.verified_at DESC NULLS LAST,
            scm.square_customer_mapping_id DESC
        LIMIT 1
    """, (
        square_connection_id,
        spa_id,
        business_unit_id,
        environment,
        customer_id,
    ))

    row = cursor.fetchone()

    return row[0] if row else None


def _square_credit_processor(
    cursor,
    *,
    spa_id,
):
    """
    Match the established Add Income Square processor rule.

    Configured rates remain metadata only. Actual Square fees
    from the authoritative payment remain authoritative.
    """

    cursor.execute("""
        SELECT
            credit_processor_id,
            percentage_fee,
            flat_fee,
            additional_fee
        FROM credit_processors
        WHERE spa_id = %s
          AND LOWER(
                credit_processor_name
              ) = 'square'
          AND is_active = TRUE
        ORDER BY credit_processor_id
        LIMIT 1
    """, (spa_id,))

    row = cursor.fetchone()

    if not row:
        raise SquarePosProcessingError(
            "An active Square credit processor is required."
        )

    return {
        "credit_processor_id": row[0],
        "percentage_fee": float(
            row[1] or 0
        ),
        "flat_fee": float(
            row[2] or 0
        ),
        "additional_fee": float(
            row[3] or 0
        ),
    }


def process_square_pos_payment(
    cursor,
    *,
    context,
    payment,
    order,
    preview,
    catalog_mapping_details,
    track_inventory_sales,
):
    """
    Post one authoritative completed Square payment through
    PeachPOS / POS Daily Sales mode.

    Transaction ownership remains with the caller. This
    function never commits or rolls back.

    Financial posting does not require Square catalog items
    to be classified as PSP Service or Retail. The complete
    pre-tax, pre-tip sale is stored in income.pos_amount.

    Safe automatic posting requires:
      - exact resolved workspace context
      - COMPLETED Square payment
      - balanced Square totals
      - no refund
      - positive pre-tax, pre-tip sales amount
      - no appointment reservation
      - unique Square payment idempotency boundary
    """

    if not isinstance(context, dict):
        raise SquarePosProcessingError(
            "Square workspace context is required."
        )

    if not isinstance(payment, dict):
        raise SquarePosProcessingError(
            "Square payment is required."
        )

    if not isinstance(order, dict):
        raise SquarePosProcessingError(
            "Square order is required."
        )

    if not isinstance(preview, dict):
        raise SquarePosProcessingError(
            "Square Income preview is required."
        )

    if not isinstance(catalog_mapping_details, dict):
        raise SquarePosProcessingError(
            "Square catalog mapping context is required."
        )

    if not isinstance(track_inventory_sales, bool):
        raise SquarePosProcessingError(
            "PeachPOS inventory tracking setting is invalid."
        )

    spa_id = context.get("spa_id")
    business_unit_id = context.get(
        "business_unit_id"
    )
    square_connection_id = context.get(
        "square_connection_id"
    )

    environment = str(
        context.get("environment") or ""
    ).strip().lower()

    square_location_id = str(
        context.get("square_location_id") or ""
    ).strip()

    merchant_id = str(
        context.get("merchant_id") or ""
    ).strip()

    square_payment_id = str(
        payment.get("id") or ""
    ).strip()

    square_order_id = str(
        order.get("id") or ""
    ).strip()

    if (
        not spa_id
        or not business_unit_id
        or not square_connection_id
    ):
        raise SquarePosProcessingError(
            "Square workspace context is incomplete."
        )

    if environment not in {
        "sandbox",
        "production",
    }:
        raise SquarePosProcessingError(
            "Square environment is invalid."
        )

    if not square_payment_id:
        raise SquarePosProcessingError(
            "Square payment ID is unavailable."
        )

    if not square_order_id:
        raise SquarePosProcessingError(
            "Square order ID is unavailable."
        )

    if (
        str(
            preview.get("status") or ""
        ).strip().upper()
        != "COMPLETED"
    ):
        raise SquarePosProcessingError(
            "Only completed Square payments can "
            "be posted through PeachPOS."
        )

    difference_cents = int(
        preview.get("difference_cents") or 0
    )

    if difference_cents != 0:
        raise SquarePosProcessingError(
            "Square PeachPOS payment totals do not balance."
        )

    refunded_amount_cents = int(
        preview.get("refunded_amount_cents") or 0
    )

    if refunded_amount_cents != 0:
        raise SquarePosProcessingError(
            "Refunded Square payments require separate review."
        )

    service_amount_cents = int(
        preview.get("service_amount_cents") or 0
    )
    retail_amount_cents = int(
        preview.get("retail_amount_cents") or 0
    )
    other_amount_cents = int(
        preview.get("other_amount_cents") or 0
    )
    unknown_amount_cents = int(
        preview.get("unknown_amount_cents") or 0
    )

    pos_amount_cents = (
        service_amount_cents
        + retail_amount_cents
        + other_amount_cents
        + unknown_amount_cents
    )

    if pos_amount_cents <= 0:
        raise SquarePosProcessingError(
            "PeachPOS sales amount must be positive."
        )

    tax_amount_cents = int(
        preview.get("tax_amount_cents") or 0
    )
    tip_amount_cents = int(
        preview.get("tip_amount_cents") or 0
    )
    total_amount_cents = int(
        preview.get("total_amount_cents") or 0
    )

    if (
        pos_amount_cents
        + tax_amount_cents
        + tip_amount_cents
        != total_amount_cents
    ):
        raise SquarePosProcessingError(
            "PeachPOS sales components do not match "
            "the authoritative Square payment total."
        )

    if total_amount_cents <= 0:
        raise SquarePosProcessingError(
            "Square PeachPOS payment total must be positive."
        )

    income_date = _square_payment_income_date(
        cursor,
        spa_id=spa_id,
        created_at=preview.get("created_at"),
    )

    mapped_client_id = _mapped_square_client_id(
        cursor,
        square_connection_id=square_connection_id,
        spa_id=spa_id,
        business_unit_id=business_unit_id,
        environment=environment,
        square_customer_id=preview.get(
            "customer_id"
        ),
    )

    processor = _square_credit_processor(
        cursor,
        spa_id=spa_id,
    )

    payment_merchant_id = str(
        payment.get("merchant_id") or ""
    ).strip()

    order_discount_cents = int(
        (
            order.get("total_discount_money")
            or {}
        ).get("amount")
        or 0
    )

    match_method = "automatic_peachpos"

    if track_inventory_sales:
        match_notes = (
            "Automatically reconciled from a completed "
            "Square payment using PeachPOS Daily Sales mode. "
            "Mapped retail inventory lines were processed "
            "through PSP Inventory."
        )
    else:
        match_notes = (
            "Automatically reconciled from a completed "
            "Square payment using PeachPOS Daily Sales mode. "
            "Item-level PSP Inventory tracking was disabled."
        )

    # -------------------------------------------------
    # Reserve the Square payment before inserting Income.
    #
    # Unique (environment, square_payment_id) remains
    # the Square-specific idempotency boundary.
    # -------------------------------------------------

    cursor.execute("""
        INSERT INTO square_payments (
            square_connection_id,
            spa_id,
            business_unit_id,
            environment,
            square_payment_id,
            square_order_id,
            square_customer_id,
            square_location_id,
            merchant_id,
            payment_status,
            tender_type,
            currency,
            amount_cents,
            service_amount_cents,
            retail_amount_cents,
            tax_amount_cents,
            tip_amount_cents,
            discount_amount_cents,
            processing_fee_cents,
            refunded_amount_cents,
            net_received_cents,
            square_created_at,
            square_updated_at,
            appointment_id,
            client_id,
            reconciliation_status,
            match_method,
            match_notes,
            retrieved_at,
            last_synced_at,
            reviewed_by,
            raw_payment,
            raw_order
        )
        VALUES (
            %s, %s, %s, %s, %s,
            %s, %s, %s, %s, %s,
            %s, %s, %s, %s, %s,
            %s, %s, %s, %s, %s,
            %s, %s, %s,
            NULL, %s,
            'matched', %s, %s,
            CURRENT_TIMESTAMP,
            CURRENT_TIMESTAMP,
            NULL, %s, %s
        )
        ON CONFLICT (
            environment,
            square_payment_id
        )
        DO NOTHING
        RETURNING square_payment_record_id
    """, (
        square_connection_id,
        spa_id,
        business_unit_id,
        environment,
        square_payment_id,
        square_order_id,
        preview.get("customer_id"),
        square_location_id,
        payment_merchant_id or merchant_id or None,
        preview.get("status"),
        preview.get("source_type"),
        preview.get("currency"),
        total_amount_cents,
        service_amount_cents,
        retail_amount_cents,
        tax_amount_cents,
        tip_amount_cents,
        order_discount_cents,
        int(
            preview.get("processing_fee_cents")
            or 0
        ),
        refunded_amount_cents,
        int(
            preview.get("net_received_cents")
            or 0
        ),
        preview.get("created_at"),
        payment.get("updated_at"),
        mapped_client_id,
        match_method,
        match_notes,
        Json(payment),
        Json(order),
    ))

    inserted_row = cursor.fetchone()

    if inserted_row:
        square_payment_record_id = (
            inserted_row[0]
        )

    else:
        cursor.execute("""
            SELECT
                square_payment_record_id,
                spa_id,
                business_unit_id,
                income_id,
                appointment_id,
                reconciliation_status
            FROM square_payments
            WHERE environment = %s
              AND square_payment_id = %s
            FOR UPDATE
        """, (
            environment,
            square_payment_id,
        ))

        existing_row = cursor.fetchone()

        if not existing_row:
            raise SquarePosProcessingError(
                "Square payment could not be reserved."
            )

        if (
            existing_row[1] != spa_id
            or existing_row[2]
                != business_unit_id
        ):
            raise SquarePosProcessingError(
                "Square payment belongs to another "
                "Provider Workspace."
            )

        if (
            existing_row[3] is not None
            or str(
                existing_row[5] or ""
            ).strip().lower()
                == "reconciled"
        ):
            income_id = existing_row[3]

            if income_id is None:
                return {
                    "status": "already_reconciled",
                    "square_payment_record_id":
                        existing_row[0],
                    "income_id": income_id,
                    "square_payment_id":
                        square_payment_id,
                }

            # Square can attach its final processing fee after
            # the payment first reaches COMPLETED. For an
            # already-posted PeachPOS payment, safely refresh
            # settlement-only fields without creating another
            # Income row.
            cursor.execute("""
                SELECT
                    income_type,
                    pos_amount,
                    tax_amount,
                    tip_amount,
                    total_amount,
                    processor_payment_id
                FROM income
                WHERE income_id = %s
                  AND spa_id = %s
                  AND business_unit_id = %s
                FOR UPDATE
            """, (
                income_id,
                spa_id,
                business_unit_id,
            ))

            income_row = cursor.fetchone()

            if not income_row:
                raise SquarePosProcessingError(
                    "Linked PeachPOS Income could not be found "
                    "in this Provider Workspace."
                )

            if str(
                income_row[0] or ""
            ).strip() != "PeachPOS":
                raise SquarePosProcessingError(
                    "Linked Income is not a PeachPOS posting."
                )

            if str(
                income_row[5] or ""
            ).strip() != square_payment_id:
                raise SquarePosProcessingError(
                    "Linked PeachPOS Income has a different "
                    "Square payment ID."
                )

            existing_pos_cents = int(
                round(float(income_row[1] or 0) * 100)
            )
            existing_tax_cents = int(
                round(float(income_row[2] or 0) * 100)
            )
            existing_tip_cents = int(
                round(float(income_row[3] or 0) * 100)
            )
            existing_total_cents = int(
                round(float(income_row[4] or 0) * 100)
            )

            if (
                existing_pos_cents != pos_amount_cents
                or existing_tax_cents != tax_amount_cents
                or existing_tip_cents != tip_amount_cents
                or existing_total_cents != total_amount_cents
            ):
                raise SquarePosProcessingError(
                    "Authoritative Square sale amounts changed "
                    "after PeachPOS posting; settlement refresh "
                    "was not applied."
                )

            processing_fee_cents = int(
                preview.get("processing_fee_cents") or 0
            )
            net_received_cents = int(
                preview.get("net_received_cents") or 0
            )

            cursor.execute("""
                UPDATE square_payments
                SET
                    processing_fee_cents = %s,
                    net_received_cents = %s,
                    square_updated_at = %s,
                    retrieved_at = CURRENT_TIMESTAMP,
                    last_synced_at = CURRENT_TIMESTAMP,
                    raw_payment = %s,
                    raw_order = %s,
                    updated_at = CURRENT_TIMESTAMP
                WHERE square_payment_record_id = %s
                  AND spa_id = %s
                  AND business_unit_id = %s
                  AND income_id = %s
            """, (
                processing_fee_cents,
                net_received_cents,
                payment.get("updated_at"),
                Json(payment),
                Json(order),
                existing_row[0],
                spa_id,
                business_unit_id,
                income_id,
            ))

            if cursor.rowcount != 1:
                raise SquarePosProcessingError(
                    "PeachPOS Square settlement could not "
                    "be refreshed safely."
                )

            processing_fee_amount = round(
                processing_fee_cents / 100,
                2,
            )
            net_received = round(
                net_received_cents / 100,
                2,
            )

            cursor.execute("""
                UPDATE income
                SET
                    processing_fee_amount = %s,
                    net_received = %s
                WHERE income_id = %s
                  AND spa_id = %s
                  AND business_unit_id = %s
                  AND income_type = 'PeachPOS'
                  AND processor_payment_id = %s
            """, (
                processing_fee_amount,
                net_received,
                income_id,
                spa_id,
                business_unit_id,
                square_payment_id,
            ))

            if cursor.rowcount != 1:
                raise SquarePosProcessingError(
                    "PeachPOS Income settlement could not "
                    "be refreshed safely."
                )

            return {
                "status": "settlement_refreshed",
                "square_payment_record_id":
                    existing_row[0],
                "income_id": income_id,
                "square_payment_id":
                    square_payment_id,
                "processing_fee_amount":
                    processing_fee_amount,
                "net_received": net_received,
            }

        if existing_row[4] is not None:
            raise SquarePosProcessingError(
                "Square payment is reserved to an "
                "appointment and cannot be auto-posted "
                "through PeachPOS."
            )

        square_payment_record_id = (
            existing_row[0]
        )

        cursor.execute("""
            UPDATE square_payments
            SET
                square_connection_id = %s,
                square_order_id = %s,
                square_customer_id = %s,
                square_location_id = %s,
                merchant_id = %s,
                payment_status = %s,
                tender_type = %s,
                currency = %s,
                amount_cents = %s,
                service_amount_cents = %s,
                retail_amount_cents = %s,
                tax_amount_cents = %s,
                tip_amount_cents = %s,
                discount_amount_cents = %s,
                processing_fee_cents = %s,
                refunded_amount_cents = %s,
                net_received_cents = %s,
                square_created_at = %s,
                square_updated_at = %s,
                appointment_id = NULL,
                client_id = %s,
                reconciliation_status = 'matched',
                match_method = %s,
                match_notes = %s,
                retrieved_at = CURRENT_TIMESTAMP,
                last_synced_at = CURRENT_TIMESTAMP,
                reviewed_by = NULL,
                raw_payment = %s,
                raw_order = %s,
                updated_at = CURRENT_TIMESTAMP
            WHERE square_payment_record_id = %s
              AND spa_id = %s
              AND business_unit_id = %s
              AND income_id IS NULL
              AND appointment_id IS NULL
        """, (
            square_connection_id,
            square_order_id,
            preview.get("customer_id"),
            square_location_id,
            payment_merchant_id
            or merchant_id
            or None,
            preview.get("status"),
            preview.get("source_type"),
            preview.get("currency"),
            total_amount_cents,
            service_amount_cents,
            retail_amount_cents,
            tax_amount_cents,
            tip_amount_cents,
            order_discount_cents,
            int(
                preview.get("processing_fee_cents")
                or 0
            ),
            refunded_amount_cents,
            int(
                preview.get("net_received_cents")
                or 0
            ),
            preview.get("created_at"),
            payment.get("updated_at"),
            mapped_client_id,
            match_method,
            match_notes,
            Json(payment),
            Json(order),
            square_payment_record_id,
            spa_id,
            business_unit_id,
        ))

        if cursor.rowcount != 1:
            raise SquarePosProcessingError(
                "Square payment reservation changed "
                "before PeachPOS posting."
            )

    # -------------------------------------------------
    # Create appointment-free PeachPOS Income.
    # -------------------------------------------------

    pos_amount = round(
        pos_amount_cents / 100,
        2,
    )

    tax_amount = round(
        tax_amount_cents / 100,
        2,
    )

    tip_amount = round(
        tip_amount_cents / 100,
        2,
    )

    total_amount = round(
        total_amount_cents / 100,
        2,
    )

    processing_fee_amount = round(
        int(
            preview.get("processing_fee_cents")
            or 0
        ) / 100,
        2,
    )

    net_received = round(
        int(
            preview.get("net_received_cents")
            or 0
        ) / 100,
        2,
    )

    cursor.execute("""
        INSERT INTO income (
            income_date,
            client_id,
            appointment_id,
            visit_id,
            income_type,
            description,
            service_amount,
            retail_amount,
            pos_amount,
            tax_amount,
            tip_amount,
            total_amount,
            payment_method,
            processor_payment_id,
            notes,
            spa_id,
            business_unit_id,
            employee_id,
            credit_processor_id,
            processing_fee_amount,
            net_received,
            processor_percentage_fee,
            processor_flat_fee,
            processor_additional_fee,
            created_at
        )
        VALUES (
            %s, %s, NULL, NULL, 'PeachPOS',
            %s, 0.00, 0.00, %s,
            %s, %s, %s,
            'Square', %s, %s,
            %s, %s, NULL, %s,
            %s, %s, %s, %s, %s,
            CURRENT_TIMESTAMP
        )
        RETURNING income_id
    """, (
        income_date,
        mapped_client_id,
        "PeachPOS Square Sale",
        pos_amount,
        tax_amount,
        tip_amount,
        total_amount,
        square_payment_id,
        (
            "Automatically imported from Square "
            "through PeachPOS Daily Sales mode."
        ),
        spa_id,
        business_unit_id,
        processor["credit_processor_id"],
        processing_fee_amount,
        net_received,
        processor["percentage_fee"],
        processor["flat_fee"],
        processor["additional_fee"],
    ))

    income_id = cursor.fetchone()[0]

    # -------------------------------------------------
    # Item-level handling is independent from PeachPOS
    # financial posting.
    # -------------------------------------------------

    if track_inventory_sales:
        post_square_income_lines_and_inventory(
            cursor,
            spa_id=spa_id,
            business_unit_id=business_unit_id,
            income_id=income_id,
            square_payment_record_id=(
                square_payment_record_id
            ),
            square_payment_id=square_payment_id,
            preview=preview,
            catalog_mapping_details=(
                catalog_mapping_details
            ),
        )

        ignored_line_count = 0

    else:
        # Keep authoritative item detail for audit without
        # creating PSP Inventory movements.
        stage_square_payment_line_items(
            cursor,
            spa_id=spa_id,
            business_unit_id=business_unit_id,
            square_payment_record_id=(
                square_payment_record_id
            ),
            preview=preview,
            catalog_mapping_details=(
                catalog_mapping_details
            ),
        )

        ignored_line_count = (
            ignore_square_payment_line_items(
                cursor,
                spa_id=spa_id,
                business_unit_id=business_unit_id,
                square_payment_record_id=(
                    square_payment_record_id
                ),
            )
        )

        finalize_square_payment_income_link(
            cursor,
            spa_id=spa_id,
            business_unit_id=business_unit_id,
            income_id=income_id,
            square_payment_record_id=(
                square_payment_record_id
            ),
        )

    return {
        "status": "posted",
        "square_payment_record_id":
            square_payment_record_id,
        "square_payment_id":
            square_payment_id,
        "income_id": income_id,
        "client_id": mapped_client_id,
        "income_date": income_date,
        "pos_amount": pos_amount,
        "tax_amount": tax_amount,
        "tip_amount": tip_amount,
        "total_amount": total_amount,
        "processing_fee_amount":
            processing_fee_amount,
        "net_received": net_received,
        "track_inventory_sales":
            track_inventory_sales,
        "ignored_line_count":
            ignored_line_count,
    }
