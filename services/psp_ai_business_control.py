"""Master Admin business-specific AI financial controls.

The caller must enforce Master Admin authorization and CSRF.
The caller owns commit/rollback.

All budget operations lock the platform budget first,
then the selected business budget.
"""

import json
import re
from decimal import Decimal


class BusinessAIControlError(ValueError):
    pass


def _validate_identity_and_reason(
    spa_id,
    actor_user_id,
    reason,
):
    if type(spa_id) is not int or spa_id <= 0:
        raise BusinessAIControlError(
            "Invalid business identity."
        )

    if (
        type(actor_user_id) is not int
        or actor_user_id <= 0
    ):
        raise BusinessAIControlError(
            "Invalid administrator identity."
        )

    if not isinstance(reason, str):
        raise BusinessAIControlError(
            "An administrator reason is required."
        )

    reason = " ".join(reason.split())

    if not 10 <= len(reason) <= 500:
        raise BusinessAIControlError(
            "Reason must contain 10 to 500 characters."
        )

    return reason


def _parse_limit(value, *, expected=False):
    if expected and value == "unconfigured":
        return None

    if not isinstance(value, str):
        raise BusinessAIControlError(
            "Invalid AI spending limit."
        )

    decimal_places = 8 if expected else 2

    pattern = (
        r"(?:0|[1-9][0-9]{0,9})"
        rf"(?:\.[0-9]{{1,{decimal_places}}})?"
    )

    if not re.fullmatch(pattern, value.strip()):
        raise BusinessAIControlError(
            "Invalid AI spending limit format."
        )

    amount = Decimal(value.strip())

    if not Decimal("0") < amount <= Decimal(
        "9999999999.99"
    ):
        raise BusinessAIControlError(
            "AI spending limit must be positive."
        )

    return amount


def _lock_business_budget(cur, spa_id):
    """Use the same platform-first ordering as the gateway."""

    cur.execute("""
        SELECT ai_budget_id
        FROM psp_ai_budgets
        WHERE scope = 'platform'
          AND spa_id IS NULL
        FOR UPDATE
    """)

    if cur.fetchone() is None:
        raise BusinessAIControlError(
            "Platform AI budget is not configured."
        )

    cur.execute("""
        SELECT spa_id, active
        FROM spas
        WHERE spa_id = %s
    """, (spa_id,))

    business = cur.fetchone()

    if business is None:
        raise BusinessAIControlError(
            "Business does not exist."
        )

    cur.execute("""
        SELECT
            ai_budget_id,
            ai_enabled,
            monthly_limit_usd
        FROM psp_ai_budgets
        WHERE scope = 'business'
          AND spa_id = %s
        FOR UPDATE
    """, (spa_id,))

    return business, cur.fetchone()


def _write_audit(
    cur,
    *,
    spa_id,
    actor_user_id,
    budget_id,
    action_type,
    old_value,
    new_value,
    reason,
):
    cur.execute("""
        INSERT INTO audit_log (
            spa_id,
            user_id,
            action_type,
            table_name,
            record_id,
            old_value,
            new_value,
            notes,
            created_at
        )
        VALUES (
            %s, %s, %s, %s, %s, %s, %s, %s,
            clock_timestamp()
        )
        RETURNING audit_log_id
    """, (
        spa_id,
        actor_user_id,
        action_type,
        "psp_ai_budgets",
        budget_id,
        json.dumps(old_value),
        json.dumps(new_value),
        reason,
    ))

    result = cur.fetchone()

    if result is None:
        raise BusinessAIControlError(
            "Business AI audit record was not created."
        )

    return result["audit_log_id"]


def set_business_ai_monthly_limit(
    cur,
    *,
    spa_id,
    monthly_limit_usd,
    expected_limit_usd,
    actor_user_id,
    reason,
):
    """Create or update one disabled business AI budget."""

    reason = _validate_identity_and_reason(
        spa_id,
        actor_user_id,
        reason,
    )

    new_limit = _parse_limit(monthly_limit_usd)
    expected_limit = _parse_limit(
        expected_limit_usd,
        expected=True,
    )

    _, row = _lock_business_budget(cur, spa_id)

    if row is not None and row["ai_enabled"]:
        raise BusinessAIControlError(
            "Disable this business's AI before changing its limit."
        )

    old_limit = (
        row["monthly_limit_usd"]
        if row is not None
        else None
    )

    if old_limit != expected_limit:
        raise BusinessAIControlError(
            "Business AI limit changed. Refresh and try again."
        )

    if old_limit == new_limit:
        raise BusinessAIControlError(
            "The new limit matches the existing limit."
        )

    if row is None:
        # Missing budgets always start disabled.
        cur.execute("""
            INSERT INTO psp_ai_budgets (
                scope,
                spa_id,
                ai_enabled,
                monthly_limit_usd,
                created_by,
                updated_by
            )
            VALUES (
                'business', %s, FALSE, %s, %s, %s
            )
            RETURNING ai_budget_id
        """, (
            spa_id,
            new_limit,
            actor_user_id,
            actor_user_id,
        ))

        inserted = cur.fetchone()

        if inserted is None:
            raise BusinessAIControlError(
                "Business AI budget creation failed."
            )

        budget_id = inserted["ai_budget_id"]

    else:
        budget_id = row["ai_budget_id"]

        cur.execute("""
            UPDATE psp_ai_budgets
            SET
                monthly_limit_usd = %s,
                updated_by = %s,
                updated_at = clock_timestamp()
            WHERE ai_budget_id = %s
        """, (
            new_limit,
            actor_user_id,
            budget_id,
        ))

        if cur.rowcount != 1:
            raise BusinessAIControlError(
                "Business AI limit update failed."
            )

    audit_id = _write_audit(
        cur,
        spa_id=spa_id,
        actor_user_id=actor_user_id,
        budget_id=budget_id,
        action_type="ai_business_monthly_limit_changed",
        old_value={
            "budget_configured": row is not None,
            "monthly_limit_usd": (
                str(old_limit)
                if old_limit is not None
                else None
            ),
        },
        new_value={
            "budget_configured": True,
            "monthly_limit_usd": str(new_limit),
        },
        reason=reason,
    )

    return {
        "spa_id": spa_id,
        "ai_budget_id": budget_id,
        "monthly_limit_usd": new_limit,
        "previous_limit_usd": old_limit,
        "ai_enabled": False,
        "audit_log_id": audit_id,
    }


def set_business_ai_enabled(
    cur,
    *,
    spa_id,
    enabled,
    expected_enabled,
    actor_user_id,
    reason,
):
    """Change one business AI state without affecting others."""

    reason = _validate_identity_and_reason(
        spa_id,
        actor_user_id,
        reason,
    )

    if type(enabled) is not bool:
        raise BusinessAIControlError(
            "Invalid requested AI status."
        )

    if type(expected_enabled) is not bool:
        raise BusinessAIControlError(
            "Invalid expected AI status."
        )

    business, row = _lock_business_budget(cur, spa_id)

    if row is None:
        raise BusinessAIControlError(
            "Configure this business's AI limit first."
        )

    previous_enabled = bool(row["ai_enabled"])

    if previous_enabled is not expected_enabled:
        raise BusinessAIControlError(
            "Business AI status changed. Refresh and try again."
        )

    if previous_enabled is enabled:
        raise BusinessAIControlError(
            "Business AI already has the requested status."
        )

    if enabled:
        if not business["active"]:
            raise BusinessAIControlError(
                "Inactive businesses cannot enable AI."
            )

        if row["monthly_limit_usd"] is None:
            raise BusinessAIControlError(
                "Configure a monthly AI limit before enabling."
            )

    cur.execute("""
        UPDATE psp_ai_budgets
        SET
            ai_enabled = %s,
            updated_by = %s,
            updated_at = clock_timestamp()
        WHERE ai_budget_id = %s
    """, (
        enabled,
        actor_user_id,
        row["ai_budget_id"],
    ))

    if cur.rowcount != 1:
        raise BusinessAIControlError(
            "Business AI status update failed."
        )

    audit_id = _write_audit(
        cur,
        spa_id=spa_id,
        actor_user_id=actor_user_id,
        budget_id=row["ai_budget_id"],
        action_type=(
            "ai_business_enabled"
            if enabled
            else "ai_business_disabled"
        ),
        old_value={
            "ai_enabled": previous_enabled,
        },
        new_value={
            "ai_enabled": enabled,
        },
        reason=reason,
    )

    return {
        "spa_id": spa_id,
        "ai_budget_id": row["ai_budget_id"],
        "previous_enabled": previous_enabled,
        "ai_enabled": enabled,
        "audit_log_id": audit_id,
    }
