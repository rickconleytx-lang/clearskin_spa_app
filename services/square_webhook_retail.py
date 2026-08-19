from services import square_service
from services.square_catalog_context import (
    load_square_catalog_mappings,
)
from services.square_payment_context import (
    load_square_payment_context,
    retrieve_authoritative_payment_order,
)
from services.square_retail_processing import (
    process_standalone_square_retail,
)


class SquareWebhookRetailError(Exception):
    """Raised when a recorded Square event cannot be processed safely."""


def _get_db_connection():
    """
    Import lazily so this service does not create an
    app/service circular import while app.py is loading.
    """
    from app import get_db_connection
    return get_db_connection()


def _set_event_status(
    cursor,
    *,
    square_webhook_event_id,
    processing_status,
    error_message=None,
):
    cursor.execute("""
        UPDATE square_webhook_events
        SET
            processing_status = %s,
            error_message = %s
        WHERE square_webhook_event_id = %s
    """, (
        processing_status,
        error_message,
        square_webhook_event_id,
    ))

    if cursor.rowcount != 1:
        raise SquareWebhookRetailError(
            "Square webhook event status could not be updated."
        )


def process_recorded_square_retail_event(
    square_webhook_event_id,
    *,
    connection=None,
):
    """
    Process one already-authenticated and already-recorded
    Square webhook event.

    Only a routed payment.updated event with an authoritative,
    completed, fully mapped pure Retail payment is eligible
    for automatic Income + inventory posting.

    Non-Retail, mixed, unmapped, or otherwise review-required
    payments are intentionally left out of automatic posting.

    The Square payment idempotency boundary protects Income
    and inventory from duplicate webhook/payment delivery.
    """

    if not square_webhook_event_id:
        raise SquareWebhookRetailError(
            "Square webhook event ID is required."
        )

    owns_connection = connection is None

    if owns_connection:
        connection = _get_db_connection()

    conn = connection
    cur = conn.cursor()

    try:
        # -------------------------------------------------
        # Lock and claim this recorded event.
        # -------------------------------------------------

        cur.execute("""
            SELECT
                environment,
                event_type,
                square_payment_id,
                square_location_id,
                square_connection_id,
                spa_id,
                business_unit_id,
                routing_status,
                processing_status,
                processing_attempts
            FROM square_webhook_events
            WHERE square_webhook_event_id = %s
            FOR UPDATE
        """, (
            square_webhook_event_id,
        ))

        row = cur.fetchone()

        if not row:
            raise SquareWebhookRetailError(
                "Recorded Square webhook event was not found."
            )

        (
            environment,
            event_type,
            square_payment_id,
            square_location_id,
            square_connection_id,
            spa_id,
            business_unit_id,
            routing_status,
            processing_status,
            processing_attempts,
        ) = row

        environment = str(
            environment or ""
        ).strip().lower()

        event_type = str(
            event_type or ""
        ).strip()

        routing_status = str(
            routing_status or ""
        ).strip().lower()

        processing_status = str(
            processing_status or ""
        ).strip().lower()

        # Terminal event states are safe no-ops on duplicate
        # Square event delivery.
        if processing_status in {
            "processed",
            "ignored",
        }:
            if owns_connection:
                conn.commit()

            return {
                "status": processing_status,
                "square_webhook_event_id":
                    square_webhook_event_id,
                "duplicate_processing": True,
            }

        ignore_reason = None

        if routing_status != "routed":
            ignore_reason = (
                "Automatic Retail skipped: Square event "
                "did not resolve to one PSP workspace."
            )

        elif event_type != "payment.updated":
            ignore_reason = (
                "Automatic Retail skipped: event type "
                "is not payment.updated."
            )

        elif not square_payment_id:
            ignore_reason = (
                "Automatic Retail skipped: payment ID "
                "is unavailable."
            )

        elif (
            not square_connection_id
            or not spa_id
            or not business_unit_id
        ):
            ignore_reason = (
                "Automatic Retail skipped: routed PSP "
                "workspace context is incomplete."
            )

        elif not square_location_id:
            ignore_reason = (
                "Automatic Retail skipped: Square "
                "location is unavailable."
            )

        if ignore_reason:
            cur.execute("""
                UPDATE square_webhook_events
                SET
                    processing_status = 'ignored',
                    processing_attempts =
                        processing_attempts + 1,
                    error_message = %s
                WHERE square_webhook_event_id = %s
            """, (
                ignore_reason,
                square_webhook_event_id,
            ))

            if cur.rowcount != 1:
                raise SquareWebhookRetailError(
                    "Square webhook event could not "
                    "be marked ignored."
                )

            if owns_connection:
                conn.commit()

            return {
                "status": "ignored",
                "square_webhook_event_id":
                    square_webhook_event_id,
                "reason": ignore_reason,
            }

        cur.execute("""
            UPDATE square_webhook_events
            SET
                processing_status = 'processing',
                processing_attempts =
                    processing_attempts + 1,
                error_message = NULL
            WHERE square_webhook_event_id = %s
              AND processing_status IN (
                    'received',
                    'error',
                    'processing'
              )
        """, (
            square_webhook_event_id,
        ))

        if cur.rowcount != 1:
            raise SquareWebhookRetailError(
                "Square webhook event could not be claimed."
            )

        # Keep the processing claim in this transaction.
        # The FOR UPDATE lock prevents competing processors,
        # while a worker/database failure rolls the claim
        # back instead of stranding the event in processing.

        # -------------------------------------------------
        # Resolve exact PSP/Square context and retrieve the
        # authoritative current payment + order.
        # -------------------------------------------------

        context = load_square_payment_context(
            cur,
            square_connection_id=(
                square_connection_id
            ),
            spa_id=spa_id,
            business_unit_id=business_unit_id,
            environment=environment,
            square_location_id=(
                square_location_id
            ),
        )

        authoritative = (
            retrieve_authoritative_payment_order(
                context=context,
                square_payment_id=(
                    square_payment_id
                ),
            )
        )

        payment = authoritative["payment"]
        order = authoritative["order"]

        mappings = load_square_catalog_mappings(
            cur,
            square_connection_id=(
                square_connection_id
            ),
            spa_id=spa_id,
            business_unit_id=business_unit_id,
            environment=environment,
        )

        preview = square_service.build_income_preview(
            payment,
            order,
            catalog_classifications=(
                mappings[
                    "catalog_classifications"
                ]
            ),
            line_classifications={},
        )

        # -------------------------------------------------
        # Automatic posting is intentionally limited to
        # fully mapped, balanced, pure Retail.
        #
        # Service, mixed, unknown, refunded, and other
        # review-required payments remain outside automatic
        # standalone Retail posting.
        # -------------------------------------------------

        if (
            preview.get("income_type") != "Retail"
            or preview.get("ready_for_income")
                is not True
            or preview.get("requires_review")
        ):
            reason = (
                "Automatic Retail skipped: authoritative "
                "Square payment is not a fully mapped, "
                "balanced pure Retail payment."
            )

            _set_event_status(
                cur,
                square_webhook_event_id=(
                    square_webhook_event_id
                ),
                processing_status="ignored",
                error_message=reason,
            )

            if owns_connection:
                conn.commit()

            return {
                "status": "ignored",
                "square_webhook_event_id":
                    square_webhook_event_id,
                "reason": reason,
                "income_type":
                    preview.get("income_type"),
                "requires_review":
                    bool(
                        preview.get(
                            "requires_review"
                        )
                    ),
            }

        # -------------------------------------------------
        # Post Income + Square lines + mapped inventory in
        # one DB transaction.
        # -------------------------------------------------

        retail_result = (
            process_standalone_square_retail(
                cur,
                context=context,
                payment=payment,
                order=order,
                preview=preview,
                catalog_mapping_details=(
                    mappings[
                        "catalog_mapping_details"
                    ]
                ),
            )
        )

        _set_event_status(
            cur,
            square_webhook_event_id=(
                square_webhook_event_id
            ),
            processing_status="processed",
            error_message=None,
        )

        if owns_connection:
            conn.commit()

        return {
            "status": "processed",
            "square_webhook_event_id":
                square_webhook_event_id,
            "retail_result": retail_result,
        }

    except Exception as error:
        if owns_connection:
            conn.rollback()

        # The event was already durably recorded by the
        # authenticated webhook layer. Preserve the failure
        # so a later duplicate/retry can attempt it again.
        if owns_connection:
            try:
                cur.execute("""
                UPDATE square_webhook_events
                SET
                    processing_status = 'error',
                    error_message = %s
                WHERE square_webhook_event_id = %s
                  AND processing_status NOT IN (
                        'processed',
                        'ignored'
                  )
            """, (
                str(error)[:1000],
                square_webhook_event_id,
            ))

                conn.commit()

            except Exception:
                conn.rollback()

        raise

    finally:
        cur.close()

        if owns_connection:
            conn.close()
