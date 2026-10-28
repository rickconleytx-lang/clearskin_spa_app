"""Coach Peach — approved multi-article Help context.

Read-only. Uses existing approved Help retrieval.
Does not access tenant data, call OpenAI, or spend funds.
"""

from services.psp_ai_help_context import (
    get_ai_help_article,
)
from services.psp_ai_help_search import (
    GENERIC_ACTIONS,
    STOP_WORDS,
    _expand,
    _words,
    search_ai_help_articles,
)

import re


MAX_ARTICLES = 3
MAX_ARTICLE_CHARS = 3000
MAX_CONTEXT_CHARS = 10000


def _focused_excerpt(content, question, limit):
    """Keep an article introduction plus the most relevant nearby section.

    Scans only the already-approved, bounded article text. Never retrieves
    unapproved material or changes the configured per-article token budget.
    """
    if len(content) <= limit:
        return content

    # Retain article context, with the rest dedicated to useful instructions.
    intro_size = min(340, limit // 6)
    focus_size = limit - intro_size - 30
    original = {
        word for word in _words(question)
        if word not in STOP_WORDS and len(word) >= 3
    }
    subjects = original - GENERIC_ACTIONS
    terms = _expand(subjects or original)
    if not terms:
        return content[:limit]

    # Prefer a relevant section heading so we capture the instructions that
    # follow it. A generic overview may repeat topic words many times but
    # omit the actual steps (e.g. Post Appointment Wrap-Up).
    best_heading = None
    for found in re.finditer(r"(?m)^([^\n]{3,120})$", content):
        heading = found.group(1).strip()
        heading_words = _expand(_words(heading))
        coverage = sum(1 for word in (subjects or original) if word in heading_words)
        if coverage == 0:
            continue
        bonus = (1 if re.match(r"(?:how to|step\s*[0-9]+)", heading.casefold()) else 0)
        candidate = (coverage, bonus, -len(heading), -found.start())
        if best_heading is None or candidate > best_heading[0]:
            best_heading = (candidate, found.start())

    # A heading naming two or more requested concepts is strong enough to
    # select directly; otherwise use the bounded window scoring fallback.
    if best_heading and best_heading[0][0] >= min(2, len(subjects or original)):
        start = best_heading[1]
        if start <= intro_size:
            return content[:limit]
        excerpt = content[start:start + focus_size].strip()
        return (content[:intro_size].rstrip() + "\n[Relevant excerpt]\n" + excerpt)[:limit]

    # Distinctive words are more informative than frequently repeated words.
    casefolded = content.casefold()
    counts = {
        term: len(re.findall(r"(?<!\w)" + re.escape(term) + r"(?!\w)", casefolded))
        for term in terms
    }
    weights = {term: 1 + 10 / (1 + counts[term]) for term in terms}
    positions = {0}
    for term in terms:
        for match in list(re.finditer(
            r"(?<!\w)" + re.escape(term) + r"(?!\w)",
            casefolded,
        ))[:80]:
            positions.add(max(0, match.start() - 380))

    def rank(start):
        snippet = casefolded[start:start + focus_size]
        unique_score = sum(
            weight for term, weight in weights.items()
            if re.search(r"(?<!\w)" + re.escape(term) + r"(?!\w)", snippet)
        )
        # Reward sections that describe concrete steps, not just an overview.
        steps = min(3, len(re.findall(r"(?:step\s*\d|how to|click |select )", snippet)))
        return unique_score + steps * 0.25

    start = max(positions, key=lambda x: (rank(x), -x))
    if start <= intro_size:
        return content[:limit]

    # Start at a paragraph boundary when near enough, retaining context.
    boundary = content.rfind("\n", max(0, start - 160), start + 1)
    if boundary >= 0:
        start = boundary + 1
    excerpt = content[start:start + focus_size].strip()
    return (content[:intro_size].rstrip() + "\n[Relevant excerpt]\n" + excerpt)[:limit]


def get_ai_help_bundle(
    cur,
    *,
    question,
    language,
    current_page_key=None,
):
    """Build a bounded collection of relevant Help articles.

    Caller provides a RealDictCursor and owns authorization,
    transaction handling, and AI spending controls.
    """

    matches = search_ai_help_articles(
        cur,
        question=question,
        language=language,
        current_page_key=current_page_key,
        limit=MAX_ARTICLES,
    )

    articles = []
    context_parts = []
    remaining = MAX_CONTEXT_CHARS

    for match in matches:
        article = get_ai_help_article(
            cur,
            page_key=match["page_key"],
            language=language,
        )

        content = str(
            article.get("article_text") or ""
        ).strip()

        title = str(
            article.get("title") or ""
        ).strip()

        if not title or not content:
            continue

        heading = (
            f"APPROVED HELP ARTICLE\n"
            f"Title: {title}\n"
            f"Page Key: {article['page_key']}\n"
            f"Content:\n"
        )

        available = min(
            MAX_ARTICLE_CHARS,
            remaining - len(heading) - 40,
        )

        if available <= 0:
            break

        excerpt = _focused_excerpt(content, question, available)

        block = (
            heading
            + excerpt
            + "\nEND HELP ARTICLE"
        )

        if len(block) > remaining:
            break

        context_parts.append(block)
        remaining -= len(block)

        articles.append({
            "page_key": article["page_key"],
            "title": title,
            "language_code": article["language_code"],
            "relevance_score": match["relevance_score"],
        })

    return {
        "articles": articles,
        "context_text": "\n\n".join(context_parts),
    }