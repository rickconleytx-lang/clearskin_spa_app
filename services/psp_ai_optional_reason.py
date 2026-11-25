"""Normalize optional reasons for routine AI allowance edits."""


def normalize_limit_change_reason(value):
    if not isinstance(value, str):
        raise ValueError("Invalid allowance change reason.")

    reason = " ".join(value.split())

    if not reason:
        return (
            "Reason not provided for routine monthly AI limit update."
        )

    # Existing audited services require at least 10 characters.
    # Preserve short user notes with a clearly labeled prefix.
    if len(reason) < 10:
        return "Admin note: " + reason

    # The existing service validates the 500-character maximum.
    return reason
