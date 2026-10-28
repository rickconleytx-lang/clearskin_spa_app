"""Coach Peach 2.0 search regression checks — NO database or OpenAI access.

Save this file in the root of the clearskin_spa_app project, then open it in
VS Code and select Run Python File (the editor Run button).
This script reads the *local* services/psp_ai_help_search.py and uses only
in-memory sample records. It does not import the Flask app or db.py.
"""

from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path


ROOT = Path(__file__).resolve().parent
SEARCH_FILE = ROOT / "services" / "psp_ai_help_search.py"
if not SEARCH_FILE.is_file():
    raise SystemExit(
        "STOP: Save this test in the clearskin_spa_app project root, "
        "next to app.py, then run it again."
    )

spec = spec_from_file_location("psp_ai_help_search_v2_test_module", SEARCH_FILE)
module = module_from_spec(spec)
spec.loader.exec_module(module)


class ReadOnlyFakeCursor:
    """In-memory stand-in for the article query; no database connection."""

    def __init__(self, rows):
        self.rows = rows
        self.sql = None
        self.params = None

    def execute(self, sql, params):
        self.sql = sql
        self.params = params
        required = (
            "FROM help_pages",
            "spa_id IS NULL",
            "is_active = TRUE",
            "page_key <> 'sms_email_terms'",
            "language_code IN (%s, 'EN')",
        )
        for rule in required:
            assert rule in sql, f"Approved-article SQL safety condition missing: {rule}"

    def fetchall(self):
        return self.rows


def article(page_key, title, keywords="", summary="", content="", display_name=None):
    return {
        "page_key": page_key,
        "title": title,
        "display_name": display_name if display_name is not None else title,
        "search_keywords": keywords,
        "summary": summary,
        "content": content,
        "language_code": "EN",
    }


# Representative help metadata; not a copy of production records.
SAMPLE = [
    article(
        "square_reconcile_payments", "Square - Reconcile Payments",
        "Square reconciliation, Square payments, payment reconciliation",
        "Follow the Square reconciliation workflow",
        "<p>Reconcile payments after daily Square sales.</p>",
    ),
    article(
        "square_connecting_account", "Square - Connecting Your Account",
        "connect Square, Square connection, authorize Square, Square Control Center",
        "Connect your Square account and review connection status",
        "<p>Review your connected account in the Square Control Center.</p>",
    ),
    article(
        "square_disconnecting_and_reconnecting", "Square - Disconnecting and Reconnecting Square",
        "disconnect Square, reconnect Square, connection",
        "How to disconnect or reconnect an existing Square account",
        "<p>Disconnect, then reconnect only when necessary.</p>",
    ),
    article(
        "general_email", "General Email", "", "",
        "<p>Send an email to a client from the General Email page.</p>",
    ),
    article(
        "email_templates", "Email Templates",
        "email templates, email messaging, merge fields, custom email templates",
        "Learn how to create and manage reusable Email Templates",
        "<p>Prepare templates for outgoing email messages.</p>",
    ),
    article(
        "sms_email_history", "SMS and Email History",
        "SMS history, email history, sent messages, email delivery",
        "Review messages previously sent",
        "<p>View past sent emails and statuses.</p>",
    ),
    article(
        "appointments", "Appointments",
        "appointments, post appointment wrap, treatment notes",
        "Manage appointments and post appointment wrap up",
        "<p>Complete the Post Appointment Wrap-Up and save notes.</p>",
    ),
    article(
        "calendar", "Calendar", "appointments, calendar views, scheduling",
        "Navigate calendar appointments", "<p>View appointments.</p>",
    ),
    article(
        "unrelated_content_only", "Business Summary", "business summary, reporting",
        "See your business totals",
        "<p>A passing email mention in an unrelated article.</p>",
    ),
]


def run(question, *, current_page_key=None, language="EN"):
    cursor = ReadOnlyFakeCursor(SAMPLE)
    result = module.search_ai_help_articles(
        cursor, question=question, language=language,
        current_page_key=current_page_key, limit=3,
    )
    assert cursor.params == (language, language), "Unexpected language fallback arguments"
    return result


cases = [
    ("How do I reconcile Square payments?", "square_reconcile_payments"),
    ("How do I send an email?", "general_email"),
    ("Where do I review my Square connection?", "square_connecting_account"),
    ("How do I complete the post appointment wrap up?", "appointments"),
]

print("COACH PEACH 2.0 — IN-MEMORY SEARCH CHECKS")
print("No database connections. No OpenAI calls. No file modifications.\n")

for question, expected_key in cases:
    results = run(question)
    top = results[0]["page_key"] if results else "(no results)"
    assert top == expected_key, (
        f"Wrong top article for '{question}': expected {expected_key}, got {top}"
    )
    print(f"PASS — {question} -> {results[0]['title']}")

out_of_scope = run("How do I make an Old Fashioned?")
assert not out_of_scope, f"Out-of-scope question incorrectly found: {out_of_scope}"
print("PASS — Out-of-scope question returns no articles")

with_article_open = run(
    "How do I reconcile Square payments?", current_page_key="appointments"
)
assert with_article_open[0]["page_key"] == "square_reconcile_payments"
print("PASS — Current Help article does not override relevant search results")

body_only_results = run("How do I send an email?")
assert all(row["page_key"] != "unrelated_content_only" for row in body_only_results)
print("PASS — Unrelated body-only match excluded")

spanish = run("How do I send an email?", language="ES")
assert spanish[0]["page_key"] == "general_email"
print("PASS — Spanish-preference SQL parameters with English sample fallback")

print("\nSUCCESS — All 8 in-memory Coach Peach search checks passed.")
print("NEXT: Actual database/browser and financial-gateway validation required before deploy.")
