BEGIN;

CREATE TABLE public.employee_payroll_expense_links (
    payment_id BIGINT PRIMARY KEY
        REFERENCES public.employee_payroll_payments(payment_id) ON DELETE RESTRICT,
    expense_id INTEGER NOT NULL UNIQUE,
    spa_id INTEGER NOT NULL,
    business_unit_id INTEGER NOT NULL,
    posted_by_user_id INTEGER NOT NULL REFERENCES public.users(user_id),
    posted_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp(),
    FOREIGN KEY (expense_id, spa_id, business_unit_id)
        REFERENCES public.expenses(expense_id, spa_id, business_unit_id)
        ON DELETE RESTRICT
);

CREATE FUNCTION public.guard_employee_payroll_expense_link()
RETURNS TRIGGER LANGUAGE plpgsql AS $$
DECLARE
    payment RECORD;
    expense RECORD;
    payroll_status TEXT;
BEGIN
    IF TG_OP <> 'INSERT' THEN
        RAISE EXCEPTION 'Payroll expense links cannot be edited or deleted.'
            USING ERRCODE = '23514';
    END IF;

    SELECT p.* INTO payment
    FROM public.employee_payroll_payments p
    WHERE p.payment_id = NEW.payment_id
      AND p.spa_id = NEW.spa_id
      AND p.business_unit_id = NEW.business_unit_id
    FOR UPDATE;
    IF NOT FOUND THEN
        RAISE EXCEPTION 'Matching payroll payment not found.'
            USING ERRCODE = '23514';
    END IF;

    SELECT status INTO payroll_status
    FROM public.employee_payroll_periods
    WHERE pay_period_id = payment.pay_period_id
      AND spa_id = NEW.spa_id
      AND business_unit_id = NEW.business_unit_id
      AND employee_id = payment.employee_id;

    IF payroll_status IS DISTINCT FROM 'paid'
       OR payment.reversed_at IS NOT NULL THEN
        RAISE EXCEPTION 'Expense posting requires a Paid, unreversed payment.'
            USING ERRCODE = '23514';
    END IF;

    SELECT e.* INTO expense FROM public.expenses e
    WHERE e.expense_id = NEW.expense_id
      AND e.spa_id = NEW.spa_id
      AND e.business_unit_id = NEW.business_unit_id
    FOR UPDATE;
    IF NOT FOUND THEN
        RAISE EXCEPTION 'Matching payroll expense not found.'
            USING ERRCODE = '23514';
    END IF;

    IF expense.amount IS DISTINCT FROM payment.payment_amount
       OR expense.expense_date IS DISTINCT FROM payment.payment_date
       OR expense.transaction_source IS DISTINCT FROM 'employee_payroll'
       OR expense.external_transaction_id IS DISTINCT FROM payment.payment_id::TEXT
    THEN
        RAISE EXCEPTION 'Expense does not match the recorded payroll payment.'
            USING ERRCODE = '23514';
    END IF;

    IF NOT EXISTS (
        SELECT 1 FROM public.users
        WHERE user_id = NEW.posted_by_user_id AND spa_id = NEW.spa_id
    ) THEN
        RAISE EXCEPTION 'Expense posting actor must belong to this business.'
            USING ERRCODE = '23514';
    END IF;
    RETURN NEW;
END;
$$;

CREATE TRIGGER trg_payroll_expense_link_guard
BEFORE INSERT OR UPDATE OR DELETE
ON public.employee_payroll_expense_links
FOR EACH ROW EXECUTE FUNCTION public.guard_employee_payroll_expense_link();

CREATE FUNCTION public.guard_linked_payroll_expense()
RETURNS TRIGGER LANGUAGE plpgsql AS $$
BEGIN
    IF EXISTS (
        SELECT 1 FROM public.employee_payroll_expense_links
        WHERE expense_id = OLD.expense_id
    ) THEN
        RAISE EXCEPTION
            'Linked payroll expenses are locked. Use an audited payroll correction.'
            USING ERRCODE = '23514';
    END IF;
    IF TG_OP = 'DELETE' THEN
        RETURN OLD;
    END IF;
    RETURN NEW;
END;
$$;

CREATE TRIGGER trg_linked_payroll_expense_guard
BEFORE UPDATE OR DELETE ON public.expenses
FOR EACH ROW EXECUTE FUNCTION public.guard_linked_payroll_expense();

CREATE FUNCTION public.audit_employee_payroll_expense_link()
RETURNS TRIGGER LANGUAGE plpgsql AS $$
BEGIN
    INSERT INTO public.employee_payroll_period_history (
        spa_id, business_unit_id, employee_id, pay_period_id,
        action_type, previous_status, new_status,
        details_json, actor_user_id
    )
    SELECT
        p.spa_id, p.business_unit_id, p.employee_id, p.pay_period_id,
        'payment_posted_to_expenses', 'paid', 'paid',
        jsonb_build_object(
            'payment_id', p.payment_id,
            'expense_id', NEW.expense_id,
            'payment_amount', p.payment_amount,
            'payment_date', p.payment_date
        ),
        NEW.posted_by_user_id
    FROM public.employee_payroll_payments p
    WHERE p.payment_id = NEW.payment_id;
    RETURN NEW;
END;
$$;

CREATE TRIGGER trg_payroll_expense_link_audit
AFTER INSERT ON public.employee_payroll_expense_links
FOR EACH ROW EXECUTE FUNCTION public.audit_employee_payroll_expense_link();

COMMENT ON TABLE public.employee_payroll_expense_links IS
    'Immutable links from recorded net payroll payments to matching expenses. '
    'Withheld deductions are excluded from these expense amounts.';

COMMIT;
