"""Active resource ownership checks for PeachPOS events.

Read-only SQL. Call within the authenticated workspace's
database transaction. The caller must supply trusted scope IDs.
"""


class EventResourceError(ValueError):
    """Resource is invalid, inactive, or outside the workspace."""


def _resource_ids(normalized):
    if not isinstance(normalized, dict):
        raise EventResourceError("Invalid event data.")

    days = normalized.get("days")

    if not isinstance(days, list):
        raise EventResourceError("Invalid operating days.")

    equipment = set()
    employees = set()

    for day in days:
        if not day["operating"]:
            continue

        for unit_id in day["equipment_ids"]:
            if (
                type(unit_id) is not int
                or not 1 <= unit_id <= 9223372036854775807
            ):
                raise EventResourceError(
                    "Invalid equipment identifier."
                )

            equipment.add(unit_id)

        for shift in day["shifts"]:
            employee_id = shift["employee_id"]

            if (
                type(employee_id) is not int
                or not 1 <= employee_id <= 2147483647
            ):
                raise EventResourceError(
                    "Invalid employee identifier."
                )

            employees.add(employee_id)

    return sorted(equipment), sorted(employees)


def validate_event_resource_ownership(
    cursor, normalized, spa_id, workspace_id
):
    """Require active, workspace-owned equipment and employees.

    This checks eligibility only. Existing-event conflicts
    must be checked separately. Recheck eligibility inside
    the final save transaction before inserting assignments.
    """

    if any(
        type(value) is not int or value <= 0
        for value in (spa_id, workspace_id)
    ):
        raise EventResourceError(
            "Invalid business or workspace scope."
        )

    equipment, employees = _resource_ids(normalized)

    if equipment:
        cursor.execute(
            """
            SELECT event_unit_id
            FROM event_units
            WHERE spa_id = %s
              AND business_unit_id = %s
              AND is_active = TRUE
              AND event_unit_id = ANY(%s::bigint[])
            """,
            (spa_id, workspace_id, equipment),
        )

        eligible_units = {
            int(row[0]) for row in cursor.fetchall()
        }

        if eligible_units != set(equipment):
            raise EventResourceError(
                "One or more selected event units are "
                "inactive or unavailable in this workspace."
            )

    if employees:
        cursor.execute(
            """
            SELECT m.employee_id
            FROM employee_business_unit_memberships AS m
            JOIN employees AS e
              ON e.spa_id = m.spa_id
             AND e.employee_id = m.employee_id
            WHERE m.spa_id = %s
              AND m.business_unit_id = %s
              AND m.is_active = TRUE
              AND e.is_active = TRUE
              AND m.employee_id = ANY(%s::integer[])
            """,
            (spa_id, workspace_id, employees),
        )

        eligible_employees = {
            int(row[0]) for row in cursor.fetchall()
        }

        if eligible_employees != set(employees):
            raise EventResourceError(
                "One or more selected employees are "
                "inactive or unavailable in this workspace."
            )

    return {
        "event_unit_ids": equipment,
        "employee_ids": employees,
        "ownership_validated": True,
    }
