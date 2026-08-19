from datetime import datetime, timezone
from zoneinfo import ZoneInfo

from psycopg2.extras import Json

from services.square_income_posting import (
    post_square_income_lines_and_inventory,
)


class SquareRetailProcessingError(Exception):
    """Raised when a Square retail payment cannot be posted safely."""


def _square_payment_income_date(
    cursor,
    *,
    spa_id,
    created_at,
):
    """
    Convert Square RFC-3339 created_at into the spa's local
    calendar date using the same UTC -> spa timezone rule as
    Add Income.
    """

    value = str(created_at or "").strip()

    if not value:
        raise SquareRetailProcessingError(
            "Square payment date is unavailable."
        )

    try:
        parsed = datetime.fromisoformat(
            value.replace("Z", "+00:00")
        )
    except ValueError as exc:
        raise SquareRetailProcessingError(
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
    Resolve Sold To only through an existing active Square
    customer mapping in this exact PSP workspace.
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

    Configured rates are metadata only. Actual Square fees
    remain authoritative for this payment.
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
        raise SquareRetailProcessingError(
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


def process_standalone_square_retail(
    cursor,
    *,
    context,
    payment,
    order,
    preview,
    catalog_mapping_details,
):
    """
    Post one authoritative, fully mapped standalone Square
    Retail payment into PSP.

    Transaction ownership stays with the caller. This function
    does not commit or roll back.

    Safe automatic posting requires:
      - exact resolved workspace context
      - COMPLETED Square payment
      - pure Retail preview
      - balanced/ready preview
      - no appointment reservation
      - unique Square payment idempotency boundary
    """

    if not isinstance(context, dict):
        raise SquareRetailProcessingError(
            "Square workspace context is required."
        )

    if not isinstance(payment, dict):
        raise SquareRetailProcessingError(
            "Square payment is required."
        )

    if not isinstance(order, dict):
        raise SquareRetailProcessingError(
            "Square order is required."
        )

    if not isinstance(preview, dict):
        raise SquareRetailProcessingError(
            "Square Income preview is required."
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
        raise SquareRetailProcessingError(
            "Square workspace context is incomplete."
        )

    if environment not in {
        "sandbox",
        "production",
    }:
        raise SquareRetailProcessingError(
            "Square environment is invalid."
        )

    if not square_payment_id:
        raise SquareRetailProcessingError(
            "Square payment ID is unavailable."
        )

    if not square_order_id:
        raise SquareRetailProcessingError(
            "Square order ID is unavailable."
        )

    if (
        str(
            preview.get("status") or ""
        ).strip().upper()
        != "COMPLETED"
    ):
        raise SquareRetailProcessingError(
            "Only completed Square payments can "
            "be posted automatically."
        )

    if preview.get("income_type") != "Retail":
        raise SquareRetailProcessingError(
            "Automatic posting is limited to pure "
            "Retail payments."
        )

    if preview.get("ready_for_income") is not True:
        raise SquareRetailProcessingError(
            "Square Retail payment requires review."
        )

    if preview.get("requires_review"):
        raise SquareRetailProcessingError(
            "Square Retail payment requires review."
        )

    if int(
        preview.get("service_amount_cents") or 0
    ) != 0:
        raise SquareRetailProcessingError(
            "Service amounts cannot be auto-posted "
            "as standalone Retail."
        )

    if int(
        preview.get("retail_amount_cents") or 0
    ) <= 0:
        raise SquareRetailProcessingError(
            "Square Retail amount must be positive."
        )

    if int(
        preview.get("difference_cents") or 0
    ) != 0:
        raise SquareRetailProcessingError(
            "Square Retail totals do not balance."
        )

    if int(
        preview.get("refunded_amount_cents") or 0
    ) != 0:
        raise SquareRetailProcessingError(
            "Refunded Square payments require review."
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

    match_method = "automatic_retail"

    match_notes = (
        "Automatically reconciled from a completed "
        "standalone Square Retail payment using active "
        "workspace catalog mappings."
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
        int(
            preview.get("total_amount_cents")
            or 0
        ),
        int(
            preview.get("service_amount_cents")
            or 0
        ),
        int(
            preview.get("retail_amount_cents")
            or 0
        ),
        int(
            preview.get("tax_amount_cents")
            or 0
        ),
        int(
            preview.get("tip_amount_cents")
            or 0
        ),
        order_discount_cents,
        int(
            preview.get("processing_fee_cents")
            or 0
        ),
        int(
            preview.get("refunded_amount_cents")
            or 0
        ),
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
        # A previous or concurrent request already owns the
        # Square idempotency reservation. Lock it and verify
        # that it is safe to continue.
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
            raise SquareRetailProcessingError(
                "Square payment could not be reserved."
            )

        if (
            existing_row[1] != spa_id
            or existing_row[2]
                != business_unit_id
        ):
            raise SquareRetailProcessingError(
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
            return {
                "status": "already_reconciled",
                "square_payment_record_id":
                    existing_row[0],
                "income_id": existing_row[3],
                "square_payment_id":
                    square_payment_id,
            }

        if existing_row[4] is not None:
            raise SquareRetailProcessingError(
                "Square payment is reserved to an "
                "appointment and cannot be auto-posted "
                "as standalone Retail."
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
            int(
                preview.get("total_amount_cents")
                or 0
            ),
            int(
                preview.get("service_amount_cents")
                or 0
            ),
            int(
                preview.get("retail_amount_cents")
                or 0
            ),
            int(
                preview.get("tax_amount_cents")
                or 0
            ),
            int(
                preview.get("tip_amount_cents")
                or 0
            ),
            order_discount_cents,
            int(
                preview.get("processing_fee_cents")
                or 0
            ),
            int(
                preview.get("refunded_amount_cents")
                or 0
            ),
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
            raise SquareRetailProcessingError(
                "Square payment reservation changed "
                "before Retail posting."
            )

    # -------------------------------------------------
    # Create appointment-free PSP Income.
    # -------------------------------------------------

    service_amount = round(
        int(
            preview.get("service_amount_cents")
            or 0
        ) / 100,
        2,
    )

    retail_amount = round(
        int(
            preview.get("retail_amount_cents")
            or 0
        ) / 100,
        2,
    )

    tax_amount = round(
        int(
            preview.get("tax_amount_cents")
            or 0
        ) / 100,
        2,
    )

    tip_amount = round(
        int(
            preview.get("tip_amount_cents")
            or 0
        ) / 100,
        2,
    )

    total_amount = round(
        int(
            preview.get("total_amount_cents")
            or 0
        ) / 100,
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
            %s, %s, NULL, NULL, 'Retail',
            %s, %s, %s, %s, %s,
            %s, 'Square', %s, %s, %s,
            %s, NULL, %s, %s, %s,
            %s, %s, %s,
            CURRENT_TIMESTAMP
        )
        RETURNING income_id
    """, (
        income_date,
        mapped_client_id,
        "Square Retail Sale",
        service_amount,
        retail_amount,
        tax_amount,
        tip_amount,
        total_amount,
        square_payment_id,
        (
            "Automatically imported from Square "
            "standalone Retail payment."
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
    # Stage Square lines, decrement mapped inventory,
    # and link the reserved Square payment to Income.
    # -------------------------------------------------

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

    return {
        "status": "posted",
        "square_payment_record_id":
            square_payment_record_id,
        "square_payment_id":
            square_payment_id,
        "income_id": income_id,
        "client_id": mapped_client_id,
        "income_date": income_date,
        "retail_amount": retail_amount,
        "tax_amount": tax_amount,
        "processing_fee_amount":
            processing_fee_amount,
        "net_received": net_received,
    }
