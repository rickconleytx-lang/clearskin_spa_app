"""Deduplicated Master Admin attention counts."""


def calculate_attention(*, alerts, backup_problems, health_problems):
    """Inputs contain only this user's eligible alerts and active problems.

    Database selection applies the review cutoff and seven-day alert window.
    Active problems remain eligible regardless of acknowledgement.
    Each problem supplies explicitly linked alert IDs to avoid double counting.
    """
    problems = {}
    for kind, records in (
        ("backup", backup_problems),
        ("health", health_problems),
    ):
        for record in records:
            key = (kind, str(record["key"]))
            problem = problems.setdefault(key, {
                "kind": kind,
                "key": str(record["key"]),
                "linked_alert_ids": set(),
            })
            problem["linked_alert_ids"].update(
                int(value) for value in record.get("linked_alert_ids", [])
            )

    covered_alert_ids = set()
    for problem in problems.values():
        covered_alert_ids.update(problem["linked_alert_ids"])

    alert_ids = {
        int(record["alert_event_id"])
        for record in alerts
        if str(record.get("severity") or "").upper() in {"ERROR", "ALERT"}
        and not str(record.get("source_related_type") or "").lower().endswith("_test")
    }
    standalone_alert_ids = alert_ids - covered_alert_ids
    backup_count = sum(p["kind"] == "backup" for p in problems.values())
    health_count = sum(p["kind"] == "health" for p in problems.values())

    return {
        "total_count": len(standalone_alert_ids) + backup_count + health_count,
        "unacknowledged_alert_count": len(standalone_alert_ids),
        "active_backup_count": backup_count,
        "critical_health_count": health_count,
        "covered_alert_count": len(alert_ids & covered_alert_ids),
    }


def read_attention_summary(cur, *, user_id, health_cards):
    """Read attention using a RealDictCursor; caller owns transaction."""
    if type(user_id) is not int or user_id <= 0:
        raise ValueError("Invalid Master Admin user.")

    cur.execute("""
        SELECT acknowledged_at
        FROM master_admin_acknowledgements
        WHERE user_id = %s AND acknowledgement_scope = 'alerts'
    """, (user_id,))
    acknowledgement = cur.fetchone()
    acknowledged_at = (
        acknowledgement["acknowledged_at"] if acknowledgement else None
    )

    cur.execute("""
        SELECT e.master_admin_alert_event_id AS alert_event_id,
               e.severity, e.source_category, e.source_related_type
        FROM master_admin_alert_events e
        WHERE e.master_admin_user_id = %s
          AND e.severity IN ('ERROR', 'ALERT')
          AND e.reserved_at >= NOW() - INTERVAL '7 days'
          AND e.reserved_at > COALESCE(%s, '-infinity'::timestamptz)
          AND RIGHT(LOWER(COALESCE(e.source_related_type, '')), 5) <> '_test'
          AND NOT EXISTS (
              SELECT 1
              FROM master_admin_backup_notifications n
              JOIN master_admin_backup_incidents i
                ON i.backup_incident_id = n.backup_incident_id
              JOIN master_admin_backup_sources s
                ON s.source_key = i.source_key
              WHERE n.alert_event_id = e.master_admin_alert_event_id
                AND s.enabled = FALSE
          )
    """, (user_id, acknowledged_at))
    alerts = [dict(row) for row in cur.fetchall()]

    cur.execute("""
        SELECT i.backup_incident_id, i.source_key, n.alert_event_id
        FROM master_admin_backup_incidents i
        JOIN master_admin_backup_sources s ON s.source_key = i.source_key
        LEFT JOIN master_admin_backup_notifications n
          ON n.backup_incident_id = i.backup_incident_id
         AND n.transition = 'failure'
        WHERE i.resolved_at IS NULL AND s.enabled = TRUE
    """)
    backups = [
        {
            "key": str(row["backup_incident_id"]),
            "source_key": row["source_key"],
            "linked_alert_ids": (
                [row["alert_event_id"]] if row["alert_event_id"] else []
            ),
        }
        for row in cur.fetchall()
    ]

    # Security/MFA/password events are represented by alerts, not counted
    # again as operational health cards. Backup has its own incident count.
    operational_keys = {
        "scheduler", "database", "square", "mailgun",
        "telnyx", "peachweb", "peachbook",
    }
    health = []
    for card in health_cards:
        key = card["key"]
        if key not in operational_keys or card["status"] != "red":
            continue
        linked = []
        for event in alerts:
            category = str(event["source_category"] or "").upper()
            related = str(event["source_related_type"] or "").lower()
            matches = (
                (key == "scheduler" and category == "SCHEDULER")
                or (key == "database" and category == "DATABASE"
                    and related == "database_heartbeat")
                or (key not in {"scheduler", "database"}
                    and category == "SYSTEM" and related == key + "_health")
            )
            if matches:
                linked.append(event["alert_event_id"])
        health.append({
            "key": key,
            "label": card["label"],
            "linked_alert_ids": linked,
        })

    result = calculate_attention(
        alerts=alerts, backup_problems=backups, health_problems=health
    )
    cur.execute("SELECT NOW() AS checked_at")
    checked_at = cur.fetchone()["checked_at"]
    result.update({
        "checked_at": checked_at.isoformat(),
        "acknowledged_at": (
            acknowledged_at.isoformat() if acknowledged_at else None
        ),
        "alert_window_days": 7,
        "active_backup_sources": sorted({b["source_key"] for b in backups}),
        "critical_health_keys": sorted({h["key"] for h in health}),
    })
    return result
