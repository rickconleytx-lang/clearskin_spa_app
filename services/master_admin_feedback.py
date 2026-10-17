"""Master Admin feedback access. The caller owns the transaction."""

import hashlib
import json

FEEDBACK_TYPES = {
    "Bug", "UX Issue", "Feature Request",
    "Navigation Issue", "General Feedback",
}

_COLUMNS = """
    uf.feedback_id, uf.spa_id, s.spa_name,
    uf.user_name, uf.user_email, uf.page_name,
    uf.feedback_type, uf.severity, uf.expected_behavior,
    uf.message, uf.created_at, uf.is_resolved,
    uf.action_taken_note
"""


def feedback_record(row):
    keys = (
        "feedback_id", "spa_id", "business_name",
        "user_name", "user_email", "page_name",
        "feedback_type", "severity", "expected_behavior",
        "message", "created_at", "is_resolved",
        "action_taken_note",
    )
    result = dict(zip(keys, row))
    # Preserve the original timezone-free wall-clock value.
    if result["created_at"] is not None:
        result["created_at"] = result["created_at"].isoformat()
    result["is_resolved"] = bool(result["is_resolved"])
    revision = json.dumps(
        result, sort_keys=True, ensure_ascii=False,
        separators=(",", ":"),
    )
    result["revision"] = hashlib.sha256(
        revision.encode("utf-8")
    ).hexdigest()
    return result


def list_feedback(cur, *, status="open", feedback_type="",
                  limit=50, offset=0):
    if status not in {"open", "resolved", "all"}:
        raise ValueError("Invalid feedback status.")
    if feedback_type and feedback_type not in FEEDBACK_TYPES:
        raise ValueError("Invalid feedback type.")
    if type(limit) is not int or not 1 <= limit <= 100:
        raise ValueError("Invalid page size.")
    if type(offset) is not int or not 0 <= offset <= 1000000:
        raise ValueError("Invalid page offset.")

    clauses = []
    params = []
    if status == "open":
        clauses.append("uf.is_resolved IS NOT TRUE")
    elif status == "resolved":
        clauses.append("uf.is_resolved IS TRUE")
    if feedback_type:
        clauses.append("uf.feedback_type = %s")
        params.append(feedback_type)
    where = " WHERE " + " AND ".join(clauses) if clauses else ""

    cur.execute("""
        SELECT COUNT(*) FROM user_feedback
        WHERE is_resolved IS NOT TRUE
    """)
    open_count = cur.fetchone()[0]

    cur.execute(
        "SELECT COUNT(*) FROM user_feedback uf" + where,
        tuple(params),
    )
    total_count = cur.fetchone()[0]

    cur.execute(
        "SELECT " + _COLUMNS + """
        FROM user_feedback uf
        LEFT JOIN spas s ON s.spa_id = uf.spa_id
        """ + where + """
        ORDER BY uf.created_at DESC NULLS LAST, uf.feedback_id DESC
        LIMIT %s OFFSET %s
        """,
        tuple(params + [limit, offset]),
    )
    items = [feedback_record(row) for row in cur.fetchall()]
    return {
        "items": items,
        "open_count": open_count,
        "total_count": total_count,
        "limit": limit,
        "offset": offset,
        "has_more": offset + len(items) < total_count,
    }


def get_feedback(cur, *, feedback_id):
    if type(feedback_id) is not int or feedback_id <= 0:
        raise ValueError("Invalid feedback ID.")
    cur.execute(
        "SELECT " + _COLUMNS + """
        FROM user_feedback uf
        LEFT JOIN spas s ON s.spa_id = uf.spa_id
        WHERE uf.feedback_id = %s
        """,
        (feedback_id,),
    )
    row = cur.fetchone()
    return feedback_record(row) if row is not None else None


class FeedbackConflictError(ValueError):
    pass


def update_feedback(cur, *, feedback_id, actor_user_id,
                    revision, is_resolved, action_taken_note,
                    audit):
    """Update a locked record and its audit entry; caller commits."""
    if type(feedback_id) is not int or feedback_id <= 0:
        raise ValueError("Invalid feedback ID.")
    if type(actor_user_id) is not int or actor_user_id <= 0:
        raise ValueError("Invalid actor.")
    if type(is_resolved) is not bool:
        raise ValueError("Resolved must be a boolean.")
    if not isinstance(action_taken_note, str):
        raise ValueError("Action note must be text.")
    if len(action_taken_note) > 10000:
        raise ValueError("Action note is too long.")
    if (
        not isinstance(revision, str)
        or len(revision) != 64
        or any(c not in "0123456789abcdef" for c in revision)
    ):
        raise ValueError("Invalid revision.")

    cur.execute(
        "SELECT " + _COLUMNS + """
        FROM user_feedback uf
        LEFT JOIN spas s ON s.spa_id = uf.spa_id
        WHERE uf.feedback_id = %s
        FOR UPDATE OF uf
        """,
        (feedback_id,),
    )
    row = cur.fetchone()
    if row is None:
        return None
    previous = feedback_record(row)
    if previous["revision"] != revision:
        raise FeedbackConflictError(
            "Feedback changed. Refresh before saving."
        )

    note = action_taken_note.strip()
    if (
        previous["is_resolved"] == is_resolved
        and (previous["action_taken_note"] or "") == note
    ):
        return {"changed": False, "item": previous}

    cur.execute("""
        UPDATE user_feedback
        SET is_resolved = %s, action_taken_note = %s,
            action_taken_by = %s, action_taken_at = CURRENT_TIMESTAMP
        WHERE feedback_id = %s
    """, (is_resolved, note, actor_user_id, feedback_id))

    audit(
        cur,
        spa_id=previous["spa_id"],
        user_id=actor_user_id,
        action_type="master_admin_feedback_updated",
        table_name="user_feedback",
        record_id=feedback_id,
        old_value="resolved" if previous["is_resolved"] else "open",
        new_value="resolved" if is_resolved else "open",
        notes="Feedback status or action note updated through Master Admin API.",
    )
    return {
        "changed": True,
        "item": get_feedback(cur, feedback_id=feedback_id),
    }
