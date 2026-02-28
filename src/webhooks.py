"""Webhook dispatch with retry logic."""

import json
import time
import logging
import httpx
from datetime import datetime, timezone
from .database import get_db

logger = logging.getLogger(__name__)

RETRY_DELAYS = [0, 5, 25]  # seconds: immediate, 5s, 25s (exponential-ish)


def fire_webhook(submission_id: str, event: str, data: dict, url: str, integration_id: int):
    """Fire webhook with up to 3 retry attempts. Runs synchronously (call from background task)."""
    payload = {
        "event": event,
        "submission_id": submission_id,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "data": data,
    }

    for attempt in range(1, len(RETRY_DELAYS) + 1):
        if attempt > 1:
            time.sleep(RETRY_DELAYS[attempt - 1])

        status_code = None
        response_body = None
        error = None
        try:
            resp = httpx.post(url, json=payload, timeout=10.0, headers={"Content-Type": "application/json"})
            status_code = resp.status_code
            response_body = resp.text[:2000]
            if 200 <= status_code < 300:
                _log_attempt(submission_id, integration_id, event, url, status_code, attempt, response_body, None)
                return True
        except Exception as e:
            error = str(e)

        _log_attempt(submission_id, integration_id, event, url, status_code, attempt, response_body, error)

    logger.warning(f"Webhook failed after {len(RETRY_DELAYS)} attempts: {event} for {submission_id}")
    return False


def _log_attempt(submission_id, integration_id, event, url, status_code, attempt, response_body, error):
    try:
        conn = get_db()
        conn.execute(
            "INSERT INTO webhook_logs (submission_id, integration_id, event, url, status_code, attempt, response_body, error) VALUES (?,?,?,?,?,?,?,?)",
            (submission_id, integration_id, event, url, status_code, attempt, response_body, error)
        )
        conn.commit()
        conn.close()
    except Exception:
        logger.exception("Failed to log webhook attempt")


def dispatch_webhook(submission_id: str, event: str, data: dict):
    """Resolve webhook URL from submission/integration and fire."""
    from .integrations import get_submission
    sub = get_submission(submission_id)
    if not sub:
        return

    # Per-submission callback_url overrides integration default
    url = sub.get("callback_url")
    integration_id = sub["integration_id"]

    if not url:
        conn = get_db()
        integration = conn.execute("SELECT webhook_url FROM integrations WHERE id=?", (integration_id,)).fetchone()
        conn.close()
        if integration:
            url = integration["webhook_url"]

    if not url:
        return

    fire_webhook(submission_id, event, data, url, integration_id)
