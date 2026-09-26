"""
PeachPOS payment-processor field display labels.

The processor-specific backend Income column names are immutable:

    processor_field_1
    ...
    processor_field_8

Only the user-facing labels may be customized. Labels are scoped
to both the Provider Workspace and the specific credit processor so
different processors may use different terminology without changing
the underlying Peach Suite Pro database schema.
"""


PEACHPOS_PROCESSOR_FIELD_DEFINITIONS = tuple(
    {
        "field_key": f"processor_field_{number}",
        "default_label": f"Processor Field {number}",
        "label_type": "text",
        "display_order": number * 10,
    }
    for number in range(1, 9)
)


def get_peachpos_processor_field_definitions():
    """Return safe copies of the PeachPOS processor-field registry."""
    return [
        dict(definition)
        for definition in PEACHPOS_PROCESSOR_FIELD_DEFINITIONS
    ]


def _require_processor_in_workspace(
    cur,
    *,
    spa_id,
    business_unit_id,
    credit_processor_id,
):
    """
    Verify that one credit processor belongs to the requested workspace.

    The processor name is user-owned data. PSP does not attempt to
    externally verify processor brands.
    """
    cur.execute(
        """
        SELECT
            credit_processor_id,
            credit_processor_name,
            is_active
        FROM credit_processors
        WHERE credit_processor_id = %s
          AND spa_id = %s
          AND business_unit_id = %s
        LIMIT 1
        """,
        (
            credit_processor_id,
            spa_id,
            business_unit_id,
        ),
    )

    processor = cur.fetchone()

    if not processor:
        raise ValueError(
            "Credit processor was not found in this Provider Workspace."
        )

    return {
        "credit_processor_id": processor[0],
        "credit_processor_name": processor[1],
        "is_active": bool(processor[2]),
    }


def get_peachpos_processor_field_labels(
    cur,
    *,
    spa_id,
    business_unit_id,
    credit_processor_id,
    require_active=False,
):
    """
    Return resolved processor-specific display labels.

    A saved override wins when present. Otherwise PSP's permanent
    generic display label is returned.
    """
    processor = (
        _require_processor_in_workspace(
            cur,
            spa_id=spa_id,
            business_unit_id=business_unit_id,
            credit_processor_id=credit_processor_id,
        )
    )

    if require_active and not processor["is_active"]:
        raise ValueError(
            "Archived credit processors cannot be used "
            "for new PeachPOS imports."
        )

    cur.execute(
        """
        SELECT
            field_key,
            custom_label
        FROM peachpos_processor_field_labels
        WHERE spa_id = %s
          AND business_unit_id = %s
          AND credit_processor_id = %s
        """,
        (
            spa_id,
            business_unit_id,
            credit_processor_id,
        ),
    )

    overrides = {
        str(field_key): str(custom_label).strip()
        for field_key, custom_label in cur.fetchall()
        if str(custom_label or "").strip()
    }

    resolved = {}

    for definition in PEACHPOS_PROCESSOR_FIELD_DEFINITIONS:
        field_key = definition["field_key"]

        resolved[field_key] = overrides.get(
            field_key,
            definition["default_label"],
        )

    return resolved


def save_peachpos_processor_field_labels(
    cur,
    *,
    spa_id,
    business_unit_id,
    credit_processor_id,
    labels,
    updated_by=None,
):
    """
    Save processor-specific display-label overrides.

    Values equal to PSP's generic default are removed from the override
    table so built-in defaults remain the single source of truth.
    """
    _require_processor_in_workspace(
        cur,
        spa_id=spa_id,
        business_unit_id=business_unit_id,
        credit_processor_id=credit_processor_id,
    )

    definitions_by_key = {
        definition["field_key"]: definition
        for definition in PEACHPOS_PROCESSOR_FIELD_DEFINITIONS
    }

    unknown_keys = set(labels) - set(definitions_by_key)

    if unknown_keys:
        raise ValueError(
            "Unknown PeachPOS processor field label key(s): "
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
                DELETE FROM peachpos_processor_field_labels
                WHERE spa_id = %s
                  AND business_unit_id = %s
                  AND credit_processor_id = %s
                  AND field_key = %s
                """,
                (
                    spa_id,
                    business_unit_id,
                    credit_processor_id,
                    field_key,
                ),
            )

            continue

        cur.execute(
            """
            INSERT INTO peachpos_processor_field_labels (
                spa_id,
                business_unit_id,
                credit_processor_id,
                field_key,
                custom_label,
                updated_by
            )
            VALUES (%s, %s, %s, %s, %s, %s)
            ON CONFLICT (
                spa_id,
                business_unit_id,
                credit_processor_id,
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
                credit_processor_id,
                field_key,
                submitted_label,
                updated_by,
            ),
        )
