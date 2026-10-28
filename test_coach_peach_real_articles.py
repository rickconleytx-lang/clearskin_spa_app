"""Coach Peach 2.0 — validate the actual search + loader + bundle with a CSV export.

Read only. NO PostgreSQL, OpenAI, payment calls, changes, or app startup.
Save this file alongside app.py, then use VS Code's Run Python File button.
The original pgAdmin export may be in ~/Downloads or in the project folder.
"""

import csv
from pathlib import Path

from services.psp_ai_help_context import get_ai_help_article
from services.psp_ai_help_bundle import get_ai_help_bundle
from services.psp_ai_help_search import search_ai_help_articles


REQUIRED_COLUMNS = {
    "page_key", "title", "display_name", "summary",
    "search_keywords", "content", "language_code",
}


def find_export():
    here = Path(__file__).resolve().parent
    search_folders = [here, Path.home() / "Downloads"]
    candidates = []
    for folder in search_folders:
        for pattern in ("coach_peach_help_test*.csv",):
            candidates.extend(folder.glob(pattern))
    for path in sorted(set(candidates), key=lambda p: p.stat().st_mtime, reverse=True):
        try:
            with path.open("r", encoding="utf-8-sig", newline="") as f:
                reader = csv.DictReader(f)
                if REQUIRED_COLUMNS <= set(reader.fieldnames or []):
                    rows = list(reader)
                    if rows:
                        return path, rows
        except (OSError, UnicodeError, csv.Error):
            pass
    raise AssertionError(
        "Can't find the article CSV. Copy coach_peach_help_test(1).csv "
        "from Downloads into the project folder beside this test file."
    )


class CsvCursor:
    """Tiny read-only stand-in for the two SELECT queries the code uses."""

    def __init__(self, rows):
        self.rows = rows
        self.result_rows = []
        self.queries = []

    def execute(self, sql, params):
        self.queries.append((sql, params))
        # This is intentionally a fake cursor: it verifies the SQL guards
        # exist and reproduces the requested language/page-key selection.
        normalized = " ".join(sql.casefold().split())
        assert "from help_pages" in normalized
        assert "spa_id is null" in normalized
        assert "is_active = true" in normalized
        assert "page_key <> 'sms_email_terms'" in normalized
        assert "language_code in" in normalized
        if "with ranked_articles as" in normalized:
            language = params[0]
            assert params == (language, language)
            keys = {}
            for row in self.rows:
                if row["language_code"] not in {language, "EN"}:
                    continue
                key = row["page_key"]
                if key not in keys or (row["language_code"] == language and keys[key]["language_code"] != language):
                    keys[key] = row
            self.result_rows = [keys[k] for k in sorted(keys)][:200]
        elif "select page_key, title, content, language_code" in normalized:
            page_key, language, repeated = params
            assert repeated == language
            matches = [r for r in self.rows if r["page_key"] == page_key and r["language_code"] in {language, "EN"}]
            matches.sort(key=lambda r: (r["language_code"] != language,))
            self.result_rows = matches[:1]
        else:
            raise AssertionError("Unexpected query in this read-only test")

    def fetchall(self):
        return list(self.result_rows)

    def fetchone(self):
        return self.result_rows[0] if self.result_rows else None


def check(condition, message):
    if not condition:
        raise AssertionError(message)
    print("PASS —", message)


def main():
    print("COACH PEACH 2.0 — REAL ARTICLE PIPELINE CHECK")
    print("CSV only. No database, OpenAI, spending, or file modifications.\n")
    path, rows = find_export()
    print(f"Loaded {len(rows)} rows from {path.name}\n")
    check(len(rows) >= 90, "Knowledge Base export contains at least 90 English articles")
    cur = CsvCursor(rows)

    questions = (
        ("How do I reconcile Square payments?", "square_reconcile_payments"),
        ("How do I send an email?", "general_email"),
        ("Where do I review my Square connection?", "square_connecting_account"),
        ("How do I complete the post appointment wrap up?", "appointments"),
    )
    for q, expected in questions:
        results = search_ai_help_articles(cur, question=q, language="EN", limit=3)
        check(bool(results) and results[0]["page_key"] == expected,
              f"'{q}' ranks {expected} first")

    no_match = search_ai_help_articles(
        cur, question="How do I make an Old Fashioned?", language="EN", limit=3
    )
    check(not no_match, "Unrelated cocktail question produces no Help articles")

    long_article = get_ai_help_article(cur, page_key="email_templates", language="EN")
    check(len(long_article["article_text"]) > 10000,
          "Updated loader retains approved content beyond 10,000 characters")
    check(len(long_article["article_text"]) <= 50000,
          "Loader keeps its 50,000-character safety ceiling")

    appointment = get_ai_help_bundle(
        cur,
        question="How do I complete the post appointment wrap up?",
        language="EN",
        current_page_key=None,
    )
    check(bool(appointment["articles"]) and appointment["articles"][0]["page_key"] == "appointments",
          "Appointment question selects the correct approved article")
    check("Save Wrap-Up" in appointment["context_text"],
          "Focused excerpt includes the actual Save Wrap-Up instructions")
    check(len(appointment["context_text"]) <= 10000 and len(appointment["articles"]) <= 3,
          "Bundled AI context remains within 10,000 characters and three articles")

    general_email = get_ai_help_bundle(
        cur, question="How do I send an email?", language="EN"
    )
    check(bool(general_email["articles"]) and general_email["articles"][0]["page_key"] == "general_email",
          "Email question bundles General Email first")

    # The production English-only CSV also exercises the fallback path.
    spanish = get_ai_help_article(cur, page_key="appointments", language="ES")
    check(spanish["language_code"] == "EN",
          "Spanish request falls back to approved English article in an English-only export")

    print("\nSUCCESS — All 13 real-article pipeline checks passed.")
    print("NEXT: Browser/API checks with local configuration, then controlled rollout review.")


if __name__ == "__main__":
    main()
