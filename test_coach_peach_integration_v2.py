"""Coach Peach 2.0 — isolated integration test (no database/OpenAI connection).

Place in clearskin_spa_app root, alongside app.py. Run using VS Code's
'Run Python File' command with the application's existing virtual environment.
Imports only local services modules; injects in-memory data and callbacks.
Never imports app.py, db.py, or calls provider/network/database functions.
"""

from pathlib import Path
import importlib.util
import sys
from decimal import Decimal

ROOT = Path(__file__).resolve().parent
REQUIRED = [
    "services/psp_ai_help_search.py",
    "services/psp_ai_help_bundle.py",
    "services/psp_ai_help_context.py",
    "services/psp_ai_help_request.py",
    "services/psp_ai_help_execution.py",
]
for filename in REQUIRED:
    if not (ROOT / filename).is_file():
        raise SystemExit(f"STOP: {filename} not found. Put this test beside app.py.")

# Compile source without writing __pycache__, opening a DB, or using OpenAI.
for filename in REQUIRED:
    code = (ROOT / filename).read_text(encoding="utf-8")
    compile(code, str(ROOT / filename), "exec")

from services import psp_ai_help_bundle as bundle
from services import psp_ai_help_execution as engine


class FakeCursor:
    def __init__(self, data, events):
        self.data = data
        self.events = events
        self.sql = ""

    def __enter__(self):
        return self

    def __exit__(self, typ, value, tb):
        return False

    def execute(self, sql, params=None):
        self.sql = sql
        if "FROM help_pages" in sql:
            assert "spa_id IS NULL" in sql
            assert "is_active = TRUE" in sql
            assert "page_key <> 'sms_email_terms'" in sql
            assert "language_code IN (%s, 'EN')" in sql
            self.events.append("read_approved_articles")
        elif "FROM psp_ai_model_pricing" in sql:
            assert params == (1, "gpt-6-luna")
            self.events.append("validate_pricing")
        else:
            raise AssertionError("Unexpected SQL during isolated integration test")

    def fetchall(self):
        assert "FROM help_pages" in self.sql
        return self.data

    def fetchone(self):
        assert "FROM psp_ai_model_pricing" in self.sql
        return {"ai_model_pricing_id": 1}


class FakeConn:
    def __init__(self, data, events):
        self.data = data
        self.events = events
        self.commits = 0

    def cursor(self, **kwargs):
        return FakeCursor(self.data, self.events)

    def commit(self):
        self.commits += 1
        self.events.append("commit")

    def rollback(self):
        self.events.append("rollback")

    def close(self):
        self.events.append("close")


def row(key, title, keywords, content):
    return {
        "page_key": key, "title": title, "display_name": title,
        "search_keywords": keywords, "summary": "", "content": content,
        "language_code": "EN",
    }


ARTICLES = [
    row("square_reconcile_payments", "Square - Reconcile Payments",
        "Square reconciliation, payment reconciliation", 
        "Reconcile Square payments using the Square Reconciliation page."),
    row("square_connecting_account", "Square - Connecting Your Account",
        "connect Square, Square connection", "Check the Square Control Center."),
    row("square_overview", "Connecting and Using Square",
        "Square payments, Square sync, reconciliation", 
        "Review Square payments and sync status."),
    row("general_email", "General Email", "email, send email", 
        "Send a client email from General Email."),
    row("appointments", "Appointments", "post appointment wrap", 
        "Use the Post Appointment Wrap-Up after the appointment."),
]


def run_case(label, question, mode):
    events = []
    connections = []
    docs = {a["page_key"]: a for a in ARTICLES}

    def connection_factory():
        connection = FakeConn(ARTICLES, events)
        connections.append(connection)
        return connection

    def context_reader(cur, *, page_key, language):
        # Stand-in for the already existing approved-article lookup.
        assert page_key in docs
        a = docs[page_key]
        events.append("load_approved_article")
        return {
            "page_key": a["page_key"], "title": a["title"],
            "language_code": "EN", "article_text": a["content"],
        }

    def reserve(cur, **kwargs):
        assert kwargs["spa_id"] == 1
        assert kwargs["business_unit_id"] == 3
        assert kwargs["actor_user_id"] == 7
        assert kwargs["pricing_id"] == 1
        assert kwargs["feature_key"] == "help_assist"
        assert kwargs["max_input_tokens"] > kwargs["max_output_tokens"]
        events.append("reserve")
        return {"ai_usage_id": 55}

    def submitted(cur, *, ai_usage_id):
        assert ai_usage_id == 55
        events.append("submitted")

    def uncertain(cur, *, ai_usage_id):
        assert ai_usage_id == 55
        events.append("uncertain")

    def settle(cur, **kwargs):
        assert kwargs["ai_usage_id"] == 55
        assert kwargs["input_tokens"] == 350
        events.append("settle")
        if mode == "settle_failure":
            raise RuntimeError("Simulated settlement failure")
        return {"actual_cost_usd": Decimal("0.00019"), "over_reservation": False}

    def provider_call(*, prepared, model):
        assert model == "gpt-6-luna"
        assert "APPROVED HELP ARTICLE" in prepared["input"]
        assert "USER QUESTION:" in prepared["input"]
        # Critical financial safety invariant: both commits before provider.
        assert events.count("commit") == 2, events
        events.append("provider")
        if mode == "provider_failure":
            raise RuntimeError("Simulated provider failure")
        return {
            "answer": "Follow the Square reconciliation Help instructions.",
            "input_tokens": 350, "cached_input_tokens": 0,
            "output_tokens": 70, "provider_request_id": "test-only-id",
        }

    originals = {
        "get_ai_help_article": bundle.get_ai_help_article,
        "reserve_ai_request": engine.reserve_ai_request,
        "mark_ai_request_submitted": engine.mark_ai_request_submitted,
        "mark_ai_request_uncertain": engine.mark_ai_request_uncertain,
        "settle_ai_request": engine.settle_ai_request,
    }
    try:
        bundle.get_ai_help_article = context_reader
        engine.reserve_ai_request = reserve
        engine.mark_ai_request_submitted = submitted
        engine.mark_ai_request_uncertain = uncertain
        engine.settle_ai_request = settle

        if mode == "no_match":
            question = "How do I make an Old Fashioned?"

        caught = None
        result = None
        try:
            result = engine.execute_ai_help(
                connection_factory=connection_factory,
                spa_id=1, business_unit_id=3, actor_user_id=7,
                page_key=None, language="EN", question=question,
                pricing_id=1, model="gpt-6-luna", provider_call=provider_call,
            )
        except Exception as exc:
            caught = exc

        if mode == "ok":
            assert caught is None, repr(caught)
            assert result and result["ai_usage_id"] == 55
            assert result["articles"]
            assert result["articles"][0]["page_key"] == "square_reconcile_payments"
            assert result["actual_cost_usd"] == Decimal("0.00019")
            assert events.index("reserve") < events.index("submitted")
            assert events.index("submitted") < events.index("provider")
            assert events.index("provider") < events.index("settle")
            assert events.count("commit") == 3
        elif mode == "no_match":
            assert caught is not None and "No matching Help articles" in str(caught)
            assert "reserve" not in events and "provider" not in events
            assert "commit" not in events
        else:
            assert isinstance(caught, engine.AIHelpExecutionError), repr(caught)
            assert "provider" in events
            assert "uncertain" in events
            assert events.count("commit") == 3, events
            if mode == "provider_failure":
                assert "settle" not in events
            else:
                assert "settle" in events
        print(f"PASS — {label}")
    finally:
        bundle.get_ai_help_article = originals["get_ai_help_article"]
        engine.reserve_ai_request = originals["reserve_ai_request"]
        engine.mark_ai_request_submitted = originals["mark_ai_request_submitted"]
        engine.mark_ai_request_uncertain = originals["mark_ai_request_uncertain"]
        engine.settle_ai_request = originals["settle_ai_request"]


print("COACH PEACH 2.0 — ISOLATED INTEGRATION CHECKS")
print("Uses in-memory data only; no PostgreSQL or OpenAI calls.\n")

run_case("Universal question retrieves multiple articles and settles cost",
         "How do I reconcile Square payments?", "ok")
run_case("Out-of-scope question stops before spending reservation",
         "How do I make an Old Fashioned?", "no_match")
run_case("Provider failure preserves uncertain spending reservation",
         "How do I reconcile Square payments?", "provider_failure")
run_case("Settlement failure preserves uncertain spending reservation",
         "How do I reconcile Square payments?", "settle_failure")

print("\nSUCCESS — All 4 isolated integration checks passed.")
print("NEXT: Real Knowledge Base and browser testing still required before deployment.")
