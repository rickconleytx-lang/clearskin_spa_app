"""Coach Peach Assist - read-only recovery detection.

Internal Master Admin use only.
Caller owns authorization and database transaction.
Never changes request status or releases funds.
"""


def find_ai_recovery_candidates(
    cur, *, older_than_minutes=30, limit=100
):
    if (
        type(older_than_minutes) is not int
        or not 1 <= older_than_minutes <= 10080
    ):
        raise ValueError("Invalid recovery age.")

    if type(limit) is not int or not 1 <= limit <= 500:
        raise ValueError("Invalid recovery limit.")

    cur.execute("""
        SELECT
            u.ai_usage_id,
            u.spa_id,
            u.business_unit_id,
            u.status,
            r.state AS reservation_state,
            r.reserved_usd,
            u.created_at,
            r.reserved_at,
            u.provider_request_id,
            u.error_code,
            CASE
                WHEN u.status = 'reserved'
                    THEN 'review_unsubmitted'
                WHEN u.status = 'submitted'
                    THEN 'investigate_provider'
                ELSE 'reconcile_uncertain'
            END AS recovery_hint
        FROM psp_ai_usage u
        JOIN psp_ai_budget_reservations r
          ON r.ai_usage_id = u.ai_usage_id
        WHERE (
            (u.status = 'reserved' AND r.state = 'held')
            OR
            (u.status = 'submitted' AND r.state = 'held')
            OR
            (u.status = 'uncertain' AND r.state = 'uncertain')
        )
        AND (
            CASE
                WHEN u.status = 'reserved'
                    THEN r.reserved_at
                ELSE u.created_at
            END
        ) <= clock_timestamp()
             - (%s * INTERVAL '1 minute')
        ORDER BY u.created_at, u.ai_usage_id
        LIMIT %s
    """, (older_than_minutes, limit))

    return cur.fetchall()
