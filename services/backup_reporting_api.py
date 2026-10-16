"""Machine-authenticated backup status ingestion; no execution controls."""

import json
import os
import re
from datetime import datetime, timezone
from flask import Blueprint, jsonify, request

from services.backup_monitoring import (
    BackupReportValidationError,
    process_backup_report,
    verify_backup_report_signature,
)


def _unique_json_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("Duplicate JSON field.")
        result[key] = value
    return result


def register_backup_reporting_api(app, *, get_connection, no_store):
    blueprint = Blueprint("backup_reporting", __name__)

    def response(payload, status):
        return no_store((jsonify(payload), status))

    @blueprint.route("/api/backup-monitor/report", methods=["POST"])
    def report():
        enabled = os.environ.get("ENABLE_BACKUP_REPORTING", "").lower()
        if enabled not in {"1", "true", "yes", "on"}:
            return response({"success": False, "error": "not_available"}, 404)

        secret = os.environ.get("BACKUP_REPORT_SECRET", "")
        source = os.environ.get("BACKUP_REPORT_SOURCE", "")
        if len(secret) < 32 or not re.fullmatch(r"[a-zA-Z0-9_-]{1,64}", source):
            return response({"success": False, "error": "not_configured"}, 503)

        if not request.is_secure and request.remote_addr not in {"127.0.0.1", "::1"}:
            return response({"success": False, "error": "https_required"}, 403)
        if request.content_length is not None and request.content_length > 8192:
            return response({"success": False, "error": "report_too_large"}, 413)
        if request.mimetype != "application/json":
            return response({"success": False, "error": "json_required"}, 415)

        body = request.stream.read(8193)
        if len(body) > 8192:
            return response({"success": False, "error": "report_too_large"}, 413)
        now = datetime.now(timezone.utc)
        if not verify_backup_report_signature(
            secret=secret,
            timestamp=request.headers.get("X-Backup-Timestamp"),
            signature=request.headers.get("X-Backup-Signature"),
            body=body,
            now=now,
        ):
            return response({"success": False, "error": "authentication_failed"}, 401)

        try:
            data = json.loads(body, object_pairs_hook=_unique_json_object)
        except (ValueError, UnicodeDecodeError):
            return response({"success": False, "error": "invalid_report"}, 400)

        conn = None
        cur = None
        try:
            conn = get_connection()
            conn.autocommit = False
            cur = conn.cursor()
            result = process_backup_report(
                cur, source_key=source, data=data, now=now
            )
            conn.commit()
            return response(
                {"success": True, "status": result["status"]}, 200
            )
        except BackupReportValidationError:
            if conn is not None:
                conn.rollback()
            return response({"success": False, "error": "invalid_report"}, 400)
        except Exception:
            if conn is not None:
                conn.rollback()
            # Do not log request bodies, headers, credentials, or DB errors.
            app.logger.error("Backup report persistence failed.")
            return response({"success": False, "error": "temporarily_unavailable"}, 503)
        finally:
            if cur is not None:
                cur.close()
            if conn is not None:
                conn.close()

    app.register_blueprint(blueprint)
