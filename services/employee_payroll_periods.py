"""Saved payroll periods. Caller owns authorization and transaction."""

from datetime import date


class PayrollPeriodError(ValueError):
    pass


def create_draft_period(
    cur, *, spa_id, business_unit_id, employee_id, actor_user_id,
    period_start, period_end, pay_frequency, work_entry_ids,
    boundaries_confirmed,
):
    """Create a Draft and allocate entries; caller commits or rolls back."""
    for value in (spa_id, business_unit_id, employee_id, actor_user_id):
        if type(value) is not int or value <= 0:
            raise PayrollPeriodError("Invalid payroll identity.")

    if type(period_start) is not date or type(period_end) is not date:
        raise PayrollPeriodError("Valid pay-period dates are required.")
    if period_end < period_start:
        raise PayrollPeriodError("Period end cannot precede its start.")
    if pay_frequency not in {"weekly", "biweekly", "semimonthly", "monthly"}:
        raise PayrollPeriodError("Invalid pay frequency.")
    if boundaries_confirmed is not True:
        raise PayrollPeriodError("Confirm the pay-period dates before saving.")

    ids = list(work_entry_ids)
    if not ids or len(ids) > 10000:
        raise PayrollPeriodError("Select between 1 and 10,000 work entries.")
    if any(type(value) is not int or value <= 0 for value in ids):
        raise PayrollPeriodError("Invalid work-entry selection.")
    if len(set(ids)) != len(ids):
        raise PayrollPeriodError("A work entry was selected more than once.")

    cur.execute("""
        SELECT employee_id
        FROM employee_business_unit_memberships
        WHERE spa_id = %s AND business_unit_id = %s
          AND employee_id = %s AND is_active = TRUE
        FOR UPDATE
    """, (spa_id, business_unit_id, employee_id))
    if cur.fetchone() is None:
        raise PayrollPeriodError("Employee is not active in this workspace.")

    # Lock entries in a consistent order before validating the selection.
    cur.execute("""
        SELECT w.work_entry_id
        FROM employee_payroll_work_entries w
        WHERE w.spa_id = %s AND w.business_unit_id = %s
          AND w.employee_id = %s
          AND w.work_entry_id = ANY(%s)
          AND w.work_date BETWEEN %s AND %s
          AND w.voided_at IS NULL
          AND (w.clock_in_at IS NULL OR w.clock_out_at IS NOT NULL)
          AND NOT EXISTS (
              SELECT 1 FROM employee_payroll_period_entries pe
              WHERE pe.work_entry_id = w.work_entry_id
          )
        ORDER BY w.work_entry_id
        FOR UPDATE OF w
    """, (
        spa_id, business_unit_id, employee_id, ids,
        period_start, period_end,
    ))
    if len(cur.fetchall()) != len(ids):
        raise PayrollPeriodError(
            "Selected work entries changed or are unavailable. Refresh and review."
        )

    cur.execute("""
        SELECT set_config('psp.payroll_draft_update_actor', %s, true),
               set_config('psp.payroll_boundaries_confirmed', 'yes', true)
    """, (str(actor_user_id),))

    cur.execute("""
        INSERT INTO employee_payroll_periods (
            spa_id, business_unit_id, employee_id,
            period_start, period_end, pay_frequency_snapshot,
            boundaries_confirmed_by_user_id, created_by_user_id
        )
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
        RETURNING pay_period_id
    """, (
        spa_id, business_unit_id, employee_id,
        period_start, period_end, pay_frequency,
        actor_user_id, actor_user_id,
    ))
    row = cur.fetchone()
    period_id = (
        row["pay_period_id"] if hasattr(row, "keys") else row[0]
    )

    cur.execute("""
        INSERT INTO employee_payroll_period_entries (
            spa_id, business_unit_id, employee_id, pay_period_id,
            work_entry_id, work_date_snapshot, entry_type_snapshot,
            regular_hours_snapshot, overtime_hours_snapshot,
            days_worked_snapshot, rate_snapshot, overtime_rate_snapshot,
            event_name_snapshot, gross_amount_snapshot, created_by_user_id
        )
        SELECT w.spa_id, w.business_unit_id, w.employee_id, %s,
               w.work_entry_id, w.work_date, w.entry_type,
               w.regular_hours, w.overtime_hours, w.days_worked,
               w.rate_snapshot, w.overtime_rate_snapshot,
               w.event_name_snapshot,
               ROUND(CASE
                   WHEN w.entry_type = 'hourly' THEN
                       w.regular_hours * w.rate_snapshot
                       + w.overtime_hours * COALESCE(w.overtime_rate_snapshot, 0)
                   WHEN w.entry_type = 'daily' THEN
                       w.days_worked * w.rate_snapshot
                   WHEN w.entry_type = 'event' THEN w.rate_snapshot
                   ELSE 0
               END, 2),
               %s
        FROM employee_payroll_work_entries w
        WHERE w.spa_id = %s AND w.business_unit_id = %s
          AND w.employee_id = %s AND w.work_entry_id = ANY(%s)
        ORDER BY w.work_entry_id
    """, (
        period_id, actor_user_id, spa_id, business_unit_id, employee_id, ids,
    ))
    if cur.rowcount != len(ids):
        raise PayrollPeriodError("Unable to allocate every selected work entry.")

    return period_id


def calculate_period_totals(lines, settings):
    """Calculate from saved earning lines and explicit employee settings."""
    from decimal import Decimal, InvalidOperation, ROUND_HALF_UP

    cent = Decimal("0.01")
    zero = Decimal("0.00")

    def number(value, field):
        if value is None or isinstance(value, (bool, float)):
            raise PayrollPeriodError(f"{field} requires an explicit decimal value.")
        try:
            result = Decimal(str(value))
        except (InvalidOperation, ValueError):
            raise PayrollPeriodError(f"Invalid {field}.")
        if not result.is_finite() or result < 0:
            raise PayrollPeriodError(f"Invalid {field}.")
        return result

    lines = list(lines)
    if not lines:
        raise PayrollPeriodError("Select at least one earning line.")

    result = {
        "regular_hours_snapshot": zero,
        "overtime_hours_snapshot": zero,
        "days_worked_snapshot": zero,
        "event_count_snapshot": 0,
        "gross_pay_snapshot": zero,
    }
    for line in lines:
        if line["entry_type_snapshot"] not in {"hourly", "daily", "event"}:
            raise PayrollPeriodError("Invalid earning type.")
        for field in (
            "regular_hours_snapshot", "overtime_hours_snapshot",
            "days_worked_snapshot",
        ):
            result[field] += number(line[field], field)
        gross = number(line["gross_amount_snapshot"], "Saved gross earnings")
        if gross != gross.quantize(cent, rounding=ROUND_HALF_UP):
            raise PayrollPeriodError("Saved earnings must be rounded to cents.")
        result["gross_pay_snapshot"] += gross
        result["event_count_snapshot"] += (
            line["entry_type_snapshot"] == "event"
        )

    percent = number(
        (settings.get("fica_withholding_percent")
         if settings.get("fica_withholding_percent") is not None
         else "0"), "FICA percentage"
    )
    if percent > 100:
        raise PayrollPeriodError("FICA percentage cannot exceed 100.")
    result["fica_percent_snapshot"] = percent
    result["fica_amount_snapshot"] = (
        result["gross_pay_snapshot"] * percent / Decimal("100")
    ).quantize(cent, rounding=ROUND_HALF_UP)

    deductions = result["fica_amount_snapshot"]
    for index in (1, 2):
        title = settings.get(f"deduction_{index}_title")
        if title is not None and not isinstance(title, str):
            raise PayrollPeriodError("Deduction titles must be text.")
        title = (title or "").strip()
        if len(title) > 100:
            raise PayrollPeriodError("Deduction title is too long.")
        raw = settings.get(f"deduction_{index}_amount")
        amount = zero if raw is None else number(raw, "Deduction amount")
        if amount != amount.quantize(cent, rounding=ROUND_HALF_UP):
            raise PayrollPeriodError("Deductions must use whole cents.")
        if amount > 0 and not title:
            raise PayrollPeriodError("Positive deductions require a title.")
        result[f"deduction_{index}_title_snapshot"] = title or None
        result[f"deduction_{index}_amount_snapshot"] = amount
        deductions += amount

    if deductions > result["gross_pay_snapshot"]:
        raise PayrollPeriodError("Deductions cannot exceed gross earnings.")
    result["total_deductions_snapshot"] = deductions
    result["estimated_net_snapshot"] = (
        result["gross_pay_snapshot"] - deductions
    )
    return result


def recalculate_draft_period(
    cur, *, spa_id, business_unit_id, employee_id,
    pay_period_id, actor_user_id,
):
    """Save Draft totals using a mapping cursor; caller owns transaction."""
    from psycopg2 import sql

    for value in (
        spa_id, business_unit_id, employee_id, pay_period_id, actor_user_id,
    ):
        if type(value) is not int or value <= 0:
            raise PayrollPeriodError("Invalid payroll identity.")

    cur.execute("""
        SELECT status
        FROM employee_payroll_periods
        WHERE spa_id = %s AND business_unit_id = %s
          AND employee_id = %s AND pay_period_id = %s
        FOR UPDATE
    """, (spa_id, business_unit_id, employee_id, pay_period_id))
    period = cur.fetchone()
    if period is None:
        raise PayrollPeriodError("Pay period not found in this workspace.")
    if period["status"] != "draft":
        raise PayrollPeriodError("Only Draft payroll can be recalculated.")

    cur.execute("""
        SELECT fica_withholding_percent,
               deduction_1_title, deduction_1_amount,
               deduction_2_title, deduction_2_amount
        FROM employee_payroll_settings
        WHERE spa_id = %s AND business_unit_id = %s AND employee_id = %s
        FOR SHARE
    """, (spa_id, business_unit_id, employee_id))
    settings = cur.fetchone() or {}

    # The parent lock also serializes allocation changes.
    cur.execute("""
        SELECT entry_type_snapshot, regular_hours_snapshot,
               overtime_hours_snapshot, days_worked_snapshot,
               gross_amount_snapshot
        FROM employee_payroll_period_entries
        WHERE spa_id = %s AND business_unit_id = %s
          AND employee_id = %s AND pay_period_id = %s
        ORDER BY period_entry_id
    """, (spa_id, business_unit_id, employee_id, pay_period_id))
    totals = calculate_period_totals(cur.fetchall(), settings)

    cur.execute("""
        SELECT set_config('psp.payroll_draft_update_actor', %s, true)
    """, (str(actor_user_id),))

    # Column names come only from the calculator's fixed output fields.
    assignments = sql.SQL(", ").join(
        sql.SQL("{} = %s").format(sql.Identifier(field))
        for field in totals
    )
    cur.execute(
        sql.SQL("""
            UPDATE employee_payroll_periods
            SET {}, calculated_at = clock_timestamp(),
                updated_by_user_id = %s, updated_at = clock_timestamp()
            WHERE spa_id = %s AND business_unit_id = %s
              AND employee_id = %s AND pay_period_id = %s
              AND status = 'draft'
        """).format(assignments),
        tuple(totals.values()) + (
            actor_user_id, spa_id, business_unit_id, employee_id, pay_period_id,
        ),
    )
    if cur.rowcount != 1:
        raise PayrollPeriodError("Draft changed. Refresh before recalculating.")

    return totals


def read_draft_candidates(
    cur, *, spa_id, business_unit_id, employee_id, selected_date,
):
    """Read scheduled boundaries and available entries using a mapping cursor."""
    from services.employee_payroll_company_schedule import (
        get_company_payroll_schedule,
    )
    from services.employee_payroll_employee_schedule import (
        resolve_employee_schedule,
    )
    from services.employee_payroll_employee_schedule_storage import (
        get_employee_schedule_settings,
    )
    from services.employee_payroll_period_navigation import (
        build_pay_period_navigation,
    )

    for value in (spa_id, business_unit_id, employee_id):
        if type(value) is not int or value <= 0:
            raise PayrollPeriodError("Invalid payroll identity.")
    if type(selected_date) is not date:
        raise PayrollPeriodError("Select a valid period date.")

    cur.execute("""
        SELECT e.employee_id, e.first_name, e.last_name
        FROM employee_business_unit_memberships m
        JOIN employees e
          ON e.spa_id = m.spa_id AND e.employee_id = m.employee_id
        WHERE m.spa_id = %s AND m.business_unit_id = %s
          AND m.employee_id = %s AND m.is_active = TRUE
    """, (spa_id, business_unit_id, employee_id))
    employee = cur.fetchone()
    if employee is None:
        raise PayrollPeriodError("Employee is not active in this workspace.")

    company = get_company_payroll_schedule(
        cur, spa_id=spa_id, business_unit_id=business_unit_id,
    )
    settings = get_employee_schedule_settings(
        cur, spa_id=spa_id, business_unit_id=business_unit_id,
        employee_id=employee_id,
    )
    source, schedule = resolve_employee_schedule(
        company_row=company, employee_row=settings,
    )
    navigation = build_pay_period_navigation(
        schedule, as_of=date.today(), selected_date=selected_date,
    )
    window = navigation.selected

    cur.execute("""
        SELECT w.work_entry_id, w.work_date, w.entry_type,
               w.regular_hours, w.overtime_hours, w.days_worked,
               w.rate_snapshot, w.overtime_rate_snapshot,
               w.event_name_snapshot,
               ROUND(CASE
                   WHEN w.entry_type = 'hourly' THEN
                       w.regular_hours * w.rate_snapshot
                       + w.overtime_hours * COALESCE(w.overtime_rate_snapshot, 0)
                   WHEN w.entry_type = 'daily' THEN
                       w.days_worked * w.rate_snapshot
                   WHEN w.entry_type = 'event' THEN w.rate_snapshot
                   ELSE 0
               END, 2) AS gross_amount
        FROM employee_payroll_work_entries w
        WHERE w.spa_id = %s AND w.business_unit_id = %s
          AND w.employee_id = %s
          AND w.work_date BETWEEN %s AND %s
          AND w.voided_at IS NULL
          AND (w.clock_in_at IS NULL OR w.clock_out_at IS NOT NULL)
          AND NOT EXISTS (
              SELECT 1 FROM employee_payroll_period_entries pe
              WHERE pe.work_entry_id = w.work_entry_id
          )
        ORDER BY w.work_date, w.work_entry_id
    """, (
        spa_id, business_unit_id, employee_id, window.start, window.end,
    ))
    return {
        "employee": employee,
        "schedule_source": source,
        "pay_frequency": schedule.pay_frequency,
        "period_start": window.start,
        "period_end": window.end,
        "is_prestart": navigation.selected_is_prestart,
        "entries": cur.fetchall(),
    }


def cancel_draft_period(
    cur, *, spa_id, business_unit_id, employee_id,
    pay_period_id, actor_user_id, reason,
):
    """Cancel only Draft payroll; caller commits or rolls back."""
    for value in (
        spa_id, business_unit_id, employee_id, pay_period_id, actor_user_id,
    ):
        if type(value) is not int or value <= 0:
            raise PayrollPeriodError("Invalid payroll identity.")
    if not isinstance(reason, str) or not reason.strip():
        raise PayrollPeriodError("A cancellation reason is required.")
    reason = reason.strip()
    if len(reason) > 1000:
        raise PayrollPeriodError("Keep the cancellation reason within 1,000 characters.")

    cur.execute("""
        SELECT status
        FROM employee_payroll_periods
        WHERE spa_id = %s AND business_unit_id = %s
          AND employee_id = %s AND pay_period_id = %s
        FOR UPDATE
    """, (spa_id, business_unit_id, employee_id, pay_period_id))
    period = cur.fetchone()
    if period is None:
        raise PayrollPeriodError("Pay period not found in this workspace.")
    if period["status"] != "draft":
        raise PayrollPeriodError("Only Draft pay periods can be cancelled.")

    cur.execute("""
        SELECT set_config('psp.payroll_draft_update_actor', %s, true)
    """, (str(actor_user_id),))
    cur.execute("""
        UPDATE employee_payroll_periods
        SET status = 'cancelled',
            cancelled_by_user_id = %s, cancelled_at = clock_timestamp(),
            cancellation_reason = %s,
            updated_by_user_id = %s, updated_at = clock_timestamp()
        WHERE spa_id = %s AND business_unit_id = %s
          AND employee_id = %s AND pay_period_id = %s
          AND status = 'draft'
    """, (
        actor_user_id, reason, actor_user_id,
        spa_id, business_unit_id, employee_id, pay_period_id,
    ))
    if cur.rowcount != 1:
        raise PayrollPeriodError("Draft changed. Refresh before cancelling.")


def approve_draft_period(
    cur, *, spa_id, business_unit_id, employee_id,
    pay_period_id, actor_user_id, reviewed_updated_at,
):
    """Approve reviewed snapshots; caller owns authorization and transaction."""
    for value in (
        spa_id, business_unit_id, employee_id, pay_period_id, actor_user_id,
    ):
        if type(value) is not int or value <= 0:
            raise PayrollPeriodError("Invalid payroll identity.")
    if not isinstance(reviewed_updated_at, str) or not reviewed_updated_at:
        raise PayrollPeriodError("Review the saved Draft before approval.")

    cur.execute("""
        SELECT status, updated_at, calculated_at
        FROM employee_payroll_periods
        WHERE spa_id = %s AND business_unit_id = %s
          AND employee_id = %s AND pay_period_id = %s
        FOR UPDATE
    """, (spa_id, business_unit_id, employee_id, pay_period_id))
    period = cur.fetchone()
    if period is None:
        raise PayrollPeriodError("Pay period not found in this workspace.")
    if period["status"] != "draft":
        raise PayrollPeriodError("Only Draft payroll can be approved.")
    if period["calculated_at"] is None:
        raise PayrollPeriodError("Calculate and review this Draft before approval.")
    if period["updated_at"].isoformat() != reviewed_updated_at:
        raise PayrollPeriodError("Draft changed. Refresh and review before approval.")

    cur.execute("""
        SELECT set_config('psp.payroll_draft_update_actor', %s, true)
    """, (str(actor_user_id),))
    cur.execute("""
        UPDATE employee_payroll_periods
        SET status = 'approved',
            approved_by_user_id = %s, approved_at = clock_timestamp(),
            updated_by_user_id = %s, updated_at = clock_timestamp()
        WHERE spa_id = %s AND business_unit_id = %s
          AND employee_id = %s AND pay_period_id = %s
          AND status = 'draft'
    """, (
        actor_user_id, actor_user_id,
        spa_id, business_unit_id, employee_id, pay_period_id,
    ))
    if cur.rowcount != 1:
        raise PayrollPeriodError("Draft changed. Refresh before approving.")


def record_period_payment(
    cur, *, spa_id, business_unit_id, employee_id, pay_period_id,
    actor_user_id, payment_date, payment_method, payment_reference="", notes="",
):
    """Record an external payment and Paid status atomically; caller owns TX."""
    for value in (
        spa_id, business_unit_id, employee_id, pay_period_id, actor_user_id,
    ):
        if type(value) is not int or value <= 0:
            raise PayrollPeriodError("Invalid payroll identity.")
    if type(payment_date) is not date:
        raise PayrollPeriodError("A valid payment date is required.")

    fields = {}
    for name, value, maximum in (
        ("method", payment_method, 80),
        ("reference", payment_reference, 160),
        ("notes", notes, 2000),
    ):
        if not isinstance(value, str) or len(value.strip()) > maximum:
            raise PayrollPeriodError(f"Invalid payment {name}.")
        fields[name] = value.strip()
    if not fields["method"]:
        raise PayrollPeriodError("A payment method is required.")

    cur.execute("""
        SELECT status, estimated_net_snapshot
        FROM employee_payroll_periods
        WHERE spa_id = %s AND business_unit_id = %s
          AND employee_id = %s AND pay_period_id = %s
        FOR UPDATE
    """, (spa_id, business_unit_id, employee_id, pay_period_id))
    period = cur.fetchone()
    if period is None:
        raise PayrollPeriodError("Pay period not found in this workspace.")
    if period["status"] != "approved":
        raise PayrollPeriodError("Only Approved payroll can be recorded as Paid.")
    if period["estimated_net_snapshot"] is None:
        raise PayrollPeriodError("Approved payroll has no saved net amount.")

    cur.execute("""
        SELECT payment_id FROM employee_payroll_payments
        WHERE spa_id = %s AND business_unit_id = %s
          AND employee_id = %s AND pay_period_id = %s
          AND reversed_at IS NULL
    """, (spa_id, business_unit_id, employee_id, pay_period_id))
    if cur.fetchone() is not None:
        raise PayrollPeriodError("A payment is already recorded for this period.")

    cur.execute("""
        INSERT INTO employee_payroll_payments (
            spa_id, business_unit_id, employee_id, pay_period_id,
            payment_date, payment_amount, payment_method,
            payment_reference, notes, recorded_by_user_id
        )
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
        RETURNING payment_id
    """, (
        spa_id, business_unit_id, employee_id, pay_period_id,
        payment_date, period["estimated_net_snapshot"], fields["method"],
        fields["reference"] or None, fields["notes"] or None, actor_user_id,
    ))
    payment_id = cur.fetchone()["payment_id"]

    cur.execute("""
        UPDATE employee_payroll_periods
        SET status = 'paid',
            paid_by_user_id = %s, paid_at = clock_timestamp(),
            updated_by_user_id = %s, updated_at = clock_timestamp()
        WHERE spa_id = %s AND business_unit_id = %s
          AND employee_id = %s AND pay_period_id = %s
          AND status = 'approved'
    """, (
        actor_user_id, actor_user_id,
        spa_id, business_unit_id, employee_id, pay_period_id,
    ))
    if cur.rowcount != 1:
        raise PayrollPeriodError("Payroll changed. Refresh before recording payment.")
    return payment_id
