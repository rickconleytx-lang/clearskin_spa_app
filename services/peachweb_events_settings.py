"""PeachPOS-only PeachWeb Events & Locations settings.

Uses the caller's database cursor and transaction.
Does not commit or connect to the database independently.
"""

from services.provisioning_service import PUBLIC_WEBSITE_DEFAULTS


EVENT_FIELDS = (
    "show_events_locations",
    "events_locations_heading",
    "events_locations_intro",
    "events_locations_show_directions",
    "events_locations_show_daily_hours",
)

BOOLEAN_FIELDS = (
    "show_events_locations",
    "events_locations_show_directions",
    "events_locations_show_daily_hours",
)


READ_SQL = """
SELECT
    pws.show_events_locations,
    pws.events_locations_heading,
    pws.events_locations_intro,
    pws.events_locations_show_directions,
    pws.events_locations_show_daily_hours
FROM public_website_settings AS pws
JOIN spas AS s
    ON s.spa_id = pws.spa_id
JOIN business_units AS bu
    ON bu.spa_id = pws.spa_id
   AND bu.business_unit_id = pws.business_unit_id
JOIN subscription_tiers AS st
    ON st.subscription_tier_id = s.subscription_tier_id
WHERE pws.spa_id = %s
  AND pws.business_unit_id = %s
  AND s.active IS TRUE
  AND bu.is_active IS TRUE
  AND LOWER(st.tier_code) = 'pos'
LIMIT 1
"""


WRITE_SQL = """
UPDATE public_website_settings AS pws
SET
    show_events_locations = %s,
    events_locations_heading = %s,
    events_locations_intro = %s,
    events_locations_show_directions = %s,
    events_locations_show_daily_hours = %s
FROM spas AS s
JOIN subscription_tiers AS st
    ON st.subscription_tier_id = s.subscription_tier_id
JOIN business_units AS bu
    ON bu.spa_id = s.spa_id
WHERE pws.spa_id = %s
  AND pws.business_unit_id = %s
  AND s.spa_id = pws.spa_id
  AND bu.business_unit_id = pws.business_unit_id
  AND s.active IS TRUE
  AND bu.is_active IS TRUE
  AND LOWER(st.tier_code) = 'pos'
"""


def _check_identity(spa_id, business_unit_id):
    if (
        type(spa_id) is not int
        or spa_id <= 0
        or type(business_unit_id) is not int
        or business_unit_id <= 0
    ):
        raise ValueError("Valid workspace identity required.")


def default_event_settings():
    """Return a fresh copy of the public schedule defaults."""

    return {
        field: PUBLIC_WEBSITE_DEFAULTS[field]
        for field in EVENT_FIELDS
    }


def parse_event_settings_form(form):
    """Validate the submitted PeachPOS website controls."""

    if not hasattr(form, "get"):
        raise ValueError("Invalid settings form.")

    defaults = default_event_settings()

    heading = str(
        form.get("events_locations_heading")
        or defaults["events_locations_heading"]
    ).strip()

    raw_intro = form.get("events_locations_intro")
    intro = (
        defaults["events_locations_intro"]
        if raw_intro is None
        else str(raw_intro).strip()
    )

    if not heading or len(heading) > 180:
        raise ValueError("Invalid Events & Locations heading.")

    if len(intro) > 1000:
        raise ValueError("Events introduction is too long.")

    return {
        "show_events_locations":
            "show_events_locations" in form,
        "events_locations_heading": heading,
        "events_locations_intro": intro,
        "events_locations_show_directions":
            "events_locations_show_directions" in form,
        "events_locations_show_daily_hours":
            "events_locations_show_daily_hours" in form,
    }


def load_event_settings(
    cursor, *, spa_id, business_unit_id
):
    """Read settings only for an active PeachPOS workspace."""

    _check_identity(spa_id, business_unit_id)

    cursor.execute(
        READ_SQL,
        (spa_id, business_unit_id),
    )

    row = cursor.fetchone()

    if row is None:
        return default_event_settings()

    if len(row) != len(EVENT_FIELDS):
        raise ValueError("Unexpected Events settings result.")

    defaults = default_event_settings()

    return {
        "show_events_locations": row[0] is True,
        "events_locations_heading":
            row[1] or defaults["events_locations_heading"],
        "events_locations_intro":
            row[2] if row[2] is not None else
            defaults["events_locations_intro"],
        "events_locations_show_directions":
            row[3] is True,
        "events_locations_show_daily_hours":
            row[4] is True,
    }


def save_event_settings(
    cursor, *, spa_id, business_unit_id, settings
):
    """Update only the five PeachPOS event website columns.

    Caller owns commit/rollback. No automatic row creation.
    """

    _check_identity(spa_id, business_unit_id)

    if (
        not isinstance(settings, dict)
        or set(settings) != set(EVENT_FIELDS)
    ):
        raise ValueError("Invalid Events settings.")

    for field in BOOLEAN_FIELDS:
        if type(settings[field]) is not bool:
            raise ValueError("Invalid visibility setting.")

    heading = settings["events_locations_heading"]
    intro = settings["events_locations_intro"]

    if (
        not isinstance(heading, str)
        or not 1 <= len(heading.strip()) <= 180
        or not isinstance(intro, str)
        or len(intro) > 1000
    ):
        raise ValueError("Invalid Events text settings.")

    cursor.execute(
        WRITE_SQL,
        (
            settings["show_events_locations"],
            heading.strip(),
            intro,
            settings["events_locations_show_directions"],
            settings["events_locations_show_daily_hours"],
            spa_id,
            business_unit_id,
        ),
    )

    if cursor.rowcount != 1:
        raise ValueError(
            "PeachPOS website settings could not be updated."
        )
