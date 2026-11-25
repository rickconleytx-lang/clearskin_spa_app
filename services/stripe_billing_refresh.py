"""
PSP Stripe billing refresh coordination.

Call claim_billing_refresh() in a short DB transaction and COMMIT
before making any Stripe request.

After the network request, call finish_billing_refresh() in a
new transaction and COMMIT.

No Stripe API calls are made by this module.
"""

import json
import secrets
from datetime import datetime, timedelta, timezone

from services.stripe_billing_snapshot import (
    format_saved_billing_quote,
)

MANUAL_COOLDOWN = timedelta(seconds=60)
AUTO_COOLDOWN = timedelta(hours=24)
REFRESH_LOCK = timedelta(minutes=2)


def _utc(value):
    if value is None:
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _refresh_due(mode, *, last_manual=None,
                 last_auto=None, verified=None, now=None):
    now = _utc(now) or datetime.now(timezone.utc)

    if mode == "manual":
        previous = _utc(last_manual)
        cooldown = MANUAL_COOLDOWN
    elif mode == "auto":
        candidates = [
            _utc(value)
            for value in (last_auto, verified)
            if value is not None
        ]
        previous = max(candidates) if candidates else None
        cooldown = AUTO_COOLDOWN
    else:
        raise ValueError("Invalid billing refresh mode.")

    return previous is None or now - previous >= cooldown


def claim_billing_refresh(
    cursor, *, spa_id, environment, mode, now=None
):
    """
    Atomically reserve one refresh using row-level DB locks.

    Caller must commit or roll back the transaction before
    contacting Stripe.
    """
    if environment not in ("test", "live"):
        raise ValueError("Invalid Stripe environment.")
    if mode not in ("manual", "auto"):
        raise ValueError("Invalid refresh mode.")

    now = _utc(now) or datetime.now(timezone.utc)

    cursor.execute(
        """
        SELECT stripe_billing_account_id,
               stripe_subscription_id
        FROM stripe_billing_accounts
        WHERE spa_id = %s AND environment = %s
        FOR UPDATE
        """,
        (spa_id, environment),
    )

    account = cursor.fetchone()

    if not account or not account[1]:
        return {"status": "no_subscription"}

    account_id, subscription_id = account

    cursor.execute(
        """
        INSERT INTO stripe_billing_display_snapshots (
            stripe_billing_account_id,
            spa_id, environment, stripe_subscription_id
        )
        VALUES (%s, %s, %s, %s)
        ON CONFLICT (stripe_billing_account_id) DO NOTHING
        """,
        (account_id, spa_id, environment, subscription_id),
    )

    cursor.execute(
        """
        SELECT stripe_subscription_id,
               last_manual_attempt_at,
               last_auto_attempt_at,
               verified_at,
               refresh_lock_expires_at
        FROM stripe_billing_display_snapshots
        WHERE stripe_billing_account_id = %s
          AND spa_id = %s
          AND environment = %s
        FOR UPDATE
        """,
        (account_id, spa_id, environment),
    )

    row = cursor.fetchone()

    if row is None:
        raise RuntimeError("Billing snapshot row was not created.")

    saved_id, last_manual, last_auto, verified, lock_until = row

    if saved_id != subscription_id:
        # Never inherit a previous subscription's pricing,
        # rate limits, or pending refresh lock.
        cursor.execute(
            """
            UPDATE stripe_billing_display_snapshots
            SET stripe_subscription_id = %s,
                quote_json = NULL,
                verified_at = NULL,
                invalidated_at = NULL,
                last_manual_attempt_at = NULL,
                last_auto_attempt_at = NULL,
                last_attempt_at = NULL,
                last_attempt_status = NULL,
                refresh_lock_token = NULL,
                refresh_lock_expires_at = NULL,
                updated_at = %s
            WHERE stripe_billing_account_id = %s
            """,
            (subscription_id, now, account_id),
        )
        last_manual = last_auto = verified = lock_until = None

    if lock_until is not None and _utc(lock_until) > now:
        return {"status": "busy"}

    if not _refresh_due(
        mode,
        last_manual=last_manual,
        last_auto=last_auto,
        verified=verified,
        now=now,
    ):
        return {"status": "cooldown"}

    token = secrets.token_hex(24)

    attempt_column = (
        "last_auto_attempt_at"
        if mode == "auto"
        else "last_manual_attempt_at"
    )

    # Column name comes only from the validated mode above.
    cursor.execute(
        f"""
        UPDATE stripe_billing_display_snapshots
        SET {attempt_column} = %s,
            last_attempt_at = %s,
            refresh_lock_token = %s,
            refresh_lock_expires_at = %s,
            updated_at = %s
        WHERE stripe_billing_account_id = %s
        """,
        (
            now,
            now,
            token,
            now + REFRESH_LOCK,
            now,
            account_id,
        ),
    )

    return {
        "status": "claimed",
        "token": token,
        "subscription_id": subscription_id,
    }


def finish_billing_refresh(
    cursor, *, spa_id, environment,
    subscription_id, token, quote, now=None
):
    """
    Save a successful verified quote or record a failed attempt.

    Never overwrite the previous quote on failure.
    Reject obsolete claims and replaced subscriptions.
    """
    if environment not in ("test", "live"):
        raise ValueError("Invalid Stripe environment.")

    now = _utc(now) or datetime.now(timezone.utc)

    valid = (
        quote is not None
        and format_saved_billing_quote(quote) is not None
    )

    if valid:
        payload = json.dumps(quote)

        cursor.execute(
            """
            UPDATE stripe_billing_display_snapshots s
            SET quote_json = %s::jsonb,
                verified_at = %s,
                invalidated_at = NULL,
                last_attempt_status = 'verified',
                refresh_lock_token = NULL,
                refresh_lock_expires_at = NULL,
                updated_at = %s
            FROM stripe_billing_accounts a
            WHERE s.stripe_billing_account_id =
                  a.stripe_billing_account_id
              AND s.spa_id = %s
              AND s.environment = %s
              AND s.stripe_subscription_id = %s
              AND a.stripe_subscription_id = %s
              AND s.refresh_lock_token = %s
              AND (
                  s.invalidated_at IS NULL
                  OR s.invalidated_at <= s.last_attempt_at
              )
            RETURNING s.stripe_billing_account_id
            """,
            (
                payload, now, now,
                spa_id, environment,
                subscription_id, subscription_id, token,
            ),
        )

        if cursor.fetchone():
            return True

    # Failed, unsupported, or invalidated during retrieval:
    # preserve previously verified pricing and clear the claim.
    cursor.execute(
        """
        UPDATE stripe_billing_display_snapshots s
        SET last_attempt_status = 'unavailable',
            refresh_lock_token = NULL,
            refresh_lock_expires_at = NULL,
            updated_at = %s
        FROM stripe_billing_accounts a
        WHERE s.stripe_billing_account_id =
              a.stripe_billing_account_id
          AND s.spa_id = %s
          AND s.environment = %s
          AND s.stripe_subscription_id = %s
          AND a.stripe_subscription_id = %s
          AND s.refresh_lock_token = %s
        RETURNING s.stripe_billing_account_id
        """,
        (
            now, spa_id, environment,
            subscription_id, subscription_id, token,
        ),
    )

    cursor.fetchone()
    return False


def _billing_db_phase(connection_factory, operation):
    """Run one short DB transaction and always close it."""
    conn = connection_factory()
    cursor = None

    try:
        cursor = conn.cursor()
        result = operation(cursor)
        conn.commit()
        return result
    except Exception:
        conn.rollback()
        raise
    finally:
        try:
            if cursor is not None:
                cursor.close()
        finally:
            conn.close()


def run_billing_refresh(
    *,
    connection_factory,
    spa_id,
    environment,
    mode,
    retriever=None,
):
    """
    Perform a coordinated, read-only Stripe billing refresh.

    Database connections are closed before contacting Stripe.
    Only verified pricing is persisted. No Stripe objects
    are created or modified.
    """
    claim = _billing_db_phase(
        connection_factory,
        lambda cursor: claim_billing_refresh(
            cursor,
            spa_id=spa_id,
            environment=environment,
            mode=mode,
        ),
    )

    if claim["status"] != "claimed":
        return {"status": claim["status"]}

    if retriever is None:
        from services.stripe_billing_quote import (
            retrieve_stripe_billing_quote,
        )
        retriever = retrieve_stripe_billing_quote

    try:
        quote = retriever(
            claim["subscription_id"],
            environment=environment,
        )
    except Exception:
        quote = None

    saved = _billing_db_phase(
        connection_factory,
        lambda cursor: finish_billing_refresh(
            cursor,
            spa_id=spa_id,
            environment=environment,
            subscription_id=claim["subscription_id"],
            token=claim["token"],
            quote=quote,
        ),
    )

    return {
        "status": "verified" if saved else "unavailable"
    }
