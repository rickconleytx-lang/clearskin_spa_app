"""Write local backup-run metadata atomically; no network operations."""

import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import tempfile


def update_status(path, *, status, icloud="unknown",
                  peachvault="unknown", failure_code=None, now=None):
    if status not in {"running", "success", "failed"}:
        raise ValueError("Invalid run status.")
    if icloud not in {"unknown", "success", "failed"}:
        raise ValueError("Invalid iCloud status.")
    if peachvault not in {"unknown", "success", "failed"}:
        raise ValueError("Invalid PeachVault status.")
    if status == "success" and (icloud, peachvault) != ("success", "success"):
        raise ValueError("Both destinations are required for success.")
    if status == "failed" and not failure_code:
        raise ValueError("Failure code required.")
    if status != "failed" and failure_code is not None:
        raise ValueError("Failure code requires failed status.")

    path = Path(path)
    now = now or datetime.now(timezone.utc)
    if now.tzinfo is None or now.utcoffset() is None:
        raise ValueError("Timestamp requires a timezone.")
    timestamp = now.astimezone(timezone.utc).isoformat()
    previous = {}
    if path.exists():
        previous = json.loads(path.read_text())
        if not isinstance(previous, dict):
            raise ValueError("Invalid previous status.")

    start = timestamp if status == "running" else previous.get("run_started_at")
    if not start:
        raise ValueError("Run start must be recorded first.")

    record = {
        "run_status": status,
        "run_started_at": start,
        "run_finished_at": None if status == "running" else timestamp,
        "last_success_at": (
            timestamp if status == "success"
            else previous.get("last_success_at")
        ),
        "icloud_status": icloud,
        "peachvault_status": peachvault,
        "failure_code": failure_code,
    }
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w", dir=path.parent, prefix=".backup-status-",
            delete=False
        ) as handle:
            temporary = handle.name
            json.dump(record, handle)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
        temporary = None
    finally:
        if temporary is not None:
            os.unlink(temporary)
    return record


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("status", choices=("running", "success", "failed"))
    parser.add_argument("--icloud", default="unknown",
                        choices=("unknown", "success", "failed"))
    parser.add_argument("--peachvault", default="unknown",
                        choices=("unknown", "success", "failed"))
    parser.add_argument("--failure-code")
    args = parser.parse_args()
    path = Path.home() / "PostgresBackups/Logs/current_backup_status.json"
    update_status(
        path, status=args.status, icloud=args.icloud,
        peachvault=args.peachvault, failure_code=args.failure_code,
    )


if __name__ == "__main__":
    main()
