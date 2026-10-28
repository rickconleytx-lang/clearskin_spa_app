"""Coach Peach AI Help - financial gateway orchestration.

The caller MUST obtain user, spa and business-unit identity from
authenticated PSP server-side authorization.

The caller also supplies the approved model/pricing configuration.

The provider callback is required and is never called on import.
No automatic provider retries.
"""

from uuid import uuid4

from psycopg2.extras import RealDictCursor

from services.psp_ai_budget_gateway import reserve_ai_request
from services.psp_ai_request_lifecycle import (
    mark_ai_request_submitted,
    mark_ai_request_uncertain,
)
from services.psp_ai_usage_settlement import settle_ai_request
from services.psp_ai_help_request import prepare_ai_help_request

from services.psp_ai_help_bundle import (
    get_ai_help_bundle,
)

from services.psp_ai_help_context import (
    AIHelpContextError,
)

class AIHelpExecutionError(RuntimeError):
    pass


def _rollback_if_possible(conn):
    """Best-effort cleanup without hiding the original failure."""
    try:
        conn.rollback()
    except Exception:
        pass


def _retain_uncertain(connection_factory, usage_id):
    """Recover financial state using a fresh database connection.

    The original connection may be broken. A submitted/held request
    remains financially reserved even if this update cannot commit.
    """
    recovery_conn = None

    try:
        recovery_conn = connection_factory()

        with recovery_conn.cursor(
            cursor_factory=RealDictCursor
        ) as cur:
            mark_ai_request_uncertain(
                cur,
                ai_usage_id=usage_id,
            )

        recovery_conn.commit()

    except Exception:
        if recovery_conn is not None:
            _rollback_if_possible(recovery_conn)

        raise AIHelpExecutionError(
            "AI financial reconciliation requires administrator review."
        ) from None

    finally:
        if recovery_conn is not None:
            try:
                recovery_conn.close()
            except Exception:
                pass


def execute_ai_help(
    *,
    connection_factory,
    spa_id,
    business_unit_id,
    actor_user_id,
    page_key,
    language,
    question,
    pricing_id,
    model,
    provider_call,
):
    """Execute one budget-controlled Help request.

    Caller is responsible for authentication, workspace membership,
    CSRF validation, and access-policy enforcement.

    No provider request occurs unless reservation and submission
    transactions both commit successfully.
    """

    for value in (
        spa_id,
        business_unit_id,
        actor_user_id,
        pricing_id,
    ):
        if type(value) is not int or value <= 0:
            raise AIHelpExecutionError(
                "Invalid authenticated AI request context."
            )

    if not isinstance(model, str) or not model:
        raise AIHelpExecutionError("AI model is not configured.")

    if not callable(connection_factory):
        raise AIHelpExecutionError("Database is not configured.")

    if not callable(provider_call):
        raise AIHelpExecutionError("AI provider is not configured.")

    conn = connection_factory()

    try:
        # STAGE 1: Validate article, question and model pricing.
        # Reserve funds atomically against both spending budgets.
        try:
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                # Find relevant approved Help articles across the
                # entire Knowledge Base. The current article, if any,
                # is only a relevance hint.

                bundle = get_ai_help_bundle(
                    cur,
                    question=question,
                    language=language,
                    current_page_key=page_key,
                )

                # Never ask OpenAI to invent an answer when no
                # supporting approved Help articles were found.
                if (
                    not bundle["articles"]
                    or not bundle["context_text"].strip()
                ):
                    raise AIHelpContextError(
                        "No matching Help articles were found. "
                        "Try describing what you want to do."
                    )

                # Reuse the existing bounded request preparation.
                # The financial gateway and provider execution
                # remain unchanged.
                article = {
                    "title": "Peach Suite Pro Knowledge Base",
                    "article_text": bundle["context_text"],
                    "language_code": (
                        "ES" if language == "ES" else "EN"
                    ),
                }

                prepared = prepare_ai_help_request(
                    question=question,
                    article=article,
                )

                cur.execute("""
                    SELECT ai_model_pricing_id
                    FROM psp_ai_model_pricing
                    WHERE ai_model_pricing_id = %s
                      AND provider = 'openai'
                      AND model_name = %s
                      AND effective_from <= clock_timestamp()
                      AND (
                          effective_to IS NULL
                          OR effective_to > clock_timestamp()
                      )
                """, (pricing_id, model))

                if not cur.fetchone():
                    raise AIHelpExecutionError(
                        "Approved AI model pricing unavailable."
                    )

                # Conservative reservation based on the bounded
                # UTF-8 request size, including extra overhead.
                # The provider adapter separately enforces request
                # size and max_output_tokens.
                instructions_bytes = len(
                    prepared["instructions"].encode("utf-8")
                )
                input_bytes = len(
                    prepared["input"].encode("utf-8")
                )

                # Match the provider adapter's byte limits
                # BEFORE creating a financial reservation.
                if (
                    instructions_bytes > 6000
                    or input_bytes > 48000
                ):
                    raise AIHelpExecutionError(
                        "AI Help request exceeds provider limits."
                    )

                input_limit = (
                    instructions_bytes
                    + input_bytes
                    + 4096
                )

                if input_limit > 1000000:
                    raise AIHelpExecutionError(
                        "AI Help request exceeds input allowance."
                    )

                reservation = reserve_ai_request(
                    cur,
                    spa_id=spa_id,
                    business_unit_id=business_unit_id,
                    actor_user_id=actor_user_id,
                    request_key=str(uuid4()),
                    feature_key="help_assist",
                    pricing_id=pricing_id,
                    max_input_tokens=input_limit,
                    max_output_tokens=prepared["max_output_tokens"],
                )

            conn.commit()

        except Exception:
            _rollback_if_possible(conn)
            raise

        usage_id = reservation["ai_usage_id"]

        # STAGE 2: Persist submission intent before network access.
        try:
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                mark_ai_request_submitted(
                    cur,
                    ai_usage_id=usage_id,
                )

            conn.commit()

        except Exception:
            _rollback_if_possible(conn)
            # Do not contact OpenAI or assume an uncertain
            # database commit can be safely reversed.
            raise AIHelpExecutionError(
                "AI submission was not confirmed."
            ) from None

        # STAGE 3: One provider call; never retry automatically.
        try:
            result = provider_call(
                prepared=prepared,
                model=model,
            )
        except Exception:
            _rollback_if_possible(conn)
            _retain_uncertain(connection_factory, usage_id)
            raise AIHelpExecutionError(
                "Coach Peach could not complete the request. "
                "The spending reservation is retained for review."
            ) from None

        # STAGE 4: Record actual provider usage.
        try:
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                settlement = settle_ai_request(
                    cur,
                    ai_usage_id=usage_id,
                    input_tokens=result["input_tokens"],
                    cached_input_tokens=result[
                        "cached_input_tokens"
                    ],
                    output_tokens=result["output_tokens"],
                    provider_request_id=result[
                        "provider_request_id"
                    ],
                )

            conn.commit()

        except Exception:
            _rollback_if_possible(conn)

            # A valid provider response may have been billed.
            # Never release this reservation on settlement failure.
            _retain_uncertain(connection_factory, usage_id)

            raise AIHelpExecutionError(
                "AI financial settlement requires review."
            ) from None

        return {
            "answer": result["answer"],
            "ai_usage_id": usage_id,
            "actual_cost_usd": settlement["actual_cost_usd"],
            "over_reservation": settlement["over_reservation"],
            "articles": [
                {
                    "page_key": article["page_key"],
                    "title": article["title"],

                }
                for article in bundle["articles"]
            ],
        }

    finally:
        conn.close()
