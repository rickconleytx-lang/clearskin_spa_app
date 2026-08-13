import os
from datetime import datetime, timezone

import requests


class SquareServiceError(RuntimeError):
    """Raised when a Square API request cannot be completed safely."""


SQUARE_BASE_URLS = {
    "sandbox": "https://connect.squareupsandbox.com/v2",
    "production": "https://connect.squareup.com/v2",
}


def normalize_square_environment(environment):
    value = str(environment or "sandbox").strip().lower()

    if value not in SQUARE_BASE_URLS:
        raise ValueError(
            "Square environment must be 'sandbox' or 'production'."
        )

    return value


def get_square_sandbox_access_token():
    token = os.getenv(
        "SQUARE_SANDBOX_ACCESS_TOKEN",
        ""
    ).strip()

    if not token:
        raise ValueError(
            "Missing SQUARE_SANDBOX_ACCESS_TOKEN."
        )

    return token


def _square_headers(access_token):
    token = str(access_token or "").strip()

    if not token:
        raise ValueError(
            "Square access token is required."
        )

    headers = {
        "Authorization": f"Bearer {token}",
        "Accept": "application/json",
        "Content-Type": "application/json",
    }

    api_version = os.getenv(
        "SQUARE_API_VERSION",
        ""
    ).strip()

    if api_version:
        headers["Square-Version"] = api_version

    return headers


def _square_request(
    method,
    path,
    *,
    access_token,
    environment="sandbox",
    params=None,
    json_body=None,
    timeout=20,
):
    environment = normalize_square_environment(
        environment
    )

    if not str(path or "").startswith("/"):
        raise ValueError(
            "Square API path must begin with '/'."
        )

    url = (
        SQUARE_BASE_URLS[environment]
        + path
    )

    try:
        response = requests.request(
            method=method,
            url=url,
            headers=_square_headers(
                access_token
            ),
            params=params,
            json=json_body,
            timeout=timeout,
        )
    except requests.RequestException as exc:
        raise SquareServiceError(
            "Unable to contact Square."
        ) from exc

    try:
        data = response.json()
    except ValueError:
        data = {}

    if not response.ok:
        errors = data.get("errors") or []
        detail = ""

        if errors:
            first_error = errors[0] or {}
            detail = (
                first_error.get("detail")
                or first_error.get("code")
                or ""
            )

        message = (
            f"Square API request failed "
            f"with HTTP {response.status_code}."
        )

        if detail:
            message += f" {detail}"

        raise SquareServiceError(
            message
        )

    return data


def upsert_catalog_object(
    catalog_object,
    *,
    idempotency_key,
    access_token,
    environment="sandbox",
):
    """
    Create or update one Square Catalog object.

    For creation, Square requires the supplied object ID to
    begin with '#'. Square replaces it with a server ID.
    """
    if not isinstance(catalog_object, dict):
        raise ValueError(
            "Square catalog object must be a dictionary."
        )

    idempotency_key = str(
        idempotency_key or ""
    ).strip()

    if not idempotency_key:
        raise ValueError(
            "Square catalog idempotency key is required."
        )

    data = _square_request(
        "POST",
        "/catalog/object",
        access_token=access_token,
        environment=environment,
        json_body={
            "idempotency_key": idempotency_key,
            "object": catalog_object,
        },
    )

    catalog_object_result = data.get(
        "catalog_object"
    )

    if not isinstance(
        catalog_object_result,
        dict
    ):
        raise SquareServiceError(
            "Square did not return the catalog object."
        )

    return {
        "catalog_object": catalog_object_result,
        "id_mappings": data.get("id_mappings") or [],
    }


def retrieve_catalog_object(
    object_id,
    *,
    access_token,
    environment="sandbox",
):
    """
    Retrieve one current Square Catalog object.
    """
    object_id = str(object_id or "").strip()

    if not object_id:
        raise ValueError(
            "Square catalog object ID is required."
        )

    data = _square_request(
        "GET",
        f"/catalog/object/{object_id}",
        access_token=access_token,
        environment=environment,
    )

    catalog_object = data.get("object")

    if not isinstance(catalog_object, dict):
        raise SquareServiceError(
            "Square did not return the catalog object."
        )

    return catalog_object


def delete_catalog_object(
    object_id,
    *,
    access_token,
    environment="sandbox",
):
    """
    Delete one Square Catalog object.
    """
    object_id = str(object_id or "").strip()

    if not object_id:
        raise ValueError(
            "Square catalog object ID is required."
        )

    return _square_request(
        "DELETE",
        f"/catalog/object/{object_id}",
        access_token=access_token,
        environment=environment,
    )


def create_order(
    order,
    *,
    idempotency_key,
    access_token,
    environment="sandbox",
):
    """
    Create one Square Order.
    """
    if not isinstance(order, dict):
        raise ValueError(
            "Square order must be a dictionary."
        )

    idempotency_key = str(
        idempotency_key or ""
    ).strip()

    if not idempotency_key:
        raise ValueError(
            "Square order idempotency key is required."
        )

    data = _square_request(
        "POST",
        "/orders",
        access_token=access_token,
        environment=environment,
        json_body={
            "idempotency_key": idempotency_key,
            "order": order,
        },
    )

    created_order = data.get("order")

    if not isinstance(created_order, dict):
        raise SquareServiceError(
            "Square did not return the created order."
        )

    return created_order


def create_payment(
    *,
    source_id,
    amount_cents,
    idempotency_key,
    access_token,
    environment="sandbox",
    order_id=None,
    location_id=None,
    reference_id=None,
    autocomplete=True,
):
    """
    Create one Square payment.

    amount_cents is expressed in the currency's smallest
    denomination, such as cents for USD.
    """
    source_id = str(source_id or "").strip()

    if not source_id:
        raise ValueError(
            "Square payment source ID is required."
        )

    try:
        amount_cents = int(amount_cents)
    except (TypeError, ValueError):
        raise ValueError(
            "Square payment amount must be an integer."
        )

    if amount_cents <= 0:
        raise ValueError(
            "Square payment amount must be greater than zero."
        )

    idempotency_key = str(
        idempotency_key or ""
    ).strip()

    if not idempotency_key:
        raise ValueError(
            "Square payment idempotency key is required."
        )

    payload = {
        "source_id": source_id,
        "idempotency_key": idempotency_key,
        "amount_money": {
            "amount": amount_cents,
            "currency": "USD",
        },
        "autocomplete": bool(autocomplete),
    }

    order_id = str(order_id or "").strip()

    if order_id:
        payload["order_id"] = order_id

    location_id = str(location_id or "").strip()

    if location_id:
        payload["location_id"] = location_id

    reference_id = str(reference_id or "").strip()

    if reference_id:
        payload["reference_id"] = reference_id

    data = _square_request(
        "POST",
        "/payments",
        access_token=access_token,
        environment=environment,
        json_body=payload,
    )

    payment = data.get("payment")

    if not isinstance(payment, dict):
        raise SquareServiceError(
            "Square did not return the created payment."
        )

    return payment


def create_customer(
    customer,
    *,
    idempotency_key,
    access_token,
    environment="sandbox",
):
    """
    Create one Square Customer profile.
    """
    if not isinstance(customer, dict):
        raise ValueError(
            "Square customer must be a dictionary."
        )

    idempotency_key = str(
        idempotency_key or ""
    ).strip()

    if not idempotency_key:
        raise ValueError(
            "Square customer idempotency key is required."
        )

    payload = dict(customer)
    payload["idempotency_key"] = idempotency_key

    data = _square_request(
        "POST",
        "/customers",
        access_token=access_token,
        environment=environment,
        json_body=payload,
    )

    created_customer = data.get("customer")

    if not isinstance(created_customer, dict):
        raise SquareServiceError(
            "Square did not return the created customer."
        )

    return created_customer


def retrieve_customer(
    customer_id,
    *,
    access_token,
    environment="sandbox",
):
    """
    Retrieve one Square Customer profile.
    """
    customer_id = str(customer_id or "").strip()

    if not customer_id:
        raise ValueError(
            "Square customer ID is required."
        )

    data = _square_request(
        "GET",
        f"/customers/{customer_id}",
        access_token=access_token,
        environment=environment,
    )

    customer = data.get("customer")

    if not isinstance(customer, dict):
        raise SquareServiceError(
            "Square did not return the customer."
        )

    return customer


def update_customer(
    customer_id,
    updates,
    *,
    access_token,
    environment="sandbox",
):
    """
    Update one Square Customer profile.

    Square supports sparse updates. Callers should include
    the current customer version whenever available so
    concurrent updates are not silently overwritten.
    """
    customer_id = str(customer_id or "").strip()

    if not customer_id:
        raise ValueError(
            "Square customer ID is required."
        )

    if not isinstance(updates, dict):
        raise ValueError(
            "Square customer updates must be a dictionary."
        )

    if not updates:
        raise ValueError(
            "Square customer updates cannot be empty."
        )

    data = _square_request(
        "PUT",
        f"/customers/{customer_id}",
        access_token=access_token,
        environment=environment,
        json_body=updates,
    )

    customer = data.get("customer")

    if not isinstance(customer, dict):
        raise SquareServiceError(
            "Square did not return the updated customer."
        )

    return customer


def search_customers(
    query,
    *,
    access_token,
    environment="sandbox",
    limit=100,
    cursor=None,
):
    """
    Search Square Customer profiles using a Square
    SearchCustomers query object.
    """
    if not isinstance(query, dict):
        raise ValueError(
            "Square customer search query must be a dictionary."
        )

    try:
        limit = int(limit)
    except (TypeError, ValueError):
        raise ValueError(
            "Square customer search limit must be an integer."
        )

    if limit < 1 or limit > 100:
        raise ValueError(
            "Square customer search limit must be between 1 and 100."
        )

    payload = {
        "query": query,
        "limit": limit,
    }

    cursor = str(cursor or "").strip()

    if cursor:
        payload["cursor"] = cursor

    data = _square_request(
        "POST",
        "/customers/search",
        access_token=access_token,
        environment=environment,
        json_body=payload,
    )

    customers = data.get("customers") or []

    if not isinstance(customers, list):
        raise SquareServiceError(
            "Square returned an invalid customer search result."
        )

    return {
        "customers": customers,
        "cursor": data.get("cursor"),
    }


def list_recent_payments(
    *,
    access_token,
    location_id=None,
    begin_time=None,
    end_time=None,
    limit=20,
    environment="sandbox",
):
    """
    Retrieve the newest Square payments.

    This function is read-only. It does not write to PSP.
    Times must be RFC 3339 strings when supplied.
    """

    try:
        limit = int(limit)
    except (TypeError, ValueError):
        raise ValueError(
            "Square payment limit must be an integer."
        )

    if limit < 1 or limit > 100:
        raise ValueError(
            "Square payment limit must be between 1 and 100."
        )

    params = {
        "sort_order": "DESC",
        "limit": limit,
    }

    if location_id:
        params["location_id"] = (
            str(location_id).strip()
        )

    if begin_time:
        params["begin_time"] = (
            str(begin_time).strip()
        )

    if end_time:
        params["end_time"] = (
            str(end_time).strip()
        )

    data = _square_request(
        "GET",
        "/payments",
        access_token=access_token,
        environment=environment,
        params=params,
    )

    return data.get("payments") or []


def retrieve_payment(
    square_payment_id,
    *,
    access_token,
    environment="sandbox",
):
    payment_id = str(
        square_payment_id or ""
    ).strip()

    if not payment_id:
        raise ValueError(
            "Square payment ID is required."
        )

    data = _square_request(
        "GET",
        f"/payments/{payment_id}",
        access_token=access_token,
        environment=environment,
    )

    payment = data.get("payment")

    if not payment:
        raise SquareServiceError(
            "Square returned no payment record."
        )

    return payment


def retrieve_order(
    square_order_id,
    *,
    access_token,
    environment="sandbox",
):
    order_id = str(
        square_order_id or ""
    ).strip()

    if not order_id:
        raise ValueError(
            "Square order ID is required."
        )

    data = _square_request(
        "GET",
        f"/orders/{order_id}",
        access_token=access_token,
        environment=environment,
    )

    order = data.get("order")

    if not order:
        raise SquareServiceError(
            "Square returned no order record."
        )

    return order


def utc_rfc3339_now():
    return (
        datetime.now(timezone.utc)
        .isoformat()
        .replace("+00:00", "Z")
    )


def _money_cents(money):
    if not isinstance(money, dict):
        return 0

    amount = money.get("amount")

    try:
        return int(amount or 0)
    except (TypeError, ValueError):
        return 0


def _normalize_line_classification(value):
    classification = str(
        value or "unknown"
    ).strip().lower()

    allowed = {
        "service",
        "retail",
        "other",
        "unknown",
    }

    if classification not in allowed:
        return "unknown"

    return classification


def build_income_preview(
    payment,
    order,
    *,
    catalog_classifications=None,
    line_classifications=None,
):
    """
    Convert retrieved Square Payment + Order objects into a
    conservative PSP Add Income preview.

    Classification is never guessed from a Square item name.

    Persistent catalog mappings can classify a line by its
    Square catalog object ID. A user-review workflow can also
    explicitly classify an individual Square order-line UID.
    """

    if not isinstance(payment, dict):
        raise ValueError(
            "Square payment must be a dictionary."
        )

    if not isinstance(order, dict):
        raise ValueError(
            "Square order must be a dictionary."
        )

    payment_id = str(
        payment.get("id") or ""
    ).strip()

    if not payment_id:
        raise ValueError(
            "Square payment is missing its ID."
        )

    payment_order_id = str(
        payment.get("order_id") or ""
    ).strip()

    order_id = str(
        order.get("id") or ""
    ).strip()

    if (
        payment_order_id
        and order_id
        and payment_order_id != order_id
    ):
        raise ValueError(
            "Square payment and order IDs do not match."
        )

    catalog_classifications = (
        catalog_classifications or {}
    )

    line_classifications = (
        line_classifications or {}
    )

    service_cents = 0
    retail_cents = 0
    other_cents = 0
    unknown_cents = 0

    normalized_lines = []

    for sequence, item in enumerate(
        order.get("line_items") or [],
        start=1,
    ):
        line_uid = str(
            item.get("uid") or ""
        ).strip()

        catalog_object_id = str(
            item.get("catalog_object_id") or ""
        ).strip()

        classification = None

        if line_uid:
            classification = (
                line_classifications.get(
                    line_uid
                )
            )

        if (
            classification is None
            and catalog_object_id
        ):
            classification = (
                catalog_classifications.get(
                    catalog_object_id
                )
            )

        classification = (
            _normalize_line_classification(
                classification
            )
        )

        line_tax_cents = _money_cents(
            item.get("total_tax_money")
        )

        line_total_cents = _money_cents(
            item.get("total_money")
        )

        if line_total_cents:
            sale_cents = (
                line_total_cents
                - line_tax_cents
            )
        else:
            gross_cents = _money_cents(
                item.get("gross_sales_money")
            )
            discount_cents = _money_cents(
                item.get(
                    "total_discount_money"
                )
            )

            sale_cents = (
                gross_cents
                - discount_cents
            )

        sale_cents = max(
            sale_cents,
            0
        )

        if classification == "service":
            service_cents += sale_cents
        elif classification == "retail":
            retail_cents += sale_cents
        elif classification == "other":
            other_cents += sale_cents
        else:
            unknown_cents += sale_cents

        normalized_lines.append({
            "sequence": sequence,
            "line_uid": line_uid or None,
            "catalog_object_id": (
                catalog_object_id or None
            ),
            "name": item.get("name"),
            "variation_name": item.get(
                "variation_name"
            ),
            "quantity": item.get("quantity"),
            "classification": classification,
            "sale_cents": sale_cents,
            "tax_cents": line_tax_cents,
            "total_cents": line_total_cents,
            "raw": item,
        })

    tax_cents = _money_cents(
        order.get("total_tax_money")
    )

    tip_cents = _money_cents(
        payment.get("tip_money")
    )

    amount_before_tip_cents = _money_cents(
        payment.get("amount_money")
    )

    total_cents = _money_cents(
        payment.get("total_money")
    )

    if not total_cents:
        total_cents = (
            amount_before_tip_cents
            + tip_cents
        )

    processing_fee_cents = sum(
        _money_cents(
            fee.get("amount_money")
        )
        for fee in (
            payment.get("processing_fee")
            or []
        )
        if isinstance(fee, dict)
    )

    refunded_cents = _money_cents(
        payment.get("refunded_money")
    )

    net_received_cents = (
        total_cents
        - processing_fee_cents
    )

    accounted_total_cents = (
        service_cents
        + retail_cents
        + other_cents
        + unknown_cents
        + tax_cents
        + tip_cents
    )

    difference_cents = (
        total_cents
        - accounted_total_cents
    )

    if (
        service_cents
        and retail_cents
        and not other_cents
        and not unknown_cents
    ):
        income_type = "Service + Retail"
    elif (
        service_cents
        and not retail_cents
        and not other_cents
        and not unknown_cents
    ):
        income_type = "Service"
    elif (
        retail_cents
        and not service_cents
        and not other_cents
        and not unknown_cents
    ):
        income_type = "Retail"
    else:
        income_type = None

    payment_status = str(
        payment.get("status") or ""
    ).strip().upper()

    requires_review = bool(
        payment_status != "COMPLETED"
        or unknown_cents
        or other_cents
        or refunded_cents
        or difference_cents
    )

    card_details = (
        payment.get("card_details")
        or {}
    )

    card = (
        card_details.get("card")
        or {}
    )

    return {
        "payment_id": payment_id,
        "order_id": (
            payment_order_id
            or order_id
            or None
        ),
        "location_id": payment.get(
            "location_id"
        ),
        "customer_id": payment.get(
            "customer_id"
        ),
        "status": payment_status,
        "currency": (
            (
                payment.get("total_money")
                or payment.get(
                    "amount_money"
                )
                or {}
            ).get("currency")
        ),
        "source_type": payment.get(
            "source_type"
        ),
        "card_brand": card.get(
            "card_brand"
        ),
        "entry_method": card_details.get(
            "entry_method"
        ),
        "created_at": payment.get(
            "created_at"
        ),
        "service_amount_cents": (
            service_cents
        ),
        "retail_amount_cents": (
            retail_cents
        ),
        "other_amount_cents": (
            other_cents
        ),
        "unknown_amount_cents": (
            unknown_cents
        ),
        "tax_amount_cents": tax_cents,
        "tip_amount_cents": tip_cents,
        "amount_before_tip_cents": (
            amount_before_tip_cents
        ),
        "total_amount_cents": total_cents,
        "processing_fee_cents": (
            processing_fee_cents
        ),
        "refunded_amount_cents": (
            refunded_cents
        ),
        "net_received_cents": (
            net_received_cents
        ),
        "difference_cents": (
            difference_cents
        ),
        "income_type": income_type,
        "requires_review": (
            requires_review
        ),
        "ready_for_income": (
            not requires_review
        ),
        "line_items": normalized_lines,
    }
