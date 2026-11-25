import unittest

from services.peachweb_events_settings import (
    READ_SQL,
    WRITE_SQL,
    default_event_settings,
    parse_event_settings_form,
    load_event_settings,
    save_event_settings,
)


class FakeCursor:

    def __init__(self, row=None, rowcount=1):
        self.row = row
        self.rowcount = rowcount
        self.sql = None
        self.params = None

    def execute(self, sql, params):
        self.sql = sql
        self.params = params

    def fetchone(self):
        return self.row


class PeachWebEventsSettingsTests(unittest.TestCase):

    def test_defaults_are_disabled(self):
        settings = default_event_settings()

        self.assertFalse(settings["show_events_locations"])
        self.assertEqual(
            settings["events_locations_heading"],
            "Where to Find Us",
        )

    def test_missing_row_defaults_to_disabled(self):
        cur = FakeCursor()

        result = load_event_settings(
            cur, spa_id=44, business_unit_id=41
        )

        self.assertFalse(result["show_events_locations"])
        self.assertEqual(cur.params, (44, 41))

    def test_existing_settings_are_loaded(self):
        cur = FakeCursor(row=(
            True, "Weekly Locations", "Visit us!",
            True, False,
        ))

        result = load_event_settings(
            cur, spa_id=44, business_unit_id=41
        )

        self.assertTrue(result["show_events_locations"])
        self.assertEqual(
            result["events_locations_heading"],
            "Weekly Locations",
        )
        self.assertFalse(
            result["events_locations_show_daily_hours"]
        )

    def test_unchecked_master_toggle_is_false(self):
        result = parse_event_settings_form({
            "events_locations_heading": "Where to Find Us",
            "events_locations_intro": "Visit our trucks!",
        })

        self.assertFalse(result["show_events_locations"])
        self.assertFalse(
            result["events_locations_show_directions"]
        )

    def test_checked_controls_are_true(self):
        result = parse_event_settings_form({
            "show_events_locations": "on",
            "events_locations_show_directions": "on",
            "events_locations_show_daily_hours": "on",
            "events_locations_heading": "Find Us",
            "events_locations_intro": "",
        })

        self.assertTrue(result["show_events_locations"])
        self.assertTrue(
            result["events_locations_show_directions"]
        )
        self.assertTrue(
            result["events_locations_show_daily_hours"]
        )
        self.assertEqual(result["events_locations_intro"], "")

    def test_invalid_heading_rejected(self):
        with self.assertRaises(ValueError):
            parse_event_settings_form({
                "events_locations_heading": "X" * 181,
            })

    def test_save_updates_only_expected_fields(self):
        cur = FakeCursor()
        settings = default_event_settings()

        save_event_settings(
            cur,
            spa_id=44,
            business_unit_id=41,
            settings=settings,
        )

        self.assertEqual(cur.params[-2:], (44, 41))
        self.assertEqual(len(cur.params), 7)
        self.assertIn(
            "UPDATE public_website_settings", cur.sql
        )
        self.assertNotIn("contact_email", cur.sql)

    def test_failed_workspace_update_is_rejected(self):
        cur = FakeCursor(rowcount=0)

        with self.assertRaises(ValueError):
            save_event_settings(
                cur,
                spa_id=44,
                business_unit_id=41,
                settings=default_event_settings(),
            )

    def test_invalid_identity_rejected_before_query(self):
        cur = FakeCursor()

        with self.assertRaises(ValueError):
            load_event_settings(
                cur, spa_id=0, business_unit_id=41
            )

        self.assertIsNone(cur.sql)

    def test_both_queries_enforce_peachpos_and_workspace(self):
        for sql in (READ_SQL, WRITE_SQL):
            with self.subTest(sql=sql[:20]):
                normalized = " ".join(sql.lower().split())

                self.assertIn(
                    "lower(st.tier_code) = 'pos'",
                    normalized,
                )
                self.assertIn(
                    "pws.spa_id = %s",
                    normalized,
                )
                self.assertIn(
                    "pws.business_unit_id = %s",
                    normalized,
                )
                self.assertIn(
                    "s.active is true",
                    normalized,
                )
                self.assertIn(
                    "bu.is_active is true",
                    normalized,
                )


if __name__ == "__main__":
    unittest.main()
