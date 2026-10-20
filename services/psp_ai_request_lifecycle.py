"""Coach Peach Assist AI request lifecycle.

Caller owns authorization, transaction, and commit.
No provider calls or external communications.
"""


class AIRequestLifecycleError(ValueError):
    pass


def _locked_request(cur, ai_usage_id):
    if type(ai_usage_id) is not int or ai_usage_id <= 0:
        raise AIRequestLifecycleError("Invalid AI request.")

    cur.execute("""
        SELECT u.status, r.state
        FROM psp_ai_usage u
        JOIN psp_ai_budget_reservations r
          ON r.ai_usage_id = u.ai_usage_id
        WHERE u.ai_usage_id = %s
        FOR UPDATE OF u, r
    """, (ai_usage_id,))

    row = cur.fetchone()
    if row is None:
        raise AIRequestLifecycleError("AI request not found.")

    return row


def mark_ai_request_submitted(cur, *, ai_usage_id):
    """Record submission intent before contacting the provider."""
    row = _locked_request(cur, ai_usage_id)

    if row["status"] != "reserved" or row["state"] != "held":
        raise AIRequestLifecycleError(
            "AI request is not awaiting submission."
        )

    cur.execute("""
        UPDATE psp_ai_usage
        SET status = 'submitted'
        WHERE ai_usage_id = %s
    """, (ai_usage_id,))


def release_unsubmitted_ai_request(cur, *, ai_usage_id):
    """Release only requests never submitted to the provider."""
    row = _locked_request(cur, ai_usage_id)

    if row["status"] != "reserved" or row["state"] != "held":
        raise AIRequestLifecycleError(
            "Only unsubmitted AI requests can be released."
        )

    cur.execute("""
        UPDATE psp_ai_usage
        SET status = 'failed',
            error_code = 'cancelled_before_submission',
            completed_at = clock_timestamp()
        WHERE ai_usage_id = %s
    """, (ai_usage_id,))

    cur.execute("""
        UPDATE psp_ai_budget_reservations
        SET state = 'released',
            settled_usd = 0,
            resolved_at = clock_timestamp()
        WHERE ai_usage_id = %s
    """, (ai_usage_id,))


def mark_ai_request_uncertain(cur, *, ai_usage_id):
    """Retain possible charges when the provider outcome is unknown."""
    row = _locked_request(cur, ai_usage_id)

    if row["status"] != "submitted" or row["state"] != "held":
        raise AIRequestLifecycleError(
            "Only submitted requests can become uncertain."
        )

    cur.execute("""
        UPDATE psp_ai_usage
        SET status = 'uncertain',
            error_code = 'provider_outcome_unknown'
        WHERE ai_usage_id = %s
    """, (ai_usage_id,))

    cur.execute("""
        UPDATE psp_ai_budget_reservations
        SET state = 'uncertain'
        WHERE ai_usage_id = %s
    """, (ai_usage_id,))
