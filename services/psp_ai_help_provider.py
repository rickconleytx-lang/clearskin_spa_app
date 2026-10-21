"""Coach Peach Assist - bounded OpenAI Help provider.

Must only be called after authenticated authorization,
budget reservation and submission state are committed.

No database writes. No automatic provider calls on import.
"""

import re
from openai import OpenAI


class AIHelpProviderError(RuntimeError):
    pass


def request_openai_help(*, prepared, model, client=None):
    """Generate one Help answer and return provider usage."""

    if not isinstance(prepared, dict):
        raise AIHelpProviderError("Invalid Help request.")

    if not isinstance(model, str) or not re.fullmatch(
        r"[A-Za-z0-9][A-Za-z0-9._-]{0,99}", model
    ):
        raise AIHelpProviderError("Invalid AI model.")

    instructions = prepared.get("instructions")
    user_input = prepared.get("input")
    output_limit = prepared.get("max_output_tokens")

    if (
        not isinstance(instructions, str)
        or not instructions.strip()
        or not isinstance(user_input, str)
        or not user_input.strip()
        or len(instructions.encode("utf-8")) > 6000
        or len(user_input.encode("utf-8")) > 48000
        or type(output_limit) is not int
        or not 1 <= output_limit <= 400
    ):
        raise AIHelpProviderError("Invalid Help request limits.")

    if client is None:
        client = OpenAI(timeout=20.0, max_retries=0)

    response = client.responses.create(
        model=model,
        instructions=instructions,
        input=user_input,
        max_output_tokens=output_limit,
        store=False,
        tools=[],
        truncation="disabled",
        reasoning={"effort": "none"},
        service_tier="default",
    )

    usage = getattr(response, "usage", None)
    details = getattr(usage, "input_tokens_details", None)

    input_tokens = getattr(usage, "input_tokens", None)
    cached_tokens = getattr(details, "cached_tokens", 0) or 0
    output_tokens = getattr(usage, "output_tokens", None)
    response_id = getattr(response, "id", None)
    answer = getattr(response, "output_text", None)

    if (
        getattr(response, "status", None) != "completed"
        or not isinstance(answer, str)
        or not answer.strip()
        or not isinstance(response_id, str)
        or not response_id
        or len(response_id) > 256
        or type(input_tokens) is not int
        or input_tokens <= 0
        or type(output_tokens) is not int
        or output_tokens < 0
        or type(cached_tokens) is not int
        or cached_tokens < 0
        or cached_tokens > input_tokens
    ):
        raise AIHelpProviderError(
            "Provider response requires reconciliation."
        )

    return {
        "answer": answer.strip()[:4000],
        "provider_request_id": response_id,
        "input_tokens": input_tokens,
        "cached_input_tokens": cached_tokens,
        "output_tokens": output_tokens,
    }
