from services import square_oauth
from services import square_service


class SquarePaymentContextError(Exception):
    """Raised when a Square payment workspace cannot be resolved safely."""


def load_square_payment_context(
    cursor,
    *,
    square_connection_id,
    spa_id,
    business_unit_id,
    environment,
    square_location_id,
):
    """
    Resolve the exact connected Square workspace/location and
    access token used for authoritative payment retrieval.

    No default workspace or location is inferred.
    """

    environment = str(
        environment or ""
    ).strip().lower()

    square_location_id = str(
        square_location_id or ""
    ).strip()

    if environment not in {
        "sandbox",
        "production",
    }:
        raise SquarePaymentContextError(
            "Square payment environment is invalid."
        )

    if not square_connection_id:
        raise SquarePaymentContextError(
            "Square connection is required."
        )

    if not spa_id or not business_unit_id:
        raise SquarePaymentContextError(
            "Square payment workspace is required."
        )

    if not square_location_id:
        raise SquarePaymentContextError(
            "Square payment location is required."
        )

    cursor.execute("""
        SELECT
            sc.square_connection_id,
            sc.merchant_id,
            sc.oauth_access_token_ciphertext,
            sl.square_location_id
        FROM square_connections sc
        JOIN square_locations sl
          ON sl.square_connection_id =
                sc.square_connection_id
         AND sl.spa_id = sc.spa_id
         AND sl.business_unit_id =
                sc.business_unit_id
         AND sl.environment = sc.environment
        WHERE sc.square_connection_id = %s
          AND sc.spa_id = %s
          AND sc.business_unit_id = %s
          AND sc.environment = %s
          AND sc.connection_status = 'connected'
          AND sl.square_location_id = %s
          AND sl.is_active = TRUE
        LIMIT 1
    """, (
        square_connection_id,
        spa_id,
        business_unit_id,
        environment,
        square_location_id,
    ))

    row = cursor.fetchone()

    if not row:
        raise SquarePaymentContextError(
            "Square connection/location does not belong "
            "to this Provider Workspace."
        )

    (
        resolved_connection_id,
        merchant_id,
        oauth_access_token_ciphertext,
        resolved_location_id,
    ) = row

    try:
        if environment == "production":
            if not oauth_access_token_ciphertext:
                raise SquarePaymentContextError(
                    "Connected Square Production account "
                    "does not have an access token."
                )

            access_token = square_oauth.decrypt_token(
                oauth_access_token_ciphertext,
                spa_id=spa_id,
                business_unit_id=business_unit_id,
                environment="production",
                token_kind="access",
            )

        else:
            access_token = (
                square_service
                .get_square_sandbox_access_token()
            )

    except square_oauth.SquareOAuthError as exc:
        raise SquarePaymentContextError(
            "Square access token could not be resolved."
        ) from exc

    if not access_token:
        raise SquarePaymentContextError(
            "Square access token is unavailable."
        )

    return {
        "square_connection_id":
            resolved_connection_id,
        "spa_id": spa_id,
        "business_unit_id":
            business_unit_id,
        "environment": environment,
        "merchant_id": str(
            merchant_id or ""
        ).strip() or None,
        "square_location_id": str(
            resolved_location_id or ""
        ).strip(),
        "access_token": access_token,
    }


class SquarePaymentRetrievalError(Exception):
    """Raised when a Square payment/order cannot be validated safely."""


def retrieve_authoritative_payment_order(
    *,
    context,
    square_payment_id,
):
    """
    Retrieve the authoritative Square payment and order for an
    already-resolved PSP workspace.

    The payment must be completed and both the payment and order
    must belong to the exact Square merchant/location in context.
    """

    if not isinstance(context, dict):
        raise SquarePaymentRetrievalError(
            "Square payment context is required."
        )

    payment_id = str(
        square_payment_id or ""
    ).strip()

    if not payment_id:
        raise SquarePaymentRetrievalError(
            "Square payment ID is required."
        )

    environment = str(
        context.get("environment") or ""
    ).strip().lower()

    access_token = context.get("access_token")

    expected_merchant_id = str(
        context.get("merchant_id") or ""
    ).strip()

    expected_location_id = str(
        context.get("square_location_id") or ""
    ).strip()

    if environment not in {
        "sandbox",
        "production",
    }:
        raise SquarePaymentRetrievalError(
            "Square payment environment is invalid."
        )

    if not access_token:
        raise SquarePaymentRetrievalError(
            "Square access token is unavailable."
        )

    if not expected_merchant_id:
        raise SquarePaymentRetrievalError(
            "Square merchant ID is unavailable."
        )

    if not expected_location_id:
        raise SquarePaymentRetrievalError(
            "Square location ID is unavailable."
        )

    try:
        payment = square_service.retrieve_payment(
            payment_id,
            access_token=access_token,
            environment=environment,
        )
    except (
        square_service.SquareServiceError,
        ValueError,
    ) as exc:
        raise SquarePaymentRetrievalError(
            "Square payment could not be retrieved."
        ) from exc

    returned_payment_id = str(
        payment.get("id") or ""
    ).strip()

    if returned_payment_id != payment_id:
        raise SquarePaymentRetrievalError(
            "Square returned an unexpected payment."
        )

    if str(
        payment.get("status") or ""
    ).strip().upper() != "COMPLETED":
        raise SquarePaymentRetrievalError(
            "Square payment is not completed."
        )

    payment_merchant_id = str(
        payment.get("merchant_id") or ""
    ).strip()

    if (
        expected_merchant_id
        and payment_merchant_id
        and payment_merchant_id != expected_merchant_id
    ):
        raise SquarePaymentRetrievalError(
            "Square payment merchant does not match "
            "the Provider Workspace."
        )

    payment_location_id = str(
        payment.get("location_id") or ""
    ).strip()

    if payment_location_id != expected_location_id:
        raise SquarePaymentRetrievalError(
            "Square payment location does not match "
            "the Provider Workspace."
        )

    order_id = str(
        payment.get("order_id") or ""
    ).strip()

    if not order_id:
        raise SquarePaymentRetrievalError(
            "Completed Square payment does not have an order."
        )

    try:
        order = square_service.retrieve_order(
            order_id,
            access_token=access_token,
            environment=environment,
        )
    except (
        square_service.SquareServiceError,
        ValueError,
    ) as exc:
        raise SquarePaymentRetrievalError(
            "Square order could not be retrieved."
        ) from exc

    returned_order_id = str(
        order.get("id") or ""
    ).strip()

    if returned_order_id != order_id:
        raise SquarePaymentRetrievalError(
            "Square returned an unexpected order."
        )

    order_location_id = str(
        order.get("location_id") or ""
    ).strip()

    if (
        order_location_id
        and order_location_id != expected_location_id
    ):
        raise SquarePaymentRetrievalError(
            "Square order location does not match "
            "the Provider Workspace."
        )

    return {
        "payment": payment,
        "order": order,
        "square_payment_id": payment_id,
        "square_order_id": order_id,
    }
