"""Assemble the public PeachPOS Events & Locations schedule."""

from services.peachweb_event_schedule import five_week_windows
from services.peachweb_public_events import fetch_public_event_days
from services.peachweb_event_presentation import (
    build_weekly_public_schedule,
)
from services.peachweb_events_settings import load_event_settings


PUBLIC_BUSINESS_TIMEZONE_SQL = """
    SELECT s.timezone_name
    FROM spas s
    JOIN business_units bu
      ON bu.spa_id = s.spa_id
    JOIN subscription_tiers st
      ON st.subscription_tier_id = s.subscription_tier_id
    WHERE s.spa_id = %s
      AND bu.business_unit_id = %s
      AND s.active IS TRUE
      AND bu.is_active IS TRUE
      AND LOWER(st.tier_code) = 'pos'
    LIMIT 1
"""


def load_public_events_section(cursor, *, tenant, now=None):
    """Return approved public data only for an enabled PeachPOS site."""
    if tenant["tier_code"] != "pos":
        return None

    spa_id = tenant["spa_id"]
    business_unit_id = tenant["business_unit_id"]

    settings = load_event_settings(
        cursor,
        spa_id=spa_id,
        business_unit_id=business_unit_id,
    )

    if settings["show_events_locations"] is not True:
        return None

    cursor.execute(
        PUBLIC_BUSINESS_TIMEZONE_SQL,
        (spa_id, business_unit_id),
    )

    timezone_row = cursor.fetchone()

    if not timezone_row:
        return None

    timezone_name = timezone_row[0]

    if (
        not isinstance(timezone_name, str)
        or not timezone_name.strip()
    ):
        return None

    windows = five_week_windows(
        timezone_name.strip(),
        now=now,
    )

    rows = fetch_public_event_days(
        cursor,
        spa_id=spa_id,
        business_unit_id=business_unit_id,
        window_start=windows[0][0],
        window_end=windows[-1][1],
    )

    weeks = build_weekly_public_schedule(
        rows,
        windows,
        show_hours=settings[
            "events_locations_show_daily_hours"
        ],
        show_directions=settings[
            "events_locations_show_directions"
        ],
    )

    return {
        "heading": settings["events_locations_heading"],
        "intro": settings["events_locations_intro"],
        "weeks": weeks,
    }
