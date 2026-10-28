"""Coach Peach — approved Knowledge Base article discovery.

Read-only; never accesses tenant records or calls an AI provider.
Caller owns authenticated identity, database transaction and spending policy.
"""

import re
from html.parser import HTMLParser


STOP_WORDS = {
    "a", "an", "and", "are", "can", "do", "does", "for", "from", "get",
    "how", "i", "in", "is", "my", "of", "on", "the", "to", "what",
    "where", "with", "you", "your", "it", "this", "that", "please",
    "como", "con", "de", "del", "el", "en", "la", "las", "los", "para",
    "por", "que", "una", "uno", "un", "y", "mi", "mis", "puedo",
}

# Common verbs do not, by themselves, establish what product topic is relevant.
# They still contribute to ranking once a topic match has been established.
GENERIC_ACTIONS = {
    "add", "complete", "create", "enter", "find", "help", "make", "open",
    "record", "review", "see", "send", "set", "show", "use", "view",
    "want", "need", "up", "start", "go", "change", "manage", "new",
}

# Explicit, small synonym groups keep queries like "send emails" and
# "Square reconciliation" usable without an external search/AI call.
SYNONYM_GROUPS = (
    {"reconcile", "reconciles", "reconciled", "reconciling", "reconciliation"},
    {"payment", "payments"},
    {"email", "emails", "correo", "correos"},
    {"send", "sending", "sent"},
    {"connect", "connected", "connecting", "connection"},
    {"reconnect", "reconnecting", "reconnected"},
    {"appointment", "appointments"},
    {"template", "templates"},
    {"message", "messages", "messaging"},
    {"text", "texts", "sms"},
    {"wrap", "wrapup"},
    {"sale", "sales"},
    {"expense", "expenses"},
    {"report", "reports"},
    {"event", "events"},
)

# A direct "send email" question is better answered by the general email
# workflow than by templates or sent-history articles. Specialty articles are
# preferred when the customer explicitly asks for that specialty.
MIN_RELEVANCE_SCORE = 20

SPECIALTY_TITLE_TERMS = {
    "template", "templates", "history", "faq", "troubleshooting",
    "automation", "reminders",
}


def _words(value):
    """Unicode words without punctuation; also tokenizes underscore page keys."""
    return set(re.findall(r"[^\W_]+", str(value or "").casefold(), re.UNICODE))


def _expand(words):
    expanded = set(words)
    for group in SYNONYM_GROUPS:
        if expanded & group:
            expanded.update(group)
    return expanded


def _question_terms(question):
    words = {
        word for word in _words(question)
        if word not in STOP_WORDS and (len(word) >= 3 or word in {"ai", "pos"})
    }
    return _expand(words)


class _VisibleText(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.parts = []
        self.hidden = 0

    def handle_starttag(self, tag, attrs):
        if tag in {"script", "style", "noscript"}:
            self.hidden += 1

    def handle_endtag(self, tag):
        if tag in {"script", "style", "noscript"}:
            self.hidden = max(0, self.hidden - 1)

    def handle_data(self, data):
        if not self.hidden:
            self.parts.append(data)


def _article_words(row, field):
    raw = str(row.get(field) or "")
    if field != "content":
        return _words(raw)
    parser = _VisibleText()
    parser.feed(raw[:18000])
    return _words(" ".join(parser.parts))


def search_ai_help_articles(
    cur, *, question, language, current_page_key=None, limit=4,
):
    """Search approved global articles and return bounded metadata references.

    Requires a psycopg2 RealDictCursor; caller owns authorization and transactions.
    No tenant content is returned; selected article text is fetched separately.
    """
    if not isinstance(question, str):
        raise ValueError("Invalid Help question.")

    question = " ".join(question.split())
    if not 3 <= len(question) <= 800:
        raise ValueError("Invalid Help question length.")
    if type(limit) is not int or not 1 <= limit <= 5:
        raise ValueError("Invalid article search limit.")

    language = "ES" if language == "ES" else "EN"
    original = {
        w for w in _words(question)
        if w not in STOP_WORDS and (len(w) >= 3 or w in {"ai", "pos"})
    }
    terms = _expand(original)
    subject_words = original - GENERIC_ACTIONS
    if not subject_words:
        subject_words = original
    subject_terms = _expand(subject_words)
    if not terms:
        return []

    # The SQL gate is mandatory: only current, active, globally approved
    # articles, language preferred with EN fallback, excluding the restricted
    # compliance article. At PSP's current knowledge-base scale, 200 is ample.
    cur.execute(
        """
        WITH ranked_articles AS (
            SELECT page_key, title, display_name, summary, search_keywords,
                   content, language_code,
                   ROW_NUMBER() OVER (
                       PARTITION BY page_key
                       ORDER BY CASE WHEN language_code = %s THEN 0
                                     WHEN language_code = 'EN' THEN 1
                                     ELSE 2 END,
                                help_page_id DESC
                   ) AS language_rank
            FROM help_pages
            WHERE spa_id IS NULL
              AND is_active = TRUE
              AND page_key <> 'sms_email_terms'
              AND language_code IN (%s, 'EN')
        )
        SELECT page_key, title, display_name, summary, search_keywords,
               content, language_code
        FROM ranked_articles
        WHERE language_rank = 1
        ORDER BY page_key
        LIMIT 200
        """,
        (language, language),
    )

    weights = {
        "page_key": 10,
        "title": 9,
        "display_name": 7,
        "search_keywords": 6,
        "summary": 3,
        "content": 1,
    }
    matches = []
    for row in cur.fetchall():
        fields = {name: _article_words(row, name) for name in weights}
        metadata = set().union(*(fields[name] for name in weights if name != "content"))

        # Prevent a generic occurrence in a long article body from making
        # an otherwise unrelated topic eligible for AI context.
        matched_subjects = subject_terms & metadata
        if not matched_subjects:
            continue

        score = sum(len(terms & words) * weights[name] for name, words in fields.items())
        score += 4 * len(matched_subjects)

        title_words = fields["title"] | fields["display_name"]
        specialty = SPECIALTY_TITLE_TERMS & title_words
        if specialty and not (specialty & terms):
            score -= 26

        # Sending a new email is a different task from viewing delivery
        # history or editing templates. General Email is the documented
        # creation-and-send workflow, even though its metadata is sparse.
        if (
            {"email", "send"} <= terms
            and "template" not in original
            and "history" not in original
            and row["page_key"] == "general_email"
        ):
            score += 15

        # Current article is an optional hint, never an automatic match.
        if current_page_key and row["page_key"] == current_page_key:
            score += 2
        if score < MIN_RELEVANCE_SCORE:
            continue

        matches.append({
            "page_key": row["page_key"],
            "title": row.get("title") or row.get("display_name") or row["page_key"],
            "language_code": row["language_code"],
            "relevance_score": score,
        })

    matches.sort(key=lambda item: (
        -item["relevance_score"],
        str(item["title"]).casefold(),
        item["page_key"],
    ))
    return matches[:limit]
