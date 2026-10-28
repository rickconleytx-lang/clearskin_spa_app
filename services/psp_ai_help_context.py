"""Coach Peach Assist — approved PSP Help article context.

Read-only. No provider calls or business-record access.
Caller owns authorization and database connection.
"""

import re
from html.parser import HTMLParser


# The multi-article bundle chooses short, question-focused excerpts from
# this approved source text. Keep enough text to include later sections;
# the bundle independently limits what is sent to the AI provider.
MAX_SEARCHABLE_ARTICLE_CHARS = 50000


class AIHelpContextError(ValueError):
    pass


class _HelpTextParser(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.parts = []
        self.hidden = 0

    def handle_starttag(self, tag, attrs):
        if tag in ("script", "style", "noscript"):
            self.hidden += 1
        elif tag in ("p", "br", "li", "div", "h1", "h2", "h3"):
            self.parts.append("\n")

    def handle_endtag(self, tag):
        if tag in ("script", "style", "noscript"):
            self.hidden = max(0, self.hidden - 1)
        elif tag in ("p", "li", "div", "h1", "h2", "h3"):
            self.parts.append("\n")

    def handle_data(self, data):
        if not self.hidden:
            self.parts.append(data)


def get_ai_help_article(cur, *, page_key, language):
    """Fetch an active global PSP Help article, never tenant data."""

    if not isinstance(page_key, str):
        raise AIHelpContextError("Invalid Help article.")

    page_key = page_key.strip()

    if not page_key or len(page_key) > 120:
        raise AIHelpContextError("Invalid Help article.")

    language = "ES" if language == "ES" else "EN"

    cur.execute("""
        SELECT page_key, title, content, language_code
        FROM help_pages
        WHERE page_key = %s
          AND spa_id IS NULL
          AND page_key <> 'sms_email_terms'
          AND is_active = TRUE
          AND language_code IN (%s, 'EN')
        ORDER BY
          CASE WHEN language_code = %s THEN 0 ELSE 1 END,
          help_page_id DESC
        LIMIT 1
    """, (page_key, language, language))

    row = cur.fetchone()

    if not row:
        raise AIHelpContextError("Help article not found.")

    parser = _HelpTextParser()
    parser.feed(str(row["content"] or ""))

    text = "".join(parser.parts)
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n\s*\n+", "\n", text).strip()

    return {
        "page_key": row["page_key"],
        "title": str(row["title"] or "")[:200],
        "language_code": row["language_code"],
        "article_text": text[:MAX_SEARCHABLE_ARTICLE_CHARS],
    }
