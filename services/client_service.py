"""
Shared client-domain helpers for Peach Suite Pro.

Keep client identity and duplicate-detection rules centralized so
manual client workflows and the Import Engine use the same logic.
"""


def find_possible_client_duplicates(
    cur,
    spa_id,
    business_unit_id,
    first_name,
    last_name,
    phone,
    email,
    exclude_client_id=None
):
    """
    Return possible duplicate clients for the current workspace.

    Strong matches:
    - Exact normalized email
    - Exact normalized phone

    Warning match:
    - Exact normalized first and last name

    Active and archived clients are both included.
    """
    import re

    def normalize_name(value):
        return " ".join(
            str(value or "")
            .strip()
            .lower()
            .split()
        )

    def normalize_email(value):
        return str(value or "").strip().lower()

    def normalize_phone(value):
        digits = re.sub(
            r"[^0-9]",
            "",
            str(value or "")
        )

        if (
            len(digits) == 11
            and digits.startswith("1")
        ):
            digits = digits[1:]

        return digits

    submitted_first_name = normalize_name(
        first_name
    )

    submitted_last_name = normalize_name(
        last_name
    )

    submitted_email = normalize_email(
        email
    )

    submitted_phone = normalize_phone(
        phone
    )

    match_conditions = []
    params = [
        spa_id,
        business_unit_id
    ]

    if (
        submitted_first_name
        and submitted_last_name
    ):
        match_conditions.append("""
            (
                LOWER(
                    REGEXP_REPLACE(
                        TRIM(
                            COALESCE(first_name, '')
                        ),
                        '\\s+',
                        ' ',
                        'g'
                    )
                ) = %s

                AND LOWER(
                    REGEXP_REPLACE(
                        TRIM(
                            COALESCE(last_name, '')
                        ),
                        '\\s+',
                        ' ',
                        'g'
                    )
                ) = %s
            )
        """)

        params.extend([
            submitted_first_name,
            submitted_last_name
        ])

    if submitted_email:
        match_conditions.append("""
            LOWER(
                TRIM(
                    COALESCE(email, '')
                )
            ) = %s
        """)

        params.append(
            submitted_email
        )

    if submitted_phone:
        match_conditions.append("""
            REGEXP_REPLACE(
                COALESCE(phone, ''),
                '[^0-9]',
                '',
                'g'
            ) IN (%s, %s)
        """)

        params.extend([
            submitted_phone,
            "1" + submitted_phone
        ])

    if not match_conditions:
        return []

    query = """
        SELECT
            client_id,
            first_name,
            last_name,
            phone,
            email,
            active_client
        FROM clients
        WHERE spa_id = %s
          AND business_unit_id = %s
          AND (
    """

    query += "\n OR ".join(
        match_conditions
    )

    query += """
          )
    """

    if exclude_client_id is not None:
        query += """
          AND client_id <> %s
        """

        params.append(
            exclude_client_id
        )

    query += """
        ORDER BY
            active_client DESC,
            last_name,
            first_name,
            client_id
    """

    cur.execute(
        query,
        tuple(params)
    )

    duplicates = []

    for row in cur.fetchall():
        (
            client_id,
            existing_first_name,
            existing_last_name,
            existing_phone,
            existing_email,
            active_client
        ) = row

        reasons = []

        existing_first_normalized = (
            normalize_name(existing_first_name)
        )

        existing_last_normalized = (
            normalize_name(existing_last_name)
        )

        existing_email_normalized = (
            normalize_email(existing_email)
        )

        existing_phone_normalized = (
            normalize_phone(existing_phone)
        )

        if (
            submitted_first_name
            and submitted_last_name
            and submitted_first_name
                == existing_first_normalized
            and submitted_last_name
                == existing_last_normalized
        ):
            reasons.append(
                "Name"
            )

        if (
            submitted_email
            and submitted_email
                == existing_email_normalized
        ):
            reasons.append(
                "Email"
            )

        if (
            submitted_phone
            and submitted_phone
                == existing_phone_normalized
        ):
            reasons.append(
                "Phone"
            )

        strong_match = (
            "Email" in reasons
            or "Phone" in reasons
        )

        duplicates.append({
            "client_id": client_id,

            "first_name": existing_first_name or "",
            "last_name": existing_last_name or "",

            "client_name": (
                f"{existing_first_name or ''} "
                f"{existing_last_name or ''}"
            ).strip()
            or f"Client {client_id}",

            "phone": existing_phone or "",
            "email": existing_email or "",

            "active_client":
                bool(active_client),

            "status_label": (
                "Active"
                if active_client
                else "Archived"
            ),

            "match_reasons": reasons,

            "match_reason_display":
                ", ".join(reasons),

            "strong_match":
                strong_match
        })

    return duplicates
