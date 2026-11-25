import unittest

from services.psp_ai_help_search import (
    search_ai_help_articles,
    _meaningful_query_words,
)


REMINDER_KEY = "business_schedules_reminders"

ARTICLES = [
    {
        "page_key": REMINDER_KEY,
        "title": "Business Schedules & Reminders",
        "display_name": "Business Schedules & Reminders",
        "summary": (
            "Learn how to create business reminders, track "
            "important dates, lease expiration, license "
            "renewals, insurance renewals, sales tax filings, "
            "subscriptions and event deadlines."
        ),
        "search_keywords": (
            "reminders remind remember forget dates deadline "
            "due date repeating license licenses "
            "professional license renewal expiration "
            "lease renewal insurance sales tax filings "
            "subscriptions business schedule business "
            "reminder important events Coach Peach "
            "Peach Suite Pro PSP"
        ),
        "content": (
            "<h2>How to Add a Business Reminder</h2>"
            "<p>Open Business Schedule. Select a category, "
            "enter a title and due date, choose repeat settings "
            "and Reminder Days Before, then save.</p>"
            "<p>Track leases, licenses, insurance, sales tax "
            "filings, important dates, renewals, and events.</p>"
        ),
        "language_code": "EN",
    },
    {
        "page_key": "square_coach_peach",
        "title": "Square - Coach Peach and Square",
        "display_name": "Square - Coach Peach and Square",
        "summary": (
            "How Coach Peach assists with Square payment "
            "reconciliation and catalog synchronization."
        ),
        "search_keywords": (
            "Coach Peach Peach Suite Pro PSP Square "
            "payments reconcile reconciliation sync catalog"
        ),
        "content": (
            "<p>Connect Square and review Square payments.</p>"
        ),
        "language_code": "EN",
    },
    {
        "page_key": "coach_peach_help",
        "title": "Coach Peach",
        "display_name": "Coach Peach",
        "summary": (
            "What Coach Peach is and how to use Coach Peach."
        ),
        "search_keywords": (
            "Coach Peach AI assistant Peach Suite Pro PSP"
        ),
        "content": (
            "<p>Coach Peach provides application guidance.</p>"
        ),
        "language_code": "EN",
    },
    {
        "page_key": "peach_suite_pro_overview",
        "title": "Peach Suite Pro Overview",
        "display_name": "Peach Suite Pro Overview",
        "summary": "Introduction to the Peach Suite Pro platform.",
        "search_keywords": (
            "Peach Suite Pro PSP overview getting started"
        ),
        "content": "<p>Welcome to Peach Suite Pro.</p>",
        "language_code": "EN",
    },
    {
        "page_key": "appointment_calendar",
        "title": "Appointment Calendar",
        "display_name": "Appointment Calendar",
        "summary": "Manage bookings and appointment schedules.",
        "search_keywords": (
            "Peach Suite Pro Coach Peach appointment "
            "appointments booking calendar schedule"
        ),
        "content": "<p>Open the Appointment Calendar.</p>",
        "language_code": "EN",
    },
    {
        "page_key": "subscription_billing",
        "title": "Subscription Billing",
        "display_name": "Subscription Billing",
        "summary": "Manage your subscription and billing.",
        "search_keywords": (
            "Peach Suite Pro Coach Peach subscription "
            "subscriptions billing plan payment"
        ),
        "content": "<p>Review subscription billing.</p>",
        "language_code": "EN",
    },
    {
        "page_key": "sms",
        "title": "SMS Messages",
        "display_name": "SMS Messages",
        "summary": "Send SMS text messages to opted-in clients.",
        "search_keywords": (
            "Peach Suite Pro Coach Peach SMS text messages send"
        ),
        "content": "<p>Open SMS Messages.</p>",
        "language_code": "EN",
    },
    {
        "page_key": "event_calendar",
        "title": "Event Calendar",
        "display_name": "Event Calendar",
        "summary": "Create and manage Event Calendar entries.",
        "search_keywords": (
            "Peach Suite Pro Coach Peach events event calendar"
        ),
        "content": "<p>Add an event to the Event Calendar.</p>",
        "language_code": "EN",
    },
    {
        "page_key": "general_email",
        "title": "General Email",
        "display_name": "General Email",
        "summary": "Compose and send general email messages.",
        "search_keywords": (
            "Peach Suite Pro Coach Peach general email "
            "emails send clients"
        ),
        "content": "<p>Compose a general email message.</p>",
        "language_code": "EN",
    },
]


QUESTIONS = [
    "I need to make sure I don't forget my license renewal",
    "is there a way to be reminded of my lease expiration",
    "can Coach Peach let me know when my sales tax needs to be filed",
    "can Coach Peach let me know when my lease is expiring",
    "can Coach Peach remind me when my lease is expiring",
    "can Coach Peach remind me my esthetician license needs renewed",
    "is there anyway psp can remind me that my spa lease renewal",
    "can Coach Peach remind me when my sales tax needs to be filed",
    "how do I enter a reminder",
    "where is the reminder form",
    "I need to be reminded of my esthetician license needing renewed next march, can PSP help",
    "I need to be reminded of sales tax needing to be filed next march, can PSP help",
    "I want to be reminded of sales tax needing to be filed next march, can PSP help",
    "I have an important event next March 5th, and psp remind me?",
    "can psp help me remember an important date",
    "can psp help me remember my spa lease expiration",
    "can psp help me remember my insurance renewal",
    "can psp remind me of my insurance renewal",
    "how do I add a reminder",
    "how do I add a date reminder",
    "how do I add a business date reminder",
    "how do I add a business reminder",
    "I need to be reminded to renew my spa room lease",
    "I need a reminder to renew my spa room lease",
]

assert len(QUESTIONS) == 24


class FakeCursor:
    def execute(self, sql, params):
        self.sql = sql
        self.params = params

    def fetchall(self):
        return list(ARTICLES)


def lookup(question):
    cursor = FakeCursor()

    results = search_ai_help_articles(
        cursor,
        question=question,
        language="EN",
        limit=4,
    )

    return results, cursor


class HelpRetrievalRegressionTests(unittest.TestCase):

    def test_square_reconciliation(self):
        results, _ = lookup(
            "How do I reconcile Square payments?"
        )
        self.assertTrue(results)
        self.assertEqual(
            results[0]["page_key"],
            "square_coach_peach",
        )

    def test_square_connection(self):
        results, _ = lookup(
            "How do I reconnect Square?"
        )
        self.assertTrue(results)
        self.assertEqual(
            results[0]["page_key"],
            "square_coach_peach",
        )

    def test_appointment_calendar(self):
        results, _ = lookup(
            "Where is my appointment calendar?"
        )
        self.assertTrue(results)
        self.assertEqual(
            results[0]["page_key"],
            "appointment_calendar",
        )

    def test_subscription_billing(self):
        results, _ = lookup(
            "How do I manage subscription billing?"
        )
        self.assertTrue(results)
        self.assertEqual(
            results[0]["page_key"],
            "subscription_billing",
        )

    def test_sms_messages(self):
        results, _ = lookup("How do I send SMS messages?")
        self.assertTrue(results)
        self.assertEqual(results[0]["page_key"], "sms")

    def test_event_calendar(self):
        results, _ = lookup(
            "How do I add an event to the Event Calendar?"
        )
        self.assertTrue(results)
        self.assertEqual(
            results[0]["page_key"],
            "event_calendar",
        )

    def test_general_email(self):
        results, _ = lookup(
            "How do I send general emails?"
        )
        self.assertTrue(results)
        self.assertEqual(
            results[0]["page_key"],
            "general_email",
        )

    def test_coach_peach_direct_question(self):
        results, _ = lookup("What is Coach Peach?")
        self.assertTrue(results)
        self.assertEqual(
            results[0]["page_key"],
            "coach_peach_help",
        )

    def test_psp_direct_question(self):
        results, _ = lookup("What is Peach Suite Pro?")
        self.assertTrue(results)
        self.assertEqual(
            results[0]["page_key"],
            "peach_suite_pro_overview",
        )

    def test_implicit_reminder_intent(self):
        questions = (
            "Can Coach Peach let me know when my sales tax "
            "needs to be filed?",
            "Can Coach Peach let me know when my lease "
            "is expiring?",
        )

        for question in questions:
            with self.subTest(question=question):
                terms = _meaningful_query_words(question)
                self.assertIn("remind", terms)

    def test_unrelated_status_not_reminder_intent(self):
        terms = _meaningful_query_words(
            "Can Coach Peach let me know when "
            "Square payments reconcile?"
        )
        self.assertNotIn("remind", terms)

    def test_forgotten_password_not_a_business_reminder(self):
        results, _ = lookup(
            "I forgot my password, can Coach Peach help?"
        )
        keys = [item["page_key"] for item in results]
        self.assertNotIn(REMINDER_KEY, keys)

    def test_unrelated_question_not_matched(self):
        results, _ = lookup(
            "How do I calibrate my quantum turbine?"
        )
        self.assertFalse(results)

    def test_approved_article_sql_gate_unchanged(self):
        _, cursor = lookup("How do I add a reminder?")
        self.assertIn("spa_id IS NULL", cursor.sql)
        self.assertIn("is_active = TRUE", cursor.sql)
        self.assertIn("language_code IN", cursor.sql)
        self.assertIn(
            "page_key <> 'sms_email_terms'",
            cursor.sql,
        )


def reminder_test(question):
    def run_test(self):
        results, _ = lookup(question)
        keys = [r["page_key"] for r in results]

        self.assertTrue(
            keys,
            f"No Help articles found: {question}",
        )
        self.assertEqual(
            keys[0],
            REMINDER_KEY,
            f"Wrong primary article: {question}; {keys}",
        )
        self.assertNotIn(
            "square_coach_peach",
            keys,
            f"Irrelevant Square result: {question}",
        )

    return run_test


for index, question in enumerate(QUESTIONS, 1):
    setattr(
        HelpRetrievalRegressionTests,
        f"test_reminder_question_{index:02d}",
        reminder_test(question),
    )


if __name__ == "__main__":
    unittest.main()
