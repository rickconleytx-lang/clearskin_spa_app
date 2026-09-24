"""
Central Client Information display-label registry.

Database field names and lookup relationships are immutable.
Only user-facing labels may be customized per workspace.

PSP defaults are intentionally generic so the Client Information
system can be used by businesses outside the skin-care industry.
"""

from psycopg2.extras import execute_values


CLIENT_INFORMATION_LABEL_DEFINITIONS = (
    # -----------------------------------------------------
    # Section headings
    # -----------------------------------------------------
    {
        "field_key": "section_information",
        "default_label": "User Def Section 1",
        "legacy_label": "Skin / Medical Information",
        "label_type": "section",
        "display_order": 10,
    },
    {
        "field_key": "section_treatment_conditions",
        "default_label": "User Def Section 2",
        "legacy_label": "Treatment Contraindications",
        "label_type": "section",
        "display_order": 20,
    },
    {
        "field_key": "section_additional_information",
        "default_label": "User Def Section 3",
        "legacy_label": "Additional Information",
        "label_type": "section",
        "display_order": 30,
    },

    # -----------------------------------------------------
    # Database-backed Client Health Profile fields
    # -----------------------------------------------------
    {
        "field_key": "skin_type_id",
        "default_label": "User Def 1",
        "legacy_label": "Skin Type",
        "label_type": "dropdown",
        "section_key": "section_information",
        "display_order": 100,
    },
    {
        "field_key": "fitzpatrick_id",
        "default_label": "User Def 2",
        "legacy_label": "Fitzpatrick Type",
        "label_type": "dropdown",
        "section_key": "section_information",
        "display_order": 110,
    },
    {
        "field_key": "skin_concerns",
        "default_label": "User Def 3",
        "legacy_label": "Skin Concerns",
        "label_type": "textarea",
        "section_key": "section_information",
        "display_order": 120,
    },
    {
        "field_key": "skin_conditions",
        "default_label": "User Def 4",
        "legacy_label": "Skin Conditions",
        "label_type": "textarea",
        "section_key": "section_information",
        "display_order": 130,
    },
    {
        "field_key": "allergies",
        "default_label": "User Def 5",
        "legacy_label": "Allergies",
        "label_type": "textarea",
        "section_key": "section_information",
        "display_order": 140,
    },
    {
        "field_key": "medications",
        "default_label": "User Def 6",
        "legacy_label": "Medications",
        "label_type": "textarea",
        "section_key": "section_information",
        "display_order": 150,
    },
    {
        "field_key": "current_medical_conditions",
        "default_label": "User Def 7",
        "legacy_label": "Current Medical Conditions",
        "label_type": "textarea",
        "section_key": "section_information",
        "display_order": 160,
    },
    {
        "field_key": "past_medical_treatments",
        "default_label": "User Def 8",
        "legacy_label": "Past Medical Treatments",
        "label_type": "textarea",
        "section_key": "section_information",
        "display_order": 170,
    },
    {
        "field_key": "recent_injections",
        "default_label": "User Def 9",
        "legacy_label": "Recent Injections",
        "label_type": "boolean",
        "section_key": "section_treatment_conditions",
        "display_order": 180,
    },
    {
        "field_key": "recent_laser",
        "default_label": "User Def 10",
        "legacy_label": "Recent Laser",
        "label_type": "boolean",
        "section_key": "section_treatment_conditions",
        "display_order": 190,
    },
    {
        "field_key": "pregnant",
        "default_label": "User Def 11",
        "legacy_label": "Pregnant",
        "label_type": "boolean",
        "section_key": "section_treatment_conditions",
        "display_order": 200,
    },
    {
        "field_key": "nursing",
        "default_label": "User Def 12",
        "legacy_label": "Nursing",
        "label_type": "boolean",
        "section_key": "section_treatment_conditions",
        "display_order": 210,
    },
    {
        "field_key": "using_retinol",
        "default_label": "User Def 13",
        "legacy_label": "Using Retinol",
        "label_type": "boolean",
        "section_key": "section_treatment_conditions",
        "display_order": 220,
    },
    {
        "field_key": "using_accutane",
        "default_label": "User Def 14",
        "legacy_label": "Using Accutane",
        "label_type": "boolean",
        "section_key": "section_treatment_conditions",
        "display_order": 230,
    },
    {
        "field_key": "sun_exposure_level",
        "default_label": "User Def 15",
        "legacy_label": "Sun Exposure Level",
        "label_type": "text",
        "section_key": "section_additional_information",
        "display_order": 240,
    },
    {
        "field_key": "last_facial_date",
        "default_label": "User Def 16",
        "legacy_label": "Last Facial Date",
        "label_type": "date",
        "section_key": "section_additional_information",
        "display_order": 250,
    },
    {
        "field_key": "notes1",
        "default_label": "Notes Four",
        "legacy_label": "Notes 1",
        "label_type": "textarea",
        "section_key": "section_additional_information",
        "display_order": 260,
    },
    {
        "field_key": "notes2",
        "default_label": "Notes Five",
        "legacy_label": "Notes 2",
        "label_type": "textarea",
        "section_key": "section_additional_information",
        "display_order": 270,
    },
    {
        "field_key": "notes3",
        "default_label": "Notes Six",
        "legacy_label": "Notes 3",
        "label_type": "textarea",
        "section_key": "section_additional_information",
        "display_order": 280,
    },
)


# -----------------------------------------------------
# Appointment-level Post Appointment Wrap-Up labels
# -----------------------------------------------------
#
# These are intentionally separate from User Def 1-19.
# Backend database field names remain immutable.
#
# -----------------------------------------------------
# Client Record note labels
# -----------------------------------------------------
#
# These are ordinary client-level notes stored on clients.
# They are separate from User Def 17-19 and from appointment
# wrap-up notes. Backend database field names remain immutable.
#
CLIENT_RECORD_NOTE_LABEL_DEFINITIONS = (
    {
        "field_key": "notes_one",
        "default_label": "Notes One",
        "legacy_label": "Referral Notes",
        "label_type": "textarea",
        "display_order": 10,
    },
    {
        "field_key": "notes_two",
        "default_label": "Notes Two",
        "legacy_label": "Client Note 2",
        "label_type": "textarea",
        "display_order": 20,
    },
    {
        "field_key": "notes_three",
        "default_label": "Notes Three",
        "legacy_label": "Client Note 3",
        "label_type": "textarea",
        "display_order": 30,
    },
)


CLIENT_RECORD_NOTE_LABEL_KEYS = {
    definition["field_key"]
    for definition in CLIENT_RECORD_NOTE_LABEL_DEFINITIONS
}


POST_APPOINTMENT_LABEL_DEFINITIONS = (
    {
        "field_key": "treatment_notes",
        "default_label": "Treatment Notes",
        "legacy_label": "Treatment Notes",
        "label_type": "textarea",
        "display_order": 10,
    },
    {
        "field_key": "products_used",
        "default_label": "Products Used",
        "legacy_label": "Products Used",
        "label_type": "textarea",
        "display_order": 20,
    },
    {
        "field_key": "home_care_advice",
        "default_label": "Home Care Advice",
        "legacy_label": "Home Care Advice",
        "label_type": "textarea",
        "display_order": 30,
    },
    {
        "field_key": "provider_notes",
        "default_label": "Provider Notes",
        "legacy_label": "Provider Notes",
        "label_type": "textarea",
        "display_order": 40,
    },
)


POST_APPOINTMENT_LABEL_KEYS = {
    definition["field_key"]
    for definition in POST_APPOINTMENT_LABEL_DEFINITIONS
}


CLIENT_INFORMATION_LABEL_KEYS = {
    definition["field_key"]
    for definition in CLIENT_INFORMATION_LABEL_DEFINITIONS
}


def get_client_information_label_definitions():
    """Return safe copies of the complete PSP label registry."""
    return [
        dict(definition)
        for definition in CLIENT_INFORMATION_LABEL_DEFINITIONS
    ]


def get_client_information_labels(
    cur,
    *,
    spa_id,
    business_unit_id,
):
    """
    Return resolved labels for one workspace.

    A workspace override wins when present. Otherwise PSP's generic
    default label is used.
    """

    cur.execute(
        """
        SELECT
            field_key,
            custom_label
        FROM client_information_labels
        WHERE spa_id = %s
          AND business_unit_id = %s
        """,
        (
            spa_id,
            business_unit_id,
        ),
    )

    overrides = {
        str(field_key): str(custom_label).strip()
        for field_key, custom_label in cur.fetchall()
        if str(custom_label or "").strip()
    }

    resolved = {}

    for definition in CLIENT_INFORMATION_LABEL_DEFINITIONS:
        field_key = definition["field_key"]

        resolved[field_key] = overrides.get(
            field_key,
            definition["default_label"],
        )

    return resolved


def save_client_information_labels(
    cur,
    *,
    spa_id,
    business_unit_id,
    labels,
    updated_by=None,
):
    """
    Save workspace label overrides.

    Values equal to the PSP generic default are removed from the
    override table so the workspace automatically follows the
    built-in default.
    """

    definitions_by_key = {
        definition["field_key"]: definition
        for definition in CLIENT_INFORMATION_LABEL_DEFINITIONS
    }

    unknown_keys = set(labels) - set(definitions_by_key)

    if unknown_keys:
        raise ValueError(
            "Unknown Client Information label key(s): "
            + ", ".join(sorted(unknown_keys))
        )

    for field_key, definition in definitions_by_key.items():
        submitted_label = str(
            labels.get(field_key) or ""
        ).strip()

        if not submitted_label:
            submitted_label = definition["default_label"]

        if len(submitted_label) > 100:
            raise ValueError(
                f"{definition['default_label']} must be "
                "100 characters or fewer."
            )

        if submitted_label == definition["default_label"]:
            cur.execute(
                """
                DELETE FROM client_information_labels
                WHERE spa_id = %s
                  AND business_unit_id = %s
                  AND field_key = %s
                """,
                (
                    spa_id,
                    business_unit_id,
                    field_key,
                ),
            )
            continue

        cur.execute(
            """
            INSERT INTO client_information_labels (
                spa_id,
                business_unit_id,
                field_key,
                custom_label,
                updated_by
            )
            VALUES (%s, %s, %s, %s, %s)
            ON CONFLICT (
                spa_id,
                business_unit_id,
                field_key
            )
            DO UPDATE SET
                custom_label = EXCLUDED.custom_label,
                updated_by = EXCLUDED.updated_by,
                updated_at = CURRENT_TIMESTAMP
            """,
            (
                spa_id,
                business_unit_id,
                field_key,
                submitted_label,
                updated_by,
            ),
        )


def get_client_record_note_label_definitions():
    """Return safe copies of Client Record Note label definitions."""

    return [
        dict(definition)
        for definition in CLIENT_RECORD_NOTE_LABEL_DEFINITIONS
    ]


def get_client_record_note_labels(
    cur,
    *,
    spa_id,
    business_unit_id,
):
    """Return resolved Client Record Note labels for one workspace."""

    cur.execute(
        """
        SELECT
            field_key,
            custom_label
        FROM client_information_labels
        WHERE spa_id = %s
          AND business_unit_id = %s
          AND field_key = ANY(%s)
        """,
        (
            spa_id,
            business_unit_id,
            list(CLIENT_RECORD_NOTE_LABEL_KEYS),
        ),
    )

    overrides = {
        str(field_key): str(custom_label).strip()
        for field_key, custom_label in cur.fetchall()
        if str(custom_label or "").strip()
    }

    resolved = {}

    for definition in CLIENT_RECORD_NOTE_LABEL_DEFINITIONS:
        field_key = definition["field_key"]

        resolved[field_key] = overrides.get(
            field_key,
            definition["default_label"],
        )

    return resolved


def save_client_record_note_labels(
    cur,
    *,
    spa_id,
    business_unit_id,
    labels,
    updated_by=None,
):
    """Save workspace Client Record Note label overrides."""

    definitions_by_key = {
        definition["field_key"]: definition
        for definition in CLIENT_RECORD_NOTE_LABEL_DEFINITIONS
    }

    unknown_keys = set(labels) - set(definitions_by_key)

    if unknown_keys:
        raise ValueError(
            "Unknown Client Record Note label key(s): "
            + ", ".join(sorted(unknown_keys))
        )

    for field_key, definition in definitions_by_key.items():
        submitted_label = str(
            labels.get(field_key) or ""
        ).strip()

        if not submitted_label:
            submitted_label = definition["default_label"]

        if len(submitted_label) > 100:
            raise ValueError(
                f"{definition['default_label']} must be "
                "100 characters or fewer."
            )

        if submitted_label == definition["default_label"]:
            cur.execute(
                """
                DELETE FROM client_information_labels
                WHERE spa_id = %s
                  AND business_unit_id = %s
                  AND field_key = %s
                """,
                (
                    spa_id,
                    business_unit_id,
                    field_key,
                ),
            )
            continue

        cur.execute(
            """
            INSERT INTO client_information_labels (
                spa_id,
                business_unit_id,
                field_key,
                custom_label,
                updated_by
            )
            VALUES (%s, %s, %s, %s, %s)

            ON CONFLICT (
                spa_id,
                business_unit_id,
                field_key
            )
            DO UPDATE SET
                custom_label = EXCLUDED.custom_label,
                updated_by = EXCLUDED.updated_by,
                updated_at = CURRENT_TIMESTAMP
            """,
            (
                spa_id,
                business_unit_id,
                field_key,
                submitted_label,
                updated_by,
            ),
        )


def get_post_appointment_label_definitions():
    """Return safe copies of Post Appointment Wrap-Up labels."""

    return [
        dict(definition)
        for definition in POST_APPOINTMENT_LABEL_DEFINITIONS
    ]


def get_post_appointment_labels(
    cur,
    *,
    spa_id,
    business_unit_id,
):
    """
    Return resolved Post Appointment Wrap-Up labels
    for one workspace.
    """

    cur.execute(
        """
        SELECT
            field_key,
            custom_label
        FROM client_information_labels
        WHERE spa_id = %s
          AND business_unit_id = %s
          AND field_key = ANY(%s)
        """,
        (
            spa_id,
            business_unit_id,
            list(POST_APPOINTMENT_LABEL_KEYS),
        ),
    )

    overrides = {
        str(field_key): str(custom_label).strip()
        for field_key, custom_label in cur.fetchall()
        if str(custom_label or "").strip()
    }

    resolved = {}

    for definition in POST_APPOINTMENT_LABEL_DEFINITIONS:
        field_key = definition["field_key"]

        resolved[field_key] = overrides.get(
            field_key,
            definition["default_label"],
        )

    return resolved


def save_post_appointment_labels(
    cur,
    *,
    spa_id,
    business_unit_id,
    labels,
    updated_by=None,
):
    """
    Save workspace Post Appointment Wrap-Up label overrides.
    """

    definitions_by_key = {
        definition["field_key"]: definition
        for definition in POST_APPOINTMENT_LABEL_DEFINITIONS
    }

    unknown_keys = set(labels) - set(definitions_by_key)

    if unknown_keys:
        raise ValueError(
            "Unknown Post Appointment label key(s): "
            + ", ".join(sorted(unknown_keys))
        )

    for field_key, definition in definitions_by_key.items():

        submitted_label = str(
            labels.get(field_key) or ""
        ).strip()

        if not submitted_label:
            submitted_label = definition["default_label"]

        if len(submitted_label) > 100:
            raise ValueError(
                f"{definition['default_label']} must be "
                "100 characters or fewer."
            )

        if submitted_label == definition["default_label"]:
            cur.execute(
                """
                DELETE FROM client_information_labels
                WHERE spa_id = %s
                  AND business_unit_id = %s
                  AND field_key = %s
                """,
                (
                    spa_id,
                    business_unit_id,
                    field_key,
                ),
            )
            continue

        cur.execute(
            """
            INSERT INTO client_information_labels (
                spa_id,
                business_unit_id,
                field_key,
                custom_label,
                updated_by
            )
            VALUES (%s, %s, %s, %s, %s)

            ON CONFLICT (
                spa_id,
                business_unit_id,
                field_key
            )
            DO UPDATE SET
                custom_label = EXCLUDED.custom_label,
                updated_by = EXCLUDED.updated_by,
                updated_at = CURRENT_TIMESTAMP
            """,
            (
                spa_id,
                business_unit_id,
                field_key,
                submitted_label,
                updated_by,
            ),
        )
