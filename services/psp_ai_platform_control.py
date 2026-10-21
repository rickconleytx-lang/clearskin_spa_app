"""Peach Suite Pro - Master Admin global AI control.

Caller must enforce Master Admin authentication and CSRF.

Caller owns the database transaction. The budget change
and audit entry must be committed or rolled back together.
"""


import json


class AIPlatformControlError(ValueError):
    pass


def set_platform_ai_enabled(
    cur,
    *,
    enabled,
    expected_enabled,
    actor_user_id,
    reason,
):
    """Change the platform AI state with durable audit history."""

    if type(enabled) is not bool:
        raise AIPlatformControlError(
            "Invalid requested AI state."
        )

    if type(expected_enabled) is not bool:
        raise AIPlatformControlError(
            "Invalid expected AI state."
        )

    if type(actor_user_id) is not int or actor_user_id <= 0:
        raise AIPlatformControlError(
            "Invalid administrator identity."
        )

    if not isinstance(reason, str):
        raise AIPlatformControlError(
            "A reason is required."
        )

    reason = " ".join(reason.split())

    if not 10 <= len(reason) <= 500:
        raise AIPlatformControlError(
            "Reason must contain 10 to 500 characters."
        )

    # Lock the single platform budget row so concurrent
    # administrators cannot silently overwrite one another.
    cur.execute("""
        SELECT
            ai_budget_id,
            ai_enabled,
            monthly_limit_usd
        FROM psp_ai_budgets
        WHERE scope = 'platform'
          AND spa_id IS NULL
        FOR UPDATE
    """)

    row = cur.fetchone()

    if not row:
        raise AIPlatformControlError(
            "Platform AI budget is not configured."
        )

    previous_enabled = row["ai_enabled"]

    if previous_enabled is not expected_enabled:
        raise AIPlatformControlError(
            "AI status changed. Refresh before trying again."
        )

    if previous_enabled is enabled:
        raise AIPlatformControlError(
            "Platform AI already has the requested status."
        )

    if enabled and row["monthly_limit_usd"] is None:
        raise AIPlatformControlError(
            "A spending limit is required before enabling AI."
        )

    budget_id = row["ai_budget_id"]

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
        budget_id,
    ))

    if cur.rowcount != 1:
        raise AIPlatformControlError(
            "Platform AI status update failed."
        )

    action = (
        "ai_platform_enabled"
        if enabled
        else "ai_platform_disabled"
    )

    # The same transaction records who made the change,
    # the old/new states, and the administrator's reason.
    cur.execute("""
        INSERT INTO audit_log (
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
            %s, %s, %s, %s, %s, %s, %s,
            clock_timestamp()
        )
        RETURNING audit_log_id
    """, (
        actor_user_id,
        action,
        "psp_ai_budgets",
        budget_id,
        json.dumps({"ai_enabled": previous_enabled}),
        json.dumps({"ai_enabled": enabled}),
        reason,
    ))

    audit_row = cur.fetchone()

    if not audit_row:
        raise AIPlatformControlError(
            "AI control audit entry was not created."
        )

    return {
        "ai_enabled": enabled,
        "previous_enabled": previous_enabled,
        "ai_budget_id": budget_id,
        "audit_log_id": audit_row["audit_log_id"],
    }
