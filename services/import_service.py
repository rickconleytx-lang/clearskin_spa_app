import csv
import hashlib
import io
import re
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path

from openpyxl import load_workbook
from psycopg2.extras import Json

from db import get_db_connection
from services.client_service import find_possible_client_duplicates
from services.client_information_labels import (
    get_client_information_label_definitions,
    get_client_information_labels,
    get_client_record_note_label_definitions,
    get_client_record_note_labels,
)


from services.peachpos_processor_labels import (
    get_peachpos_processor_field_definitions,
    get_peachpos_processor_field_labels,
)


class ImportServiceError(Exception):
    """Raised when a PSP import file cannot be processed safely."""


IMPORT_MAX_BYTES = 10 * 1024 * 1024
IMPORT_MAX_ROWS = 25000
IMPORT_MAX_COLUMNS = 200

IMPORT_ALLOWED_EXTENSIONS = {
    "csv",
    "xlsx",
}


def _clean_cell_value(value):
    """
    Convert imported spreadsheet values into safe, predictable
    values for preview/mapping without changing their meaning.
    """

    if value is None:
        return ""

    if isinstance(value, (datetime, date)):
        return value.isoformat()

    return str(value).strip()


def _trim_trailing_empty(values):
    values = list(values)

    while values and not str(values[-1] or "").strip():
        values.pop()

    return values


def validate_import_upload(uploaded_file):
    """
    Validate a customer-supplied CSV/XLSX upload before parsing.

    Returns the lowercase extension when valid.
    Raises ImportServiceError when invalid.
    """

    if uploaded_file is None:
        raise ImportServiceError(
            "Choose a CSV or Excel file to import."
        )

    filename = str(
        uploaded_file.filename or ""
    ).strip()

    if not filename:
        raise ImportServiceError(
            "Choose a CSV or Excel file to import."
        )

    if "." not in filename:
        raise ImportServiceError(
            "The import filename must include a valid extension."
        )

    extension = (
        filename.rsplit(".", 1)[1]
        .strip()
        .lower()
    )

    if extension not in IMPORT_ALLOWED_EXTENSIONS:
        raise ImportServiceError(
            "Import files must be CSV (.csv) or Excel (.xlsx)."
        )

    uploaded_file.stream.seek(
        0,
        io.SEEK_END,
    )

    file_size = uploaded_file.stream.tell()

    uploaded_file.stream.seek(0)

    if file_size <= 0:
        raise ImportServiceError(
            "The selected import file is empty."
        )

    if file_size > IMPORT_MAX_BYTES:
        raise ImportServiceError(
            "Import files must be 10 MB or smaller."
        )

    return extension


def _parse_csv(payload):
    """
    Parse CSV bytes using common export encodings.
    """

    decoded = None

    for encoding in (
        "utf-8-sig",
        "utf-8",
        "cp1252",
    ):
        try:
            decoded = payload.decode(encoding)
            break
        except UnicodeDecodeError:
            continue

    if decoded is None:
        raise ImportServiceError(
            "The CSV file encoding could not be read."
        )

    stream = io.StringIO(decoded)

    try:
        rows = list(csv.reader(stream))
    except csv.Error as exc:
        raise ImportServiceError(
            "The CSV file could not be parsed."
        ) from exc

    return rows


def _parse_xlsx(payload):
    """
    Parse the active worksheet from an XLSX workbook.
    """

    try:
        workbook = load_workbook(
            filename=io.BytesIO(payload),
            read_only=True,
            data_only=True,
        )
    except Exception as exc:
        raise ImportServiceError(
            "The Excel workbook could not be read."
        ) from exc

    try:
        worksheet = workbook.active

        rows = [
            list(row)
            for row in worksheet.iter_rows(
                values_only=True
            )
        ]
    finally:
        workbook.close()

    return rows


def parse_import_upload(uploaded_file):
    """
    Parse one CSV/XLSX upload into a generic import-table structure.

    No database writes occur here. The returned rows are intentionally
    entity-neutral so Clients, Income, Expenses, Loans, Appointments,
    and future import profiles can all use the same engine.
    """

    extension = validate_import_upload(
        uploaded_file
    )

    filename = Path(
        str(uploaded_file.filename or "")
    ).name

    uploaded_file.stream.seek(0)
    payload = uploaded_file.stream.read()
    uploaded_file.stream.seek(0)

    if extension == "csv":
        raw_rows = _parse_csv(payload)
    else:
        raw_rows = _parse_xlsx(payload)

    normalized_rows = []

    for raw_row in raw_rows:
        values = _trim_trailing_empty(
            [
                _clean_cell_value(value)
                for value in raw_row
            ]
        )

        if not values:
            continue

        normalized_rows.append(values)

    if not normalized_rows:
        raise ImportServiceError(
            "The import file does not contain any usable rows."
        )

    headers = normalized_rows[0]

    if not any(
        str(header or "").strip()
        for header in headers
    ):
        raise ImportServiceError(
            "The import file must contain a header row."
        )

    if len(headers) > IMPORT_MAX_COLUMNS:
        raise ImportServiceError(
            f"Import files may contain no more than "
            f"{IMPORT_MAX_COLUMNS} columns."
        )

    headers = [
        (
            str(header).strip()
            if str(header or "").strip()
            else f"Column {index + 1}"
        )
        for index, header in enumerate(headers)
    ]

    source_rows = normalized_rows[1:]

    if len(source_rows) > IMPORT_MAX_ROWS:
        raise ImportServiceError(
            f"Import files may contain no more than "
            f"{IMPORT_MAX_ROWS:,} data rows."
        )

    rows = []

    for source_index, source_row in enumerate(
        source_rows,
        start=2,
    ):
        values = list(source_row)

        if len(values) < len(headers):
            values.extend(
                [""] * (
                    len(headers) - len(values)
                )
            )
        elif len(values) > len(headers):
            raise ImportServiceError(
                f"Row {source_index} contains more columns "
                "than the header row."
            )

        rows.append({
            "row_number": source_index,
            "values": values,
        })

    return {
        "filename": filename,
        "extension": extension,
        "headers": headers,
        "rows": rows,
        "row_count": len(rows),
        "column_count": len(headers),
    }


# =========================================================
# CLIENT IMPORT PROFILE
# =========================================================


CLIENT_IMPORT_COMMUNICATION_DEFAULTS = {
    "ok_to_call": False,
    "ok_to_text": False,
    "ok_to_email": False,
    "sms_opt_in": False,
    "sms_opt_out": False,
    "email_opt_in": False,
    "email_opt_out": False,
    "sms_marketing_status": "opt_out",
    "email_marketing_status": "not_set",
    "sms_consent_timestamp": None,
    "email_consent_timestamp": None,
}


CLIENT_INFORMATION_IMPORT_FIELDS = tuple(
    {
        "key": definition["field_key"],
        "label": definition["default_label"],
        "required": False,
        "aliases": (),
        "field_type": definition["label_type"],
    }
    for definition in get_client_information_label_definitions()
    if definition.get("label_type") != "section"
)


CLIENT_IMPORT_FIELDS = (
    {
        "key": "first_name",
        "label": "First Name",
        "required": True,
        "aliases": (
            "first",
            "firstname",
            "first name",
            "given name",
            "given_name",
            "fname",
        ),
    },
    {
        "key": "last_name",
        "label": "Last Name",
        "required": True,
        "aliases": (
            "last",
            "lastname",
            "last name",
            "family name",
            "family_name",
            "surname",
            "lname",
        ),
    },
    {
        "key": "phone",
        "label": "Phone",
        "required": False,
        "aliases": (
            "phone",
            "phone number",
            "telephone",
            "mobile",
            "mobile phone",
            "cell",
            "cell phone",
        ),
    },
    {
        "key": "email",
        "label": "Email",
        "required": False,
        "aliases": (
            "email",
            "email address",
            "e-mail",
            "e-mail address",
        ),
    },
    {
        "key": "birth_date",
        "label": "Birth Date",
        "required": False,
        "aliases": (
            "birth date",
            "birthdate",
            "birthday",
            "date of birth",
            "dob",
        ),
    },
    {
        "key": "address",
        "label": "Address",
        "required": False,
        "aliases": (
            "address",
            "street",
            "street address",
            "address 1",
            "address1",
        ),
    },
    {
        "key": "city",
        "label": "City",
        "required": False,
        "aliases": (
            "city",
            "town",
        ),
    },
    {
        "key": "state",
        "label": "State",
        "required": False,
        "aliases": (
            "state",
            "province",
            "region",
        ),
    },
    {
        "key": "zip",
        "label": "ZIP / Postal Code",
        "required": False,
        "aliases": (
            "zip",
            "zip code",
            "zipcode",
            "postal code",
            "postalcode",
        ),
    },
    {
        "key": "emergency_contact_name",
        "label": "Emergency Contact Name",
        "required": False,
        "aliases": (
            "emergency contact",
            "emergency contact name",
            "emergency name",
        ),
    },
    {
        "key": "emergency_contact_phone",
        "label": "Emergency Contact Phone",
        "required": False,
        "aliases": (
            "emergency contact phone",
            "emergency phone",
        ),
    },
    {
        "key": "client_status",
        "label": "Client Status",
        "required": False,
        "aliases": (
            "client status",
            "customer status",
            "status",
        ),
    },
    {
        "key": "preferred_language",
        "label": "Preferred Language",
        "required": False,
        "aliases": (
            "preferred language",
            "language",
        ),
    },
    {
        "key": "preferred_contact_method",
        "label": "Preferred Contact Method",
        "required": False,
        "aliases": (
            "preferred contact method",
            "contact method",
            "preferred contact",
        ),
    },
    {
        "key": "referred_by",
        "label": "Referred By",
        "required": False,
        "aliases": (
            "referred by",
            "referral",
            "referral source",
        ),
    },
    {
        "key": "sex",
        "label": "Sex",
        "required": False,
        "aliases": (
            "sex",
            "gender",
        ),
    },
    {
        "key": "notes_one",
        "label": "Notes One",
        "required": False,
        "aliases": (
            "notes",
            "note",
            "client notes",
            "customer notes",
            "notes one",
            "client note 1",
            "client note one",
        ),
    },
    {
        "key": "notes_two",
        "label": "Notes Two",
        "required": False,
        "aliases": (
            "notes two",
            "client note 2",
            "client note two",
            "secondary notes",
        ),
    },
    {
        "key": "notes_three",
        "label": "Notes Three",
        "required": False,
        "aliases": (
            "notes three",
            "client note 3",
            "client note three",
        ),
    },
    {
        "key": "active_client",
        "label": "Active Client",
        "required": False,
        "aliases": (
            "active",
            "active client",
            "active customer",
            "is active",
        ),
    },
    *CLIENT_INFORMATION_IMPORT_FIELDS,
)


# =========================================================
# STANDARD INCOME IMPORT PROFILE
# =========================================================


INCOME_IMPORT_FIELDS = (
    {
        "key": "income_date",
        "label": "Income Date",
        "required": True,
        "aliases": (
            "income date",
            "date",
            "payment date",
            "sale date",
            "transaction date",
        ),
    },
    {
        "key": "income_type",
        "label": "Income Type",
        "required": True,
        "aliases": (
            "income type",
            "type",
            "category",
            "income category",
        ),
    },
    {
        "key": "payment_method",
        "label": "Payment Method",
        "required": True,
        "aliases": (
            "payment method",
            "payment type",
            "method",
            "tender",
            "tender type",
        ),
    },
    {
        "key": "client_name",
        "label": "Client",
        "required": False,
        "aliases": (
            "client",
            "client name",
            "customer",
            "customer name",
        ),
    },
    {
        "key": "description",
        "label": "Description",
        "required": False,
        "aliases": (
            "description",
            "income description",
            "details",
        ),
    },
    {
        "key": "service_amount",
        "label": "Service Amount",
        "required": False,
        "aliases": (
            "service amount",
            "services",
            "service sales",
        ),
    },
    {
        "key": "retail_amount",
        "label": "Retail Amount",
        "required": False,
        "aliases": (
            "retail amount",
            "retail",
            "retail sales",
            "product sales",
        ),
    },
    {
        "key": "tax_amount",
        "label": "Tax Amount",
        "required": False,
        "aliases": (
            "tax",
            "tax amount",
            "sales tax",
        ),
    },
    {
        "key": "total_amount",
        "label": "Total Amount",
        "required": False,
        "aliases": (
            "total",
            "total amount",
            "amount",
            "gross amount",
        ),
    },
    {
        "key": "processor_payment_id",
        "label": "Processor Payment ID",
        "required": False,
        "aliases": (
            "processor payment id",
            "payment id",
            "transaction id",
            "reference id",
            "reference number",
        ),
    },
    {
        "key": "notes",
        "label": "Notes",
        "required": False,
        "aliases": (
            "notes",
            "note",
            "memo",
            "comments",
        ),
    },
)


# =========================================================
# EXPENSE IMPORT PROFILE
# =========================================================

EXPENSE_IMPORT_FIELDS = (
    {
        "key": "expense_date",
        "label": "Expense Date",
        "required": True,
        "aliases": (
            "expense date",
            "date",
            "transaction date",
            "purchase date",
            "payment date",
        ),
    },
    {
        "key": "vendor_name",
        "label": "Vendor Name",
        "required": True,
        "aliases": (
            "vendor",
            "vendor name",
            "merchant",
            "payee",
            "supplier",
        ),
    },
    {
        "key": "category",
        "label": "Expense Category",
        "required": True,
        "aliases": (
            "expense category",
            "category",
            "expense type",
        ),
    },
    {
        "key": "amount",
        "label": "Amount",
        "required": True,
        "aliases": (
            "amount",
            "expense amount",
            "transaction amount",
            "total amount",
            "total",
        ),
    },
    {
        "key": "description",
        "label": "Description",
        "required": False,
        "aliases": (
            "description",
            "expense description",
            "details",
        ),
    },
    {
        "key": "payment_method",
        "label": "Payment Method",
        "required": False,
        "aliases": (
            "payment method",
            "payment type",
            "method",
            "paid by",
        ),
    },
    {
        "key": "notes",
        "label": "Notes",
        "required": False,
        "aliases": (
            "notes",
            "note",
            "memo",
            "comments",
        ),
    },
    {
        "key": "external_transaction_id",
        "label": "External Transaction ID",
        "required": False,
        "aliases": (
            "external transaction id",
            "transaction id",
            "bank transaction id",
            "reference id",
            "reference number",
        ),
    },
    {
        "key": "transaction_source",
        "label": "Transaction Source",
        "required": False,
        "aliases": (
            "transaction source",
            "source system",
            "statement source",
        ),
    },
)


# =========================================================
# APPOINTMENT IMPORT PROFILE
# =========================================================


APPOINTMENT_IMPORT_FIELDS = (
    {
        "key": "client_first_name",
        "label": "Client First Name",
        "required": False,
        "aliases": (
            "client first name",
            "customer first name",
            "first name",
            "firstname",
            "first",
        ),
    },
    {
        "key": "client_last_name",
        "label": "Client Last Name",
        "required": False,
        "aliases": (
            "client last name",
            "customer last name",
            "last name",
            "lastname",
            "last",
            "surname",
        ),
    },
    {
        "key": "client_email",
        "label": "Client Email",
        "required": False,
        "aliases": (
            "client email",
            "customer email",
            "email",
            "email address",
            "e-mail",
        ),
    },
    {
        "key": "client_phone",
        "label": "Client Phone",
        "required": False,
        "aliases": (
            "client phone",
            "customer phone",
            "phone",
            "phone number",
            "mobile",
            "cell",
        ),
    },
    {
        "key": "appointment_date",
        "label": "Appointment Date",
        "required": True,
        "aliases": (
            "appointment date",
            "booking date",
            "service date",
            "date",
        ),
    },
    {
        "key": "appointment_time",
        "label": "Appointment Time",
        "required": True,
        "aliases": (
            "appointment time",
            "booking time",
            "service time",
            "start time",
            "time",
        ),
    },
    {
        "key": "service_name",
        "label": "Service",
        "required": True,
        "aliases": (
            "service",
            "service name",
            "service type",
            "appointment type",
            "booking service",
        ),
    },
    {
        "key": "provider_name",
        "label": "Provider",
        "required": False,
        "aliases": (
            "provider",
            "provider name",
            "employee",
            "employee name",
            "staff",
            "staff member",
            "team member",
        ),
    },
    {
        "key": "duration_minutes",
        "label": "Duration Minutes",
        "required": False,
        "aliases": (
            "duration",
            "duration minutes",
            "duration_minutes",
            "length",
            "session length",
            "minutes",
        ),
    },
    {
        "key": "price_at_booking",
        "label": "Price at Booking",
        "required": False,
        "aliases": (
            "price",
            "service price",
            "appointment price",
            "price at booking",
            "amount",
        ),
    },
    {
        "key": "status",
        "label": "Appointment Status",
        "required": True,
        "aliases": (
            "status",
            "appointment status",
            "booking status",
        ),
    },
    {
        "key": "notes",
        "label": "Appointment Notes",
        "required": False,
        "aliases": (
            "notes",
            "appointment notes",
            "booking notes",
            "note",
            "comments",
            "memo",
        ),
    },
    {
        "key": "external_source",
        "label": "Booking System / Source",
        "required": False,
        "aliases": (
            "booking system",
            "booking source",
            "source system",
            "external source",
            "source",
            "platform",
        ),
    },
    {
        "key": "external_order_id",
        "label": "External Appointment ID",
        "required": False,
        "aliases": (
            "external appointment id",
            "appointment id",
            "booking id",
            "booking number",
            "confirmation number",
            "confirmation id",
            "external id",
        ),
    },
)


# =========================================================
# PEACHPOS INCOME IMPORT PROFILE
# =========================================================


PEACHPOS_PROCESSOR_IMPORT_FIELDS = tuple(
    {
        "key": definition["field_key"],
        "label": definition["default_label"],
        "required": False,
        "aliases": (),
        "field_type": definition["label_type"],
    }
    for definition in get_peachpos_processor_field_definitions()
)


PEACHPOS_INCOME_IMPORT_FIELDS = (
    {
        "key": "transaction_at",
        "label": "Transaction Date / Time",
        "required": True,
        "aliases": (
            "transaction date",
            "transaction datetime",
            "transaction date time",
            "date time",
            "datetime",
            "sale date",
            "created at",
            "created_at",
        ),
    },
    {
        "key": "transaction_time",
        "label": "Transaction Time",
        "required": False,
        "aliases": (
            "transaction time",
            "time",
            "sale time",
            "payment time",
            "created time",
        ),
    },
    {
        "key": "processor_payment_id",
        "label": "Processor Transaction ID",
        "required": True,
        "aliases": (
            "transaction id",
            "transaction_id",
            "payment id",
            "payment_id",
            "processor transaction id",
            "processor payment id",
            "reference id",
            "reference number",
            "transaction number",
        ),
    },
    {
        "key": "merchant_account_identifier",
        "label": "Merchant ID / Account ID",
        "required": True,
        "aliases": (
            "merchant id",
            "merchant_id",
            "merchant account id",
            "merchant account",
            "merchant account identifier",
            "mid",
            "account id",
            "account_id",
            "processor account id",
        ),
    },
    {
        "key": "pos_amount",
        "label": "Sales",
        "required": True,
        "aliases": (
            "sales",
            "sale amount",
            "sales amount",
            "subtotal",
            "pre tax sales",
            "pre-tax sales",
            "net sales before tax",
        ),
    },
    {
        "key": "tax_amount",
        "label": "Tax",
        "required": False,
        "aliases": (
            "tax",
            "tax amount",
            "sales tax",
            "tax collected",
        ),
    },
    {
        "key": "tip_amount",
        "label": "Tips",
        "required": False,
        "aliases": (
            "tip",
            "tips",
            "tip amount",
            "tips collected",
            "gratuity",
        ),
    },
    {
        "key": "total_amount",
        "label": "Gross Collected",
        "required": False,
        "aliases": (
            "total",
            "total amount",
            "gross",
            "gross amount",
            "gross collected",
            "amount",
            "payment amount",
        ),
    },
    {
        "key": "processing_fee_amount",
        "label": "Processor Fees",
        "required": False,
        "aliases": (
            "fee",
            "fees",
            "processing fee",
            "processing fees",
            "processor fee",
            "processor fees",
        ),
    },
    {
        "key": "net_received",
        "label": "Net Received",
        "required": False,
        "aliases": (
            "net",
            "net amount",
            "net received",
            "deposit amount",
            "settlement amount",
        ),
    },
    {
        "key": "payment_method",
        "label": "Payment Method",
        "required": False,
        "aliases": (
            "payment method",
            "payment type",
            "tender",
            "tender type",
            "card type",
        ),
    },
    {
        "key": "processor_status",
        "label": "Processor Status",
        "required": False,
        "aliases": (
            "status",
            "payment status",
            "transaction status",
            "processor status",
        ),
    },
    *PEACHPOS_PROCESSOR_IMPORT_FIELDS,
)


def normalize_import_header(value):
    """
    Normalize a source column heading only for matching purposes.
    The original heading remains unchanged for display.
    """

    value = str(value or "").strip().lower()

    return "".join(
        character
        for character in value
        if character.isalnum()
    )


def get_import_profile(entity_type):
    """
    Return the entity-specific rules used by the shared Import Engine.
    """

    entity_type = str(
        entity_type or ""
    ).strip().lower()

    if entity_type == "clients":
        return {
            "entity_type": "clients",
            "display_name": "Clients",
            "fields": CLIENT_IMPORT_FIELDS,
            "defaults": {
                "client_status": "Current",
                "active_client": True,
            },
        }

    if entity_type == "income":
        return {
            "entity_type": "income",
            "display_name": "Income",
            "fields": INCOME_IMPORT_FIELDS,
            "defaults": {},
        }

    if entity_type == "expenses":
        return {
            "entity_type": "expenses",
            "display_name": "Expenses",
            "fields": EXPENSE_IMPORT_FIELDS,
            "defaults": {},
        }

    if entity_type == "appointments":
        return {
            "entity_type": "appointments",
            "display_name": "Appointments",
            "fields": APPOINTMENT_IMPORT_FIELDS,
            "defaults": {},
        }

    if entity_type == "peachpos_income":
        return {
            "entity_type": "peachpos_income",
            "display_name": "PeachPOS Income",
            "fields": PEACHPOS_INCOME_IMPORT_FIELDS,
            "defaults": {},
        }

    raise ImportServiceError(
        f"Unsupported import type: {entity_type or 'unknown'}."
    )



def get_workspace_import_profile(
    cur,
    *,
    spa_id,
    business_unit_id,
    entity_type,
    options=None,
):
    """
    Return a workspace-aware copy of an Import Engine profile.

    Backend target keys remain immutable. Workspace customization
    affects only display labels and exact-header matching aliases.
    """

    base_profile = get_import_profile(
        entity_type
    )

    profile = {
        **base_profile,
        "fields": [
            dict(field)
            for field in base_profile["fields"]
        ],
    }

    if profile["entity_type"] == "peachpos_income":
        options_payload = dict(options or {})
        credit_processor_id = options_payload.get(
            "credit_processor_id"
        )

        try:
            credit_processor_id = int(
                credit_processor_id
            )
        except (TypeError, ValueError):
            raise ImportServiceError(
                "Choose a credit processor before importing "
                "PeachPOS Income."
            )

        if credit_processor_id <= 0:
            raise ImportServiceError(
                "Choose a credit processor before importing "
                "PeachPOS Income."
            )

        try:
            resolved_processor_labels = (
                get_peachpos_processor_field_labels(
                    cur,
                    spa_id=spa_id,
                    business_unit_id=business_unit_id,
                    credit_processor_id=credit_processor_id,
                    require_active=True,
                )
            )
        except ValueError as exc:
            raise ImportServiceError(str(exc)) from exc

        processor_definitions = {
            definition["field_key"]: definition
            for definition
            in get_peachpos_processor_field_definitions()
        }

        for field in profile["fields"]:
            field_key = field["key"]
            definition = processor_definitions.get(
                field_key
            )
            if not definition:
                continue

            current_label = (
                resolved_processor_labels.get(
                    field_key
                )
                or definition["default_label"]
            )
            field["label"] = current_label
            field["workspace_match_labels"] = (
                current_label,
                definition["default_label"],
            )

        return profile

    if profile["entity_type"] != "clients":
        return profile

    resolved_client_information_labels = (
        get_client_information_labels(
            cur,
            spa_id=spa_id,
            business_unit_id=business_unit_id,
        )
    )

    client_information_definitions = {
        definition["field_key"]: definition
        for definition
        in get_client_information_label_definitions()
        if definition.get("label_type") != "section"
    }

    resolved_note_labels = (
        get_client_record_note_labels(
            cur,
            spa_id=spa_id,
            business_unit_id=business_unit_id,
        )
    )

    note_definitions = {
        definition["field_key"]: definition
        for definition
        in get_client_record_note_label_definitions()
    }

    workspace_definitions = {
        **client_information_definitions,
        **note_definitions,
    }

    resolved_workspace_labels = {
        **resolved_client_information_labels,
        **resolved_note_labels,
    }

    for field in profile["fields"]:
        field_key = field["key"]

        definition = workspace_definitions.get(
            field_key
        )

        if not definition:
            continue

        current_label = (
            resolved_workspace_labels.get(
                field_key
            )
            or definition["default_label"]
        )

        field["label"] = current_label

        field["workspace_match_labels"] = (
            current_label,
            definition["default_label"],
            definition["legacy_label"],
        )

    return profile

def suggest_import_mapping(
    headers,
    entity_type="clients",
    *,
    profile=None,
):
    """
    Suggest safe source-column -> PSP-field mappings.

    Matching is exact after header normalization.

    Priority:
      1. current workspace label
      2. generic PSP label
      3. original / legacy PSP label
      4. immutable backend key and known aliases

    A priority level must resolve to exactly one target.
    Ambiguous or repeated matches remain unmapped for review.
    """

    if profile is None:
        profile = get_import_profile(
            entity_type
        )

    match_levels = [
        {},
        {},
        {},
        {},
    ]

    for field in profile["fields"]:
        field_key = field["key"]

        workspace_labels = tuple(
            field.get(
                "workspace_match_labels",
                (),
            )
        )

        current_label = (
            workspace_labels[0]
            if len(workspace_labels) > 0
            else field["label"]
        )

        generic_label = (
            workspace_labels[1]
            if len(workspace_labels) > 1
            else field["label"]
        )

        legacy_label = (
            workspace_labels[2]
            if len(workspace_labels) > 2
            else None
        )

        level_values = (
            (current_label,),
            (generic_label,),
            (legacy_label,),
            (
                field_key,
                *field.get("aliases", ()),
            ),
        )

        for level_index, aliases in enumerate(
            level_values
        ):
            for alias in aliases:
                normalized = normalize_import_header(
                    alias
                )

                if not normalized:
                    continue

                match_levels[level_index].setdefault(
                    normalized,
                    set(),
                ).add(
                    field_key
                )

    suggestions = []
    used_targets = set()

    for source_index, header in enumerate(headers):
        normalized_header = normalize_import_header(
            header
        )

        target_key = None

        for lookup in match_levels:
            candidates = lookup.get(
                normalized_header,
                set(),
            )

            if not candidates:
                continue

            if len(candidates) == 1:
                candidate = next(
                    iter(candidates)
                )

                if candidate not in used_targets:
                    target_key = candidate
                    used_targets.add(candidate)

            # A match at a higher-priority level prevents
            # falling through to lower-priority aliases.
            break

        suggestions.append({
            "source_index": source_index,
            "source_header": str(
                header or ""
            ).strip(),
            "target_key": target_key,
        })

    return suggestions


# =========================================================
# CLIENT IMPORT ROW NORMALIZATION / VALIDATION
# =========================================================

def _normalize_import_email(value):
    return str(value or "").strip().lower()


def _is_valid_import_email(value):
    value = _normalize_import_email(value)

    if not value:
        return True

    if value.count("@") != 1:
        return False

    local_part, domain = value.split("@", 1)

    return bool(
        local_part
        and domain
        and "." in domain
        and not any(
            character.isspace()
            for character in value
        )
    )


def _parse_import_money(value, *, default=None):
    """
    Normalize common processor-export currency values.
    Returns Decimal for nonblank values.
    Blank values return the supplied default.
    """
    if value is None:
        return default

    if isinstance(value, Decimal):
        return value

    raw = str(value).strip()
    if not raw:
        return default

    negative_parentheses = (
        raw.startswith("(")
        and raw.endswith(")")
    )

    if negative_parentheses:
        raw = raw[1:-1].strip()

    raw = (
        raw.replace(",", "")
        .replace("$", "")
        .strip()
    )

    try:
        amount = Decimal(raw)
    except (InvalidOperation, ValueError):
        raise ImportServiceError(
            f"Amount '{value}' is not a valid monetary value."
        )

    if negative_parentheses:
        amount = -abs(amount)

    return amount.quantize(Decimal("0.01"))


def _parse_import_transaction_datetime(
    value,
    *,
    time_value=None,
):
    """
    Normalize a processor transaction date/time.

    Supports either one combined timestamp or a separate
    date column plus time column. Naive timestamps remain
    naive here; posting later applies the workspace timezone.
    PSP does not invent a missing transaction time.
    """
    raw = str(value or "").strip()
    raw_time = str(time_value or "").strip()

    if not raw:
        raise ImportServiceError(
            "Transaction Date / Time is required."
        )

    if raw_time:
        raw = f"{raw} {raw_time}"

    iso_candidate = raw
    if iso_candidate.endswith("Z"):
        iso_candidate = iso_candidate[:-1] + "+00:00"

    try:
        parsed = datetime.fromisoformat(iso_candidate)
        if isinstance(parsed, datetime):
            return parsed.isoformat()
    except ValueError:
        pass

    datetime_formats = (
        "%m/%d/%Y %I:%M:%S %p",
        "%m/%d/%Y %I:%M %p",
        "%m/%d/%y %I:%M:%S %p",
        "%m/%d/%y %I:%M %p",
        "%m-%d-%Y %I:%M:%S %p",
        "%m-%d-%Y %I:%M %p",
        "%m/%d/%Y %H:%M:%S",
        "%m/%d/%Y %H:%M",
        "%m/%d/%y %H:%M:%S",
        "%m/%d/%y %H:%M",
        "%m-%d-%Y %H:%M:%S",
        "%m-%d-%Y %H:%M",
        "%Y-%m-%d %I:%M:%S %p",
        "%Y-%m-%d %I:%M %p",
        "%Y-%m-%d %H:%M:%S",
        "%Y-%m-%d %H:%M",
    )

    for date_format in datetime_formats:
        try:
            parsed = datetime.strptime(
                raw,
                date_format,
            )
            return parsed.isoformat()
        except ValueError:
            continue

    date_only_formats = (
        "%Y-%m-%d",
        "%m/%d/%Y",
        "%m/%d/%y",
        "%m-%d-%Y",
        "%m-%d-%y",
    )

    for date_format in date_only_formats:
        try:
            datetime.strptime(raw, date_format)
        except ValueError:
            continue
        raise ImportServiceError(
            "Transaction time is missing. Map the processor "
            "time column or use a combined Date / Time column."
        )

    raise ImportServiceError(
        f"Transaction Date / Time '{raw}' is not in a "
        "supported format."
    )


def _parse_import_date(value):
    """
    Accept common customer-export date formats and return ISO YYYY-MM-DD.
    Blank values remain blank.
    """

    raw = str(value or "").strip()

    if not raw:
        return ""

    date_formats = (
        "%Y-%m-%d",
        "%m/%d/%Y",
        "%m/%d/%y",
        "%m-%d-%Y",
        "%m-%d-%y",
        "%Y/%m/%d",
        "%B %d, %Y",
        "%b %d, %Y",
    )

    for date_format in date_formats:
        try:
            parsed = datetime.strptime(
                raw,
                date_format,
            ).date()

            return parsed.isoformat()
        except ValueError:
            continue

    raise ImportServiceError(
        f"Date '{raw}' is not in a supported format."
    )


def _parse_import_time(value):
    """
    Accept common appointment-export time formats and return HH:MM:SS.
    Blank values remain blank.
    """

    raw = str(value or "").strip()

    if not raw:
        return ""

    time_formats = (
        "%H:%M:%S",
        "%H:%M",
        "%I:%M:%S %p",
        "%I:%M %p",
        "%I %p",
    )

    for time_format in time_formats:
        try:
            parsed = datetime.strptime(
                raw,
                time_format,
            ).time()

            return parsed.strftime("%H:%M:%S")
        except ValueError:
            continue

    raise ImportServiceError(
        f"Time '{raw}' is not in a supported format."
    )


def _parse_import_boolean(
    value,
    *,
    default=None,
):
    """
    Parse common boolean values found in CSV/Excel exports.
    """

    if isinstance(value, bool):
        return value

    raw = str(value or "").strip().lower()

    if not raw:
        return default

    truthy = {
        "1",
        "true",
        "yes",
        "y",
        "active",
    }

    falsey = {
        "0",
        "false",
        "no",
        "n",
        "inactive",
    }

    if raw in truthy:
        return True

    if raw in falsey:
        return False

    raise ImportServiceError(
        f"Value '{value}' is not a recognized yes/no value."
    )


def apply_import_mapping(
    values,
    mapping,
    *,
    entity_type="clients",
):
    """
    Convert one source row into an entity-keyed dictionary using
    the reviewed source-column mapping.

    Mapping entries use:
      source_index
      target_key

    Unmapped source columns are intentionally ignored.
    """

    profile = get_import_profile(
        entity_type
    )

    valid_target_keys = {
        field["key"]
        for field in profile["fields"]
    }

    result = dict(
        profile.get(
            "defaults",
            {}
        )
    )

    used_targets = set()

    for item in mapping:
        target_key = str(
            item.get("target_key") or ""
        ).strip()

        if not target_key:
            continue

        if target_key not in valid_target_keys:
            raise ImportServiceError(
                f"Unknown {profile['display_name']} import "
                f"field: {target_key}."
            )

        if target_key in used_targets:
            raise ImportServiceError(
                f"The import mapping assigns more than one "
                f"source column to {target_key}."
            )

        try:
            source_index = int(
                item.get("source_index")
            )
        except (TypeError, ValueError) as exc:
            raise ImportServiceError(
                "The import mapping contains an invalid "
                "source column."
            ) from exc

        if (
            source_index < 0
            or source_index >= len(values)
        ):
            raise ImportServiceError(
                "The import mapping references a source "
                "column outside this row."
            )

        result[target_key] = str(
            values[source_index] or ""
        ).strip()

        used_targets.add(
            target_key
        )

    return result


def validate_client_import_row(
    row_data,
):
    """
    Normalize and validate one mapped Client import row.

    Import policy:
      - first and last name are required
      - phone and email may be blank for historical records
      - email is validated only when present
      - birth date is normalized when present
      - Client Status defaults to Current
      - Active Client defaults to True
      - marketing/SMS/email consent is NOT inferred here
    """

    normalized = {
        key: str(
            value or ""
        ).strip()
        for key, value in row_data.items()
        if key != "active_client"
    }

    errors = []

    first_name = normalized.get(
        "first_name",
        "",
    )

    last_name = normalized.get(
        "last_name",
        "",
    )

    if not first_name:
        errors.append(
            "First Name is required."
        )

    if not last_name:
        errors.append(
            "Last Name is required."
        )

    email = _normalize_import_email(
        normalized.get(
            "email",
            "",
        )
    )

    if email and not _is_valid_import_email(email):
        errors.append(
            "Email address is not valid."
        )

    normalized["email"] = email

    birth_date = normalized.get(
        "birth_date",
        "",
    )

    if birth_date:
        try:
            normalized["birth_date"] = (
                _parse_import_date(
                    birth_date
                )
            )
        except ImportServiceError as exc:
            errors.append(
                str(exc)
            )
            normalized["birth_date"] = (
                birth_date
            )

    user_def_boolean_keys = (
        "recent_injections",
        "recent_laser",
        "pregnant",
        "nursing",
        "using_retinol",
        "using_accutane",
    )

    for field_key in user_def_boolean_keys:
        if field_key not in row_data:
            continue

        try:
            normalized[field_key] = (
                _parse_import_boolean(
                    row_data.get(field_key),
                    default=None,
                )
            )
        except ImportServiceError as exc:
            errors.append(
                str(exc)
            )
            normalized[field_key] = str(
                row_data.get(field_key) or ""
            ).strip()

    if "last_facial_date" in row_data:
        last_facial_date = str(
            row_data.get("last_facial_date") or ""
        ).strip()

        if last_facial_date:
            try:
                normalized["last_facial_date"] = (
                    _parse_import_date(
                        last_facial_date
                    )
                )
            except ImportServiceError as exc:
                errors.append(
                    str(exc)
                )
                normalized["last_facial_date"] = (
                    last_facial_date
                )
        else:
            normalized["last_facial_date"] = ""

    normalized["client_status"] = (
        normalized.get(
            "client_status",
            "",
        )
        or "Current"
    )

    try:
        normalized["active_client"] = (
            _parse_import_boolean(
                row_data.get(
                    "active_client"
                ),
                default=True,
            )
        )
    except ImportServiceError as exc:
        errors.append(
            str(exc)
        )
        normalized["active_client"] = True

    return {
        "valid": not errors,
        "data": normalized,
        "errors": errors,
    }


def validate_income_import_row(
    row_data,
):
    """
    Normalize and validate one mapped standard Income row.

    This mirrors PSP General Income entry rules:
      - Income Date is required
      - Income Type is required
      - Payment Method is required
      - Client is optional and resolved later within the workspace
      - monetary values must be valid when supplied
      - Total Amount cannot be negative
      - PSP never invents missing source values
    """
    normalized = {
        key: str(value or "").strip()
        for key, value in row_data.items()
    }
    errors = []

    income_date = normalized.get(
        "income_date",
        "",
    )

    if not income_date:
        errors.append(
            "Income Date is required."
        )
    else:
        try:
            normalized["income_date"] = (
                _parse_import_date(
                    income_date
                )
            )
        except ImportServiceError as exc:
            errors.append(str(exc))
            normalized["income_date"] = income_date

    if not normalized.get(
        "income_type",
        "",
    ):
        errors.append(
            "Income Type is required."
        )

    if not normalized.get(
        "payment_method",
        "",
    ):
        errors.append(
            "Payment Method is required."
        )

    money_fields = (
        ("service_amount", "Service Amount"),
        ("retail_amount", "Retail Amount"),
        ("tax_amount", "Tax Amount"),
        ("total_amount", "Total Amount"),
    )

    for field_key, field_label in money_fields:
        raw_value = normalized.get(
            field_key,
            "",
        )

        if not raw_value:
            normalized[field_key] = ""
            continue

        try:
            amount = _parse_import_money(
                raw_value
            )
            normalized[field_key] = str(
                amount
            )
        except ImportServiceError:
            errors.append(
                f"{field_label} is not a valid monetary amount."
            )

    total_amount = normalized.get(
        "total_amount",
        "",
    )

    if total_amount:
        try:
            if Decimal(total_amount) < 0:
                errors.append(
                    "Total Amount cannot be negative."
                )
        except (InvalidOperation, ValueError):
            pass

    return {
        "valid": not errors,
        "data": normalized,
        "errors": errors,
    }


def validate_expense_import_row(row_data):
    """
    Normalize and validate one mapped Expense import row.

    Required:
      - Expense Date
      - Vendor Name
      - Expense Category
      - Amount

    Optional:
      - Description
      - Payment Method
      - Notes
      - External Transaction ID
      - Transaction Source

    Database-backed lookup resolution happens separately.
    PSP never invents missing source values.
    """

    normalized = {
        key: str(
            value if value is not None else ""
        ).strip()
        for key, value in row_data.items()
    }

    errors = []

    expense_date = normalized.get(
        "expense_date", ""
    )

    if not expense_date:
        errors.append(
            "Expense Date is required."
        )
    else:
        try:
            normalized["expense_date"] = (
                _parse_import_date(expense_date)
            )
        except ImportServiceError as exc:
            errors.append(str(exc))

    if not normalized.get("vendor_name", ""):
        errors.append(
            "Vendor Name is required."
        )

    if not normalized.get("category", ""):
        errors.append(
            "Expense Category is required."
        )

    raw_amount = normalized.get(
        "amount", ""
    )

    if not raw_amount:
        errors.append(
            "Amount is required."
        )
    else:
        try:
            amount = _parse_import_money(
                raw_amount
            )

            if amount is None:
                raise ImportServiceError(
                    "Amount is invalid."
                )

            amount = Decimal(str(amount))

            if not amount.is_finite():
                raise ImportServiceError(
                    "Amount must be finite."
                )

            normalized["amount"] = str(
                amount
            )

        except (
            ImportServiceError,
            InvalidOperation,
            ValueError,
        ):
            errors.append(
                "Amount is not a valid monetary amount."
            )

    if (
        normalized.get("external_transaction_id")
        and not normalized.get("transaction_source")
    ):
        errors.append(
            "Transaction Source is required when "
            "External Transaction ID is provided."
        )

    return {
        "valid": not errors,
        "data": normalized,
        "errors": errors,
    }


def validate_appointment_import_row(
    row_data,
):
    """
    Normalize and validate one mapped Appointment import row.

    Import policy:
      - appointment date, time, service, and status are required
      - client must be identifiable by email, phone, or unique full name
      - client/service/provider database resolution happens later
      - duration is required for operational booked appointments
      - duration may remain blank for historical completed/cancelled/no_show rows
      - historical price remains optional
      - supplied duration and price must be valid
      - PSP does not invent missing appointment facts
    """

    normalized = {
        key: str(value or "").strip()
        for key, value in row_data.items()
    }
    errors = []

    # -------------------------------------------------
    # Client identity
    # -------------------------------------------------
    client_email = _normalize_import_email(
        normalized.get(
            "client_email",
            "",
        )
    )

    if client_email and not _is_valid_import_email(
        client_email
    ):
        errors.append(
            "Client Email is not valid."
        )

    normalized["client_email"] = client_email

    client_phone = normalized.get(
        "client_phone",
        "",
    )

    normalized_phone = normalize_client_import_phone(
        client_phone
    )

    client_first_name = normalized.get(
        "client_first_name",
        "",
    )
    client_last_name = normalized.get(
        "client_last_name",
        "",
    )

    has_full_name = bool(
        client_first_name
        and client_last_name
    )

    if not (
        client_email
        or normalized_phone
        or has_full_name
    ):
        errors.append(
            "Identify the client with Client Email, "
            "Client Phone, or both Client First Name "
            "and Client Last Name."
        )

    # -------------------------------------------------
    # Appointment date
    # -------------------------------------------------
    appointment_date = normalized.get(
        "appointment_date",
        "",
    )

    if not appointment_date:
        errors.append(
            "Appointment Date is required."
        )
    else:
        try:
            normalized["appointment_date"] = (
                _parse_import_date(
                    appointment_date
                )
            )
        except ImportServiceError as exc:
            errors.append(str(exc))
            normalized["appointment_date"] = (
                appointment_date
            )

    # -------------------------------------------------
    # Appointment time
    # -------------------------------------------------
    appointment_time = normalized.get(
        "appointment_time",
        "",
    )

    if not appointment_time:
        errors.append(
            "Appointment Time is required."
        )
    else:
        try:
            normalized["appointment_time"] = (
                _parse_import_time(
                    appointment_time
                )
            )
        except ImportServiceError as exc:
            errors.append(str(exc))
            normalized["appointment_time"] = (
                appointment_time
            )

    # -------------------------------------------------
    # Service
    # -------------------------------------------------
    if not normalized.get(
        "service_name",
        "",
    ):
        errors.append(
            "Service is required."
        )

    # -------------------------------------------------
    # Appointment status
    # -------------------------------------------------
    raw_status = normalized.get(
        "status",
        "",
    )

    status_key = " ".join(
        raw_status
        .strip()
        .lower()
        .replace("_", " ")
        .replace("-", " ")
        .split()
    )

    status_map = {
        "booked": "booked",
        "scheduled": "booked",
        "confirmed": "booked",
        "complete": "completed",
        "completed": "completed",
        "cancelled": "cancelled",
        "canceled": "cancelled",
        "no show": "no_show",
        "noshow": "no_show",
    }

    if not raw_status:
        errors.append(
            "Appointment Status is required."
        )
    elif status_key not in status_map:
        errors.append(
            "Appointment Status must be Booked, "
            "Scheduled, Confirmed, Completed, "
            "Cancelled, Canceled, or No Show."
        )
    else:
        normalized["status"] = (
            status_map[status_key]
        )

    # -------------------------------------------------
    # Optional external appointment identity
    # -------------------------------------------------
    external_order_id = str(
        normalized.get(
            "external_order_id",
            "",
        )
        or ""
    ).strip()

    external_source = str(
        normalized.get(
            "external_source",
            "",
        )
        or ""
    ).strip()

    if external_order_id and not external_source:
        errors.append(
            "Booking System / Source is required when an "
            "External Appointment ID is supplied."
        )

    normalized["external_order_id"] = external_order_id
    normalized["external_source"] = external_source

    # -------------------------------------------------
    # Duration
    #
    # A future/operational booked appointment must carry the
    # actual imported duration. PSP does not silently substitute
    # today's Service Catalog duration for missing source data.
    #
    # Historical completed/cancelled/no_show rows may preserve
    # a blank duration when the source system did not provide it.
    # -------------------------------------------------
    duration_raw = normalized.get(
        "duration_minutes",
        "",
    )

    normalized_status = str(
        normalized.get("status") or ""
    ).strip().lower()

    if not duration_raw:
        if normalized_status == "booked":
            errors.append(
                "Duration Minutes is required for Booked appointments."
            )

    else:
        try:
            duration_value = Decimal(
                duration_raw
            )

            if (
                duration_value <= 0
                or duration_value
                != duration_value.to_integral_value()
            ):
                raise ValueError

            normalized["duration_minutes"] = str(
                int(duration_value)
            )
        except (
            InvalidOperation,
            ValueError,
        ):
            errors.append(
                "Duration Minutes must be a positive whole number."
            )

    # -------------------------------------------------
    # Optional historical price
    # -------------------------------------------------
    price_raw = normalized.get(
        "price_at_booking",
        "",
    )

    if price_raw:
        try:
            price = _parse_import_money(
                price_raw
            )

            if price < Decimal("0.00"):
                errors.append(
                    "Price at Booking cannot be negative."
                )
            else:
                normalized["price_at_booking"] = (
                    format(price, ".2f")
                )
        except ImportServiceError as exc:
            errors.append(
                f"Price at Booking: {exc}"
            )

    return {
        "valid": not errors,
        "data": normalized,
        "errors": errors,
    }


def validate_peachpos_income_import_row(
    row_data,
):
    """
    Normalize and validate one mapped PeachPOS Income row.

    Data-integrity policy:
      - PSP never invents missing processor data
      - transaction date/time, transaction ID, and Sales
        are required
      - optional monetary values remain blank when absent
      - supplied accounting values are verified when enough
        source values exist to perform the check
      - no missing Total, Fees, Net, Tax, or Tips are derived
    """
    normalized = {
        key: str(value or "").strip()
        for key, value in row_data.items()
    }
    errors = []

    # -------------------------------------------------
    # Processor transaction timestamp
    # -------------------------------------------------
    transaction_value = normalized.get(
        "transaction_at",
        "",
    )
    transaction_time = normalized.get(
        "transaction_time",
        "",
    )

    try:
        normalized["transaction_at"] = (
            _parse_import_transaction_datetime(
                transaction_value,
                time_value=transaction_time,
            )
        )
    except ImportServiceError as exc:
        errors.append(str(exc))
        normalized["transaction_at"] = transaction_value

    # transaction_time is an import-only helper. The original
    # source value remains preserved in source_data.
    normalized.pop("transaction_time", None)

    # -------------------------------------------------
    # Processor transaction identity
    # -------------------------------------------------
    processor_payment_id = normalized.get(
        "processor_payment_id",
        "",
    )
    if not processor_payment_id:
        errors.append(
            "Processor Transaction ID is required."
        )

    merchant_account_identifier = normalized.get(
        "merchant_account_identifier",
        "",
    )
    if not merchant_account_identifier:
        errors.append(
            "Merchant ID / Account ID is required."
        )

    # -------------------------------------------------
    # Monetary values
    # -------------------------------------------------
    money_fields = (
        ("pos_amount", "Sales"),
        ("tax_amount", "Tax"),
        ("tip_amount", "Tips"),
        ("total_amount", "Gross Collected"),
        ("processing_fee_amount", "Processor Fees"),
        ("net_received", "Net Received"),
    )

    parsed_money = {}

    for field_key, field_label in money_fields:
        raw_value = normalized.get(field_key, "")

        if field_key == "pos_amount" and not raw_value:
            errors.append(
                "Sales is required."
            )
            continue

        if not raw_value:
            # Never infer zero or calculate a missing value.
            continue

        try:
            amount = _parse_import_money(raw_value)
        except ImportServiceError as exc:
            errors.append(
                f"{field_label}: {exc}"
            )
            continue

        parsed_money[field_key] = amount
        normalized[field_key] = format(amount, ".2f")

    # PeachPOS represents positive completed sales. Refunds,
    # voids, and other lifecycle cases require separate review.
    pos_amount = parsed_money.get("pos_amount")
    if pos_amount is not None and pos_amount <= Decimal("0.00"):
        errors.append(
            "Sales must be greater than zero for a PeachPOS sale."
        )

    tax_amount = parsed_money.get("tax_amount")
    if tax_amount is not None and tax_amount < Decimal("0.00"):
        errors.append(
            "Tax cannot be negative for a PeachPOS sale."
        )

    tip_amount = parsed_money.get("tip_amount")
    if tip_amount is not None and tip_amount < Decimal("0.00"):
        errors.append(
            "Tips cannot be negative for a PeachPOS sale."
        )

    total_amount = parsed_money.get("total_amount")
    if total_amount is not None and total_amount <= Decimal("0.00"):
        errors.append(
            "Gross Collected must be greater than zero when supplied."
        )

    processing_fee = parsed_money.get("processing_fee_amount")
    if processing_fee is not None and processing_fee < Decimal("0.00"):
        errors.append(
            "Processor Fees cannot be negative in PSP. "
            "Review the processor export fee convention."
        )

    net_received = parsed_money.get("net_received")
    if net_received is not None and net_received < Decimal("0.00"):
        errors.append(
            "Net Received cannot be negative for a PeachPOS sale."
        )

    # -------------------------------------------------
    # Verify supplied accounting relationships.
    # Never fill a missing component.
    # -------------------------------------------------
    if all(
        key in parsed_money
        for key in (
            "pos_amount",
            "tax_amount",
            "tip_amount",
            "total_amount",
        )
    ):
        expected_total = (
            parsed_money["pos_amount"]
            + parsed_money["tax_amount"]
            + parsed_money["tip_amount"]
        ).quantize(Decimal("0.01"))

        if expected_total != parsed_money["total_amount"]:
            errors.append(
                "Sales + Tax + Tips does not equal "
                "Gross Collected."
            )

    if all(
        key in parsed_money
        for key in (
            "total_amount",
            "processing_fee_amount",
            "net_received",
        )
    ):
        expected_net = (
            parsed_money["total_amount"]
            - parsed_money["processing_fee_amount"]
        ).quantize(Decimal("0.01"))

        if expected_net != parsed_money["net_received"]:
            errors.append(
                "Gross Collected - Processor Fees does not "
                "equal Net Received."
            )

    return {
        "valid": not errors,
        "data": normalized,
        "errors": errors,
    }



def verify_peachpos_import_merchant_identity(
    cur,
    *,
    spa_id,
    business_unit_id,
    credit_processor_id,
    prepared_rows,
):
    """
    Hard safety gate for generic non-Square PeachPOS imports.

    The uploaded file must contain exactly one Merchant ID /
    Account ID, and it must exactly match the identifier saved
    for the selected processor account.

    Square uses PSP's native Square integration and is not
    permitted through the generic processor-file importer.
    """
    try:
        credit_processor_id = int(
            credit_processor_id
        )
    except (TypeError, ValueError):
        raise ImportServiceError(
            "Choose a processor before importing "
            "PeachPOS Income."
        )

    cur.execute(
        """
        SELECT
            credit_processor_name,
            merchant_account_identifier
        FROM credit_processors
        WHERE credit_processor_id = %s
          AND spa_id = %s
          AND business_unit_id = %s
        LIMIT 1
        """,
        (
            credit_processor_id,
            spa_id,
            business_unit_id,
        ),
    )
    processor = cur.fetchone()

    if not processor:
        raise ImportServiceError(
            "The selected processor was not found in this "
            "Provider Workspace."
        )

    processor_name = str(
        processor[0] or ""
    ).strip()

    if processor_name.lower() == "square":
        raise ImportServiceError(
            "Square transactions use PSP's native Square "
            "integration and cannot be imported through the "
            "generic PeachPOS Income Import."
        )

    configured_identifier = str(
        processor[1] or ""
    ).strip()

    if not configured_identifier:
        raise ImportServiceError(
            "Merchant ID / Account ID is not configured for "
            f"{processor_name or 'this processor'}. "
            "Enter it in Processor Company Setup before "
            "importing."
        )

    detected_identifiers = set()
    missing_rows = []

    for row in prepared_rows:
        data = row.get("data") or {}
        identifier = str(
            data.get(
                "merchant_account_identifier"
            )
            or ""
        ).strip()

        if not identifier:
            missing_rows.append(
                row.get("row_number")
            )
            continue

        detected_identifiers.add(
            identifier
        )

    if missing_rows:
        raise ImportServiceError(
            "Merchant ID / Account ID is missing from one "
            "or more rows in the uploaded processor file. "
            "Import is blocked."
        )

    if len(detected_identifiers) != 1:
        raise ImportServiceError(
            "The uploaded processor file contains multiple "
            "Merchant ID / Account ID values. "
            "Import is blocked."
        )

    detected_identifier = next(
        iter(detected_identifiers)
    )

    if detected_identifier != configured_identifier:
        raise ImportServiceError(
            "Merchant ID / Account ID in the uploaded file "
            "does not match Processor Company Setup. "
            "Import is blocked."
        )

    return {
        "processor_company": processor_name,
        "detected_identifier": detected_identifier,
        "configured_identifier_at_verification": (
            configured_identifier
        ),
        "verified": True,
    }

def _normalize_import_dropdown_value(value):
    return " ".join(
        str(value or "")
        .strip()
        .lower()
        .split()
    )


def validate_income_import_workspace_values(
    cur,
    *,
    spa_id,
    business_unit_id,
    prepared_rows,
):
    """
    Resolve database-backed standard Income values.

    Income Type:
      imported display value -> existing spa income type

    Payment Method:
      imported display value -> existing spa payment method

    Client:
      imported client display name -> exact current-workspace client_id

    Matching is case-insensitive and whitespace-normalized.
    PSP never creates or guesses missing reference data.
    Unknown or ambiguous values become review errors.
    """

    # -------------------------------------------------
    # Income Types
    # -------------------------------------------------
    cur.execute(
        """
        SELECT income_type_name
        FROM income_types
        WHERE spa_id = %s
        ORDER BY income_type_name
        """,
        (spa_id,),
    )

    income_type_lookup = {}

    for (income_type_name,) in cur.fetchall():
        normalized_value = (
            _normalize_import_dropdown_value(
                income_type_name
            )
        )

        if not normalized_value:
            continue

        income_type_lookup.setdefault(
            normalized_value,
            [],
        ).append(
            str(income_type_name).strip()
        )

    # -------------------------------------------------
    # Payment Methods
    # -------------------------------------------------
    cur.execute(
        """
        SELECT payment_method
        FROM payment_methods
        WHERE spa_id = %s
        ORDER BY payment_method
        """,
        (spa_id,),
    )

    payment_method_lookup = {}

    for (payment_method,) in cur.fetchall():
        normalized_value = (
            _normalize_import_dropdown_value(
                payment_method
            )
        )

        if not normalized_value:
            continue

        payment_method_lookup.setdefault(
            normalized_value,
            [],
        ).append(
            str(payment_method).strip()
        )

    # -------------------------------------------------
    # Clients
    # -------------------------------------------------
    cur.execute(
        """
        SELECT
            client_id,
            first_name,
            last_name
        FROM clients
        WHERE spa_id = %s
          AND business_unit_id = %s
        ORDER BY client_id
        """,
        (
            spa_id,
            business_unit_id,
        ),
    )

    client_lookup = {}

    for client_id, first_name, last_name in cur.fetchall():
        display_name = " ".join(
            part
            for part in (
                str(first_name or "").strip(),
                str(last_name or "").strip(),
            )
            if part
        )

        normalized_value = (
            _normalize_import_dropdown_value(
                display_name
            )
        )

        if not normalized_value:
            continue

        client_lookup.setdefault(
            normalized_value,
            [],
        ).append(
            client_id
        )

    for row in prepared_rows:
        data = row.get("data") or {}
        errors = list(
            row.get("errors") or []
        )

        # Income Type
        raw_income_type = data.get(
            "income_type",
            "",
        )

        normalized_income_type = (
            _normalize_import_dropdown_value(
                raw_income_type
            )
        )

        if normalized_income_type:
            matches = income_type_lookup.get(
                normalized_income_type,
                [],
            )

            if len(matches) == 1:
                data["income_type"] = matches[0]
            elif not matches:
                errors.append(
                    f"Income Type '{raw_income_type}' "
                    "does not exist in this business."
                )
            else:
                errors.append(
                    f"Income Type '{raw_income_type}' "
                    "matches more than one existing value."
                )

        # Payment Method
        raw_payment_method = data.get(
            "payment_method",
            "",
        )

        normalized_payment_method = (
            _normalize_import_dropdown_value(
                raw_payment_method
            )
        )

        if normalized_payment_method:
            matches = payment_method_lookup.get(
                normalized_payment_method,
                [],
            )

            if len(matches) == 1:
                data["payment_method"] = matches[0]
            elif not matches:
                errors.append(
                    f"Payment Method '{raw_payment_method}' "
                    "does not exist in this business."
                )
            else:
                errors.append(
                    f"Payment Method '{raw_payment_method}' "
                    "matches more than one existing value."
                )

        # Optional Client
        raw_client_name = data.get(
            "client_name",
            "",
        )

        normalized_client_name = (
            _normalize_import_dropdown_value(
                raw_client_name
            )
        )

        if not normalized_client_name:
            data["client_id"] = None
        else:
            matches = client_lookup.get(
                normalized_client_name,
                [],
            )

            if len(matches) == 1:
                data["client_id"] = matches[0]
            elif not matches:
                errors.append(
                    f"Client '{raw_client_name}' was not found "
                    "in this Provider Workspace."
                )
            else:
                errors.append(
                    f"Client '{raw_client_name}' matches more "
                    "than one client in this Provider Workspace."
                )

        row["errors"] = errors
        row["valid"] = not errors
        row["data"] = data

    return prepared_rows


def validate_expense_import_workspace_values(
    cur,
    *,
    spa_id,
    business_unit_id,
    prepared_rows,
):
    """
    Resolve Expense Import lookup values within the current business.

    Vendor Name, Expense Category, and Payment Method:
      - only active values are eligible
      - matching is case-insensitive and whitespace-normalized
      - unique matches use the existing PSP display value
      - unknown or ambiguous matches become validation errors
      - missing lookup records are never created

    Required-field validation happens in the row validator.
    """

    lookup_specs = (
        (
            "vendor_name",
            "Vendor Name",
            """
            SELECT vendors_name
            FROM vendor_name
            WHERE spa_id = %s
              AND is_active = TRUE
            ORDER BY vendor_id
            """,
        ),
        (
            "category",
            "Expense Category",
            """
            SELECT expense_cat_name
            FROM expense_categories
            WHERE spa_id = %s
              AND is_active = TRUE
            ORDER BY expense_cat_id
            """,
        ),
        (
            "payment_method",
            "Payment Method",
            """
            SELECT payment_method
            FROM payment_methods
            WHERE spa_id = %s
              AND is_active = TRUE
            ORDER BY payment_method_id
            """,
        ),
    )

    lookups = {}

    for field_key, field_label, query in lookup_specs:
        cur.execute(query, (spa_id,))

        values = {}

        for (stored_value,) in cur.fetchall():
            canonical_value = str(
                stored_value or ""
            ).strip()

            normalized_value = (
                _normalize_import_dropdown_value(
                    canonical_value
                )
            )

            if not normalized_value:
                continue

            values.setdefault(
                normalized_value,
                [],
            ).append(canonical_value)

        lookups[field_key] = values

    for row in prepared_rows:
        data = dict(row.get("data") or {})
        errors = list(row.get("errors") or [])

        for field_key, field_label, _ in lookup_specs:
            raw_value = str(
                data.get(field_key) or ""
            ).strip()

            normalized_value = (
                _normalize_import_dropdown_value(
                    raw_value
                )
            )

            if not normalized_value:
                continue

            matches = lookups[field_key].get(
                normalized_value,
                [],
            )

            if len(matches) == 1:
                data[field_key] = matches[0]

            elif not matches:
                errors.append(
                    f"{field_label} '{raw_value}' "
                    "does not match an active value "
                    "in this business."
                )

            else:
                errors.append(
                    f"{field_label} '{raw_value}' "
                    "matches more than one active value "
                    "in this business."
                )

        row["data"] = data
        row["errors"] = errors
        row["valid"] = not errors

    return prepared_rows


def validate_appointment_import_workspace_values(
    cur,
    *,
    spa_id,
    business_unit_id,
    prepared_rows,
):
    """
    Resolve database-backed Appointment import values.

    Client:
      - exact email and/or normalized phone when supplied
      - otherwise exact unique first + last name
      - client must belong to the current Provider Workspace
      - inactive clients remain eligible for historical imports

    Service:
      - exact normalized active Service Catalog name
      - service_type_id and canonical service name are resolved
      - catalog duration/price are retained as reference values only;
        missing imported historical values are not silently invented

    Provider:
      - blank / Any Available resolves to no employee assignment
      - otherwise exact nickname or full-name match
      - provider must be active in the current business

    Unknown, ambiguous, or conflicting reference data becomes a
    review error. PSP never guesses a reference record.
    """

    # -------------------------------------------------
    # Clients -- current Provider Workspace
    # -------------------------------------------------
    cur.execute(
        """
        SELECT
            client_id,
            first_name,
            last_name,
            phone,
            email
        FROM clients
        WHERE spa_id = %s
          AND business_unit_id = %s
        ORDER BY client_id
        """,
        (
            spa_id,
            business_unit_id,
        ),
    )

    client_email_lookup = {}
    client_phone_lookup = {}
    client_name_lookup = {}

    for (
        client_id,
        first_name,
        last_name,
        phone,
        email,
    ) in cur.fetchall():
        normalized_email = _normalize_import_email(
            email
        )

        normalized_phone = normalize_client_import_phone(
            phone
        )

        normalized_name = " ".join(
            part
            for part in (
                normalize_client_import_name(first_name),
                normalize_client_import_name(last_name),
            )
            if part
        )

        if normalized_email:
            client_email_lookup.setdefault(
                normalized_email,
                [],
            ).append(client_id)

        if normalized_phone:
            client_phone_lookup.setdefault(
                normalized_phone,
                [],
            ).append(client_id)

        if normalized_name:
            client_name_lookup.setdefault(
                normalized_name,
                [],
            ).append(client_id)

    # -------------------------------------------------
    # Services -- active Service Catalog for business
    # -------------------------------------------------
    cur.execute(
        """
        SELECT
            service_type_id,
            service_name,
            default_duration_minutes,
            default_price
        FROM service_name_types
        WHERE spa_id = %s
          AND is_active = TRUE
        ORDER BY service_type_id
        """,
        (spa_id,),
    )

    service_lookup = {}

    for (
        service_type_id,
        service_name,
        default_duration_minutes,
        default_price,
    ) in cur.fetchall():
        normalized_service = (
            _normalize_import_dropdown_value(
                service_name
            )
        )

        if not normalized_service:
            continue

        service_lookup.setdefault(
            normalized_service,
            [],
        ).append({
            "service_type_id": service_type_id,
            "service_name": str(
                service_name or ""
            ).strip(),
            "default_duration_minutes": (
                default_duration_minutes
            ),
            "default_price": default_price,
        })

    # -------------------------------------------------
    # Providers -- active employees for business
    # -------------------------------------------------
    cur.execute(
        """
        SELECT
            employee_id,
            first_name,
            last_name,
            employee_nickname
        FROM employees
        WHERE spa_id = %s
          AND is_active = TRUE
        ORDER BY employee_id
        """,
        (spa_id,),
    )

    provider_lookup = {}

    for (
        employee_id,
        first_name,
        last_name,
        employee_nickname,
    ) in cur.fetchall():
        first_name = str(
            first_name or ""
        ).strip()

        last_name = str(
            last_name or ""
        ).strip()

        nickname = str(
            employee_nickname or ""
        ).strip()

        full_name = " ".join(
            part
            for part in (
                first_name,
                last_name,
            )
            if part
        )

        provider_snapshot = (
            nickname
            or full_name
            or "Provider"
        )

        match_names = {
            _normalize_import_dropdown_value(
                value
            )
            for value in (
                nickname,
                full_name,
            )
            if str(value or "").strip()
        }

        for normalized_provider in match_names:
            provider_lookup.setdefault(
                normalized_provider,
                {},
            )[employee_id] = provider_snapshot

    # -------------------------------------------------
    # Resolve every prepared row
    # -------------------------------------------------
    for row in prepared_rows:
        data = row.get("data") or {}

        errors = list(
            row.get("errors") or []
        )

        # ---------------------------------------------
        # Client
        # ---------------------------------------------
        raw_email = _normalize_import_email(
            data.get(
                "client_email",
                "",
            )
        )

        raw_phone = normalize_client_import_phone(
            data.get(
                "client_phone",
                "",
            )
        )

        strong_client_ids = []
        strong_identifier_supplied = False

        if raw_email:
            strong_identifier_supplied = True

            email_matches = client_email_lookup.get(
                raw_email,
                [],
            )

            if len(email_matches) == 1:
                strong_client_ids.append(
                    email_matches[0]
                )
            elif not email_matches:
                errors.append(
                    f"Client Email '{raw_email}' was not found "
                    "in this Provider Workspace."
                )
            else:
                errors.append(
                    f"Client Email '{raw_email}' matches more "
                    "than one client in this Provider Workspace."
                )

        if raw_phone:
            strong_identifier_supplied = True

            phone_matches = client_phone_lookup.get(
                raw_phone,
                [],
            )

            if len(phone_matches) == 1:
                strong_client_ids.append(
                    phone_matches[0]
                )
            elif not phone_matches:
                errors.append(
                    "Client Phone was not found in this "
                    "Provider Workspace."
                )
            else:
                errors.append(
                    "Client Phone matches more than one client "
                    "in this Provider Workspace."
                )

        if strong_identifier_supplied:
            unique_client_ids = set(
                strong_client_ids
            )

            if len(unique_client_ids) == 1:
                data["client_id"] = next(
                    iter(unique_client_ids)
                )
            elif len(unique_client_ids) > 1:
                errors.append(
                    "Client Email and Client Phone resolve to "
                    "different clients. Review this row."
                )

        else:
            first_name = normalize_client_import_name(
                data.get(
                    "client_first_name",
                    "",
                )
            )

            last_name = normalize_client_import_name(
                data.get(
                    "client_last_name",
                    "",
                )
            )

            normalized_name = " ".join(
                part
                for part in (
                    first_name,
                    last_name,
                )
                if part
            )

            name_matches = client_name_lookup.get(
                normalized_name,
                [],
            )

            if len(name_matches) == 1:
                data["client_id"] = name_matches[0]
            elif not name_matches:
                errors.append(
                    "Client name was not found in this "
                    "Provider Workspace."
                )
            else:
                errors.append(
                    "Client name matches more than one client "
                    "in this Provider Workspace. Map Email or "
                    "Phone to identify the correct client."
                )

        # ---------------------------------------------
        # Appointment lifecycle context
        # ---------------------------------------------
        appointment_status = str(
            data.get("status") or ""
        ).strip().lower()

        historical_statuses = {
            "completed",
            "cancelled",
            "no_show",
        }

        is_historical = (
            appointment_status in historical_statuses
        )

        # ---------------------------------------------
        # Appointment lifecycle context
        # ---------------------------------------------
        appointment_status = str(
            data.get("status") or ""
        ).strip().lower()

        historical_statuses = {
            "completed",
            "cancelled",
            "no_show",
        }

        is_historical = (
            appointment_status in historical_statuses
        )

        # ---------------------------------------------
        # Service
        # ---------------------------------------------
        raw_service_name = str(
            data.get(
                "service_name",
                "",
            )
            or ""
        ).strip()

        # Always preserve the source-facing service name as the
        # booking-time snapshot, even when a current PSP Service
        # Catalog record resolves successfully.
        data["external_service_name"] = raw_service_name

        normalized_service = (
            _normalize_import_dropdown_value(
                raw_service_name
            )
        )

        service_matches = service_lookup.get(
            normalized_service,
            [],
        )

        if len(service_matches) == 1:
            service = service_matches[0]

            data["service_type_id"] = (
                service["service_type_id"]
            )

            # service_name becomes the current canonical PSP service
            # name used by the operational appointment record.
            data["service_name"] = (
                service["service_name"]
            )

            data[
                "service_default_duration_minutes"
            ] = service[
                "default_duration_minutes"
            ]

            default_price = service[
                "default_price"
            ]

            data["service_default_price"] = (
                format(
                    default_price,
                    ".2f",
                )
                if default_price is not None
                else None
            )

        elif not service_matches:
            if is_historical:
                # Historical records may reference a discontinued
                # service. Preserve the source snapshot without
                # inventing a current Service Catalog relationship.
                data["service_type_id"] = None
                data["service_name"] = raw_service_name
                data[
                    "service_default_duration_minutes"
                ] = None
                data["service_default_price"] = None

            else:
                errors.append(
                    f"Service '{raw_service_name}' does not match "
                    "an active Service Catalog service."
                )

        else:
            # Never guess between multiple current PSP records.
            errors.append(
                f"Service '{raw_service_name}' matches more "
                "than one active Service Catalog service."
            )

        # ---------------------------------------------
        # Provider
        # ---------------------------------------------
        raw_provider_name = str(
            data.get(
                "provider_name",
                "",
            )
            or ""
        ).strip()

        normalized_provider = (
            _normalize_import_dropdown_value(
                raw_provider_name
            )
        )

        any_provider_values = {
            "",
            "any",
            "any available",
            "any provider",
            "no preference",
            "unassigned",
        }

        if normalized_provider in any_provider_values:
            data["provider_employee_id"] = None
            data["provider_name_at_booking"] = (
                "Any Available"
            )

        else:
            provider_matches = provider_lookup.get(
                normalized_provider,
                {},
            )

            if len(provider_matches) == 1:
                (
                    provider_employee_id,
                    _provider_snapshot,
                ) = next(
                    iter(
                        provider_matches.items()
                    )
                )

                data["provider_employee_id"] = (
                    provider_employee_id
                )

                # Preserve exactly what the source file called this
                # provider as the booking-time snapshot.
                data["provider_name_at_booking"] = (
                    raw_provider_name
                )

            elif not provider_matches:
                if is_historical:
                    # Former providers are valid historical context.
                    # Preserve the source name without assigning it to
                    # a current employee record.
                    data["provider_employee_id"] = None
                    data["provider_name_at_booking"] = (
                        raw_provider_name
                    )

                else:
                    errors.append(
                        f"Provider '{raw_provider_name}' was not "
                        "found as an active employee in this business."
                    )

            else:
                # Ambiguous current matches remain an error even for
                # historical rows. PSP never guesses identities.
                errors.append(
                    f"Provider '{raw_provider_name}' matches more "
                    "than one active employee in this business."
                )

        row["errors"] = errors
        row["valid"] = not errors
        row["data"] = data

    return prepared_rows


def validate_client_import_workspace_dropdowns(
    cur,
    *,
    spa_id,
    business_unit_id,
    prepared_rows,
):
    """
    Resolve database-backed Client Information dropdown values.

    User Def 1 / skin_type_id:
      imported Skin Type display value -> active spa skin_type_id

    User Def 2 / fitzpatrick_id:
      imported Fitzpatrick display value -> active spa fitzpatrick_id

    Values are matched exactly after case/whitespace normalization.
    Blank values remain blank. Unknown values are review errors.
    """

    resolved_labels = get_client_information_labels(
        cur,
        spa_id=spa_id,
        business_unit_id=business_unit_id,
    )

    dropdown_specs = (
        {
            "field_key": "skin_type_id",
            "table": "skin_types",
            "id_column": "skin_type_id",
            "value_column": "skin_type_name",
        },
        {
            "field_key": "fitzpatrick_id",
            "table": "fitzpatrick_types",
            "id_column": "fitzpatrick_id",
            "value_column": "fitzpatrick_level",
        },
    )

    for spec in dropdown_specs:
        cur.execute(
            f"""
                SELECT
                    {spec["id_column"]},
                    {spec["value_column"]}
                FROM {spec["table"]}
                WHERE spa_id = %s
                  AND is_active = TRUE
                ORDER BY {spec["id_column"]}
            """,
            (spa_id,),
        )

        options = cur.fetchall()

        option_lookup = {}

        for option_id, option_value in options:
            normalized_value = (
                _normalize_import_dropdown_value(
                    option_value
                )
            )

            if not normalized_value:
                continue

            option_lookup.setdefault(
                normalized_value,
                [],
            ).append(
                option_id
            )

        field_key = spec["field_key"]

        field_label = (
            resolved_labels.get(field_key)
            or field_key
        )

        for row in prepared_rows:
            data = row.get("data") or {}

            if field_key not in data:
                continue

            raw_value = data.get(field_key)

            normalized_value = (
                _normalize_import_dropdown_value(
                    raw_value
                )
            )

            if not normalized_value:
                data[field_key] = ""
                continue

            matches = option_lookup.get(
                normalized_value,
                [],
            )

            if len(matches) == 1:
                data[field_key] = matches[0]
                continue

            errors = list(
                row.get("errors") or []
            )

            if not options:
                errors.append(
                    f"{field_label} has no active dropdown "
                    "options configured. Leave this field "
                    "unmapped or configure its options before "
                    "importing."
                )
            elif len(matches) > 1:
                errors.append(
                    f"{field_label} value '{raw_value}' matches "
                    "more than one active option."
                )
            else:
                errors.append(
                    f"{field_label} value '{raw_value}' does "
                    "not match an active dropdown option."
                )

            row["errors"] = errors
            row["valid"] = False

    return prepared_rows


def prepare_import_rows(
    parsed_import,
    mapping,
    *,
    entity_type="clients",
):
    """
    Apply a reviewed mapping and entity validation to every source row.

    Still performs no database writes.
    """

    prepared_rows = []

    for source_row in parsed_import.get(
        "rows",
        []
    ):
        mapped = apply_import_mapping(
            source_row.get(
                "values",
                []
            ),
            mapping,
            entity_type=entity_type,
        )

        if entity_type == "clients":
            validation = (
                validate_client_import_row(
                    mapped
                )
            )
        elif entity_type == "income":
            validation = (
                validate_income_import_row(
                    mapped
                )
            )
        elif entity_type == "appointments":
            validation = (
                validate_appointment_import_row(
                    mapped
                )
            )
        elif entity_type == "peachpos_income":
            validation = (
                validate_peachpos_income_import_row(
                    mapped
                )
            )
        else:
            raise ImportServiceError(
                f"Unsupported import type: {entity_type}."
            )

        prepared_rows.append({
            "row_number": source_row.get(
                "row_number"
            ),
            "valid": validation["valid"],
            "data": validation["data"],
            "errors": validation["errors"],
        })

    return prepared_rows


# =========================================================
# CLIENT IMPORT DUPLICATE DETECTION
# =========================================================

def normalize_client_import_name(value):
    return " ".join(
        str(value or "")
        .strip()
        .lower()
        .split()
    )


def normalize_client_import_phone(value):
    digits = re.sub(
        r"[^0-9]",
        "",
        str(value or ""),
    )

    if (
        len(digits) == 11
        and digits.startswith("1")
    ):
        digits = digits[1:]

    return digits


def annotate_client_import_file_duplicates(
    prepared_rows,
):
    """
    Detect duplicates within one uploaded Client file.

    Strong duplicate:
      - exact normalized email
      - exact normalized phone

    Possible duplicate:
      - exact normalized first + last name only

    Invalid rows are left invalid and are not used as duplicate anchors.
    """

    seen_emails = {}
    seen_phones = {}
    seen_names = {}

    annotated_rows = []

    for row in prepared_rows:
        result = dict(row)

        result["duplicate_type"] = None
        result["duplicate_reasons"] = []
        result["duplicate_row_numbers"] = []

        if not result.get("valid"):
            annotated_rows.append(
                result
            )
            continue

        data = result.get(
            "data",
            {},
        )

        row_number = result.get(
            "row_number"
        )

        email = _normalize_import_email(
            data.get(
                "email",
                "",
            )
        )

        phone = normalize_client_import_phone(
            data.get(
                "phone",
                "",
            )
        )

        first_name = normalize_client_import_name(
            data.get(
                "first_name",
                "",
            )
        )

        last_name = normalize_client_import_name(
            data.get(
                "last_name",
                "",
            )
        )

        name_key = (
            first_name,
            last_name,
        )

        strong_matches = []
        possible_matches = []

        if (
            email
            and email in seen_emails
        ):
            strong_matches.append((
                "Email",
                seen_emails[email],
            ))

        if (
            phone
            and phone in seen_phones
        ):
            strong_matches.append((
                "Phone",
                seen_phones[phone],
            ))

        if (
            first_name
            and last_name
            and name_key in seen_names
        ):
            possible_matches.append((
                "Name",
                seen_names[name_key],
            ))

        if strong_matches:
            result["duplicate_type"] = (
                "strong"
            )

            result["duplicate_reasons"] = sorted({
                reason
                for reason, _row
                in strong_matches
            })

            result["duplicate_row_numbers"] = sorted({
                duplicate_row
                for _reason, duplicate_row
                in strong_matches
            })

        elif possible_matches:
            result["duplicate_type"] = (
                "possible"
            )

            result["duplicate_reasons"] = [
                "Name"
            ]

            result["duplicate_row_numbers"] = sorted({
                duplicate_row
                for _reason, duplicate_row
                in possible_matches
            })

        annotated_rows.append(
            result
        )

        # Only the first occurrence becomes the anchor.
        # This keeps repeated duplicates pointing back to the
        # original source row instead of forming a chain.
        if email:
            seen_emails.setdefault(
                email,
                row_number,
            )

        if phone:
            seen_phones.setdefault(
                phone,
                row_number,
            )

        if first_name and last_name:
            seen_names.setdefault(
                name_key,
                row_number,
            )

    return annotated_rows


def annotate_client_import_existing_duplicates(
    cur,
    *,
    spa_id,
    business_unit_id,
    prepared_rows,
):
    """
    Compare prepared Client import rows against existing PSP clients.

    Uses the same authoritative duplicate checker as normal Add/Edit
    Client workflows.

    Strong duplicate:
      - exact normalized email
      - exact normalized phone

    Possible duplicate:
      - exact normalized first + last name only

    This function performs database reads only.
    """

    annotated_rows = []

    for row in prepared_rows:
        result = dict(row)

        result["existing_duplicate_type"] = None
        result["existing_duplicate_matches"] = []

        if not result.get("valid"):
            annotated_rows.append(
                result
            )
            continue

        data = result.get(
            "data",
            {},
        )

        duplicates = find_possible_client_duplicates(
            cur=cur,
            spa_id=spa_id,
            business_unit_id=business_unit_id,
            first_name=data.get(
                "first_name",
                "",
            ),
            last_name=data.get(
                "last_name",
                "",
            ),
            phone=data.get(
                "phone",
                "",
            ),
            email=data.get(
                "email",
                "",
            ),
        )

        if duplicates:
            has_strong_match = any(
                duplicate.get(
                    "strong_match"
                )
                for duplicate in duplicates
            )

            result["existing_duplicate_type"] = (
                "strong"
                if has_strong_match
                else "possible"
            )

            result["existing_duplicate_matches"] = (
                duplicates
            )

        annotated_rows.append(
            result
        )

    return annotated_rows



def annotate_income_import_file_duplicates(
    prepared_rows,
):
    """
    Detect strong duplicates inside one standard Income import file.

    Strong duplicate:
      exact nonblank Processor Payment ID

    Date/amount/type/payment method alone are not sufficient because
    legitimate income records can share those values.
    """
    seen_payment_ids = {}
    annotated_rows = []

    for row in prepared_rows:
        result = dict(row)

        result["duplicate_type"] = None
        result["duplicate_reasons"] = []
        result["duplicate_row_numbers"] = []

        if not result.get("valid"):
            annotated_rows.append(result)
            continue

        data = result.get("data") or {}

        processor_payment_id = str(
            data.get("processor_payment_id") or ""
        ).strip()

        row_number = result.get("row_number")

        if (
            processor_payment_id
            and processor_payment_id in seen_payment_ids
        ):
            result["duplicate_type"] = "strong"
            result["duplicate_reasons"] = [
                "Processor Payment ID"
            ]
            result["duplicate_row_numbers"] = [
                seen_payment_ids[processor_payment_id]
            ]

        annotated_rows.append(result)

        if processor_payment_id:
            seen_payment_ids.setdefault(
                processor_payment_id,
                row_number,
            )

    return annotated_rows


def annotate_income_import_existing_duplicates(
    cur,
    *,
    spa_id,
    business_unit_id,
    prepared_rows,
):
    """
    Compare standard Income rows against existing PSP Income.

    Strong duplicate:
      workspace + exact nonblank Processor Payment ID
    """
    payment_ids = sorted({
        str(
            (row.get("data") or {}).get(
                "processor_payment_id"
            )
            or ""
        ).strip()
        for row in prepared_rows
        if row.get("valid")
        and str(
            (row.get("data") or {}).get(
                "processor_payment_id"
            )
            or ""
        ).strip()
    })

    existing_by_payment_id = {}

    if payment_ids:
        cur.execute(
            """
            SELECT
                income_id,
                processor_payment_id,
                income_date,
                income_type,
                total_amount
            FROM income
            WHERE spa_id = %s
              AND business_unit_id = %s
              AND processor_payment_id = ANY(%s)
            """,
            (
                spa_id,
                business_unit_id,
                payment_ids,
            ),
        )

        for (
            income_id,
            processor_payment_id,
            income_date,
            income_type,
            total_amount,
        ) in cur.fetchall():
            payment_id = str(
                processor_payment_id or ""
            ).strip()

            if not payment_id:
                continue

            existing_by_payment_id.setdefault(
                payment_id,
                [],
            ).append({
                "income_id": income_id,
                "processor_payment_id": payment_id,
                "income_date": (
                    income_date.isoformat()
                    if income_date
                    else None
                ),
                "income_type": income_type,
                "total_amount": (
                    str(total_amount)
                    if total_amount is not None
                    else None
                ),
            })

    annotated_rows = []

    for row in prepared_rows:
        result = dict(row)

        result["existing_duplicate_type"] = None
        result["existing_duplicate_matches"] = []

        if not result.get("valid"):
            annotated_rows.append(result)
            continue

        data = result.get("data") or {}

        processor_payment_id = str(
            data.get("processor_payment_id") or ""
        ).strip()

        if processor_payment_id:
            matches = existing_by_payment_id.get(
                processor_payment_id,
                [],
            )

            if matches:
                result["existing_duplicate_type"] = "strong"
                result["existing_duplicate_matches"] = matches

        annotated_rows.append(result)

    return annotated_rows


def _appointment_import_duplicate_service_identity(data):
    """
    Build the service portion of an Appointment possible-duplicate key.

    Prefer the resolved PSP Service Catalog identity when one exists.
    Historical rows may legitimately have no current service_type_id,
    so fall back to the normalized booking-time service snapshot.

    This identity is used only for possible-duplicate review. Strong
    external-source duplicate protection remains separate.
    """
    service_type_id = data.get("service_type_id")

    if service_type_id is not None:
        return (
            "service_type_id",
            service_type_id,
        )

    service_snapshot = str(
        data.get("external_service_name")
        or data.get("service_name")
        or ""
    ).strip()

    normalized_snapshot = (
        _normalize_import_dropdown_value(
            service_snapshot
        )
    )

    if normalized_snapshot:
        return (
            "service_snapshot",
            normalized_snapshot,
        )

    return None


def annotate_expense_import_file_duplicates(prepared_rows):
    """Detect strong and possible duplicates within an Expense file."""
    seen_ids = {}
    seen_values = {}
    results = []

    for original in prepared_rows:
        row = dict(original)
        row["duplicate_type"] = None
        row["duplicate_reasons"] = []
        row["duplicate_row_numbers"] = []

        if not row.get("valid"):
            results.append(row)
            continue

        data = row.get("data") or {}
        source = _normalize_import_dropdown_value(
            data.get("transaction_source")
        )
        external_id = str(
            data.get("external_transaction_id") or ""
        ).strip()
        identity = (source, external_id) if source and external_id else None

        expense_date = str(data.get("expense_date") or "").strip()
        vendor = _normalize_import_dropdown_value(data.get("vendor_name"))
        fingerprint = None

        try:
            amount = Decimal(str(data.get("amount") or ""))
            if expense_date and vendor and amount.is_finite():
                fingerprint = (expense_date, vendor, amount)
        except InvalidOperation:
            pass

        if identity and identity in seen_ids:
            row["duplicate_type"] = "strong"
            row["duplicate_reasons"] = ["Source + Transaction ID"]
            row["duplicate_row_numbers"] = [seen_ids[identity]]
        elif fingerprint and fingerprint in seen_values:
            row["duplicate_type"] = "possible"
            row["duplicate_reasons"] = ["Date + Vendor + Amount"]
            row["duplicate_row_numbers"] = [seen_values[fingerprint]]

        if identity:
            seen_ids.setdefault(identity, row["row_number"])
        if fingerprint:
            seen_values.setdefault(fingerprint, row["row_number"])

        results.append(row)

    return results


def annotate_expense_import_existing_duplicates(
    cur, *, spa_id, business_unit_id, prepared_rows
):
    """Find possible matches against existing workspace Expenses."""
    from collections import defaultdict

    dates = sorted({
        str((r.get("data") or {}).get("expense_date") or "")
        for r in prepared_rows if r.get("valid")
    } - {""})

    existing = defaultdict(list)

    # Query bounded groups of dates using the workspace/date index.
    for start in range(0, len(dates), 200):
        cur.execute("""
            SELECT expense_id, expense_date, vendor_name,
                   amount, category, payment_method
            FROM expenses
            WHERE spa_id = %s
              AND business_unit_id = %s
              AND expense_date = ANY(%s::date[])
        """, (
            spa_id, business_unit_id, dates[start:start + 200]
        ))

        for eid, edate, vendor, amount, category, method in cur:
            if not vendor or amount is None:
                continue
            key = (
                edate.isoformat(),
                _normalize_import_dropdown_value(vendor),
                Decimal(str(amount)),
            )
            if len(existing[key]) < 5:
                existing[key].append({
                    "expense_id": eid,
                    "expense_date": edate.isoformat(),
                    "vendor_name": vendor,
                    "amount": str(amount),
                    "category": category,
                    "payment_method": method,
                })

    results = []
    for original in prepared_rows:
        row = dict(original)
        row["existing_duplicate_type"] = None
        row["existing_duplicate_matches"] = []

        if row.get("valid"):
            data = row.get("data") or {}
            try:
                key = (
                    str(data.get("expense_date") or ""),
                    _normalize_import_dropdown_value(
                        data.get("vendor_name")
                    ),
                    Decimal(str(data.get("amount") or "")),
                )
                matches = existing.get(key, [])
                if matches:
                    row["existing_duplicate_type"] = "possible"
                    row["existing_duplicate_matches"] = matches
            except InvalidOperation:
                pass

        results.append(row)

    return results


def annotate_expense_import_existing_identity_duplicates(
    cur, *, spa_id, business_unit_id, prepared_rows
):
    """Detect existing Expenses with matching external identity."""
    identities = set()

    for row in prepared_rows:
        if not row.get("valid"):
            continue
        data = row.get("data") or {}
        source = _normalize_import_dropdown_value(
            data.get("transaction_source")
        )
        external_id = str(
            data.get("external_transaction_id") or ""
        ).strip()
        if source and external_id:
            identities.add((source, external_id))

    identities = sorted(identities)
    existing = {}

    for start in range(0, len(identities), 200):
        batch = identities[start:start + 200]

        cur.execute("""
            SELECT e.expense_id, e.transaction_source,
                   e.external_transaction_id, e.expense_date,
                   e.vendor_name, e.amount
            FROM expenses e
            JOIN UNNEST(
                %s::text[], %s::text[]
            ) AS wanted(source_key, external_id)
              ON LOWER(REGEXP_REPLACE(
                   BTRIM(e.transaction_source),
                   '[[:space:]]+', ' ', 'g'
                 )) = wanted.source_key
             AND BTRIM(e.external_transaction_id) =
                 wanted.external_id
            WHERE e.spa_id = %s
              AND e.business_unit_id = %s
        """, (
            [pair[0] for pair in batch],
            [pair[1] for pair in batch],
            spa_id,
            business_unit_id,
        ))

        for eid, src, txid, day, vendor, amount in cur.fetchall():
            key = (
                _normalize_import_dropdown_value(src),
                str(txid).strip(),
            )
            existing[key] = {
                "expense_id": eid,
                "transaction_source": src,
                "external_transaction_id": txid,
                "expense_date": day.isoformat(),
                "vendor_name": vendor,
                "amount": str(amount),
            }

    results = []

    for original in prepared_rows:
        row = dict(original)

        if row.get("valid"):
            data = row.get("data") or {}
            key = (
                _normalize_import_dropdown_value(
                    data.get("transaction_source")
                ),
                str(
                    data.get("external_transaction_id") or ""
                ).strip(),
            )
            match = existing.get(key)

            if match:
                row["existing_duplicate_type"] = "strong"
                row["existing_duplicate_matches"] = [match]

        results.append(row)

    return results


def annotate_appointment_import_file_duplicates(
    prepared_rows,
):
    """
    Detect duplicate Appointment rows inside one uploaded file.

    Strong duplicate:
      exact normalized Booking System / Source
      + exact nonblank External Appointment ID

    Possible duplicate:
      same resolved client
      + appointment date
      + appointment time
      + resolved Service Catalog identity, or historical
        booking-time service snapshot

    Possible matches require review rather than automatic rejection.
    """

    seen_external_ids = {}
    seen_appointment_keys = {}
    annotated_rows = []

    for row in prepared_rows:
        result = dict(row)

        result["duplicate_type"] = None
        result["duplicate_reasons"] = []
        result["duplicate_row_numbers"] = []

        if not result.get("valid"):
            annotated_rows.append(result)
            continue

        data = result.get("data") or {}
        row_number = result.get("row_number")

        external_source = (
            _normalize_import_dropdown_value(
                data.get(
                    "external_source",
                    "",
                )
            )
        )

        external_order_id = str(
            data.get(
                "external_order_id",
                "",
            )
            or ""
        ).strip()

        external_key = None

        if external_source and external_order_id:
            external_key = (
                external_source,
                external_order_id,
            )

        appointment_key = (
            data.get("client_id"),
            str(
                data.get(
                    "appointment_date",
                    "",
                )
                or ""
            ).strip(),
            str(
                data.get(
                    "appointment_time",
                    "",
                )
                or ""
            ).strip(),
            _appointment_import_duplicate_service_identity(
                data
            ),
        )

        if (
            external_key
            and external_key in seen_external_ids
        ):
            result["duplicate_type"] = "strong"
            result["duplicate_reasons"] = [
                "Booking System / Source + External Appointment ID"
            ]
            result["duplicate_row_numbers"] = [
                seen_external_ids[external_key]
            ]

        elif (
            all(
                value not in (
                    None,
                    "",
                )
                for value in appointment_key
            )
            and appointment_key in seen_appointment_keys
        ):
            result["duplicate_type"] = "possible"
            result["duplicate_reasons"] = [
                "Client + Date + Time + Service"
            ]
            result["duplicate_row_numbers"] = [
                seen_appointment_keys[
                    appointment_key
                ]
            ]

        annotated_rows.append(result)

        if external_key:
            seen_external_ids.setdefault(
                external_key,
                row_number,
            )

        if all(
            value not in (
                None,
                "",
            )
            for value in appointment_key
        ):
            seen_appointment_keys.setdefault(
                appointment_key,
                row_number,
            )

    return annotated_rows


def annotate_appointment_import_existing_duplicates(
    cur,
    *,
    spa_id,
    business_unit_id,
    prepared_rows,
):
    """
    Compare prepared Appointment rows against existing PSP appointments.

    Strong duplicate:
      same business
      + normalized Booking System / Source
      + exact External Appointment ID

    Possible duplicate:
      same Provider Workspace
      + resolved client
      + appointment date
      + appointment time
      + resolved Service Catalog identity, or historical
        booking-time service snapshot

    Database reads only. Nothing is inserted or changed here.
    """

    external_pairs = {
        (
            _normalize_import_dropdown_value(
                (row.get("data") or {}).get(
                    "external_source",
                    "",
                )
            ),
            str(
                (row.get("data") or {}).get(
                    "external_order_id",
                    "",
                )
                or ""
            ).strip(),
        )
        for row in prepared_rows
        if row.get("valid")
        and _normalize_import_dropdown_value(
            (row.get("data") or {}).get(
                "external_source",
                "",
            )
        )
        and str(
            (row.get("data") or {}).get(
                "external_order_id",
                "",
            )
            or ""
        ).strip()
    }

    appointment_keys = {
        (
            (row.get("data") or {}).get(
                "client_id"
            ),
            str(
                (row.get("data") or {}).get(
                    "appointment_date",
                    "",
                )
                or ""
            ).strip(),
            str(
                (row.get("data") or {}).get(
                    "appointment_time",
                    "",
                )
                or ""
            ).strip(),
            _appointment_import_duplicate_service_identity(
                row.get("data") or {}
            ),
        )
        for row in prepared_rows
        if row.get("valid")
        and (row.get("data") or {}).get(
            "client_id"
        ) is not None
        and str(
            (row.get("data") or {}).get(
                "appointment_date",
                "",
            )
            or ""
        ).strip()
        and str(
            (row.get("data") or {}).get(
                "appointment_time",
                "",
            )
            or ""
        ).strip()
        and _appointment_import_duplicate_service_identity(
            row.get("data") or {}
        ) is not None
    }

    existing_by_external = {}
    existing_by_appointment = {}

    if external_pairs:
        external_ids = sorted({
            external_id
            for _source, external_id
            in external_pairs
        })

        cur.execute(
            """
            SELECT
                appointment_id,
                external_source,
                external_order_id,
                appointment_date,
                appointment_time,
                client_id,
                service_type_id,
                provider_employee_id,
                status
            FROM appointments
            WHERE spa_id = %s
              AND external_order_id = ANY(%s)
            """,
            (
                spa_id,
                external_ids,
            ),
        )

        for (
            appointment_id,
            external_source,
            external_order_id,
            appointment_date,
            appointment_time,
            client_id,
            service_type_id,
            provider_employee_id,
            status,
        ) in cur.fetchall():
            source_key = (
                _normalize_import_dropdown_value(
                    external_source
                )
            )

            external_id = str(
                external_order_id or ""
            ).strip()

            pair_key = (
                source_key,
                external_id,
            )

            if (
                source_key
                and external_id
                and pair_key in external_pairs
            ):
                existing_by_external.setdefault(
                    pair_key,
                    [],
                ).append({
                    "appointment_id": appointment_id,
                    "external_source": external_source,
                    "external_order_id": external_id,
                    "appointment_date": (
                        appointment_date.isoformat()
                        if appointment_date
                        else None
                    ),
                    "appointment_time": (
                        appointment_time.isoformat()
                        if appointment_time
                        else None
                    ),
                    "client_id": client_id,
                    "service_type_id": service_type_id,
                    "provider_employee_id": (
                        provider_employee_id
                    ),
                    "status": status,
                })

    if appointment_keys:
        client_ids = sorted({
            key[0]
            for key in appointment_keys
        })

        appointment_dates = sorted({
            key[1]
            for key in appointment_keys
        })

        cur.execute(
            """
            SELECT
                appointment_id,
                client_id,
                appointment_date,
                appointment_time,
                service_type_id,
                external_service_name,
                service_type,
                provider_employee_id,
                external_source,
                external_order_id,
                status
            FROM appointments
            WHERE spa_id = %s
              AND business_unit_id = %s
              AND client_id = ANY(%s)
              AND appointment_date = ANY(%s::date[])
            """,
            (
                spa_id,
                business_unit_id,
                client_ids,
                appointment_dates,
            ),
        )

        for (
            appointment_id,
            client_id,
            appointment_date,
            appointment_time,
            service_type_id,
            external_service_name,
            service_type,
            provider_employee_id,
            external_source,
            external_order_id,
            status,
        ) in cur.fetchall():
            key = (
                client_id,
                (
                    appointment_date.isoformat()
                    if appointment_date
                    else ""
                ),
                (
                    appointment_time.isoformat()
                    if appointment_time
                    else ""
                ),
                _appointment_import_duplicate_service_identity({
                    "service_type_id": service_type_id,
                    "external_service_name": external_service_name,
                    "service_name": service_type,
                }),
            )

            if key not in appointment_keys:
                continue

            existing_by_appointment.setdefault(
                key,
                [],
            ).append({
                "appointment_id": appointment_id,
                "client_id": client_id,
                "appointment_date": key[1],
                "appointment_time": key[2],
                "service_type_id": service_type_id,
                "provider_employee_id": (
                    provider_employee_id
                ),
                "external_source": external_source,
                "external_order_id": (
                    external_order_id
                ),
                "status": status,
            })

    annotated_rows = []

    for row in prepared_rows:
        result = dict(row)

        result["existing_duplicate_type"] = None
        result["existing_duplicate_matches"] = []

        if not result.get("valid"):
            annotated_rows.append(result)
            continue

        data = result.get("data") or {}

        external_key = (
            _normalize_import_dropdown_value(
                data.get(
                    "external_source",
                    "",
                )
            ),
            str(
                data.get(
                    "external_order_id",
                    "",
                )
                or ""
            ).strip(),
        )

        strong_matches = []

        if all(external_key):
            strong_matches = (
                existing_by_external.get(
                    external_key,
                    [],
                )
            )

        appointment_key = (
            data.get("client_id"),
            str(
                data.get(
                    "appointment_date",
                    "",
                )
                or ""
            ).strip(),
            str(
                data.get(
                    "appointment_time",
                    "",
                )
                or ""
            ).strip(),
            _appointment_import_duplicate_service_identity(
                data
            ),
        )

        possible_matches = (
            existing_by_appointment.get(
                appointment_key,
                [],
            )
            if all(
                value not in (
                    None,
                    "",
                )
                for value in appointment_key
            )
            else []
        )

        if strong_matches:
            result[
                "existing_duplicate_type"
            ] = "strong"

            result[
                "existing_duplicate_matches"
            ] = strong_matches

        elif possible_matches:
            result[
                "existing_duplicate_type"
            ] = "possible"

            result[
                "existing_duplicate_matches"
            ] = possible_matches

        annotated_rows.append(result)

    return annotated_rows


def annotate_peachpos_import_file_duplicates(
    prepared_rows,
):
    """
    Detect repeated processor transaction IDs inside one
    PeachPOS import file.

    Every Import Run belongs to one selected processor, so
    an exact repeated Processor Transaction ID is a strong
    duplicate within that file.
    """
    seen_payment_ids = {}
    annotated_rows = []

    for row in prepared_rows:
        result = dict(row)
        result["duplicate_type"] = None
        result["duplicate_reasons"] = []
        result["duplicate_row_numbers"] = []

        if not result.get("valid"):
            annotated_rows.append(result)
            continue

        data = result.get("data") or {}
        processor_payment_id = str(
            data.get("processor_payment_id") or ""
        ).strip()
        row_number = result.get("row_number")

        if (
            processor_payment_id
            and processor_payment_id in seen_payment_ids
        ):
            result["duplicate_type"] = "strong"
            result["duplicate_reasons"] = [
                "Processor Transaction ID"
            ]
            result["duplicate_row_numbers"] = [
                seen_payment_ids[processor_payment_id]
            ]

        annotated_rows.append(result)

        if processor_payment_id:
            seen_payment_ids.setdefault(
                processor_payment_id,
                row_number,
            )

    return annotated_rows


def annotate_peachpos_import_existing_duplicates(
    cur,
    *,
    spa_id,
    business_unit_id,
    credit_processor_id,
    prepared_rows,
):
    """
    Compare PeachPOS rows against already-posted Income.

    Strong duplicate identity:
      workspace + processor + Processor Transaction ID

    Transaction IDs belonging to a different processor do
    not collide.
    """
    try:
        credit_processor_id = int(credit_processor_id)
    except (TypeError, ValueError):
        raise ImportServiceError(
            "A valid credit processor is required for "
            "PeachPOS duplicate detection."
        )

    payment_ids = sorted({
        str(
            (row.get("data") or {}).get(
                "processor_payment_id"
            )
            or ""
        ).strip()
        for row in prepared_rows
        if row.get("valid")
        and str(
            (row.get("data") or {}).get(
                "processor_payment_id"
            )
            or ""
        ).strip()
    })

    existing_by_payment_id = {}

    if payment_ids:
        cur.execute(
            """
            SELECT
                income_id,
                processor_payment_id
            FROM income
            WHERE spa_id = %s
              AND business_unit_id = %s
              AND income_type = 'PeachPOS'
              AND credit_processor_id = %s
              AND processor_payment_id = ANY(%s)
            """,
            (
                spa_id,
                business_unit_id,
                credit_processor_id,
                payment_ids,
            ),
        )

        for income_id, processor_payment_id in cur.fetchall():
            payment_id = str(
                processor_payment_id or ""
            ).strip()
            if not payment_id:
                continue
            existing_by_payment_id.setdefault(
                payment_id,
                [],
            ).append({
                "income_id": income_id,
                "processor_payment_id": payment_id,
            })

    annotated_rows = []

    for row in prepared_rows:
        result = dict(row)
        result["existing_duplicate_type"] = None
        result["existing_duplicate_matches"] = []

        if not result.get("valid"):
            annotated_rows.append(result)
            continue

        data = result.get("data") or {}
        processor_payment_id = str(
            data.get("processor_payment_id") or ""
        ).strip()

        matches = existing_by_payment_id.get(
            processor_payment_id,
            [],
        )

        if matches:
            result["existing_duplicate_type"] = "strong"
            result["existing_duplicate_matches"] = matches

        annotated_rows.append(result)

    return annotated_rows


# =========================================================
# DURABLE IMPORT RUN STAGING
# =========================================================

def create_import_run(
    uploaded_file,
    *,
    spa_id,
    business_unit_id,
    entity_type,
    requested_by=None,
    allow_repeat=False,
    options=None,
):
    """
    Create one durable Import Engine run and stage its source rows.

    This persists the uploaded data for mapping/review, but does NOT
    create any entity records such as Clients, Income, Expenses,
    Loans, or Appointments.

    Exact-file retry protection prevents an accidental second upload
    of the same file while an earlier run is still actionable or has
    already completed.
    """

    profile = get_import_profile(
        entity_type
    )

    options_payload = dict(
        options or {}
    )

    parsed = parse_import_upload(
        uploaded_file
    )

    uploaded_file.stream.seek(0)
    payload = uploaded_file.stream.read()
    uploaded_file.stream.seek(0)

    source_size_bytes = len(payload)

    if source_size_bytes <= 0:
        raise ImportServiceError(
            "The selected import file is empty."
        )

    source_sha256 = hashlib.sha256(
        payload
    ).hexdigest()

    conn = get_db_connection()
    cur = conn.cursor()

    try:
        workspace_profile = get_workspace_import_profile(
            cur,
            spa_id=spa_id,
            business_unit_id=business_unit_id,
            entity_type=entity_type,
            options=options_payload,
        )

        mapping = suggest_import_mapping(
            parsed["headers"],
            entity_type=entity_type,
            profile=workspace_profile,
        )

        mapping_payload = {
            "headers": parsed["headers"],
            "suggestions": mapping,
        }

        if not allow_repeat:
            cur.execute(
                """
                SELECT
                    import_run_id,
                    run_status
                FROM import_runs
                WHERE spa_id = %s
                  AND business_unit_id = %s
                  AND entity_type = %s
                  AND source_sha256 = %s
                  AND run_status IN (
                      'mapping',
                      'review',
                      'ready',
                      'importing',
                      'completed'
                  )
                ORDER BY import_run_id DESC
                LIMIT 1
                """,
                (
                    spa_id,
                    business_unit_id,
                    profile["entity_type"],
                    source_sha256,
                ),
            )

            existing = cur.fetchone()

            if existing:
                raise ImportServiceError(
                    "This exact file has already been uploaded "
                    f"as Import Run #{existing[0]} "
                    f"({existing[1]})."
                )

        cur.execute(
            """
            INSERT INTO import_runs (
                spa_id,
                business_unit_id,
                entity_type,
                run_status,
                source_filename,
                source_extension,
                source_size_bytes,
                source_sha256,
                mapping_json,
                options_json,
                total_rows,
                requested_by
            )
            VALUES (
                %s, %s, %s, 'mapping',
                %s, %s, %s, %s, %s, %s, %s, %s
            )
            RETURNING import_run_id
            """,
            (
                spa_id,
                business_unit_id,
                profile["entity_type"],
                parsed["filename"],
                parsed["extension"],
                source_size_bytes,
                source_sha256,
                Json(mapping_payload),
                Json(options_payload),
                parsed["row_count"],
                requested_by,
            ),
        )

        import_run_id = cur.fetchone()[0]

        if parsed["rows"]:
            cur.executemany(
                """
                INSERT INTO import_run_rows (
                    import_run_id,
                    spa_id,
                    business_unit_id,
                    source_row_number,
                    source_data
                )
                VALUES (
                    %s, %s, %s, %s, %s
                )
                """,
                [
                    (
                        import_run_id,
                        spa_id,
                        business_unit_id,
                        source_row["row_number"],
                        Json({
                            "values": source_row["values"],
                        }),
                    )
                    for source_row in parsed["rows"]
                ],
            )

        conn.commit()

        return {
            "import_run_id": import_run_id,
            "entity_type": profile["entity_type"],
            "display_name": profile["display_name"],
            "filename": parsed["filename"],
            "extension": parsed["extension"],
            "source_size_bytes": source_size_bytes,
            "source_sha256": source_sha256,
            "headers": parsed["headers"],
            "mapping": mapping,
            "options": options_payload,
            "row_count": parsed["row_count"],
            "run_status": "mapping",
        }

    except Exception:
        conn.rollback()
        raise

    finally:
        cur.close()
        conn.close()


# =========================================================
# DURABLE IMPORT RUN ANALYSIS / REVIEW
# =========================================================

def analyze_import_run(
    import_run_id,
    *,
    spa_id,
    business_unit_id,
    mapping,
):
    """
    Apply the reviewed mapping to one durable staged Import Run.

    For Clients this:
      - validates required fields and field formats
      - detects duplicates inside the uploaded file
      - detects duplicates against existing PSP clients
      - persists review results per staged row
      - updates Import Run counters/status

    No Client records are created or changed here.
    """

    conn = get_db_connection()
    cur = conn.cursor()

    try:
        cur.execute(
            """
            SELECT
                entity_type,
                run_status,
                mapping_json,
                options_json
            FROM import_runs
            WHERE import_run_id = %s
              AND spa_id = %s
              AND business_unit_id = %s
            LIMIT 1
            """,
            (
                import_run_id,
                spa_id,
                business_unit_id,
            ),
        )

        run = cur.fetchone()

        if not run:
            raise ImportServiceError(
                "Import Run was not found in this workspace."
            )

        entity_type = str(
            run[0] or ""
        ).strip().lower()

        run_status = str(
            run[1] or ""
        ).strip().lower()

        existing_mapping_json = (
            run[2]
            if isinstance(run[2], dict)
            else {}
        )

        options_payload = (
            run[3]
            if isinstance(run[3], dict)
            else {}
        )

        if run_status in {
            "importing",
            "completed",
            "cancelled",
        }:
            raise ImportServiceError(
                "This Import Run can no longer be remapped."
            )

        profile = get_import_profile(
            entity_type
        )

        valid_target_keys = {
            field["key"]
            for field in profile["fields"]
        }

        required_target_keys = {
            field["key"]
            for field in profile["fields"]
            if field.get("required")
        }

        mapped_target_keys = []

        for item in mapping:
            target_key = str(
                item.get("target_key") or ""
            ).strip()

            if not target_key:
                continue

            if target_key not in valid_target_keys:
                raise ImportServiceError(
                    f"Unknown {profile['display_name']} import "
                    f"field: {target_key}."
                )

            mapped_target_keys.append(
                target_key
            )

        if len(mapped_target_keys) != len(
            set(mapped_target_keys)
        ):
            raise ImportServiceError(
                "More than one source column is mapped to the "
                "same PSP field."
            )

        missing_required = sorted(
            required_target_keys
            - set(mapped_target_keys)
        )

        if missing_required:
            labels_by_key = {
                field["key"]: field["label"]
                for field in profile["fields"]
            }

            missing_labels = [
                labels_by_key.get(
                    key,
                    key,
                )
                for key in missing_required
            ]

            raise ImportServiceError(
                "Required import fields are not mapped: "
                + ", ".join(missing_labels)
                + "."
            )

        cur.execute(
            """
            SELECT
                source_row_number,
                source_data
            FROM import_run_rows
            WHERE import_run_id = %s
              AND spa_id = %s
              AND business_unit_id = %s
            ORDER BY source_row_number
            """,
            (
                import_run_id,
                spa_id,
                business_unit_id,
            ),
        )

        staged_rows = cur.fetchall()

        prepared_rows = []

        for (
            source_row_number,
            source_data,
        ) in staged_rows:
            source_data = (
                source_data
                if isinstance(
                    source_data,
                    dict,
                )
                else {}
            )

            values = source_data.get(
                "values",
                []
            )

            mapped = apply_import_mapping(
                values,
                mapping,
                entity_type=entity_type,
            )

            if entity_type == "clients":
                validation = (
                    validate_client_import_row(
                        mapped
                    )
                )
            elif entity_type == "income":
                validation = (
                    validate_income_import_row(
                        mapped
                    )
                )
            elif entity_type == "expenses":
                validation = (
                    validate_expense_import_row(
                        mapped
                    )
                )
            elif entity_type == "appointments":
                validation = (
                    validate_appointment_import_row(
                        mapped
                    )
                )
            elif entity_type == "peachpos_income":
                validation = (
                    validate_peachpos_income_import_row(
                        mapped
                    )
                )
            else:
                raise ImportServiceError(
                    f"Unsupported import type: {entity_type}."
                )

            prepared_rows.append({
                "row_number": source_row_number,
                "valid": validation["valid"],
                "data": validation["data"],
                "errors": validation["errors"],
            })

        if entity_type == "clients":
            prepared_rows = (
                validate_client_import_workspace_dropdowns(
                    cur,
                    spa_id=spa_id,
                    business_unit_id=business_unit_id,
                    prepared_rows=prepared_rows,
                )
            )

            prepared_rows = (
                annotate_client_import_file_duplicates(
                    prepared_rows
                )
            )

        elif entity_type == "income":
            prepared_rows = (
                validate_income_import_workspace_values(
                    cur,
                    spa_id=spa_id,
                    business_unit_id=business_unit_id,
                    prepared_rows=prepared_rows,
                )
            )

            prepared_rows = (
                annotate_income_import_file_duplicates(
                    prepared_rows
                )
            )

            prepared_rows = (
                annotate_income_import_existing_duplicates(
                    cur,
                    spa_id=spa_id,
                    business_unit_id=business_unit_id,
                    prepared_rows=prepared_rows,
                )
            )

        elif entity_type == "expenses":
            prepared_rows = (
                validate_expense_import_workspace_values(
                    cur,
                    spa_id=spa_id,
                    business_unit_id=business_unit_id,
                    prepared_rows=prepared_rows,
                )
            )
            prepared_rows = (
                annotate_expense_import_file_duplicates(
                    prepared_rows
                )
            )
            prepared_rows = (
                annotate_expense_import_existing_duplicates(
                    cur,
                    spa_id=spa_id,
                    business_unit_id=business_unit_id,
                    prepared_rows=prepared_rows,
                )
            )
            prepared_rows = (
                annotate_expense_import_existing_identity_duplicates(
                    cur,
                    spa_id=spa_id,
                    business_unit_id=business_unit_id,
                    prepared_rows=prepared_rows,
                )
            )

        elif entity_type == "appointments":
            prepared_rows = (
                validate_appointment_import_workspace_values(
                    cur,
                    spa_id=spa_id,
                    business_unit_id=business_unit_id,
                    prepared_rows=prepared_rows,
                )
            )

            prepared_rows = (
                annotate_appointment_import_file_duplicates(
                    prepared_rows
                )
            )

            prepared_rows = (
                annotate_appointment_import_existing_duplicates(
                    cur,
                    spa_id=spa_id,
                    business_unit_id=business_unit_id,
                    prepared_rows=prepared_rows,
                )
            )

        elif entity_type == "peachpos_income":
            merchant_verification = (
                verify_peachpos_import_merchant_identity(
                    cur,
                    spa_id=spa_id,
                    business_unit_id=business_unit_id,
                    credit_processor_id=(
                        options_payload.get(
                            "credit_processor_id"
                        )
                    ),
                    prepared_rows=prepared_rows,
                )
            )
            prepared_rows = (
                annotate_peachpos_import_file_duplicates(
                    prepared_rows
                )
            )
            prepared_rows = (
                annotate_peachpos_import_existing_duplicates(
                    cur,
                    spa_id=spa_id,
                    business_unit_id=business_unit_id,
                    credit_processor_id=(
                        options_payload.get(
                            "credit_processor_id"
                        )
                    ),
                    prepared_rows=prepared_rows,
                )
            )
        valid_rows = 0
        invalid_rows = 0
        strong_duplicate_rows = 0
        possible_duplicate_rows = 0
        appointment_needs_review_rows = 0
        expense_needs_review_rows = 0

        for row in prepared_rows:
            validation_status = (
                "valid"
                if row.get("valid")
                else "invalid"
            )

            if validation_status == "valid":
                valid_rows += 1
            else:
                invalid_rows += 1

            file_duplicate_type = row.get(
                "duplicate_type"
            )

            existing_duplicate_type = row.get(
                "existing_duplicate_type"
            )

            if (
                file_duplicate_type == "strong"
                or existing_duplicate_type == "strong"
            ):
                duplicate_status = "strong"
                strong_duplicate_rows += 1

            elif (
                file_duplicate_type == "possible"
                or existing_duplicate_type == "possible"
            ):
                duplicate_status = "possible"
                possible_duplicate_rows += 1

            else:
                duplicate_status = "none"

            duplicate_details = {
                "file": {
                    "type": file_duplicate_type,
                    "reasons": row.get(
                        "duplicate_reasons",
                        [],
                    ),
                    "row_numbers": row.get(
                        "duplicate_row_numbers",
                        [],
                    ),
                },
                "existing_psp": {
                    "type": existing_duplicate_type,
                    "matches": row.get(
                        "existing_duplicate_matches",
                        [],
                    ),
                },
            }

            if (
                entity_type in {"appointments", "expenses"}
                and duplicate_status == "strong"
            ):
                # Confirmed duplicates are discarded automatically.
                review_decision = "discard"

            elif (
                validation_status == "valid"
                and duplicate_status == "none"
            ):
                review_decision = "approved"

            else:
                review_decision = "needs_review"

            if (
                entity_type == "appointments"
                and review_decision == "needs_review"
            ):
                appointment_needs_review_rows += 1

            if (
                entity_type == "expenses"
                and review_decision == "needs_review"
            ):
                expense_needs_review_rows += 1

            cur.execute(
                """
                UPDATE import_run_rows
                SET mapped_data = %s,
                    validation_status = %s,
                    validation_errors = %s,
                    duplicate_status = %s,
                    duplicate_details = %s,
                    review_decision = %s,
                    updated_at = CURRENT_TIMESTAMP
                WHERE import_run_id = %s
                  AND spa_id = %s
                  AND business_unit_id = %s
                  AND source_row_number = %s
                """,
                (
                    Json(
                        row.get(
                            "data",
                            {},
                        )
                    ),
                    validation_status,
                    Json(
                        row.get(
                            "errors",
                            [],
                        )
                    ),
                    duplicate_status,
                    Json(
                        duplicate_details
                    ),
                    review_decision,
                    import_run_id,
                    spa_id,
                    business_unit_id,
                    row["row_number"],
                ),
            )

            if cur.rowcount != 1:
                raise ImportServiceError(
                    "A staged import row could not be updated safely."
                )

        if entity_type == "appointments":
            needs_review = bool(
                appointment_needs_review_rows
            )
        elif entity_type == "expenses":
            needs_review = bool(
                expense_needs_review_rows
            )
        else:
            needs_review = bool(
                invalid_rows
                or strong_duplicate_rows
                or possible_duplicate_rows
            )

        next_status = (
            "review"
            if needs_review
            else "ready"
        )

        updated_mapping_json = dict(
            existing_mapping_json
        )

        updated_mapping_json[
            "selected"
        ] = mapping

        updated_options_json = dict(
            options_payload
        )
        if entity_type == "peachpos_income":
            updated_options_json[
                "merchant_verification"
            ] = merchant_verification

        cur.execute(
            """
            UPDATE import_runs
            SET mapping_json = %s,
                options_json = %s,
                run_status = %s,
                valid_rows = %s,
                invalid_rows = %s,
                strong_duplicate_rows = %s,
                possible_duplicate_rows = %s,
                last_activity_at = CURRENT_TIMESTAMP,
                updated_at = CURRENT_TIMESTAMP
            WHERE import_run_id = %s
              AND spa_id = %s
              AND business_unit_id = %s
            """,
            (
                Json(
                    updated_mapping_json
                ),
                Json(
                    updated_options_json
                ),
                next_status,
                valid_rows,
                invalid_rows,
                strong_duplicate_rows,
                possible_duplicate_rows,
                import_run_id,
                spa_id,
                business_unit_id,
            ),
        )

        if cur.rowcount != 1:
            raise ImportServiceError(
                "Import Run could not be updated safely."
            )

        conn.commit()

        return {
            "import_run_id": import_run_id,
            "entity_type": entity_type,
            "run_status": next_status,
            "total_rows": len(
                prepared_rows
            ),
            "valid_rows": valid_rows,
            "invalid_rows": invalid_rows,
            "strong_duplicate_rows": (
                strong_duplicate_rows
            ),
            "possible_duplicate_rows": (
                possible_duplicate_rows
            ),
        }

    except Exception:
        conn.rollback()
        raise

    finally:
        cur.close()
        conn.close()


# =========================================================
# IMPORT RUN RECORDS
# =========================================================

def get_import_run_records(
    import_run_id,
    *,
    spa_id,
    business_unit_id,
):
    """
    Load the complete durable transaction/review view for one
    Import Run.

    Returns the batch header and every staged source row with:
      - original source data
      - mapped data
      - validation state/errors
      - duplicate state/details
      - review decision
      - import/posting state
      - resulting Income record ID when posted

    This is read-only and strictly workspace scoped.
    """
    conn = get_db_connection()
    cur = conn.cursor()

    try:
        cur.execute(
            """
            SELECT
                entity_type,
                run_status,
                source_filename,
                source_extension,
                source_size_bytes,
                options_json,
                total_rows,
                valid_rows,
                invalid_rows,
                strong_duplicate_rows,
                possible_duplicate_rows,
                imported_rows,
                skipped_rows,
                error_rows,
                requested_at,
                started_at,
                completed_at,
                failure_message
            FROM import_runs
            WHERE import_run_id = %s
              AND spa_id = %s
              AND business_unit_id = %s
            LIMIT 1
            """,
            (
                import_run_id,
                spa_id,
                business_unit_id,
            ),
        )

        run = cur.fetchone()

        if not run:
            raise ImportServiceError(
                "Import Run was not found in this workspace."
            )

        entity_type = str(
            run[0] or ""
        ).strip().lower()

        options_payload = (
            run[5]
            if isinstance(run[5], dict)
            else {}
        )

        profile = get_workspace_import_profile(
            cur,
            spa_id=spa_id,
            business_unit_id=business_unit_id,
            entity_type=entity_type,
            options=options_payload,
        )

        credit_processor_name = None

        if entity_type == "peachpos_income":
            credit_processor_id = options_payload.get(
                "credit_processor_id"
            )

            try:
                credit_processor_id = int(
                    credit_processor_id
                )
            except (TypeError, ValueError):
                credit_processor_id = None

            if credit_processor_id:
                cur.execute(
                    """
                    SELECT credit_processor_name
                    FROM credit_processors
                    WHERE credit_processor_id = %s
                      AND spa_id = %s
                      AND business_unit_id = %s
                    LIMIT 1
                    """,
                    (
                        credit_processor_id,
                        spa_id,
                        business_unit_id,
                    ),
                )
                processor_row = cur.fetchone()

                if processor_row:
                    credit_processor_name = (
                        str(
                            processor_row[0] or ""
                        ).strip()
                        or None
                    )

        exception_review_counts = None

        if entity_type in {"appointments", "expenses"}:
            cur.execute(
                """
                SELECT
                    COUNT(*) FILTER (
                        WHERE review_decision = 'approved'
                    ),
                    COUNT(*) FILTER (
                        WHERE review_decision = 'needs_review'
                    ),
                    COUNT(*) FILTER (
                        WHERE review_decision = 'hold'
                    ),
                    COUNT(*) FILTER (
                        WHERE review_decision = 'discard'
                    ),
                    COUNT(*) FILTER (
                        WHERE import_status = 'pending'
                          AND (
                              review_decision IS NULL
                              OR review_decision NOT IN (
                                  'approved',
                                  'discard'
                              )
                          )
                    )
                FROM import_run_rows
                WHERE import_run_id = %s
                  AND spa_id = %s
                  AND business_unit_id = %s
                """,
                (
                    import_run_id,
                    spa_id,
                    business_unit_id,
                ),
            )

            exception_review_counts = cur.fetchone()

            cur.execute(
                """
                SELECT
                    import_run_row_id,
                    source_row_number,
                    source_data,
                    mapped_data,
                    validation_status,
                    validation_errors,
                    duplicate_status,
                    duplicate_details,
                    review_decision,
                    import_status,
                    imported_record_id,
                    error_message
                FROM import_run_rows
                WHERE import_run_id = %s
                  AND spa_id = %s
                  AND business_unit_id = %s
                  AND (
                      review_decision IS NULL
                      OR review_decision <> 'approved'
                      OR import_status = 'error'
                  )
                ORDER BY source_row_number
                """,
                (
                    import_run_id,
                    spa_id,
                    business_unit_id,
                ),
            )
        else:
            cur.execute(
                """
                SELECT
                    import_run_row_id,
                    source_row_number,
                    source_data,
                    mapped_data,
                    validation_status,
                    validation_errors,
                    duplicate_status,
                    duplicate_details,
                    review_decision,
                    import_status,
                    imported_record_id,
                    error_message
                FROM import_run_rows
                WHERE import_run_id = %s
                  AND spa_id = %s
                  AND business_unit_id = %s
                ORDER BY source_row_number
                """,
                (
                    import_run_id,
                    spa_id,
                    business_unit_id,
                ),
            )

        records = []

        for (
            import_run_row_id,
            source_row_number,
            source_data,
            mapped_data,
            validation_status,
            validation_errors,
            duplicate_status,
            duplicate_details,
            review_decision,
            import_status,
            imported_record_id,
            error_message,
        ) in cur.fetchall():

            source_data = (
                source_data
                if isinstance(source_data, dict)
                else {}
            )

            mapped_data = (
                mapped_data
                if isinstance(mapped_data, dict)
                else {}
            )

            validation_errors = (
                validation_errors
                if isinstance(validation_errors, list)
                else []
            )

            duplicate_details = (
                duplicate_details
                if isinstance(duplicate_details, dict)
                else {}
            )

            records.append({
                "import_run_row_id": import_run_row_id,
                "source_row_number": source_row_number,
                "source_values": source_data.get(
                    "values",
                    [],
                ),
                "mapped_data": mapped_data,
                "validation_status": validation_status,
                "validation_errors": validation_errors,
                "duplicate_status": duplicate_status,
                "duplicate_details": duplicate_details,
                "review_decision": review_decision,
                "import_status": import_status,
                "imported_record_id": imported_record_id,
                "error_message": error_message,
            })

        if entity_type in {"appointments", "expenses"}:
            (
                approved_rows,
                needs_review_rows,
                hold_rows,
                discard_rows,
                unresolved_review_rows,
            ) = exception_review_counts

            review_visible_rows = len(records)
            review_hidden_rows = max(
                int(run[6] or 0) - review_visible_rows,
                0,
            )
        else:
            approved_rows = sum(
                1
                for record in records
                if record.get("review_decision") == "approved"
            )

            needs_review_rows = sum(
                1
                for record in records
                if record.get("review_decision") == "needs_review"
            )

            hold_rows = sum(
                1
                for record in records
                if record.get("review_decision") == "hold"
            )

            discard_rows = sum(
                1
                for record in records
                if record.get("review_decision") == "discard"
            )

            unresolved_review_rows = sum(
                1
                for record in records
                if (
                    record.get("import_status") == "pending"
                    and record.get("review_decision")
                    not in {"approved", "discard"}
                )
            )

            review_visible_rows = len(records)
            review_hidden_rows = 0

        financial_summary = {
            "transactions": 0,
            "sales": Decimal("0.00"),
            "tax": Decimal("0.00"),
            "tips": Decimal("0.00"),
            "gross": Decimal("0.00"),
            "processor_fees": Decimal("0.00"),
            "net_received": Decimal("0.00"),
        }

        financial_field_map = (
            ("pos_amount", "sales"),
            ("tax_amount", "tax"),
            ("tip_amount", "tips"),
            ("total_amount", "gross"),
            (
                "processing_fee_amount",
                "processor_fees",
            ),
            ("net_received", "net_received"),
        )

        for record in records:
            if (
                record.get("review_decision")
                != "approved"
            ):
                continue

            financial_summary[
                "transactions"
            ] += 1

            data = record.get("mapped_data") or {}

            for field_key, summary_key in (
                financial_field_map
            ):
                raw_value = str(
                    data.get(field_key) or ""
                ).strip()

                if not raw_value:
                    continue

                try:
                    amount = Decimal(
                        raw_value
                    ).quantize(
                        Decimal("0.01")
                    )
                except (
                    InvalidOperation,
                    ValueError,
                ):
                    continue

                financial_summary[
                    summary_key
                ] += amount

        # Expense exception review hides approved records, so its
        # financial totals must be calculated from all staged rows.
        # Keep existing Income and PeachPOS calculations unchanged.
        if entity_type == "expenses":
            cur.execute(
                """
                SELECT
                    COUNT(*),
                    COALESCE(
                        SUM(
                            CASE
                                WHEN validation_status = 'valid'
                                 AND BTRIM(
                                     COALESCE(
                                         mapped_data ->> 'amount',
                                         ''
                                     )
                                 ) ~
                                 '^[+-]?([0-9]+([.][0-9]*)?|[.][0-9]+)([eE][+-]?[0-9]+)?$'
                                THEN (
                                    mapped_data ->> 'amount'
                                )::numeric
                                ELSE NULL
                            END
                        ),
                        0
                    ),
                    COUNT(*) FILTER (
                        WHERE validation_status = 'valid'
                          AND BTRIM(
                              COALESCE(
                                  mapped_data ->> 'amount',
                                  ''
                              )
                          ) ~
                          '^[+-]?([0-9]+([.][0-9]*)?|[.][0-9]+)([eE][+-]?[0-9]+)?$'
                    )
                FROM import_run_rows
                WHERE import_run_id = %s
                  AND spa_id = %s
                  AND business_unit_id = %s
                  AND review_decision = 'approved'
                """,
                (
                    import_run_id,
                    spa_id,
                    business_unit_id,
                ),
            )

            (
                expense_approved_count,
                expense_approved_total,
                expense_amount_count,
            ) = cur.fetchone()

            if expense_approved_count != expense_amount_count:
                raise ImportServiceError(
                    "Approved Expense Import records contain "
                    "an invalid or missing amount."
                )

            financial_summary["transactions"] = int(
                expense_approved_count
            )
            financial_summary["expense_total"] = Decimal(
                expense_approved_total
            ).quantize(Decimal("0.01"))

        total_gross = financial_summary["gross"]
        total_net = financial_summary[
            "net_received"
        ]

        return {
            "import_run_id": import_run_id,
            "entity_type": entity_type,
            "display_name": profile["display_name"],
            "run_status": run[1],
            "filename": run[2],
            "extension": run[3],
            "source_size_bytes": run[4],
            "options": options_payload,
            "credit_processor_name": credit_processor_name,
            "fields": [
                {
                    "key": field["key"],
                    "label": field["label"],
                    "required": bool(
                        field.get("required")
                    ),
                }
                for field in profile["fields"]
            ],
            "total_rows": run[6],
            "valid_rows": run[7],
            "approved_rows": approved_rows,
            "needs_review_rows": needs_review_rows,
            "hold_rows": hold_rows,
            "discard_rows": discard_rows,
            "unresolved_review_rows": unresolved_review_rows,
            "review_visible_rows": review_visible_rows,
            "review_hidden_rows": review_hidden_rows,
            "financial_summary": financial_summary,
            "total_gross": total_gross,
            "total_net": total_net,
            "invalid_rows": run[8],
            "strong_duplicate_rows": run[9],
            "possible_duplicate_rows": run[10],
            "imported_rows": run[11],
            "skipped_rows": run[12],
            "error_rows": run[13],
            "requested_at": run[14],
            "started_at": run[15],
            "completed_at": run[16],
            "failure_message": run[17],
            "records": records,
        }

    finally:
        cur.close()
        conn.close()



def update_financial_import_review_decision(
    import_run_id,
    import_run_row_id,
    *,
    decision,
    spa_id,
    business_unit_id,
):
    """
    Apply one durable financial Import review decision.

    Supported entity types:
      - income
      - peachpos_income
      - expenses

    Review policy:
      - clean valid rows may be approved
      - invalid rows may never be approved
      - strong duplicates may never be approved
      - any still-pending row may be discarded
      - validation/duplicate evidence remains preserved
      - the run becomes ready only when no unresolved
        pending review decisions remain
    """
    decision = str(
        decision or ""
    ).strip().lower()

    if decision not in {
        "approved",
        "discard",
    }:
        raise ImportServiceError(
            "Financial import review decision must be "
            "Approve or Discard."
        )

    conn = get_db_connection()
    cur = conn.cursor()

    try:
        cur.execute(
            """
            SELECT
                entity_type,
                run_status
            FROM import_runs
            WHERE import_run_id = %s
              AND spa_id = %s
              AND business_unit_id = %s
            FOR UPDATE
            """,
            (
                import_run_id,
                spa_id,
                business_unit_id,
            ),
        )

        run = cur.fetchone()

        if not run:
            raise ImportServiceError(
                "Import Run was not found in this workspace."
            )

        entity_type = str(
            run[0] or ""
        ).strip().lower()

        run_status = str(
            run[1] or ""
        ).strip().lower()

        if entity_type not in {
            "income",
            "peachpos_income",
            "expenses",
        }:
            raise ImportServiceError(
                "This review action is available for "
                "financial imports only."
            )

        if run_status in {
            "completed",
            "failed",
        }:
            raise ImportServiceError(
                "This financial Import Run can no longer "
                "be reviewed."
            )

        cur.execute(
            """
            SELECT
                validation_status,
                duplicate_status,
                review_decision,
                import_status
            FROM import_run_rows
            WHERE import_run_row_id = %s
              AND import_run_id = %s
              AND spa_id = %s
              AND business_unit_id = %s
            FOR UPDATE
            """,
            (
                import_run_row_id,
                import_run_id,
                spa_id,
                business_unit_id,
            ),
        )

        row = cur.fetchone()

        if not row:
            raise ImportServiceError(
                "Financial Import row was not found "
                "in this workspace."
            )

        validation_status = str(
            row[0] or ""
        ).strip().lower()

        duplicate_status = str(
            row[1] or "none"
        ).strip().lower()

        import_status = str(
            row[3] or ""
        ).strip().lower()

        if import_status != "pending":
            raise ImportServiceError(
                "Only pending financial Import rows "
                "can be reviewed."
            )

        if decision == "approved":
            if validation_status != "valid":
                raise ImportServiceError(
                    "Invalid financial Import rows cannot "
                    "be approved."
                )

            if duplicate_status == "strong":
                raise ImportServiceError(
                    "Strong duplicate financial Import rows "
                    "cannot be approved."
                )

            if duplicate_status not in {
                "none",
                "possible",
            }:
                raise ImportServiceError(
                    "This financial Import row has an "
                    "unresolved duplicate state."
                )

        cur.execute(
            """
            UPDATE import_run_rows
            SET review_decision = %s,
                updated_at = CURRENT_TIMESTAMP
            WHERE import_run_row_id = %s
              AND import_run_id = %s
              AND spa_id = %s
              AND business_unit_id = %s
              AND import_status = 'pending'
            """,
            (
                decision,
                import_run_row_id,
                import_run_id,
                spa_id,
                business_unit_id,
            ),
        )

        if cur.rowcount != 1:
            raise ImportServiceError(
                "The financial Import row changed while "
                "it was being reviewed."
            )

        cur.execute(
            """
            SELECT COUNT(*)
            FROM import_run_rows
            WHERE import_run_id = %s
              AND spa_id = %s
              AND business_unit_id = %s
              AND import_status = 'pending'
              AND (
                  review_decision IS NULL
                  OR review_decision NOT IN (
                      'approved',
                      'discard'
                  )
              )
            """,
            (
                import_run_id,
                spa_id,
                business_unit_id,
            ),
        )

        unresolved_review_rows = cur.fetchone()[0]

        next_status = (
            "review"
            if unresolved_review_rows > 0
            else "ready"
        )

        cur.execute(
            """
            UPDATE import_runs
            SET run_status = %s,
                failure_message = NULL,
                completed_at = NULL,
                last_activity_at = CURRENT_TIMESTAMP,
                updated_at = CURRENT_TIMESTAMP
            WHERE import_run_id = %s
              AND spa_id = %s
              AND business_unit_id = %s
            """,
            (
                next_status,
                import_run_id,
                spa_id,
                business_unit_id,
            ),
        )

        conn.commit()

        return {
            "import_run_id": import_run_id,
            "import_run_row_id": import_run_row_id,
            "entity_type": entity_type,
            "review_decision": decision,
            "run_status": next_status,
            "unresolved_review_rows": (
                unresolved_review_rows
            ),
        }

    except Exception:
        conn.rollback()
        raise

    finally:
        cur.close()
        conn.close()


def update_appointment_import_review_decision(
    import_run_id,
    import_run_row_id,
    *,
    decision,
    spa_id,
    business_unit_id,
    reviewed_by_user_id,
):
    """
    Apply one durable Appointment Import review decision.

    Appointment review policy:
      - clean valid rows may be approved
      - possible duplicates may be explicitly approved
      - invalid rows may never be approved
      - strong duplicates may never be approved
      - any still-pending row may be discarded
      - duplicate/validation evidence is preserved
      - the Import Run becomes ready only when no unresolved
        pending review decisions remain
    """
    decision = str(decision or "").strip().lower()

    if decision not in {"approved", "discard"}:
        raise ImportServiceError(
            "Appointment review decision must be Approve or Discard."
        )

    try:
        reviewed_by_user_id = int(reviewed_by_user_id)
    except (TypeError, ValueError):
        raise ImportServiceError(
            "A valid authenticated reviewer is required."
        )

    if reviewed_by_user_id <= 0:
        raise ImportServiceError(
            "A valid authenticated reviewer is required."
        )

    conn = get_db_connection()
    cur = conn.cursor()

    try:
        cur.execute(
            """
            SELECT
                entity_type,
                run_status
            FROM import_runs
            WHERE import_run_id = %s
              AND spa_id = %s
              AND business_unit_id = %s
            FOR UPDATE
            """,
            (
                import_run_id,
                spa_id,
                business_unit_id,
            ),
        )

        run = cur.fetchone()

        if not run:
            raise ImportServiceError(
                "Import Run was not found in this workspace."
            )

        entity_type = str(run[0] or "").strip().lower()
        run_status = str(run[1] or "").strip().lower()

        if entity_type != "appointments":
            raise ImportServiceError(
                "This review action is available for "
                "Appointment imports only."
            )

        if run_status in {"completed", "failed"}:
            raise ImportServiceError(
                "This Appointment Import Run can no longer be reviewed."
            )

        cur.execute(
            """
            SELECT
                validation_status,
                duplicate_status,
                review_decision,
                import_status
            FROM import_run_rows
            WHERE import_run_row_id = %s
              AND import_run_id = %s
              AND spa_id = %s
              AND business_unit_id = %s
            FOR UPDATE
            """,
            (
                import_run_row_id,
                import_run_id,
                spa_id,
                business_unit_id,
            ),
        )

        row = cur.fetchone()

        if not row:
            raise ImportServiceError(
                "Appointment Import row was not found "
                "in this workspace."
            )

        validation_status = str(
            row[0] or ""
        ).strip().lower()

        duplicate_status = str(
            row[1] or "none"
        ).strip().lower()

        current_review_decision = str(
            row[2] or ""
        ).strip().lower()

        import_status = str(
            row[3] or ""
        ).strip().lower()

        if import_status != "pending":
            raise ImportServiceError(
                "Only pending Appointment Import rows "
                "can be reviewed."
            )

        if decision == "approved":
            if validation_status != "valid":
                raise ImportServiceError(
                    "Invalid Appointment rows cannot be approved. "
                    "Correct the source data and re-import, or "
                    "discard the row."
                )

            if duplicate_status == "strong":
                raise ImportServiceError(
                    "Strong duplicate Appointment rows cannot be "
                    "approved. Discard the row or correct the "
                    "source data and re-import."
                )

            if duplicate_status not in {"none", "possible"}:
                raise ImportServiceError(
                    "This Appointment row has an unresolved "
                    "duplicate state."
                )

        cur.execute(
            """
            UPDATE import_run_rows
            SET review_decision = %s,
                updated_at = CURRENT_TIMESTAMP
            WHERE import_run_row_id = %s
              AND import_run_id = %s
              AND spa_id = %s
              AND business_unit_id = %s
              AND import_status = 'pending'
            """,
            (
                decision,
                import_run_row_id,
                import_run_id,
                spa_id,
                business_unit_id,
            ),
        )

        if cur.rowcount != 1:
            raise ImportServiceError(
                "The Appointment Import row changed while "
                "it was being reviewed."
            )

        audit_action_type = (
            "appointment_import_row_approved"
            if decision == "approved"
            else "appointment_import_row_discarded"
        )

        cur.execute(
            """
            INSERT INTO audit_log (
                spa_id,
                user_id,
                action_type,
                table_name,
                record_id,
                old_value,
                new_value,
                notes,
                business_unit_id,
                verified_employee_id
            )
            VALUES (
                %s, %s, %s, %s, %s,
                %s, %s, %s, %s, %s
            )
            """,
            (
                spa_id,
                reviewed_by_user_id,
                audit_action_type,
                "import_run_rows",
                import_run_row_id,
                current_review_decision or None,
                decision,
                (
                    f"Appointment Import Run {import_run_id}; "
                    f"duplicate status: {duplicate_status}."
                ),
                business_unit_id,
                None,
            ),
        )

        cur.execute(
            """
            SELECT COUNT(*)
            FROM import_run_rows
            WHERE import_run_id = %s
              AND spa_id = %s
              AND business_unit_id = %s
              AND import_status = 'pending'
              AND (
                  review_decision IS NULL
                  OR review_decision NOT IN (
                      'approved',
                      'discard'
                  )
              )
            """,
            (
                import_run_id,
                spa_id,
                business_unit_id,
            ),
        )

        unresolved_review_rows = cur.fetchone()[0]

        next_status = (
            "review"
            if unresolved_review_rows > 0
            else "ready"
        )

        cur.execute(
            """
            UPDATE import_runs
            SET run_status = %s,
                failure_message = NULL,
                completed_at = NULL,
                last_activity_at = CURRENT_TIMESTAMP,
                updated_at = CURRENT_TIMESTAMP
            WHERE import_run_id = %s
              AND spa_id = %s
              AND business_unit_id = %s
            """,
            (
                next_status,
                import_run_id,
                spa_id,
                business_unit_id,
            ),
        )

        conn.commit()

        return {
            "import_run_id": import_run_id,
            "import_run_row_id": import_run_row_id,
            "review_decision": decision,
            "run_status": next_status,
            "unresolved_review_rows": unresolved_review_rows,
        }

    except Exception:
        conn.rollback()
        raise

    finally:
        cur.close()
        conn.close()


def update_client_import_review_decision(
    import_run_id,
    import_run_row_id,
    *,
    decision,
    spa_id,
    business_unit_id,
):
    """
    Apply one durable Client Import review decision.

    Client review policy:
      - clean valid rows may be approved
      - possible duplicates may be explicitly approved
      - invalid rows may never be approved
      - strong duplicates may never be approved
      - any still-pending row may be discarded
      - duplicate/validation evidence is preserved
      - the Import Run becomes ready only when no unresolved
        pending review decisions remain
    """
    decision = str(decision or "").strip().lower()

    if decision not in {"approved", "discard"}:
        raise ImportServiceError(
            "Client review decision must be Approve or Discard."
        )

    conn = get_db_connection()
    cur = conn.cursor()

    try:
        cur.execute(
            """
            SELECT
                entity_type,
                run_status
            FROM import_runs
            WHERE import_run_id = %s
              AND spa_id = %s
              AND business_unit_id = %s
            FOR UPDATE
            """,
            (
                import_run_id,
                spa_id,
                business_unit_id,
            ),
        )

        run = cur.fetchone()

        if not run:
            raise ImportServiceError(
                "Import Run was not found in this workspace."
            )

        entity_type = str(run[0] or "").strip().lower()
        run_status = str(run[1] or "").strip().lower()

        if entity_type != "clients":
            raise ImportServiceError(
                "This review action is available for Client imports only."
            )

        if run_status in {"completed", "failed"}:
            raise ImportServiceError(
                "This Client Import Run can no longer be reviewed."
            )

        cur.execute(
            """
            SELECT
                validation_status,
                duplicate_status,
                review_decision,
                import_status
            FROM import_run_rows
            WHERE import_run_row_id = %s
              AND import_run_id = %s
              AND spa_id = %s
              AND business_unit_id = %s
            FOR UPDATE
            """,
            (
                import_run_row_id,
                import_run_id,
                spa_id,
                business_unit_id,
            ),
        )

        row = cur.fetchone()

        if not row:
            raise ImportServiceError(
                "Client Import row was not found in this workspace."
            )

        validation_status = str(
            row[0] or ""
        ).strip().lower()

        duplicate_status = str(
            row[1] or "none"
        ).strip().lower()

        import_status = str(
            row[3] or ""
        ).strip().lower()

        if import_status != "pending":
            raise ImportServiceError(
                "Only pending Client Import rows can be reviewed."
            )

        if decision == "approved":
            if validation_status != "valid":
                raise ImportServiceError(
                    "Invalid Client rows cannot be approved. "
                    "Correct the source data and re-import, or discard the row."
                )

            if duplicate_status == "strong":
                raise ImportServiceError(
                    "Strong duplicate Client rows cannot be approved. "
                    "Discard the row or correct the source data and re-import."
                )

            if duplicate_status not in {"none", "possible"}:
                raise ImportServiceError(
                    "This Client row has an unresolved duplicate state."
                )

        cur.execute(
            """
            UPDATE import_run_rows
            SET review_decision = %s,
                updated_at = CURRENT_TIMESTAMP
            WHERE import_run_row_id = %s
              AND import_run_id = %s
              AND spa_id = %s
              AND business_unit_id = %s
              AND import_status = 'pending'
            """,
            (
                decision,
                import_run_row_id,
                import_run_id,
                spa_id,
                business_unit_id,
            ),
        )

        if cur.rowcount != 1:
            raise ImportServiceError(
                "The Client Import row changed while it was being reviewed."
            )

        cur.execute(
            """
            SELECT COUNT(*)
            FROM import_run_rows
            WHERE import_run_id = %s
              AND spa_id = %s
              AND business_unit_id = %s
              AND import_status = 'pending'
              AND (
                  review_decision IS NULL
                  OR review_decision NOT IN ('approved', 'discard')
              )
            """,
            (
                import_run_id,
                spa_id,
                business_unit_id,
            ),
        )

        unresolved_review_rows = cur.fetchone()[0]

        next_status = (
            "review"
            if unresolved_review_rows > 0
            else "ready"
        )

        cur.execute(
            """
            UPDATE import_runs
            SET run_status = %s,
                failure_message = NULL,
                completed_at = NULL,
                last_activity_at = CURRENT_TIMESTAMP,
                updated_at = CURRENT_TIMESTAMP
            WHERE import_run_id = %s
              AND spa_id = %s
              AND business_unit_id = %s
            """,
            (
                next_status,
                import_run_id,
                spa_id,
                business_unit_id,
            ),
        )

        conn.commit()

        return {
            "import_run_id": import_run_id,
            "import_run_row_id": import_run_row_id,
            "review_decision": decision,
            "run_status": next_status,
            "unresolved_review_rows": unresolved_review_rows,
        }

    except Exception:
        conn.rollback()
        raise

    finally:
        cur.close()
        conn.close()




def discard_client_import_review_rows(
    import_run_id,
    *,
    spa_id,
    business_unit_id,
    import_run_row_ids=None,
):
    """
    Bulk-discard unresolved Client Import review rows.

    If import_run_row_ids is None, every unresolved pending row
    in the run is discarded.

    If row IDs are supplied, only those unresolved pending rows
    are discarded.

    Already-approved rows are deliberately protected from this
    bulk action. Validation and duplicate evidence is preserved.
    """
    discard_all_remaining = import_run_row_ids is None

    selected_row_ids = None

    if not discard_all_remaining:
        try:
            selected_row_ids = sorted({
                int(row_id)
                for row_id in import_run_row_ids
            })
        except (TypeError, ValueError):
            raise ImportServiceError(
                "One or more selected Client rows are invalid."
            )

        if not selected_row_ids:
            raise ImportServiceError(
                "Select at least one Client row to discard."
            )

    conn = get_db_connection()
    cur = conn.cursor()

    try:
        cur.execute(
            """
            SELECT
                entity_type,
                run_status
            FROM import_runs
            WHERE import_run_id = %s
              AND spa_id = %s
              AND business_unit_id = %s
            FOR UPDATE
            """,
            (
                import_run_id,
                spa_id,
                business_unit_id,
            ),
        )

        run = cur.fetchone()

        if not run:
            raise ImportServiceError(
                "Import Run was not found in this workspace."
            )

        entity_type = str(
            run[0] or ""
        ).strip().lower()

        run_status = str(
            run[1] or ""
        ).strip().lower()

        if entity_type != "clients":
            raise ImportServiceError(
                "This bulk review action is available "
                "for Client imports only."
            )

        if run_status in {"completed", "failed"}:
            raise ImportServiceError(
                "This Client Import Run can no longer be reviewed."
            )

        if discard_all_remaining:
            cur.execute(
                """
                UPDATE import_run_rows
                SET review_decision = 'discard',
                    updated_at = CURRENT_TIMESTAMP
                WHERE import_run_id = %s
                  AND spa_id = %s
                  AND business_unit_id = %s
                  AND import_status = 'pending'
                  AND (
                      review_decision IS NULL
                      OR review_decision NOT IN (
                          'approved',
                          'discard'
                      )
                  )
                """,
                (
                    import_run_id,
                    spa_id,
                    business_unit_id,
                ),
            )

        else:
            cur.execute(
                """
                UPDATE import_run_rows
                SET review_decision = 'discard',
                    updated_at = CURRENT_TIMESTAMP
                WHERE import_run_id = %s
                  AND spa_id = %s
                  AND business_unit_id = %s
                  AND import_run_row_id = ANY(%s)
                  AND import_status = 'pending'
                  AND (
                      review_decision IS NULL
                      OR review_decision NOT IN (
                          'approved',
                          'discard'
                      )
                  )
                """,
                (
                    import_run_id,
                    spa_id,
                    business_unit_id,
                    selected_row_ids,
                ),
            )

        discarded_rows = cur.rowcount

        if (
            not discard_all_remaining
            and discarded_rows == 0
        ):
            raise ImportServiceError(
                "None of the selected Client rows still require review."
            )

        cur.execute(
            """
            SELECT COUNT(*)
            FROM import_run_rows
            WHERE import_run_id = %s
              AND spa_id = %s
              AND business_unit_id = %s
              AND import_status = 'pending'
              AND (
                  review_decision IS NULL
                  OR review_decision NOT IN (
                      'approved',
                      'discard'
                  )
              )
            """,
            (
                import_run_id,
                spa_id,
                business_unit_id,
            ),
        )

        unresolved_review_rows = cur.fetchone()[0]

        next_status = (
            "review"
            if unresolved_review_rows > 0
            else "ready"
        )

        cur.execute(
            """
            UPDATE import_runs
            SET run_status = %s,
                failure_message = NULL,
                completed_at = NULL,
                last_activity_at = CURRENT_TIMESTAMP,
                updated_at = CURRENT_TIMESTAMP
            WHERE import_run_id = %s
              AND spa_id = %s
              AND business_unit_id = %s
            """,
            (
                next_status,
                import_run_id,
                spa_id,
                business_unit_id,
            ),
        )

        conn.commit()

        return {
            "import_run_id": import_run_id,
            "discarded_rows": discarded_rows,
            "run_status": next_status,
            "unresolved_review_rows": unresolved_review_rows,
        }

    except Exception:
        conn.rollback()
        raise

    finally:
        cur.close()
        conn.close()



# =========================================================
# IMPORT RUN RECORD DETAILS
# =========================================================

def get_import_run_record_details(
    import_run_id,
    import_run_row_id,
    *,
    spa_id,
    business_unit_id,
):
    """
    Load one durable PeachPOS Import Run transaction for a
    read-only transaction-details view.

    Returns standard imported transaction data plus all 12
    processor-specific fields using the processor's current
    workspace-configured display labels.

    No writes are performed.
    """
    conn = get_db_connection()
    cur = conn.cursor()

    try:
        cur.execute(
            """
            SELECT
                r.entity_type,
                r.options_json,
                rr.import_run_row_id,
                rr.source_row_number,
                rr.source_data,
                rr.mapped_data,
                rr.validation_status,
                rr.validation_errors,
                rr.duplicate_status,
                rr.duplicate_details,
                rr.review_decision,
                rr.import_status,
                rr.imported_record_id,
                rr.error_message
            FROM import_runs r
            JOIN import_run_rows rr
              ON rr.import_run_id = r.import_run_id
             AND rr.spa_id = r.spa_id
             AND rr.business_unit_id = r.business_unit_id
            WHERE r.import_run_id = %s
              AND r.spa_id = %s
              AND r.business_unit_id = %s
              AND rr.import_run_row_id = %s
            LIMIT 1
            """,
            (
                import_run_id,
                spa_id,
                business_unit_id,
                import_run_row_id,
            ),
        )

        row = cur.fetchone()

        if not row:
            raise ImportServiceError(
                "Import Record was not found in this workspace."
            )

        entity_type = str(
            row[0] or ""
        ).strip().lower()

        if entity_type != "peachpos_income":
            raise ImportServiceError(
                "This transaction details view is available "
                "for PeachPOS Income imports only."
            )

        options_payload = (
            row[1]
            if isinstance(row[1], dict)
            else {}
        )

        credit_processor_id = options_payload.get(
            "credit_processor_id"
        )

        try:
            credit_processor_id = int(
                credit_processor_id
            )
        except (TypeError, ValueError):
            raise ImportServiceError(
                "This PeachPOS Import Run does not have a valid "
                "credit processor."
            )

        processor_labels = (
            get_peachpos_processor_field_labels(
                cur,
                spa_id=spa_id,
                business_unit_id=business_unit_id,
                credit_processor_id=credit_processor_id,
            )
        )

        processor_definitions = (
            get_peachpos_processor_field_definitions()
        )

        source_data = (
            row[4]
            if isinstance(row[4], dict)
            else {}
        )

        mapped_data = (
            row[5]
            if isinstance(row[5], dict)
            else {}
        )

        validation_errors = (
            row[7]
            if isinstance(row[7], list)
            else []
        )

        duplicate_details = (
            row[9]
            if isinstance(row[9], dict)
            else {}
        )

        processor_fields = []

        for definition in processor_definitions:
            field_key = definition["field_key"]

            processor_fields.append({
                "field_key": field_key,
                "label": (
                    processor_labels.get(field_key)
                    or definition["default_label"]
                ),
                "default_label": definition[
                    "default_label"
                ],
                "value": mapped_data.get(
                    field_key
                ),
            })

        return {
            "import_run_id": import_run_id,
            "import_run_row_id": row[2],
            "source_row_number": row[3],
            "source_values": source_data.get(
                "values",
                [],
            ),
            "mapped_data": mapped_data,
            "validation_status": row[6],
            "validation_errors": validation_errors,
            "duplicate_status": row[8],
            "duplicate_details": duplicate_details,
            "review_decision": row[10],
            "import_status": row[11],
            "imported_record_id": row[12],
            "error_message": row[13],
            "options": options_payload,
            "credit_processor_id": credit_processor_id,
            "processor_fields": processor_fields,
        }

    finally:
        cur.close()
        conn.close()


# =========================================================
# CLIENT IMPORT EXECUTION
# =========================================================

PEACHPOS_INCOME_IMPORT_PACKET_SIZE = 50
PEACHPOS_INCOME_IMPORT_PACKET_MAX_ROWS = 50

CLIENT_IMPORT_PACKET_SIZE = 50
CLIENT_IMPORT_PACKET_MAX_ROWS = 50


def process_client_import_packet(
    import_run_id,
    *,
    spa_id,
    business_unit_id,
    packet_size=CLIENT_IMPORT_PACKET_SIZE,
):
    """
    Import one bounded packet of validated Client rows.

    Safety rules:
      - only READY / already-IMPORTING Client runs may execute
      - only explicitly approved, valid rows may be imported
      - possible duplicates may import only after explicit approval
      - strong duplicates and invalid rows may never import
      - discarded rows become permanently skipped
      - duplicate/validation evidence remains preserved
      - each Client insert and row-state update are atomic
      - communication permissions are explicitly conservative
      - no Square synchronization occurs here
      - repeated calls are safe; imported rows are never reinserted
    """

    try:
        packet_size = int(packet_size)
    except (TypeError, ValueError):
        raise ImportServiceError(
            "Import packet size must be a whole number."
        )

    if (
        packet_size < 1
        or packet_size > CLIENT_IMPORT_PACKET_MAX_ROWS
    ):
        raise ImportServiceError(
            "Import packet size must be between 1 and "
            f"{CLIENT_IMPORT_PACKET_MAX_ROWS}."
        )

    conn = get_db_connection()
    cur = conn.cursor()

    try:
        # Lock the run so two requests cannot process the same
        # packet at the same time.
        cur.execute(
            """
            SELECT
                entity_type,
                run_status
            FROM import_runs
            WHERE import_run_id = %s
              AND spa_id = %s
              AND business_unit_id = %s
            FOR UPDATE
            """,
            (
                import_run_id,
                spa_id,
                business_unit_id,
            ),
        )

        run = cur.fetchone()

        if not run:
            raise ImportServiceError(
                "Import Run was not found in this workspace."
            )

        entity_type = str(
            run[0] or ""
        ).strip().lower()

        run_status = str(
            run[1] or ""
        ).strip().lower()

        if entity_type != "clients":
            raise ImportServiceError(
                "This importer currently executes Client runs only."
            )

        # A completed run is safely idempotent.
        if run_status == "completed":
            cur.execute(
                """
                SELECT
                    total_rows,
                    imported_rows,
                    skipped_rows,
                    error_rows
                FROM import_runs
                WHERE import_run_id = %s
                """,
                (import_run_id,),
            )

            counts = cur.fetchone()

            conn.rollback()

            return {
                "import_run_id": import_run_id,
                "run_status": "completed",
                "total_rows": counts[0],
                "imported_rows": counts[1],
                "skipped_rows": counts[2],
                "error_rows": counts[3],
                "processed_this_packet": 0,
                "remaining_rows": 0,
            }

        if run_status not in {
            "ready",
            "importing",
        }:
            raise ImportServiceError(
                "This Import Run is not ready to import. "
                "Complete its review first."
            )

        # Approval never overrides validation or a strong duplicate.
        # A possible duplicate may proceed only because the user
        # explicitly approved that warning during review.
        cur.execute(
            """
            SELECT COUNT(*)
            FROM import_run_rows
            WHERE import_run_id = %s
              AND spa_id = %s
              AND business_unit_id = %s
              AND import_status = 'pending'
              AND review_decision = 'approved'
              AND (
                  validation_status <> 'valid'
                  OR duplicate_status NOT IN ('none', 'possible')
              )
            """,
            (
                import_run_id,
                spa_id,
                business_unit_id,
            ),
        )

        unsafe_approved_rows = cur.fetchone()[0]

        if unsafe_approved_rows:
            raise ImportServiceError(
                "One or more approved Client rows still require "
                "validation or duplicate review."
            )

        # A READY Client run must not contain unresolved review rows.
        cur.execute(
            """
            SELECT COUNT(*)
            FROM import_run_rows
            WHERE import_run_id = %s
              AND spa_id = %s
              AND business_unit_id = %s
              AND import_status = 'pending'
              AND (
                  review_decision IS NULL
                  OR review_decision NOT IN ('approved', 'discard')
              )
            """,
            (
                import_run_id,
                spa_id,
                business_unit_id,
            ),
        )

        unresolved_review_rows = cur.fetchone()[0]

        if unresolved_review_rows:
            raise ImportServiceError(
                "This Import Run still has rows requiring review."
            )

        # Discard is terminal. Preserve the staged row for history,
        # but make sure it can never be imported later.
        cur.execute(
            """
            UPDATE import_run_rows
            SET import_status = 'skipped',
                imported_record_id = NULL,
                error_message = NULL,
                updated_at = CURRENT_TIMESTAMP
            WHERE import_run_id = %s
              AND spa_id = %s
              AND business_unit_id = %s
              AND import_status = 'pending'
              AND review_decision = 'discard'
            """,
            (
                import_run_id,
                spa_id,
                business_unit_id,
            ),
        )

        cur.execute(
            """
            UPDATE import_runs
            SET run_status = 'importing',
                started_at = COALESCE(
                    started_at,
                    CURRENT_TIMESTAMP
                ),
                last_activity_at = CURRENT_TIMESTAMP,
                updated_at = CURRENT_TIMESTAMP
            WHERE import_run_id = %s
              AND spa_id = %s
              AND business_unit_id = %s
            """,
            (
                import_run_id,
                spa_id,
                business_unit_id,
            ),
        )

        cur.execute(
            """
            SELECT
                import_run_row_id,
                source_row_number,
                mapped_data
            FROM import_run_rows
            WHERE import_run_id = %s
              AND spa_id = %s
              AND business_unit_id = %s
              AND validation_status = 'valid'
              AND duplicate_status IN ('none', 'possible')
              AND review_decision = 'approved'
              AND import_status = 'pending'
            ORDER BY source_row_number
            LIMIT %s
            """,
            (
                import_run_id,
                spa_id,
                business_unit_id,
                packet_size,
            ),
        )

        packet_rows = cur.fetchall()
        processed_this_packet = 0

        for (
            import_run_row_id,
            source_row_number,
            mapped_data,
        ) in packet_rows:

            data = (
                mapped_data
                if isinstance(mapped_data, dict)
                else {}
            )

            cur.execute(
                "SAVEPOINT client_import_row"
            )

            try:
                cur.execute(
                    """
                    INSERT INTO clients (
                        spa_id,
                        business_unit_id,
                        first_name,
                        last_name,
                        phone,
                        email,
                        birth_date,
                        address,
                        city,
                        state,
                        zip,
                        client_status,
                        preferred_language,
                        ok_to_call,
                        ok_to_text,
                        ok_to_email,
                        preferred_contact_method,
                        emergency_contact_name,
                        emergency_contact_phone,
                        referred_by,
                        notes_one,
                        notes_two,
                        notes_three,
                        active_client,
                        sms_opt_in,
                        sms_opt_out,
                        email_opt_in,
                        email_opt_out,
                        sms_marketing_status,
                        email_marketing_status,
                        sms_consent_timestamp,
                        email_consent_timestamp
                    )
                    VALUES (
                        %s, %s, %s, %s, %s,
                        %s, %s, %s, %s, %s,
                        %s, %s, %s, %s, %s,
                        %s, %s, %s, %s, %s,
                        %s, %s, %s, %s, %s,
                        %s, %s, %s, %s, %s,
                        %s, %s
                    )
                    RETURNING client_id
                    """,
                    (
                        spa_id,
                        business_unit_id,
                        data.get("first_name", ""),
                        data.get("last_name", ""),
                        data.get("phone", ""),
                        data.get("email", ""),
                        data.get("birth_date") or None,
                        data.get("address", ""),
                        data.get("city", ""),
                        data.get("state", ""),
                        data.get("zip", ""),
                        data.get(
                            "client_status",
                            "Current",
                        ),
                        data.get(
                            "preferred_language"
                        ) or None,
                        CLIENT_IMPORT_COMMUNICATION_DEFAULTS[
                            "ok_to_call"
                        ],
                        CLIENT_IMPORT_COMMUNICATION_DEFAULTS[
                            "ok_to_text"
                        ],
                        CLIENT_IMPORT_COMMUNICATION_DEFAULTS[
                            "ok_to_email"
                        ],
                        data.get(
                            "preferred_contact_method"
                        ) or None,
                        data.get(
                            "emergency_contact_name",
                            "",
                        ),
                        data.get(
                            "emergency_contact_phone",
                            "",
                        ),
                        data.get("referred_by") or None,
                        data.get("notes_one", ""),
                        data.get("notes_two", ""),
                        data.get("notes_three", ""),
                        bool(
                            data.get(
                                "active_client",
                                True,
                            )
                        ),
                        CLIENT_IMPORT_COMMUNICATION_DEFAULTS[
                            "sms_opt_in"
                        ],
                        CLIENT_IMPORT_COMMUNICATION_DEFAULTS[
                            "sms_opt_out"
                        ],
                        CLIENT_IMPORT_COMMUNICATION_DEFAULTS[
                            "email_opt_in"
                        ],
                        CLIENT_IMPORT_COMMUNICATION_DEFAULTS[
                            "email_opt_out"
                        ],
                        CLIENT_IMPORT_COMMUNICATION_DEFAULTS[
                            "sms_marketing_status"
                        ],
                        CLIENT_IMPORT_COMMUNICATION_DEFAULTS[
                            "email_marketing_status"
                        ],
                        CLIENT_IMPORT_COMMUNICATION_DEFAULTS[
                            "sms_consent_timestamp"
                        ],
                        CLIENT_IMPORT_COMMUNICATION_DEFAULTS[
                            "email_consent_timestamp"
                        ],
                    ),
                )

                client_id = cur.fetchone()[0]

                client_information_keys = tuple(
                    field["key"]
                    for field in CLIENT_INFORMATION_IMPORT_FIELDS
                )

                client_information_presence_keys = (
                    "sex",
                    *client_information_keys,
                )

                has_client_information_data = any(
                    (
                        data.get(field_key) is not None
                        and (
                            not isinstance(
                                data.get(field_key),
                                str,
                            )
                            or bool(
                                data.get(field_key).strip()
                            )
                        )
                    )
                    for field_key in client_information_presence_keys
                    if field_key in data
                )

                if has_client_information_data:
                    cur.execute(
                        """
                        INSERT INTO client_health_profile (
                            spa_id,
                            client_id,
                            sex,
                            skin_type_id,
                            fitzpatrick_id,
                            skin_concerns,
                            skin_conditions,
                            allergies,
                            medications,
                            current_medical_conditions,
                            past_medical_treatments,
                            recent_injections,
                            recent_laser,
                            pregnant,
                            nursing,
                            using_retinol,
                            using_accutane,
                            sun_exposure_level,
                            last_facial_date,
                            notes1,
                            notes2,
                            notes3
                        )
                        VALUES (
                            %s, %s, %s, %s, %s, %s, %s,
                            %s, %s, %s, %s, %s, %s, %s,
                            %s, %s, %s, %s, %s, %s, %s,
                            %s
                        )
                        """,
                        (
                            spa_id,
                            client_id,
                            data.get("sex") or None,
                            data.get("skin_type_id") or None,
                            data.get("fitzpatrick_id") or None,
                            data.get("skin_concerns") or None,
                            data.get("skin_conditions") or None,
                            data.get("allergies") or None,
                            data.get("medications") or None,
                            data.get(
                                "current_medical_conditions"
                            ) or None,
                            data.get(
                                "past_medical_treatments"
                            ) or None,
                            data.get("recent_injections"),
                            data.get("recent_laser"),
                            data.get("pregnant"),
                            data.get("nursing"),
                            data.get("using_retinol"),
                            data.get("using_accutane"),
                            data.get("sun_exposure_level") or None,
                            data.get("last_facial_date") or None,
                            data.get("notes1") or None,
                            data.get("notes2") or None,
                            data.get("notes3") or None,
                        ),
                    )

                cur.execute(
                    """
                    UPDATE import_run_rows
                    SET import_status = 'imported',
                        imported_record_id = %s,
                        error_message = NULL,
                        updated_at = CURRENT_TIMESTAMP
                    WHERE import_run_row_id = %s
                      AND import_run_id = %s
                      AND spa_id = %s
                      AND business_unit_id = %s
                      AND review_decision = 'approved'
                      AND import_status = 'pending'
                    """,
                    (
                        client_id,
                        import_run_row_id,
                        import_run_id,
                        spa_id,
                        business_unit_id,
                    ),
                )

                if cur.rowcount != 1:
                    raise ImportServiceError(
                        "The staged Client row changed while "
                        "it was being imported."
                    )

                cur.execute(
                    "RELEASE SAVEPOINT client_import_row"
                )

                processed_this_packet += 1

            except Exception as exc:
                cur.execute(
                    "ROLLBACK TO SAVEPOINT client_import_row"
                )

                cur.execute(
                    "RELEASE SAVEPOINT client_import_row"
                )

                cur.execute(
                    """
                    UPDATE import_run_rows
                    SET import_status = 'error',
                        imported_record_id = NULL,
                        error_message = %s,
                        updated_at = CURRENT_TIMESTAMP
                    WHERE import_run_row_id = %s
                      AND import_run_id = %s
                      AND spa_id = %s
                      AND business_unit_id = %s
                    """,
                    (
                        str(exc)[:1000],
                        import_run_row_id,
                        import_run_id,
                        spa_id,
                        business_unit_id,
                    ),
                )

        # Recalculate from durable row state rather than relying
        # on in-memory increments. This keeps retries deterministic.
        cur.execute(
            """
            SELECT
                COUNT(*) FILTER (
                    WHERE import_status = 'imported'
                ),
                COUNT(*) FILTER (
                    WHERE import_status = 'skipped'
                ),
                COUNT(*) FILTER (
                    WHERE import_status = 'error'
                ),
                COUNT(*) FILTER (
                    WHERE import_status = 'pending'
                )
            FROM import_run_rows
            WHERE import_run_id = %s
              AND spa_id = %s
              AND business_unit_id = %s
            """,
            (
                import_run_id,
                spa_id,
                business_unit_id,
            ),
        )

        (
            imported_rows,
            skipped_rows,
            error_rows,
            remaining_rows,
        ) = cur.fetchone()

        if remaining_rows > 0:
            next_status = "importing"
            failure_message = None
            completed_at_sql = "completed_at"

        elif error_rows > 0:
            next_status = "failed"
            failure_message = (
                "One or more Client rows could not be imported."
            )
            completed_at_sql = "CURRENT_TIMESTAMP"

        else:
            next_status = "completed"
            failure_message = None
            completed_at_sql = "CURRENT_TIMESTAMP"

        cur.execute(
            f"""
            UPDATE import_runs
            SET run_status = %s,
                imported_rows = %s,
                skipped_rows = %s,
                error_rows = %s,
                failure_message = %s,
                completed_at = {completed_at_sql},
                last_activity_at = CURRENT_TIMESTAMP,
                updated_at = CURRENT_TIMESTAMP
            WHERE import_run_id = %s
              AND spa_id = %s
              AND business_unit_id = %s
            """,
            (
                next_status,
                imported_rows,
                skipped_rows,
                error_rows,
                failure_message,
                import_run_id,
                spa_id,
                business_unit_id,
            ),
        )

        conn.commit()

        return {
            "import_run_id": import_run_id,
            "run_status": next_status,
            "imported_rows": imported_rows,
            "skipped_rows": skipped_rows,
            "error_rows": error_rows,
            "processed_this_packet": (
                processed_this_packet
            ),
            "remaining_rows": remaining_rows,
        }

    except Exception:
        conn.rollback()
        raise

    finally:
        cur.close()
        conn.close()



# =========================================================
# STANDARD INCOME IMPORT POSTING
# =========================================================

APPOINTMENT_IMPORT_PACKET_SIZE = 50
APPOINTMENT_IMPORT_PACKET_MAX_ROWS = 50


def process_appointment_import_packet(
    import_run_id,
    *,
    spa_id,
    business_unit_id,
    packet_size=APPOINTMENT_IMPORT_PACKET_SIZE,
):
    """
    Import one bounded packet of validated Appointment rows.

    Safety rules:
      - only ready/importing Appointment runs may execute
      - only valid, approved rows may import
      - possible duplicates require prior explicit approval
      - strong duplicates and invalid rows never import
      - discarded rows become permanently skipped
      - each appointment, audit/history write, and staged-row
        update are atomic inside one row savepoint
      - posting rechecks duplicate identity
      - no live availability rule is imposed on migrated history
      - repeated calls never reinsert imported rows
    """
    try:
        packet_size = int(packet_size)
    except (TypeError, ValueError):
        raise ImportServiceError(
            "Import packet size must be a whole number."
        )

    if (
        packet_size < 1
        or packet_size > APPOINTMENT_IMPORT_PACKET_MAX_ROWS
    ):
        raise ImportServiceError(
            "Import packet size must be between 1 and "
            f"{APPOINTMENT_IMPORT_PACKET_MAX_ROWS}."
        )

    conn = get_db_connection()
    cur = conn.cursor()

    try:
        cur.execute(
            """
            SELECT
                entity_type,
                run_status,
                requested_by
            FROM import_runs
            WHERE import_run_id = %s
              AND spa_id = %s
              AND business_unit_id = %s
            FOR UPDATE
            """,
            (
                import_run_id,
                spa_id,
                business_unit_id,
            ),
        )

        run = cur.fetchone()

        if not run:
            raise ImportServiceError(
                "Import Run was not found in this workspace."
            )

        entity_type = str(
            run[0] or ""
        ).strip().lower()

        run_status = str(
            run[1] or ""
        ).strip().lower()

        requested_by = run[2]

        if entity_type != "appointments":
            raise ImportServiceError(
                "This importer currently executes "
                "Appointment runs only."
            )

        if run_status == "completed":
            cur.execute(
                """
                SELECT
                    total_rows,
                    imported_rows,
                    skipped_rows,
                    error_rows
                FROM import_runs
                WHERE import_run_id = %s
                """,
                (import_run_id,),
            )

            counts = cur.fetchone()

            conn.rollback()

            return {
                "import_run_id": import_run_id,
                "run_status": "completed",
                "total_rows": counts[0],
                "imported_rows": counts[1],
                "skipped_rows": counts[2],
                "error_rows": counts[3],
                "processed_this_packet": 0,
                "remaining_rows": 0,
            }

        if run_status not in {
            "ready",
            "importing",
        }:
            raise ImportServiceError(
                "This Appointment Import Run is not ready "
                "to import. Complete its review first."
            )

        cur.execute(
            """
            SELECT COUNT(*)
            FROM import_run_rows
            WHERE import_run_id = %s
              AND spa_id = %s
              AND business_unit_id = %s
              AND import_status = 'pending'
              AND review_decision = 'approved'
              AND (
                  validation_status <> 'valid'
                  OR duplicate_status NOT IN ('none', 'possible')
              )
            """,
            (
                import_run_id,
                spa_id,
                business_unit_id,
            ),
        )

        if cur.fetchone()[0]:
            raise ImportServiceError(
                "One or more approved Appointment rows still "
                "require validation or duplicate review."
            )

        cur.execute(
            """
            SELECT COUNT(*)
            FROM import_run_rows
            WHERE import_run_id = %s
              AND spa_id = %s
              AND business_unit_id = %s
              AND import_status = 'pending'
              AND (
                  review_decision IS NULL
                  OR review_decision NOT IN ('approved', 'discard')
              )
            """,
            (
                import_run_id,
                spa_id,
                business_unit_id,
            ),
        )

        if cur.fetchone()[0]:
            raise ImportServiceError(
                "This Appointment Import Run still has "
                "rows requiring review."
            )

        cur.execute(
            """
            UPDATE import_run_rows
            SET import_status = 'skipped',
                imported_record_id = NULL,
                error_message = NULL,
                updated_at = CURRENT_TIMESTAMP
            WHERE import_run_id = %s
              AND spa_id = %s
              AND business_unit_id = %s
              AND import_status = 'pending'
              AND review_decision = 'discard'
            """,
            (
                import_run_id,
                spa_id,
                business_unit_id,
            ),
        )

        cur.execute(
            """
            UPDATE import_runs
            SET run_status = 'importing',
                started_at = COALESCE(
                    started_at,
                    CURRENT_TIMESTAMP
                ),
                last_activity_at = CURRENT_TIMESTAMP,
                updated_at = CURRENT_TIMESTAMP
            WHERE import_run_id = %s
              AND spa_id = %s
              AND business_unit_id = %s
            """,
            (
                import_run_id,
                spa_id,
                business_unit_id,
            ),
        )

        cur.execute(
            """
            SELECT
                import_run_row_id,
                source_row_number,
                mapped_data,
                duplicate_status
            FROM import_run_rows
            WHERE import_run_id = %s
              AND spa_id = %s
              AND business_unit_id = %s
              AND validation_status = 'valid'
              AND duplicate_status IN ('none', 'possible')
              AND review_decision = 'approved'
              AND import_status = 'pending'
            ORDER BY source_row_number
            LIMIT %s
            """,
            (
                import_run_id,
                spa_id,
                business_unit_id,
                packet_size,
            ),
        )

        packet_rows = cur.fetchall()
        processed_this_packet = 0

        for (
            import_run_row_id,
            source_row_number,
            mapped_data,
            analyzed_duplicate_status,
        ) in packet_rows:
            data = (
                mapped_data
                if isinstance(mapped_data, dict)
                else {}
            )

            cur.execute(
                "SAVEPOINT appointment_import_row"
            )

            try:
                try:
                    client_id = int(
                        data.get("client_id")
                    )
                except (TypeError, ValueError):
                    raise ImportServiceError(
                        "Resolved Client is missing or invalid."
                    )

                appointment_date = str(
                    data.get("appointment_date") or ""
                ).strip()

                appointment_time = str(
                    data.get("appointment_time") or ""
                ).strip()

                status = str(
                    data.get("status") or ""
                ).strip().lower()

                if status not in {
                    "booked",
                    "completed",
                    "cancelled",
                    "no_show",
                }:
                    raise ImportServiceError(
                        "Appointment status is no longer valid."
                    )

                duration_raw = str(
                    data.get("duration_minutes") or ""
                ).strip()

                duration_minutes = (
                    int(duration_raw)
                    if duration_raw
                    else None
                )

                if (
                    status == "booked"
                    and duration_minutes is None
                ):
                    raise ImportServiceError(
                        "Duration Minutes is required for "
                        "Booked appointments."
                    )

                price_raw = str(
                    data.get("price_at_booking") or ""
                ).strip()

                price_at_booking = (
                    Decimal(price_raw)
                    if price_raw
                    else None
                )

                service_type_id_raw = data.get(
                    "service_type_id"
                )

                service_type_id = (
                    int(service_type_id_raw)
                    if service_type_id_raw not in {
                        None,
                        "",
                    }
                    else None
                )

                if (
                    status == "booked"
                    and service_type_id is None
                ):
                    raise ImportServiceError(
                        "Booked appointments must resolve "
                        "to an active Service Catalog service."
                    )

                provider_employee_id_raw = data.get(
                    "provider_employee_id"
                )

                provider_employee_id = (
                    int(provider_employee_id_raw)
                    if provider_employee_id_raw not in {
                        None,
                        "",
                    }
                    else None
                )

                service_name = str(
                    data.get("service_name") or ""
                ).strip()

                external_service_name = str(
                    data.get("external_service_name")
                    or service_name
                    or ""
                ).strip()

                provider_name_at_booking = str(
                    data.get("provider_name_at_booking")
                    or data.get("provider_name")
                    or ""
                ).strip() or None

                external_source = str(
                    data.get("external_source") or ""
                ).strip()

                external_order_id = str(
                    data.get("external_order_id") or ""
                ).strip()

                notes = str(
                    data.get("notes") or ""
                ).strip() or None

                # Client must still exist in this workspace.
                cur.execute(
                    """
                    SELECT client_id
                    FROM clients
                    WHERE client_id = %s
                      AND spa_id = %s
                      AND business_unit_id = %s
                    """,
                    (
                        client_id,
                        spa_id,
                        business_unit_id,
                    ),
                )

                if not cur.fetchone():
                    raise ImportServiceError(
                        "The resolved Client no longer exists "
                        "in this Provider Workspace."
                    )

                # Strong duplicate recheck.
                if external_order_id:
                    normalized_source = (
                        _normalize_import_dropdown_value(
                            external_source
                        )
                    )

                    duplicate_lock_key = (
                        "psp-appointment-import:"
                        f"{spa_id}:"
                        f"{normalized_source}:"
                        f"{external_order_id}"
                    )

                    cur.execute(
                        """
                        SELECT pg_advisory_xact_lock(
                            hashtext(%s)
                        )
                        """,
                        (duplicate_lock_key,),
                    )

                    cur.execute(
                        """
                        SELECT
                            appointment_id,
                            external_source
                        FROM appointments
                        WHERE spa_id = %s
                          AND external_order_id = %s
                        """,
                        (
                            spa_id,
                            external_order_id,
                        ),
                    )

                    strong_existing = None

                    for (
                        existing_appointment_id,
                        existing_external_source,
                    ) in cur.fetchall():
                        if (
                            _normalize_import_dropdown_value(
                                existing_external_source
                            )
                            == normalized_source
                        ):
                            strong_existing = (
                                existing_appointment_id
                            )
                            break

                    if strong_existing is not None:
                        raise ImportServiceError(
                            "A strong duplicate Appointment now "
                            "exists for this Booking System / "
                            "Source and External Appointment ID."
                        )

                # Possible duplicate recheck.
                staged_service_identity = (
                    _appointment_import_duplicate_service_identity(
                        data
                    )
                )

                cur.execute(
                    """
                    SELECT
                        appointment_id,
                        service_type_id,
                        external_service_name,
                        service_type
                    FROM appointments
                    WHERE spa_id = %s
                      AND business_unit_id = %s
                      AND client_id = %s
                      AND appointment_date = %s
                      AND appointment_time = %s
                    """,
                    (
                        spa_id,
                        business_unit_id,
                        client_id,
                        appointment_date,
                        appointment_time,
                    ),
                )

                current_possible_duplicate = None

                for (
                    existing_appointment_id,
                    existing_service_type_id,
                    existing_external_service_name,
                    existing_service_type,
                ) in cur.fetchall():
                    existing_identity = (
                        _appointment_import_duplicate_service_identity(
                            {
                                "service_type_id":
                                    existing_service_type_id,
                                "external_service_name":
                                    existing_external_service_name,
                                "service_name":
                                    existing_service_type,
                            }
                        )
                    )

                    if (
                        staged_service_identity is not None
                        and existing_identity
                        == staged_service_identity
                    ):
                        current_possible_duplicate = (
                            existing_appointment_id
                        )
                        break

                analyzed_duplicate_status = str(
                    analyzed_duplicate_status or "none"
                ).strip().lower()

                if (
                    current_possible_duplicate is not None
                    and analyzed_duplicate_status == "none"
                ):
                    raise ImportServiceError(
                        "A possible duplicate Appointment "
                        "appeared after this Import Run was "
                        "analyzed. Re-import the source file "
                        "so the duplicate can be reviewed."
                    )

                # Create the Appointment.
                #
                # booking_channel is intentionally omitted so the
                # existing database default ('manual') remains intact.
                #
                # owner_reviewed/import_reviewed are TRUE because the
                # controlled generic import workflow has already cleared
                # the row for normal PSP operation. import_reviewed_by
                # stays NULL for auto-approved clean rows so PSP does not
                # falsely attribute human review.
                cur.execute(
                    """
                    INSERT INTO appointments (
                        spa_id,
                        business_unit_id,
                        client_id,
                        service_type_id,
                        appointment_date,
                        appointment_time,
                        duration_minutes,
                        status,
                        price_at_booking,
                        notes,
                        service_type,
                        external_service_name,
                        external_source,
                        external_order_id,
                        imported_at,
                        import_reviewed,
                        import_reviewed_at,
                        import_reviewed_by,
                        parser_version,
                        import_status,
                        provider_name_at_booking,
                        provider_employee_id,
                        owner_reviewed,
                        owner_reviewed_at
                    )
                    VALUES (
                        %s, %s, %s, %s, %s, %s,
                        %s, %s, %s, %s, %s, %s,
                        %s, %s,
                        CURRENT_TIMESTAMP,
                        TRUE,
                        CURRENT_TIMESTAMP,
                        NULL,
                        'psp_appt_import_v1',
                        'Imported',
                        %s, %s,
                        TRUE,
                        CURRENT_TIMESTAMP
                    )
                    RETURNING appointment_id
                    """,
                    (
                        spa_id,
                        business_unit_id,
                        client_id,
                        service_type_id,
                        appointment_date,
                        appointment_time,
                        duration_minutes,
                        status,
                        price_at_booking,
                        notes,
                        service_name or None,
                        external_service_name or None,
                        external_source or None,
                        external_order_id or None,
                        provider_name_at_booking,
                        provider_employee_id,
                    ),
                )

                appointment_id = cur.fetchone()[0]

                # Audit entry.
                cur.execute(
                    """
                    INSERT INTO audit_log (
                        spa_id,
                        user_id,
                        action_type,
                        table_name,
                        record_id,
                        old_value,
                        new_value,
                        notes,
                        business_unit_id,
                        verified_employee_id
                    )
                    VALUES (
                        %s, %s, %s, %s, %s,
                        %s, %s, %s, %s, %s
                    )
                    """,
                    (
                        spa_id,
                        requested_by,
                        "appointment_imported",
                        "appointments",
                        appointment_id,
                        None,
                        (
                            f"{appointment_date} "
                            f"{appointment_time}"
                        ),
                        (
                            f"Appointment imported by Import Run "
                            f"{import_run_id}, source row "
                            f"{source_row_number}."
                        ),
                        business_unit_id,
                        None,
                    ),
                )

                # Initial Appointment History entry. This gives the
                # future Imported/I badge a durable starting point;
                # later normal appointment actions will naturally
                # clear the visible indicator without erasing
                # permanent import provenance.
                cur.execute(
                    """
                    INSERT INTO appointment_history (
                        spa_id,
                        business_unit_id,
                        appointment_id,
                        client_id,
                        user_id,
                        action_type,
                        old_date,
                        old_time,
                        new_date,
                        new_time,
                        old_status,
                        new_status,
                        notes
                    )
                    VALUES (
                        %s, %s, %s, %s, %s, %s,
                        %s, %s, %s, %s, %s, %s, %s
                    )
                    """,
                    (
                        spa_id,
                        business_unit_id,
                        appointment_id,
                        client_id,
                        requested_by,
                        "created",
                        None,
                        None,
                        appointment_date,
                        appointment_time,
                        None,
                        status,
                        (
                            f"Appointment created by Appointment "
                            f"Import Run {import_run_id}, source "
                            f"row {source_row_number}."
                        ),
                    ),
                )

                # Mark the staged row imported only after the
                # Appointment plus audit/history writes succeed.
                cur.execute(
                    """
                    UPDATE import_run_rows
                    SET import_status = 'imported',
                        imported_record_id = %s,
                        error_message = NULL,
                        updated_at = CURRENT_TIMESTAMP
                    WHERE import_run_row_id = %s
                      AND import_run_id = %s
                      AND spa_id = %s
                      AND business_unit_id = %s
                      AND review_decision = 'approved'
                      AND import_status = 'pending'
                    """,
                    (
                        appointment_id,
                        import_run_row_id,
                        import_run_id,
                        spa_id,
                        business_unit_id,
                    ),
                )

                if cur.rowcount != 1:
                    raise ImportServiceError(
                        "The staged Appointment row changed while "
                        "it was being imported."
                    )

                cur.execute(
                    "RELEASE SAVEPOINT appointment_import_row"
                )

                processed_this_packet += 1

            except Exception as exc:
                cur.execute(
                    "ROLLBACK TO SAVEPOINT appointment_import_row"
                )

                cur.execute(
                    "RELEASE SAVEPOINT appointment_import_row"
                )

                cur.execute(
                    """
                    UPDATE import_run_rows
                    SET import_status = 'error',
                        imported_record_id = NULL,
                        error_message = %s,
                        updated_at = CURRENT_TIMESTAMP
                    WHERE import_run_row_id = %s
                      AND import_run_id = %s
                      AND spa_id = %s
                      AND business_unit_id = %s
                    """,
                    (
                        str(exc)[:1000],
                        import_run_row_id,
                        import_run_id,
                        spa_id,
                        business_unit_id,
                    ),
                )

        # Recalculate counts from durable staged-row state.
        cur.execute(
            """
            SELECT
                COUNT(*) FILTER (
                    WHERE import_status = 'imported'
                ),
                COUNT(*) FILTER (
                    WHERE import_status = 'skipped'
                ),
                COUNT(*) FILTER (
                    WHERE import_status = 'error'
                ),
                COUNT(*) FILTER (
                    WHERE import_status = 'pending'
                )
            FROM import_run_rows
            WHERE import_run_id = %s
              AND spa_id = %s
              AND business_unit_id = %s
            """,
            (
                import_run_id,
                spa_id,
                business_unit_id,
            ),
        )

        (
            imported_rows,
            skipped_rows,
            error_rows,
            remaining_rows,
        ) = cur.fetchone()

        if remaining_rows > 0:
            next_status = "importing"
            failure_message = None
            completed_at_sql = "completed_at"

        elif error_rows > 0:
            next_status = "failed"
            failure_message = (
                "One or more Appointment rows could not "
                "be imported."
            )
            completed_at_sql = "CURRENT_TIMESTAMP"

        else:
            next_status = "completed"
            failure_message = None
            completed_at_sql = "CURRENT_TIMESTAMP"

        cur.execute(
            f"""
            UPDATE import_runs
            SET run_status = %s,
                imported_rows = %s,
                skipped_rows = %s,
                error_rows = %s,
                failure_message = %s,
                completed_at = {completed_at_sql},
                last_activity_at = CURRENT_TIMESTAMP,
                updated_at = CURRENT_TIMESTAMP
            WHERE import_run_id = %s
              AND spa_id = %s
              AND business_unit_id = %s
            """,
            (
                next_status,
                imported_rows,
                skipped_rows,
                error_rows,
                failure_message,
                import_run_id,
                spa_id,
                business_unit_id,
            ),
        )

        conn.commit()

        return {
            "import_run_id": import_run_id,
            "run_status": next_status,
            "imported_rows": imported_rows,
            "skipped_rows": skipped_rows,
            "error_rows": error_rows,
            "processed_this_packet": (
                processed_this_packet
            ),
            "remaining_rows": remaining_rows,
        }

    except Exception:
        conn.rollback()
        raise

    finally:
        cur.close()
        conn.close()

INCOME_IMPORT_PACKET_SIZE = 50
INCOME_IMPORT_PACKET_MAX_ROWS = 50


def insert_validated_expense_import_row(
    cur,
    *,
    spa_id,
    business_unit_id,
    mapped_data,
):
    """
    Insert one approved Expense using current workspace validation.

    The caller owns the transaction and any savepoint.
    Returns the Expense ID, or None for an existing strong
    transaction-identity duplicate.

    Approval and pending-row checks belong to the packet processor.
    """
    if not isinstance(mapped_data, dict):
        raise ImportServiceError(
            "Expense Import data must be a mapped record."
        )

    validated = validate_expense_import_row(mapped_data)

    if not validated["valid"]:
        raise ImportServiceError(
            "; ".join(validated["errors"])
        )

    prepared = [{
        "valid": True,
        "data": validated["data"],
        "errors": [],
    }]

    validate_expense_import_workspace_values(
        cur,
        spa_id=spa_id,
        business_unit_id=business_unit_id,
        prepared_rows=prepared,
    )

    row = prepared[0]

    if not row["valid"]:
        raise ImportServiceError(
            "; ".join(row["errors"])
        )

    data = row["data"]

    source = str(
        data.get("transaction_source") or ""
    ).strip() or None

    external_id = str(
        data.get("external_transaction_id") or ""
    ).strip() or None

    if external_id:
        source_key = _normalize_import_dropdown_value(source)

        cur.execute(
            """
            SELECT expense_id
            FROM expenses
            WHERE spa_id = %s
              AND business_unit_id = %s
              AND LOWER(REGEXP_REPLACE(
                    BTRIM(transaction_source),
                    '[[:space:]]+', ' ', 'g'
                  )) = %s
              AND BTRIM(external_transaction_id) = %s
            LIMIT 1
            """,
            (
                spa_id,
                business_unit_id,
                source_key,
                external_id,
            ),
        )

        if cur.fetchone():
            return None

    cur.execute(
        """
        INSERT INTO expenses (
            spa_id,
            business_unit_id,
            expense_date,
            vendor_name,
            category,
            description,
            amount,
            payment_method,
            notes,
            transaction_source,
            external_transaction_id
        )
        VALUES (
            %s, %s, %s, %s, %s, %s,
            %s, %s, %s, %s, %s
        )
        RETURNING expense_id
        """,
        (
            spa_id,
            business_unit_id,
            data["expense_date"],
            data["vendor_name"],
            data["category"],
            str(data.get("description") or "").strip() or None,
            Decimal(data["amount"]),
            str(data.get("payment_method") or "").strip() or None,
            str(data.get("notes") or "").strip() or None,
            source,
            external_id,
        ),
    )

    inserted = cur.fetchone()

    if not inserted:
        raise ImportServiceError(
            "Expense insert did not return an Expense ID."
        )

    return inserted[0]


def process_expense_import_packet(
    import_run_id,
    *,
    spa_id,
    business_unit_id,
    packet_size=50,
):
    """Post one durable packet of approved Expense Import rows."""
    try:
        packet_size = int(packet_size)
    except (TypeError, ValueError):
        raise ImportServiceError(
            "Expense packet size must be a whole number."
        )

    if not 1 <= packet_size <= 50:
        raise ImportServiceError(
            "Expense packet size must be between 1 and 50."
        )

    conn = get_db_connection()
    cur = conn.cursor()

    try:
        cur.execute(
            """
            SELECT entity_type, run_status
            FROM import_runs
            WHERE import_run_id = %s
              AND spa_id = %s
              AND business_unit_id = %s
            FOR UPDATE
            """,
            (import_run_id, spa_id, business_unit_id),
        )
        run = cur.fetchone()

        if not run:
            raise ImportServiceError(
                "Expense Import Run was not found in this workspace."
            )

        entity_type, run_status = run

        if entity_type != "expenses":
            raise ImportServiceError(
                "This processor accepts Expense imports only."
            )

        if run_status == "completed":
            cur.execute(
                """
                SELECT total_rows, imported_rows,
                       skipped_rows, error_rows
                FROM import_runs
                WHERE import_run_id = %s
                  AND spa_id = %s
                  AND business_unit_id = %s
                """,
                (import_run_id, spa_id, business_unit_id),
            )
            total, imported, skipped, errors = cur.fetchone()
            conn.rollback()
            return {
                "import_run_id": import_run_id,
                "run_status": "completed",
                "total_rows": total,
                "imported_rows": imported,
                "skipped_rows": skipped,
                "error_rows": errors,
                "processed_this_packet": 0,
                "remaining_rows": 0,
            }

        if run_status not in ("ready", "importing"):
            raise ImportServiceError(
                "Expense Import is not ready. Complete review first."
            )

        cur.execute(
            """
            SELECT COUNT(*)
            FROM import_run_rows
            WHERE import_run_id = %s
              AND spa_id = %s
              AND business_unit_id = %s
              AND import_status = 'pending'
              AND (
                  review_decision IS NULL
                  OR review_decision NOT IN ('approved', 'discard')
                  OR (
                      review_decision = 'approved'
                      AND (
                          validation_status <> 'valid'
                          OR duplicate_status NOT IN ('none', 'possible')
                      )
                  )
              )
            """,
            (import_run_id, spa_id, business_unit_id),
        )

        if cur.fetchone()[0]:
            raise ImportServiceError(
                "Expense Import contains unresolved or unsafe rows."
            )

        cur.execute(
            """
            UPDATE import_run_rows
            SET import_status = 'skipped',
                imported_record_id = NULL,
                error_message = NULL,
                updated_at = CURRENT_TIMESTAMP
            WHERE import_run_id = %s
              AND spa_id = %s
              AND business_unit_id = %s
              AND import_status = 'pending'
              AND review_decision = 'discard'
            """,
            (import_run_id, spa_id, business_unit_id),
        )

        cur.execute(
            """
            UPDATE import_runs
            SET run_status = 'importing',
                started_at = COALESCE(
                    started_at, CURRENT_TIMESTAMP
                ),
                last_activity_at = CURRENT_TIMESTAMP,
                updated_at = CURRENT_TIMESTAMP
            WHERE import_run_id = %s
              AND spa_id = %s
              AND business_unit_id = %s
            """,
            (import_run_id, spa_id, business_unit_id),
        )

        cur.execute(
            """
            SELECT import_run_row_id, mapped_data
            FROM import_run_rows
            WHERE import_run_id = %s
              AND spa_id = %s
              AND business_unit_id = %s
              AND validation_status = 'valid'
              AND duplicate_status IN ('none', 'possible')
              AND review_decision = 'approved'
              AND import_status = 'pending'
            ORDER BY source_row_number
            LIMIT %s
            """,
            (import_run_id, spa_id, business_unit_id, packet_size),
        )

        packet_rows = cur.fetchall()
        processed_this_packet = 0

        for row_id, mapped_data in packet_rows:
            cur.execute("SAVEPOINT expense_import_row")

            try:
                expense_id = insert_validated_expense_import_row(
                    cur,
                    spa_id=spa_id,
                    business_unit_id=business_unit_id,
                    mapped_data=mapped_data,
                )

                if expense_id is None:
                    cur.execute(
                        """
                        UPDATE import_run_rows
                        SET import_status = 'skipped',
                            review_decision = 'discard',
                            duplicate_status = 'strong',
                            imported_record_id = NULL,
                            error_message =
                                'External transaction identity already exists.',
                            updated_at = CURRENT_TIMESTAMP
                        WHERE import_run_row_id = %s
                          AND import_run_id = %s
                          AND spa_id = %s
                          AND business_unit_id = %s
                          AND import_status = 'pending'
                        """,
                        (row_id, import_run_id, spa_id, business_unit_id),
                    )
                else:
                    cur.execute(
                        """
                        UPDATE import_run_rows
                        SET import_status = 'imported',
                            imported_record_id = %s,
                            error_message = NULL,
                            updated_at = CURRENT_TIMESTAMP
                        WHERE import_run_row_id = %s
                          AND import_run_id = %s
                          AND spa_id = %s
                          AND business_unit_id = %s
                          AND review_decision = 'approved'
                          AND import_status = 'pending'
                        """,
                        (
                            expense_id, row_id, import_run_id,
                            spa_id, business_unit_id,
                        ),
                    )

                if cur.rowcount != 1:
                    raise ImportServiceError(
                        "Staged Expense row changed during posting."
                    )

                cur.execute("RELEASE SAVEPOINT expense_import_row")
                processed_this_packet += 1

            except Exception as exc:
                cur.execute(
                    "ROLLBACK TO SAVEPOINT expense_import_row"
                )
                cur.execute(
                    "RELEASE SAVEPOINT expense_import_row"
                )

                constraint = getattr(
                    getattr(exc, "diag", None),
                    "constraint_name",
                    None,
                )

                if constraint == (
                    "uq_expenses_workspace_external_identity"
                ):
                    cur.execute(
                        """
                        UPDATE import_run_rows
                        SET import_status = 'skipped',
                            review_decision = 'discard',
                            duplicate_status = 'strong',
                            imported_record_id = NULL,
                            error_message =
                                'External transaction identity already exists.',
                            updated_at = CURRENT_TIMESTAMP
                        WHERE import_run_row_id = %s
                          AND import_run_id = %s
                          AND spa_id = %s
                          AND business_unit_id = %s
                          AND import_status = 'pending'
                        """,
                        (
                            row_id, import_run_id,
                            spa_id, business_unit_id,
                        ),
                    )
                else:
                    cur.execute(
                        """
                        UPDATE import_run_rows
                        SET import_status = 'error',
                            imported_record_id = NULL,
                            error_message = %s,
                            updated_at = CURRENT_TIMESTAMP
                        WHERE import_run_row_id = %s
                          AND import_run_id = %s
                          AND spa_id = %s
                          AND business_unit_id = %s
                          AND import_status = 'pending'
                        """,
                        (
                            str(exc)[:2000], row_id, import_run_id,
                            spa_id, business_unit_id,
                        ),
                    )

                if cur.rowcount != 1:
                    raise ImportServiceError(
                        "Failed to record Expense posting outcome."
                    )

        cur.execute(
            """
            SELECT
                COUNT(*) FILTER (
                    WHERE import_status = 'imported'
                ),
                COUNT(*) FILTER (
                    WHERE import_status = 'skipped'
                ),
                COUNT(*) FILTER (
                    WHERE import_status = 'error'
                ),
                COUNT(*) FILTER (
                    WHERE import_status = 'pending'
                )
            FROM import_run_rows
            WHERE import_run_id = %s
              AND spa_id = %s
              AND business_unit_id = %s
            """,
            (import_run_id, spa_id, business_unit_id),
        )

        imported, skipped, errors, remaining = cur.fetchone()

        if remaining:
            next_status = "importing"
        elif errors:
            next_status = "failed"
        else:
            next_status = "completed"

        failure_message = (
            "One or more Expense rows could not be imported."
            if next_status == "failed"
            else None
        )

        cur.execute(
            """
            UPDATE import_runs
            SET run_status = %s,
                imported_rows = %s,
                skipped_rows = %s,
                error_rows = %s,
                failure_message = %s,
                completed_at = CASE
                    WHEN %s = 'completed'
                    THEN CURRENT_TIMESTAMP
                    ELSE completed_at
                END,
                last_activity_at = CURRENT_TIMESTAMP,
                updated_at = CURRENT_TIMESTAMP
            WHERE import_run_id = %s
              AND spa_id = %s
              AND business_unit_id = %s
            """,
            (
                next_status, imported, skipped, errors,
                failure_message, next_status,
                import_run_id, spa_id, business_unit_id,
            ),
        )

        if cur.rowcount != 1:
            raise ImportServiceError(
                "Expense Import progress could not be saved."
            )

        conn.commit()

        return {
            "import_run_id": import_run_id,
            "run_status": next_status,
            "imported_rows": imported,
            "skipped_rows": skipped,
            "error_rows": errors,
            "processed_this_packet": processed_this_packet,
            "remaining_rows": remaining,
        }

    except Exception:
        conn.rollback()
        raise

    finally:
        cur.close()
        conn.close()


def process_income_import_packet(
    import_run_id,
    *,
    spa_id,
    business_unit_id,
    packet_size=INCOME_IMPORT_PACKET_SIZE,
):
    """
    Post one bounded packet of approved standard Income rows.

    Safety rules:
      - only READY / already-IMPORTING Income runs execute
      - only valid, non-duplicate, approved, pending rows post
      - strong duplicates can never post
      - unresolved review rows block posting
      - discarded rows are permanently skipped
      - Income Type and Payment Method are revalidated at posting
      - optional Client is revalidated in the current workspace
      - each Income insert and staged-row update are atomic
      - repeated calls are safe; imported rows are never reinserted
    """

    try:
        packet_size = int(packet_size)
    except (TypeError, ValueError):
        raise ImportServiceError(
            "Import packet size must be a whole number."
        )

    if (
        packet_size < 1
        or packet_size > INCOME_IMPORT_PACKET_MAX_ROWS
    ):
        raise ImportServiceError(
            "Import packet size must be between 1 and "
            f"{INCOME_IMPORT_PACKET_MAX_ROWS}."
        )

    conn = get_db_connection()
    cur = conn.cursor()

    try:
        # Lock the run so two requests cannot post the same packet
        # at the same time.
        cur.execute(
            """
            SELECT
                entity_type,
                run_status
            FROM import_runs
            WHERE import_run_id = %s
              AND spa_id = %s
              AND business_unit_id = %s
            FOR UPDATE
            """,
            (
                import_run_id,
                spa_id,
                business_unit_id,
            ),
        )

        run = cur.fetchone()

        if not run:
            raise ImportServiceError(
                "Import Run was not found in this workspace."
            )

        entity_type = str(
            run[0] or ""
        ).strip().lower()

        run_status = str(
            run[1] or ""
        ).strip().lower()

        if entity_type != "income":
            raise ImportServiceError(
                "This importer executes standard Income runs only."
            )

        # A completed run is safely idempotent.
        if run_status == "completed":
            cur.execute(
                """
                SELECT
                    total_rows,
                    imported_rows,
                    skipped_rows,
                    error_rows
                FROM import_runs
                WHERE import_run_id = %s
                """,
                (import_run_id,),
            )

            counts = cur.fetchone()
            conn.rollback()

            return {
                "import_run_id": import_run_id,
                "run_status": "completed",
                "total_rows": counts[0],
                "imported_rows": counts[1],
                "skipped_rows": counts[2],
                "error_rows": counts[3],
                "processed_this_packet": 0,
                "remaining_rows": 0,
            }

        if run_status not in {
            "ready",
            "importing",
        }:
            raise ImportServiceError(
                "This Income Import Run is not ready to post. "
                "Complete its review first."
            )

        # Approval never overrides validation or a duplicate.
        cur.execute(
            """
            SELECT COUNT(*)
            FROM import_run_rows
            WHERE import_run_id = %s
              AND spa_id = %s
              AND business_unit_id = %s
              AND import_status = 'pending'
              AND review_decision = 'approved'
              AND (
                  validation_status <> 'valid'
                  OR duplicate_status <> 'none'
              )
            """,
            (
                import_run_id,
                spa_id,
                business_unit_id,
            ),
        )

        unsafe_approved_rows = cur.fetchone()[0]

        if unsafe_approved_rows:
            raise ImportServiceError(
                "One or more approved Income rows still require "
                "validation or duplicate review."
            )

        # READY means every pending row must have a final review
        # decision before posting begins.
        cur.execute(
            """
            SELECT COUNT(*)
            FROM import_run_rows
            WHERE import_run_id = %s
              AND spa_id = %s
              AND business_unit_id = %s
              AND import_status = 'pending'
              AND (
                  review_decision IS NULL
                  OR review_decision NOT IN ('approved', 'discard')
              )
            """,
            (
                import_run_id,
                spa_id,
                business_unit_id,
            ),
        )

        unresolved_review_rows = cur.fetchone()[0]

        if unresolved_review_rows:
            raise ImportServiceError(
                "This Income Import Run still has rows requiring review."
            )

        # Discard is terminal.
        cur.execute(
            """
            UPDATE import_run_rows
            SET import_status = 'skipped',
                imported_record_id = NULL,
                error_message = NULL,
                updated_at = CURRENT_TIMESTAMP
            WHERE import_run_id = %s
              AND spa_id = %s
              AND business_unit_id = %s
              AND import_status = 'pending'
              AND review_decision = 'discard'
            """,
            (
                import_run_id,
                spa_id,
                business_unit_id,
            ),
        )

        cur.execute(
            """
            UPDATE import_runs
            SET run_status = 'importing',
                started_at = COALESCE(
                    started_at,
                    CURRENT_TIMESTAMP
                ),
                last_activity_at = CURRENT_TIMESTAMP,
                updated_at = CURRENT_TIMESTAMP
            WHERE import_run_id = %s
              AND spa_id = %s
              AND business_unit_id = %s
            """,
            (
                import_run_id,
                spa_id,
                business_unit_id,
            ),
        )

        cur.execute(
            """
            SELECT
                import_run_row_id,
                source_row_number,
                mapped_data
            FROM import_run_rows
            WHERE import_run_id = %s
              AND spa_id = %s
              AND business_unit_id = %s
              AND validation_status = 'valid'
              AND duplicate_status = 'none'
              AND review_decision = 'approved'
              AND import_status = 'pending'
            ORDER BY source_row_number
            LIMIT %s
            """,
            (
                import_run_id,
                spa_id,
                business_unit_id,
                packet_size,
            ),
        )

        packet_rows = cur.fetchall()
        processed_this_packet = 0

        for (
            import_run_row_id,
            source_row_number,
            mapped_data,
        ) in packet_rows:

            data = (
                mapped_data
                if isinstance(mapped_data, dict)
                else {}
            )

            cur.execute(
                "SAVEPOINT income_import_row"
            )

            try:
                income_date_raw = str(
                    data.get("income_date") or ""
                ).strip()

                if not income_date_raw:
                    raise ImportServiceError(
                        "Income Date is required."
                    )

                try:
                    income_date = date.fromisoformat(
                        income_date_raw
                    )
                except ValueError:
                    raise ImportServiceError(
                        "Income Date is invalid."
                    )

                income_type = str(
                    data.get("income_type") or ""
                ).strip()

                if not income_type:
                    raise ImportServiceError(
                        "Income Type is required."
                    )

                payment_method = str(
                    data.get("payment_method") or ""
                ).strip()

                if not payment_method:
                    raise ImportServiceError(
                        "Payment Method is required."
                    )

                # Defense-in-depth: these values must still exist
                # when the row actually posts.
                cur.execute(
                    """
                    SELECT 1
                    FROM income_types
                    WHERE spa_id = %s
                      AND LOWER(TRIM(income_type_name)) =
                          LOWER(TRIM(%s))
                    LIMIT 1
                    """,
                    (
                        spa_id,
                        income_type,
                    ),
                )

                if not cur.fetchone():
                    raise ImportServiceError(
                        f"Income Type '{income_type}' no longer "
                        "exists in this business."
                    )

                cur.execute(
                    """
                    SELECT 1
                    FROM payment_methods
                    WHERE spa_id = %s
                      AND LOWER(TRIM(payment_method)) =
                          LOWER(TRIM(%s))
                    LIMIT 1
                    """,
                    (
                        spa_id,
                        payment_method,
                    ),
                )

                if not cur.fetchone():
                    raise ImportServiceError(
                        f"Payment Method '{payment_method}' no longer "
                        "exists in this business."
                    )

                client_id = data.get("client_id")

                if client_id in ("", None):
                    client_id = None
                else:
                    try:
                        client_id = int(client_id)
                    except (TypeError, ValueError):
                        raise ImportServiceError(
                            "Resolved Client ID is invalid."
                        )

                    cur.execute(
                        """
                        SELECT 1
                        FROM clients
                        WHERE client_id = %s
                          AND spa_id = %s
                          AND business_unit_id = %s
                        LIMIT 1
                        """,
                        (
                            client_id,
                            spa_id,
                            business_unit_id,
                        ),
                    )

                    if not cur.fetchone():
                        raise ImportServiceError(
                            "The resolved Client is no longer "
                            "available in this Provider Workspace."
                        )

                def money_value(key):
                    value = _parse_import_money(
                        data.get(key),
                        default=Decimal("0.00"),
                    )

                    if value is None:
                        return Decimal("0.00")

                    return value

                service_amount = money_value(
                    "service_amount"
                )
                retail_amount = money_value(
                    "retail_amount"
                )
                tax_amount = money_value(
                    "tax_amount"
                )
                total_amount = money_value(
                    "total_amount"
                )

                if total_amount < 0:
                    raise ImportServiceError(
                        "Total Amount cannot be negative."
                    )

                description = str(
                    data.get("description") or ""
                ).strip()

                processor_payment_id = str(
                    data.get("processor_payment_id") or ""
                ).strip() or None

                notes = str(
                    data.get("notes") or ""
                ).strip()

                cur.execute(
                    """
                    INSERT INTO income (
                        spa_id,
                        business_unit_id,
                        income_date,
                        client_id,
                        appointment_id,
                        visit_id,
                        income_type,
                        description,
                        service_amount,
                        retail_amount,
                        tax_amount,
                        total_amount,
                        payment_method,
                        processor_payment_id,
                        notes
                    )
                    VALUES (
                        %s, %s, %s, %s,
                        NULL, NULL,
                        %s, %s, %s, %s,
                        %s, %s, %s, %s, %s
                    )
                    RETURNING income_id
                    """,
                    (
                        spa_id,
                        business_unit_id,
                        income_date,
                        client_id,
                        income_type,
                        description,
                        service_amount,
                        retail_amount,
                        tax_amount,
                        total_amount,
                        payment_method,
                        processor_payment_id,
                        notes,
                    ),
                )

                income_id = cur.fetchone()[0]

                cur.execute(
                    """
                    UPDATE import_run_rows
                    SET import_status = 'imported',
                        imported_record_id = %s,
                        error_message = NULL,
                        updated_at = CURRENT_TIMESTAMP
                    WHERE import_run_row_id = %s
                      AND import_run_id = %s
                      AND spa_id = %s
                      AND business_unit_id = %s
                      AND review_decision = 'approved'
                      AND import_status = 'pending'
                    """,
                    (
                        income_id,
                        import_run_row_id,
                        import_run_id,
                        spa_id,
                        business_unit_id,
                    ),
                )

                if cur.rowcount != 1:
                    raise ImportServiceError(
                        "The staged Income row changed while "
                        "it was being imported."
                    )

                cur.execute(
                    "RELEASE SAVEPOINT income_import_row"
                )

                processed_this_packet += 1

            except Exception as exc:
                cur.execute(
                    "ROLLBACK TO SAVEPOINT income_import_row"
                )

                cur.execute(
                    "RELEASE SAVEPOINT income_import_row"
                )

                cur.execute(
                    """
                    UPDATE import_run_rows
                    SET import_status = 'error',
                        imported_record_id = NULL,
                        error_message = %s,
                        updated_at = CURRENT_TIMESTAMP
                    WHERE import_run_row_id = %s
                      AND import_run_id = %s
                      AND spa_id = %s
                      AND business_unit_id = %s
                    """,
                    (
                        str(exc)[:1000],
                        import_run_row_id,
                        import_run_id,
                        spa_id,
                        business_unit_id,
                    ),
                )

        # Recalculate counters from durable staged-row state.
        cur.execute(
            """
            SELECT
                COUNT(*) FILTER (
                    WHERE import_status = 'imported'
                ),
                COUNT(*) FILTER (
                    WHERE import_status = 'skipped'
                ),
                COUNT(*) FILTER (
                    WHERE import_status = 'error'
                ),
                COUNT(*) FILTER (
                    WHERE import_status = 'pending'
                )
            FROM import_run_rows
            WHERE import_run_id = %s
              AND spa_id = %s
              AND business_unit_id = %s
            """,
            (
                import_run_id,
                spa_id,
                business_unit_id,
            ),
        )

        (
            imported_rows,
            skipped_rows,
            error_rows,
            remaining_rows,
        ) = cur.fetchone()

        if remaining_rows > 0:
            next_status = "importing"
            failure_message = None
            completed_at_sql = "completed_at"

        elif error_rows > 0:
            next_status = "failed"
            failure_message = (
                "One or more Income rows could not be imported."
            )
            completed_at_sql = "CURRENT_TIMESTAMP"

        else:
            next_status = "completed"
            failure_message = None
            completed_at_sql = "CURRENT_TIMESTAMP"

        cur.execute(
            f"""
            UPDATE import_runs
            SET run_status = %s,
                imported_rows = %s,
                skipped_rows = %s,
                error_rows = %s,
                failure_message = %s,
                completed_at = {completed_at_sql},
                last_activity_at = CURRENT_TIMESTAMP,
                updated_at = CURRENT_TIMESTAMP
            WHERE import_run_id = %s
              AND spa_id = %s
              AND business_unit_id = %s
            """,
            (
                next_status,
                imported_rows,
                skipped_rows,
                error_rows,
                failure_message,
                import_run_id,
                spa_id,
                business_unit_id,
            ),
        )

        conn.commit()

        return {
            "import_run_id": import_run_id,
            "run_status": next_status,
            "imported_rows": imported_rows,
            "skipped_rows": skipped_rows,
            "error_rows": error_rows,
            "processed_this_packet": (
                processed_this_packet
            ),
            "remaining_rows": remaining_rows,
        }

    except Exception:
        conn.rollback()
        raise

    finally:
        cur.close()
        conn.close()


# =========================================================
# PEACHPOS INCOME IMPORT POSTING
# =========================================================

def process_peachpos_income_import_packet(
    import_run_id,
    *,
    spa_id,
    business_unit_id,
    packet_size=PEACHPOS_INCOME_IMPORT_PACKET_SIZE,
):
    """
    Post one bounded packet of approved PeachPOS Income rows.

    Safety rules:
      - only READY / already-IMPORTING PeachPOS Income runs execute
      - only valid, non-duplicate, approved, pending rows post
      - held / needs-review rows remain staged and unposted
      - discarded rows are marked skipped and never post
      - each Income insert and staged-row update are atomic
      - Processor Fields 1-8 are the active imported custom fields
      - repeated calls are safe; imported rows are never reinserted
      - database uniqueness protects processor transaction identity
    """
    try:
        packet_size = int(packet_size)
    except (TypeError, ValueError):
        raise ImportServiceError(
            "Import packet size must be a whole number."
        )

    if (
        packet_size < 1
        or packet_size > PEACHPOS_INCOME_IMPORT_PACKET_MAX_ROWS
    ):
        raise ImportServiceError(
            "Import packet size must be between 1 and "
            f"{PEACHPOS_INCOME_IMPORT_PACKET_MAX_ROWS}."
        )

    conn = get_db_connection()
    cur = conn.cursor()

    try:
        # Lock the run so two requests cannot post the same packet
        # at the same time.
        cur.execute(
            """
            SELECT
                entity_type,
                run_status,
                options_json
            FROM import_runs
            WHERE import_run_id = %s
              AND spa_id = %s
              AND business_unit_id = %s
            FOR UPDATE
            """,
            (
                import_run_id,
                spa_id,
                business_unit_id,
            ),
        )
        run = cur.fetchone()

        if not run:
            raise ImportServiceError(
                "Import Run was not found in this workspace."
            )

        entity_type = str(run[0] or "").strip().lower()
        run_status = str(run[1] or "").strip().lower()
        options = (
            run[2]
            if isinstance(run[2], dict)
            else {}
        )

        if entity_type != "peachpos_income":
            raise ImportServiceError(
                "This importer executes PeachPOS Income runs only."
            )

        if run_status == "completed":
            cur.execute(
                """
                SELECT
                    total_rows,
                    imported_rows,
                    skipped_rows,
                    error_rows
                FROM import_runs
                WHERE import_run_id = %s
                """,
                (import_run_id,),
            )
            counts = cur.fetchone()
            conn.rollback()

            return {
                "import_run_id": import_run_id,
                "run_status": "completed",
                "total_rows": counts[0],
                "imported_rows": counts[1],
                "skipped_rows": counts[2],
                "error_rows": counts[3],
                "processed_this_packet": 0,
                "remaining_rows": 0,
            }

        if run_status not in {
            "ready",
            "importing",
        }:
            raise ImportServiceError(
                "This PeachPOS Import Run is not ready to post."
            )

        credit_processor_id = options.get(
            "credit_processor_id"
        )
        try:
            credit_processor_id = int(
                credit_processor_id
            )
        except (TypeError, ValueError):
            raise ImportServiceError(
                "This PeachPOS Import Run does not have a valid "
                "credit processor."
            )

        event_name = str(
            options.get("event_name") or ""
        ).strip() or None

        # Verify that the selected processor belongs to this exact
        # Provider Workspace. Historical/inactive processors remain
        # valid for durable import history.
        cur.execute(
            """
            SELECT
                credit_processor_name,
                percentage_fee,
                flat_fee,
                additional_fee,
                merchant_account_identifier
            FROM credit_processors
            WHERE credit_processor_id = %s
              AND spa_id = %s
              AND business_unit_id = %s
            """,
            (
                credit_processor_id,
                spa_id,
                business_unit_id,
            ),
        )
        processor = cur.fetchone()

        if not processor:
            raise ImportServiceError(
                "The selected credit processor was not found in "
                "this workspace."
            )

        processor_name = str(
            processor[0] or ""
        ).strip()

        if not processor_name:
            raise ImportServiceError(
                "The selected credit processor does not have a "
                "valid name."
            )

        # -------------------------------------------------
        # Defense-in-depth Merchant ID posting gate.
        #
        # Analysis must have already verified one Merchant ID
        # from the uploaded file against Processor Company Setup.
        # Recheck that durable verification snapshot here before
        # any Income row can be created.
        # -------------------------------------------------

        if processor_name.lower() == "square":
            raise ImportServiceError(
                "Square transactions use PSP's native Square "
                "integration and cannot be posted through the "
                "generic PeachPOS Income Import."
            )

        merchant_verification = options.get(
            "merchant_verification"
        )
        if not isinstance(
            merchant_verification,
            dict,
        ):
            raise ImportServiceError(
                "This PeachPOS Import Run does not have a "
                "Merchant ID / Account ID verification. "
                "Re-analyze the import before posting."
            )

        if merchant_verification.get("verified") is not True:
            raise ImportServiceError(
                "Merchant ID / Account ID verification was not "
                "successful. Import posting is blocked."
            )

        detected_identifier = str(
            merchant_verification.get(
                "detected_identifier"
            )
            or ""
        ).strip()

        verified_configured_identifier = str(
            merchant_verification.get(
                "configured_identifier_at_verification"
            )
            or ""
        ).strip()

        verified_processor_company = str(
            merchant_verification.get(
                "processor_company"
            )
            or ""
        ).strip()

        current_configured_identifier = str(
            processor[4] or ""
        ).strip()

        if (
            not detected_identifier
            or not verified_configured_identifier
            or detected_identifier
                != verified_configured_identifier
        ):
            raise ImportServiceError(
                "This PeachPOS Import Run has an invalid "
                "Merchant ID / Account ID verification record. "
                "Posting is blocked."
            )

        if (
            verified_processor_company
            and verified_processor_company != processor_name
        ):
            raise ImportServiceError(
                "The processor company changed after Merchant "
                "ID verification. Re-analyze the import before "
                "posting."
            )

        if not current_configured_identifier:
            raise ImportServiceError(
                "Merchant ID / Account ID is no longer "
                "configured for this processor. "
                "Posting is blocked."
            )

        if (
            current_configured_identifier
            != verified_configured_identifier
        ):
            raise ImportServiceError(
                "Merchant ID / Account ID in Processor Company "
                "Setup changed after this import was verified. "
                "Re-analyze the import before posting."
            )

        processor_percentage_fee = (
            processor[1]
            if processor[1] is not None
            else Decimal("0")
        )
        processor_flat_fee = (
            processor[2]
            if processor[2] is not None
            else Decimal("0")
        )
        processor_additional_fee = (
            processor[3]
            if processor[3] is not None
            else Decimal("0")
        )

        # A row cannot be posted merely because somebody marked it
        # approved. It must also have passed validation and duplicate
        # analysis.
        cur.execute(
            """
            SELECT COUNT(*)
            FROM import_run_rows
            WHERE import_run_id = %s
              AND spa_id = %s
              AND business_unit_id = %s
              AND import_status = 'pending'
              AND review_decision = 'approved'
              AND (
                    validation_status <> 'valid'
                    OR duplicate_status <> 'none'
              )
            """,
            (
                import_run_id,
                spa_id,
                business_unit_id,
            ),
        )
        unsafe_approved_rows = cur.fetchone()[0]

        if unsafe_approved_rows:
            raise ImportServiceError(
                "One or more approved PeachPOS rows still require "
                "validation or duplicate review."
            )

        # Discard is a terminal review decision. Mark those rows
        # skipped so they remain in the Import Record but can never
        # accidentally post later.
        cur.execute(
            """
            UPDATE import_run_rows
            SET import_status = 'skipped',
                imported_record_id = NULL,
                error_message = NULL,
                updated_at = CURRENT_TIMESTAMP
            WHERE import_run_id = %s
              AND spa_id = %s
              AND business_unit_id = %s
              AND import_status = 'pending'
              AND review_decision = 'discard'
            """,
            (
                import_run_id,
                spa_id,
                business_unit_id,
            ),
        )

        cur.execute(
            """
            UPDATE import_runs
            SET run_status = 'importing',
                started_at = COALESCE(
                    started_at,
                    CURRENT_TIMESTAMP
                ),
                last_activity_at = CURRENT_TIMESTAMP,
                updated_at = CURRENT_TIMESTAMP
            WHERE import_run_id = %s
              AND spa_id = %s
              AND business_unit_id = %s
            """,
            (
                import_run_id,
                spa_id,
                business_unit_id,
            ),
        )

        cur.execute(
            """
            SELECT
                import_run_row_id,
                source_row_number,
                mapped_data
            FROM import_run_rows
            WHERE import_run_id = %s
              AND spa_id = %s
              AND business_unit_id = %s
              AND validation_status = 'valid'
              AND duplicate_status = 'none'
              AND review_decision = 'approved'
              AND import_status = 'pending'
            ORDER BY source_row_number
            LIMIT %s
            """,
            (
                import_run_id,
                spa_id,
                business_unit_id,
                packet_size,
            ),
        )
        packet_rows = cur.fetchall()
        processed_this_packet = 0

        for (
            import_run_row_id,
            source_row_number,
            mapped_data,
        ) in packet_rows:
            data = (
                mapped_data
                if isinstance(mapped_data, dict)
                else {}
            )

            cur.execute(
                "SAVEPOINT peachpos_income_import_row"
            )

            try:
                transaction_at_raw = str(
                    data.get("transaction_at") or ""
                ).strip()

                if not transaction_at_raw:
                    raise ImportServiceError(
                        "Transaction Date/Time is required."
                    )

                try:
                    transaction_at = datetime.fromisoformat(
                        transaction_at_raw
                    )
                except ValueError:
                    raise ImportServiceError(
                        "Transaction Date/Time is invalid."
                    )

                processor_payment_id = str(
                    data.get("processor_payment_id") or ""
                ).strip()

                if not processor_payment_id:
                    raise ImportServiceError(
                        "Processor Transaction ID is required."
                    )

                def money_value(key, *, required=False):
                    raw = data.get(key)

                    if raw is None or str(raw).strip() == "":
                        if required:
                            raise ImportServiceError(
                                f"{key} is required."
                            )
                        return Decimal("0.00")

                    try:
                        return Decimal(str(raw))
                    except (InvalidOperation, ValueError):
                        raise ImportServiceError(
                            f"{key} is not a valid money amount."
                        )

                pos_amount = money_value(
                    "pos_amount",
                    required=True,
                )
                tax_amount = money_value("tax_amount")
                tip_amount = money_value("tip_amount")
                total_amount = money_value("total_amount")
                processing_fee_amount = money_value(
                    "processing_fee_amount"
                )
                net_received = money_value("net_received")

                # Income accounting columns are historically NOT NULL.
                # Preserve whether each optional amount was actually
                # supplied by the processor so a compatibility 0.00 is
                # never mistaken for processor-reported zero.
                optional_money_fields = (
                    "tax_amount",
                    "tip_amount",
                    "total_amount",
                    "processing_fee_amount",
                    "net_received",
                )
                processor_import_data = {
                    "source_presence": {
                        key: (
                            data.get(key) is not None
                            and str(data.get(key)).strip() != ""
                        )
                        for key in optional_money_fields
                    }
                }

                payment_method = str(
                    data.get("payment_method") or ""
                ).strip() or None

                processor_status = str(
                    data.get("processor_status") or ""
                ).strip() or None

                processor_fields = [
                    (
                        str(
                            data.get(
                                f"processor_field_{number}"
                            )
                            or ""
                        ).strip()
                        or None
                    )
                    for number in range(1, 9)
                ]

                description = (
                    f"PeachPOS {processor_name} Sale"
                )

                cur.execute(
                    """
                    INSERT INTO income (
                        income_date,
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
                        spa_id,
                        credit_processor_id,
                        processing_fee_amount,
                        net_received,
                        processor_percentage_fee,
                        processor_flat_fee,
                        processor_additional_fee,
                        business_unit_id,
                        transaction_at,
                        event_name,
                        processor_status,
                        processor_import_data,
                        processor_field_1,
                        processor_field_2,
                        processor_field_3,
                        processor_field_4,
                        processor_field_5,
                        processor_field_6,
                        processor_field_7,
                        processor_field_8
                    )
                    VALUES (
                        %s, %s, %s, %s, %s,
                        %s, %s, %s, %s, %s,
                        %s, %s, %s, %s, %s,
                        %s, %s, %s, %s, %s,
                        %s, %s, %s, %s, %s,
                        %s, %s, %s, %s, %s,
                        %s
                    )
                    RETURNING income_id
                    """,
                    (
                        transaction_at.date(),
                        "PeachPOS",
                        description,
                        Decimal("0.00"),
                        Decimal("0.00"),
                        pos_amount,
                        tax_amount,
                        tip_amount,
                        total_amount,
                        payment_method,
                        processor_payment_id,
                        spa_id,
                        credit_processor_id,
                        processing_fee_amount,
                        net_received,
                        processor_percentage_fee,
                        processor_flat_fee,
                        processor_additional_fee,
                        business_unit_id,
                        transaction_at,
                        event_name,
                        processor_status,
                        Json(processor_import_data),
                        *processor_fields,
                    ),
                )
                income_id = cur.fetchone()[0]

                cur.execute(
                    """
                    UPDATE import_run_rows
                    SET import_status = 'imported',
                        imported_record_id = %s,
                        error_message = NULL,
                        updated_at = CURRENT_TIMESTAMP
                    WHERE import_run_row_id = %s
                      AND import_run_id = %s
                      AND spa_id = %s
                      AND business_unit_id = %s
                      AND review_decision = 'approved'
                      AND import_status = 'pending'
                    """,
                    (
                        income_id,
                        import_run_row_id,
                        import_run_id,
                        spa_id,
                        business_unit_id,
                    ),
                )

                if cur.rowcount != 1:
                    raise ImportServiceError(
                        "The staged PeachPOS row changed while "
                        "it was being posted."
                    )

                cur.execute(
                    "RELEASE SAVEPOINT "
                    "peachpos_income_import_row"
                )
                processed_this_packet += 1

            except Exception as exc:
                cur.execute(
                    "ROLLBACK TO SAVEPOINT "
                    "peachpos_income_import_row"
                )
                cur.execute(
                    "RELEASE SAVEPOINT "
                    "peachpos_income_import_row"
                )

                cur.execute(
                    """
                    UPDATE import_run_rows
                    SET import_status = 'error',
                        imported_record_id = NULL,
                        error_message = %s,
                        updated_at = CURRENT_TIMESTAMP
                    WHERE import_run_row_id = %s
                      AND import_run_id = %s
                      AND spa_id = %s
                      AND business_unit_id = %s
                    """,
                    (
                        str(exc)[:1000],
                        import_run_row_id,
                        import_run_id,
                        spa_id,
                        business_unit_id,
                    ),
                )

        # Durable counters are always recalculated from staged row
        # state so retries remain deterministic.
        cur.execute(
            """
            SELECT
                COUNT(*) FILTER (
                    WHERE import_status = 'imported'
                ),
                COUNT(*) FILTER (
                    WHERE import_status = 'skipped'
                ),
                COUNT(*) FILTER (
                    WHERE import_status = 'error'
                )
            FROM import_run_rows
            WHERE import_run_id = %s
              AND spa_id = %s
              AND business_unit_id = %s
            """,
            (
                import_run_id,
                spa_id,
                business_unit_id,
            ),
        )
        (
            imported_rows,
            skipped_rows,
            error_rows,
        ) = cur.fetchone()

        # Only approved, still-pending rows are remaining posting
        # work. Hold and needs_review deliberately remain staged.
        cur.execute(
            """
            SELECT COUNT(*)
            FROM import_run_rows
            WHERE import_run_id = %s
              AND spa_id = %s
              AND business_unit_id = %s
              AND review_decision = 'approved'
              AND import_status = 'pending'
            """,
            (
                import_run_id,
                spa_id,
                business_unit_id,
            ),
        )
        remaining_rows = cur.fetchone()[0]

        # Hold and needs_review rows are intentionally unresolved.
        # Keep the run open so they can be reviewed, approved, and
        # posted later instead of being stranded by a completed run.
        cur.execute(
            """
            SELECT COUNT(*)
            FROM import_run_rows
            WHERE import_run_id = %s
              AND spa_id = %s
              AND business_unit_id = %s
              AND review_decision IN ('hold', 'needs_review')
              AND import_status = 'pending'
            """,
            (
                import_run_id,
                spa_id,
                business_unit_id,
            ),
        )
        unresolved_review_rows = cur.fetchone()[0]

        if remaining_rows > 0:
            next_status = "importing"
            failure_message = None
            completed_at_sql = "completed_at"
        elif error_rows > 0:
            next_status = "failed"
            failure_message = (
                "One or more PeachPOS transactions could not "
                "be posted."
            )
            completed_at_sql = "CURRENT_TIMESTAMP"
        elif unresolved_review_rows > 0:
            next_status = "ready"
            failure_message = None
            completed_at_sql = "NULL"
        else:
            next_status = "completed"
            failure_message = None
            completed_at_sql = "CURRENT_TIMESTAMP"

        cur.execute(
            f"""
            UPDATE import_runs
            SET run_status = %s,
                imported_rows = %s,
                skipped_rows = %s,
                error_rows = %s,
                failure_message = %s,
                completed_at = {completed_at_sql},
                last_activity_at = CURRENT_TIMESTAMP,
                updated_at = CURRENT_TIMESTAMP
            WHERE import_run_id = %s
              AND spa_id = %s
              AND business_unit_id = %s
            """,
            (
                next_status,
                imported_rows,
                skipped_rows,
                error_rows,
                failure_message,
                import_run_id,
                spa_id,
                business_unit_id,
            ),
        )

        conn.commit()

        return {
            "import_run_id": import_run_id,
            "run_status": next_status,
            "imported_rows": imported_rows,
            "skipped_rows": skipped_rows,
            "error_rows": error_rows,
            "processed_this_packet": processed_this_packet,
            "remaining_rows": remaining_rows,
        }

    except Exception:
        conn.rollback()
        raise

    finally:
        cur.close()
        conn.close()


# =========================================================
# IMPORT RUN MAPPING DATA
# =========================================================

def get_import_run_mapping_data(
    import_run_id,
    *,
    spa_id,
    business_unit_id,
    preview_limit=10,
):
    """
    Load one durable Import Run for the column-mapping screen.

    Returns:
      - run metadata
      - source headers
      - PSP destination fields
      - current/suggested mapping
      - a small source-data preview

    This is read-only and remains strictly workspace scoped.
    """

    try:
        preview_limit = int(preview_limit)
    except (TypeError, ValueError):
        preview_limit = 10

    preview_limit = max(
        1,
        min(
            preview_limit,
            25,
        ),
    )

    conn = get_db_connection()
    cur = conn.cursor()

    try:
        cur.execute(
            """
            SELECT
                entity_type,
                run_status,
                source_filename,
                source_extension,
                source_size_bytes,
                mapping_json,
                options_json,
                total_rows,
                valid_rows,
                invalid_rows,
                strong_duplicate_rows,
                possible_duplicate_rows,
                imported_rows,
                skipped_rows,
                error_rows,
                requested_at
            FROM import_runs
            WHERE import_run_id = %s
              AND spa_id = %s
              AND business_unit_id = %s
            LIMIT 1
            """,
            (
                import_run_id,
                spa_id,
                business_unit_id,
            ),
        )

        run = cur.fetchone()

        if not run:
            raise ImportServiceError(
                "Import Run was not found in this workspace."
            )

        entity_type = str(
            run[0] or ""
        ).strip().lower()

        options_payload = (
            run[6]
            if isinstance(run[6], dict)
            else {}
        )

        profile = get_workspace_import_profile(
            cur,
            spa_id=spa_id,
            business_unit_id=business_unit_id,
            entity_type=entity_type,
            options=options_payload,
        )

        mapping_json = (
            run[5]
            if isinstance(run[5], dict)
            else {}
        )

        headers = mapping_json.get(
            "headers",
            [],
        )

        mapping = (
            mapping_json.get("selected")
            or mapping_json.get("suggestions")
            or []
        )

        cur.execute(
            """
            SELECT
                source_row_number,
                source_data
            FROM import_run_rows
            WHERE import_run_id = %s
              AND spa_id = %s
              AND business_unit_id = %s
            ORDER BY source_row_number
            LIMIT %s
            """,
            (
                import_run_id,
                spa_id,
                business_unit_id,
                preview_limit,
            ),
        )

        preview_rows = []

        for (
            source_row_number,
            source_data,
        ) in cur.fetchall():
            source_data = (
                source_data
                if isinstance(source_data, dict)
                else {}
            )

            preview_rows.append({
                "row_number": source_row_number,
                "values": source_data.get(
                    "values",
                    [],
                ),
            })

        return {
            "import_run_id": import_run_id,
            "entity_type": entity_type,
            "display_name": profile["display_name"],
            "run_status": run[1],
            "filename": run[2],
            "extension": run[3],
            "source_size_bytes": run[4],
            "headers": headers,
            "mapping": mapping,
            "options": options_payload,
            "fields": [
                {
                    "key": field["key"],
                    "label": field["label"],
                    "required": bool(
                        field.get("required")
                    ),
                }
                for field in profile["fields"]
            ],
            "preview_rows": preview_rows,
            "total_rows": run[7],
            "valid_rows": run[8],
            "invalid_rows": run[9],
            "strong_duplicate_rows": run[10],
            "possible_duplicate_rows": run[11],
            "imported_rows": run[12],
            "skipped_rows": run[13],
            "error_rows": run[14],
            "requested_at": run[15],
        }

    finally:
        cur.close()
        conn.close()
