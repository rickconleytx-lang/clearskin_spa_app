"""Post recorded net payroll payments to Expenses; caller owns authorization/TX."""

from decimal import Decimal

from services.employee_payroll_periods import PayrollPeriodError


def post_payment_expense(
    cur, *, spa_id, business_unit_id, payment_id, actor_user_id,
    vendor_name, category, payment_method,
):
    for value in (spa_id, business_unit_id, payment_id, actor_user_id):
        if type(value) is not int or value <= 0:
            raise PayrollPeriodError("Invalid payroll expense identity.")

    choices = []
    for value, maximum in (
        (vendor_name, 100), (category, 50), (payment_method, 50),
    ):
        if not isinstance(value, str) or not value.strip():
            raise PayrollPeriodError("Select a vendor, category, and payment method.")
        value = value.strip()
        if len(value) > maximum:
            raise PayrollPeriodError("An expense selection is too long.")
        choices.append(value)
    vendor_name, category, payment_method = choices

    cur.execute("""
        SELECT p.payment_id, p.pay_period_id, p.payment_date,
               p.payment_amount, p.payment_reference, p.reversed_at,
               r.status, e.first_name, e.last_name
        FROM employee_payroll_payments p
        JOIN employee_payroll_periods r
          ON r.pay_period_id = p.pay_period_id
         AND r.spa_id = p.spa_id AND r.business_unit_id = p.business_unit_id
         AND r.employee_id = p.employee_id
        JOIN employees e
          ON e.employee_id = p.employee_id AND e.spa_id = p.spa_id
        WHERE p.payment_id = %s AND p.spa_id = %s AND p.business_unit_id = %s
        FOR UPDATE OF r, p
    """, (payment_id, spa_id, business_unit_id))
    payment = cur.fetchone()
    if payment is None:
        raise PayrollPeriodError("Payroll payment not found in this workspace.")
    if payment["status"] != "paid" or payment["reversed_at"] is not None:
        raise PayrollPeriodError("Only a Paid, unreversed payment can be posted.")

    cur.execute("""
        SELECT expense_id FROM employee_payroll_expense_links
        WHERE payment_id = %s AND spa_id = %s AND business_unit_id = %s
    """, (payment_id, spa_id, business_unit_id))
    if cur.fetchone() is not None:
        raise PayrollPeriodError("This payroll payment is already posted to Expenses.")
    if payment["payment_amount"] > Decimal("99999999.99"):
        raise PayrollPeriodError("Payment exceeds the supported expense amount.")

    checks = (
        ("SELECT 1 FROM vendor_name WHERE spa_id = %s AND vendors_name = %s "
         "AND is_active = TRUE FOR SHARE", vendor_name),
        ("SELECT 1 FROM expense_categories WHERE spa_id = %s AND expense_cat_name = %s "
         "AND is_active = TRUE FOR SHARE", category),
        ("SELECT 1 FROM payment_methods WHERE spa_id = %s AND payment_method = %s "
         "AND is_active = TRUE FOR SHARE", payment_method),
    )
    for query, value in checks:
        cur.execute(query, (spa_id, value))
        if cur.fetchone() is None:
            raise PayrollPeriodError("An expense selection is no longer available.")

    name = " ".join(filter(None, (payment["first_name"], payment["last_name"])))
    description = (
        f"Net payroll payment for {name}; pay period #{payment['pay_period_id']}."
    )
    cur.execute("""
        INSERT INTO expenses (
            spa_id, business_unit_id, expense_date, vendor_name, category,
            description, amount, payment_method, notes,
            transaction_source, external_transaction_id
        ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s,
                  'employee_payroll', %s)
        RETURNING expense_id
    """, (
        spa_id, business_unit_id, payment["payment_date"], vendor_name, category,
        description, payment["payment_amount"], payment_method,
        "Net payment only. Withheld deductions are excluded. Payment reference: "
        + (payment["payment_reference"] or "None"),
        str(payment_id),
    ))
    expense_id = cur.fetchone()["expense_id"]
    cur.execute("""
        INSERT INTO employee_payroll_expense_links (
            payment_id, expense_id, spa_id, business_unit_id, posted_by_user_id
        ) VALUES (%s, %s, %s, %s, %s)
    """, (payment_id, expense_id, spa_id, business_unit_id, actor_user_id))
    return expense_id
