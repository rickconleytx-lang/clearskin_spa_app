"""Build and submit signed backup metadata; never execute backups."""

from datetime import datetime, timezone
import json
from pathlib import Path
from uuid import uuid4

from services.backup_monitoring import validate_backup_report


def build_backup_report(status_path, *, now=None, report_uuid=None):
    now = now or datetime.now(timezone.utc)
    path = Path(status_path)
    with path.open("rb") as handle:
        raw = handle.read(8193)
    if len(raw) > 8192:
        raise ValueError("Status file is too large.")
    record = json.loads(raw)
    if not isinstance(record, dict):
        raise ValueError("Invalid status file.")

    # The validator rejects unexpected keys, including logs or credentials.
    payload = dict(record)
    payload["report_uuid"] = str(report_uuid or uuid4())
    payload["reported_at"] = now.isoformat()
    validate_backup_report(payload, now=now)
    return json.dumps(
        payload, sort_keys=True, separators=(",", ":"), allow_nan=False
    ).encode("utf-8")


REPORT_ENDPOINT = "https://app.peachsuitepro.com/api/backup-monitor/report"


def load_reporting_config(path):
    import os
    import re
    import stat

    descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
    with os.fdopen(descriptor, "rb") as handle:
        metadata = os.fstat(handle.fileno())
        if (
            not stat.S_ISREG(metadata.st_mode)
            or metadata.st_uid != os.getuid()
            or metadata.st_mode & 0o077
        ):
            raise ValueError("Reporting configuration must be private and user-owned.")
        raw = handle.read(4097)
    if len(raw) > 4096:
        raise ValueError("Reporting configuration is too large.")
    config = json.loads(raw)
    if (
        not isinstance(config, dict)
        or set(config) != {"enabled", "endpoint", "secret"}
        or type(config["enabled"]) is not bool
        or config["endpoint"] != REPORT_ENDPOINT
    ):
        raise ValueError("Invalid reporting configuration.")
    if not isinstance(config["secret"], str) or not re.fullmatch(
        r"[0-9a-f]{64}", config["secret"]
    ):
        raise ValueError("Invalid reporting credential.")
    return config


def send_backup_report(body, *, config, now=None, opener=None):
    import hashlib
    import hmac
    from urllib.request import (
        HTTPRedirectHandler, Request, build_opener,
    )

    if config.get("enabled") is not True:
        return "disabled"
    if config.get("endpoint") != REPORT_ENDPOINT:
        raise ValueError("Unexpected reporting endpoint.")
    now = now or datetime.now(timezone.utc)
    validate_backup_report(json.loads(body), now=now)
    if not isinstance(body, bytes) or not 1 <= len(body) <= 8192:
        raise ValueError("Invalid report size.")

    timestamp = str(int(now.timestamp()))
    signature = hmac.new(
        config["secret"].encode("utf-8"),
        timestamp.encode("ascii") + b"." + body,
        hashlib.sha256,
    ).hexdigest()

    class NoRedirect(HTTPRedirectHandler):
        def redirect_request(self, req, fp, code, msg, headers, newurl):
            return None

    transport = opener or build_opener(NoRedirect())
    request = Request(
        REPORT_ENDPOINT, data=body, method="POST",
        headers={
            "Content-Type": "application/json",
            "X-Backup-Timestamp": timestamp,
            "X-Backup-Signature": signature,
        },
    )
    with transport.open(request, timeout=15) as response:
        if response.status != 200:
            raise ValueError("Report was not accepted.")
        raw = response.read(1025)
    if len(raw) > 1024:
        raise ValueError("Unexpected reporting response.")
    result = json.loads(raw)
    if (
        not isinstance(result, dict)
        or result.get("success") is not True
        or result.get("status") not in {"accepted", "duplicate"}
    ):
        raise ValueError("Report was not acknowledged.")
    return result["status"]


def main():
    config_path = Path.home() / ".config/peach-suite-pro/backup-reporting.json"
    try:
        config = load_reporting_config(config_path)
        if not config["enabled"]:
            print("Backup reporting is disabled.")
            return 0
        status_path = Path.home() / "PostgresBackups/Logs/current_backup_status.json"
        body = build_backup_report(status_path)
        result = send_backup_report(body, config=config)
        print("Backup report: " + result)
        return 0
    except Exception as exc:
        # Never print exception text, headers, configuration, or credentials.
        print("Backup reporting failed: " + type(exc).__name__)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
