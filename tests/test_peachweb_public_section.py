"""Publication and isolation tests for PeachWeb public sections."""

import unittest
from datetime import date, datetime, timedelta, timezone
from unittest.mock import patch

from services import peachweb_public_section as section


class FakeCursor:
    def __init__(self, timezone_row=("America/Chicago",)):
        self.timezone_row = timezone_row
        self.queries = []

    def execute(self, statement, parameters):
        self.queries.append((statement, parameters))

    def fetchone(self):
        return self.timezone_row


class PeachWebPublicSectionTests(unittest.TestCase):
    def setUp(self):
        self.tenant = {
            "tier_code": "pos",
            "spa_id": 44,
            "business_unit_id": 41,
        }
        self.now = datetime(
            2026, 11, 14, 20, 0,
            tzinfo=timezone.utc,
        )
        first = date(2026, 11, 9)
        self.windows = tuple(
            (
                first + timedelta(weeks=i),
                first + timedelta(weeks=i, days=6),
            )
            for i in range(5)
        )
        self.settings = {
            "show_events_locations": True,
            "events_locations_heading": "Where to Find Us",
            "events_locations_intro": "Find us this week!",
            "events_locations_show_directions": True,
            "events_locations_show_daily_hours": True,
        }

    def test_non_peachpos_never_loads_settings(self):
        cursor = FakeCursor()
        tenant = dict(self.tenant, tier_code="solo")

        with patch.object(
            section, "load_event_settings"
        ) as loader:
            result = section.load_public_events_section(
                cursor, tenant=tenant,
            )

        self.assertIsNone(result)
        loader.assert_not_called()
        self.assertEqual(cursor.queries, [])

    def test_master_off_prevents_event_query(self):
        cursor = FakeCursor()
        disabled = dict(
            self.settings,
            show_events_locations=False,
        )

        with patch.object(
            section, "load_event_settings",
            return_value=disabled,
        ), patch.object(
            section, "fetch_public_event_days"
        ) as fetcher:
            result = section.load_public_events_section(
                cursor, tenant=self.tenant,
            )

        self.assertIsNone(result)
        self.assertEqual(cursor.queries, [])
        fetcher.assert_not_called()

    def test_missing_timezone_fails_closed(self):
        cursor = FakeCursor(timezone_row=None)

        with patch.object(
            section, "load_event_settings",
            return_value=self.settings,
        ), patch.object(
            section, "fetch_public_event_days"
        ) as fetcher:
            result = section.load_public_events_section(
                cursor, tenant=self.tenant,
            )

        self.assertIsNone(result)
        fetcher.assert_not_called()

    def test_enabled_schedule_uses_five_weeks(self):
        cursor = FakeCursor()
        rows = [{"event_id": 12}]
        weeks = [{
            "heading": "November 9–15",
            "events": [{"name": "Taco Festival"}],
        }]

        with patch.object(
            section, "load_event_settings",
            return_value=self.settings,
        ) as loader, patch.object(
            section, "five_week_windows",
            return_value=self.windows,
        ) as window_builder, patch.object(
            section, "fetch_public_event_days",
            return_value=rows,
        ) as fetcher, patch.object(
            section, "build_weekly_public_schedule",
            return_value=weeks,
        ) as presenter:
            result = section.load_public_events_section(
                cursor,
                tenant=self.tenant,
                now=self.now,
            )

        loader.assert_called_once_with(
            cursor,
            spa_id=44,
            business_unit_id=41,
        )
        window_builder.assert_called_once_with(
            "America/Chicago",
            now=self.now,
        )
        fetcher.assert_called_once_with(
            cursor,
            spa_id=44,
            business_unit_id=41,
            window_start=date(2026, 11, 9),
            window_end=date(2026, 12, 13),
        )
        presenter.assert_called_once_with(
            rows,
            self.windows,
            show_hours=True,
            show_directions=True,
        )

        self.assertEqual(result, {
            "heading": "Where to Find Us",
            "intro": "Find us this week!",
            "weeks": weeks,
        })
        self.assertEqual(
            cursor.queries[0][1],
            (44, 41),
        )

    def test_hours_and_directions_options(self):
        cursor = FakeCursor()
        settings = dict(
            self.settings,
            events_locations_show_daily_hours=False,
            events_locations_show_directions=False,
        )

        with patch.object(
            section, "load_event_settings",
            return_value=settings,
        ), patch.object(
            section, "five_week_windows",
            return_value=self.windows,
        ), patch.object(
            section, "fetch_public_event_days",
            return_value=[],
        ), patch.object(
            section, "build_weekly_public_schedule",
            return_value=[],
        ) as presenter:
            section.load_public_events_section(
                cursor, tenant=self.tenant,
            )

        presenter.assert_called_once_with(
            [],
            self.windows,
            show_hours=False,
            show_directions=False,
        )

    def test_timezone_query_is_workspace_scoped(self):
        sql = section.PUBLIC_BUSINESS_TIMEZONE_SQL

        for required in (
            "s.spa_id = %s",
            "bu.business_unit_id = %s",
            "s.active IS TRUE",
            "bu.is_active IS TRUE",
            "LOWER(st.tier_code) = 'pos'",
        ):
            self.assertIn(required, sql)


if __name__ == "__main__":
    unittest.main()
