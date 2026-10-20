from datetime import date, timedelta
from decimal import Decimal, InvalidOperation
import re


class PayrollSettingsValidationError(ValueError):
    pass


PAY_PERIODS = {
    "weekly",
    "biweekly",
    "semimonthly",
    "monthly",
}


def parse_payroll_decimal(value, field, maximum):
    """Validate nonnegative money or percentage input."""
    raw = str(value or "").strip()

    if not raw:
        return None

    if not re.fullmatch(
        r"[0-9]+(?:\.[0-9]{1,2})?",
        raw,
    ):
        raise PayrollSettingsValidationError(
            f"{field} must be a nonnegative number "
            "with no more than two decimal places."
        )

    try:
        amount = Decimal(raw)
    except InvalidOperation:
        raise PayrollSettingsValidationError(
            f"Invalid {field}."
        )

    if (
        not amount.is_finite()
        or amount < 0
        or amount > maximum
    ):
        raise PayrollSettingsValidationError(
            f"{field} is outside its allowed range."
        )

    return amount


def validate_employee_payroll_settings(form):
    """Validate shared employee payroll configuration."""

    money_max = Decimal("9999999999.99")

    result = {}

    for field in (
        "hourly_rate",
        "daily_rate",
        "default_event_rate",
    ):
        result[field] = parse_payroll_decimal(
            form.get(field),
            field,
            money_max,
        )

    effective_raw = str(
        form.get("pay_effective_date") or ""
    ).strip()

    if effective_raw:
        try:
            result["pay_effective_date"] = (
                date.fromisoformat(effective_raw)
            )
        except ValueError:
            raise PayrollSettingsValidationError(
                "Invalid pay effective date."
            )
    else:
        result["pay_effective_date"] = None

    if (
        any(
            result[field] is not None
            for field in (
                "hourly_rate",
                "daily_rate",
                "default_event_rate",
            )
        )
        and result["pay_effective_date"] is None
    ):
        raise PayrollSettingsValidationError(
            "An effective date is required "
            "when entering pay rates."
        )

    period = str(
        form.get("default_pay_period") or ""
    ).strip()

    if period and period not in PAY_PERIODS:
        raise PayrollSettingsValidationError(
            "Invalid default pay period."
        )

    result["default_pay_period"] = period or None

    result["fica_withholding_percent"] = (
        parse_payroll_decimal(
            (str(form.get("fica_withholding_percent") or "").strip() or "0"),
            "FICA withholding percentage",
            Decimal("100.00"),
        )
    )

    for number in (1, 2):
        title_field = f"deduction_{number}_title"
        amount_field = f"deduction_{number}_amount"

        title = str(
            form.get(title_field) or ""
        ).strip()

        if len(title) > 100:
            raise PayrollSettingsValidationError(
                f"Deduction {number} title is too long."
            )

        amount = parse_payroll_decimal(
            form.get(amount_field),
            f"Deduction {number} amount",
            money_max,
        )

        if amount is not None and amount > 0 and not title:
            raise PayrollSettingsValidationError(
                f"Deduction {number} needs a title."
            )

        result[title_field] = title or None
        result[amount_field] = amount

    return result


def save_employee_payroll_settings(
    cur,
    *,
    spa_id,
    business_unit_id,
    employee_id,
    settings,
    allow_legacy_pay_period_update=False,
):
    """
    Save employee payroll configuration.

    The caller owns the transaction and audit logging.
    Returns True if a row was inserted or changed.
    """

    cur.execute("""
        SELECT 1
        FROM employee_business_unit_memberships
        WHERE spa_id = %s
          AND business_unit_id = %s
          AND employee_id = %s
          AND is_active = TRUE
        FOR SHARE
    """, (
        spa_id,
        business_unit_id,
        employee_id,
    ))

    if not cur.fetchone():
        raise PermissionError(
            "Employee is not assigned to the active workspace."
        )

    fields = (
        "default_pay_period",
        "fica_withholding_percent",
        "deduction_1_title",
        "deduction_1_amount",
        "deduction_2_title",
        "deduction_2_amount",
    )

    values = tuple(settings[field] for field in fields)

    # Legacy employee forms cannot overwrite operational
    # payroll schedules without explicit authorization.
    allow_legacy_pay_period_update = bool(
        allow_legacy_pay_period_update
    )

    if not allow_legacy_pay_period_update:
        values = (None, *values[1:])

    # Permit explicitly authorized legacy edits only when
    # no individual payroll cycle has been configured.
    # This also handles migration-marked legacy employees.
    #
    # A configured starting date or semimonthly start days
    # always protect operational employee payroll scheduling.
    cur.execute("""
        INSERT INTO employee_payroll_settings (
            spa_id,
            business_unit_id,
            employee_id,
            default_pay_period,
            fica_withholding_percent,
            deduction_1_title,
            deduction_1_amount,
            deduction_2_title,
            deduction_2_amount
        )
        VALUES (
            %s, %s, %s, %s, %s,
            %s, %s, %s, %s
        )
        ON CONFLICT (
            spa_id,
            business_unit_id,
            employee_id
        )
        DO UPDATE SET
            default_pay_period = CASE
                WHEN %s
                 AND employee_payroll_settings.pay_period_anchor_date
                     IS NULL
                 AND employee_payroll_settings.semimonthly_first_start_day
                     IS NULL
                 AND employee_payroll_settings.semimonthly_second_start_day
                     IS NULL
                THEN EXCLUDED.default_pay_period
                ELSE employee_payroll_settings.default_pay_period
            END,
            fica_withholding_percent =
                EXCLUDED.fica_withholding_percent,
            deduction_1_title = EXCLUDED.deduction_1_title,
            deduction_1_amount = EXCLUDED.deduction_1_amount,
            deduction_2_title = EXCLUDED.deduction_2_title,
            deduction_2_amount = EXCLUDED.deduction_2_amount,
            updated_at = NOW()
        WHERE (
            employee_payroll_settings.default_pay_period,
            employee_payroll_settings.fica_withholding_percent,
            employee_payroll_settings.deduction_1_title,
            employee_payroll_settings.deduction_1_amount,
            employee_payroll_settings.deduction_2_title,
            employee_payroll_settings.deduction_2_amount
        ) IS DISTINCT FROM (
            CASE
                WHEN %s
                 AND employee_payroll_settings.pay_period_anchor_date
                     IS NULL
                 AND employee_payroll_settings.semimonthly_first_start_day
                     IS NULL
                 AND employee_payroll_settings.semimonthly_second_start_day
                     IS NULL
                THEN EXCLUDED.default_pay_period
                ELSE employee_payroll_settings.default_pay_period
            END,
            EXCLUDED.fica_withholding_percent,
            EXCLUDED.deduction_1_title,
            EXCLUDED.deduction_1_amount,
            EXCLUDED.deduction_2_title,
            EXCLUDED.deduction_2_amount
        )
        RETURNING employee_id
    """, (
        spa_id,
        business_unit_id,
        employee_id,
        *values,
        allow_legacy_pay_period_update,
        allow_legacy_pay_period_update,
    ))

    return cur.fetchone() is not None


def save_employee_pay_rates(
    cur,
    *,
    spa_id,
    business_unit_id,
    employee_id,
    settings,
):
    """
    Save effective-dated employee pay rates.

    Hourly and daily rates are regular compensation rates.
    Event rate is an optional default suggestion.

    Existing historical rate amounts are never overwritten.
    Caller owns transaction and audit logging.

    Returns changed pay-rate types and their record IDs.
    """

    rate_fields = (
        ("hourly", "hourly_rate"),
        ("daily", "daily_rate"),
        ("event", "default_event_rate"),
    )

    pending = [
        (pay_type, settings.get(field))
        for pay_type, field in rate_fields
        if settings.get(field) is not None
    ]

    if not pending:
        return []

    effective_date = settings.get("pay_effective_date")

    if not isinstance(effective_date, date):
        raise PayrollSettingsValidationError(
            "A valid effective date is required."
        )

    # Lock membership to serialize rate changes
    # for this employee in this workspace.
    cur.execute("""
        SELECT 1
        FROM employee_business_unit_memberships
        WHERE spa_id = %s
          AND business_unit_id = %s
          AND employee_id = %s
          AND is_active = TRUE
        FOR UPDATE
    """, (
        spa_id,
        business_unit_id,
        employee_id,
    ))

    if not cur.fetchone():
        raise PermissionError(
            "Employee is not assigned to the active workspace."
        )

    changes = []

    for pay_type, new_rate in pending:
        identity = (spa_id, business_unit_id, employee_id, pay_type)

        cur.execute("""
            SELECT pay_rate_id, rate, effective_date, end_date
            FROM employee_pay_rates
            WHERE spa_id = %s AND business_unit_id = %s
              AND employee_id = %s AND pay_type = %s
              AND effective_date <= %s
            ORDER BY effective_date DESC
            LIMIT 1
            FOR UPDATE
        """, identity + (effective_date,))
        previous = cur.fetchone()

        if previous and previous[2] == effective_date:
            if new_rate == previous[1]:
                continue
            raise PayrollSettingsValidationError(
                f"{pay_type.title()} rate already exists for this effective date. "
                "Choose a different effective date for a rate change."
            )

        cur.execute("""
            SELECT effective_date
            FROM employee_pay_rates
            WHERE spa_id = %s AND business_unit_id = %s
              AND employee_id = %s AND pay_type = %s
              AND effective_date > %s
            ORDER BY effective_date ASC
            LIMIT 1
            FOR UPDATE
        """, identity + (effective_date,))
        following = cur.fetchone()
        new_end = (
            following[0] - timedelta(days=1)
            if following else None
        )

        if previous:
            previous_id, previous_rate, previous_start, previous_end = previous
            covers_date = (
                previous_end is None or previous_end >= effective_date
            )
            if new_rate == previous_rate and covers_date:
                continue

            if covers_date:
                cur.execute("""
                    UPDATE employee_pay_rates
                    SET end_date = %s
                    WHERE pay_rate_id = %s AND spa_id = %s
                      AND business_unit_id = %s AND employee_id = %s
                """, (
                    effective_date - timedelta(days=1),
                    previous_id, spa_id, business_unit_id, employee_id,
                ))
                if cur.rowcount != 1:
                    raise RuntimeError("Unable to close previous pay rate.")

        cur.execute("""
            INSERT INTO employee_pay_rates (
                spa_id, business_unit_id, employee_id,
                pay_type, rate, effective_date, end_date
            )
            VALUES (%s, %s, %s, %s, %s, %s, %s)
            RETURNING pay_rate_id
        """, identity + (new_rate, effective_date, new_end))
        pay_rate_id = cur.fetchone()[0]
        changes.append((pay_type, pay_rate_id))

    return changes
