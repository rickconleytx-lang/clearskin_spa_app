class ContactSecurityError(ValueError):
    """Raised when PSP contact information is invalid."""


def normalize_user_mobile_phone(value):
    """
    Normalize a U.S. mobile number to PSP's canonical format:

        +1##########

    Blank input remains blank so callers can decide whether a
    mobile number is required for their particular workflow.
    """
    raw_value = str(value or "").strip()

    if not raw_value:
        return ""

    allowed_format_characters = {
        " ",
        "+",
        "(",
        ")",
        "-",
        ".",
    }

    if any(
        not character.isdigit()
        and character not in allowed_format_characters
        for character in raw_value
    ):
        raise ContactSecurityError(
            "Please enter a valid U.S. mobile number."
        )

    digits = "".join(
        character
        for character in raw_value
        if character.isdigit()
    )

    if (
        len(digits) == 11
        and digits.startswith("1")
    ):
        digits = digits[1:]

    if len(digits) != 10:
        raise ContactSecurityError(
            "Please enter a valid 10-digit U.S. mobile number."
        )

    return "+1" + digits
