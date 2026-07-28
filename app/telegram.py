from __future__ import annotations

import logging

import httpx

log = logging.getLogger(__name__)


def send(settings, message: str) -> bool:
    """Send one Telegram message without leaking the bot token in logs.

    A failed delivery returns False so the caller can leave the alert pending
    and retry it on the next run.
    """
    token = (settings.telegram_token or "").strip()
    chat_id = (settings.telegram_chat_id or "").strip()
    if not token or not chat_id:
        log.info("Telegram not configured; skipping alert delivery")
        return False

    url = f"https://api.telegram.org/bot{token}/sendMessage"
    try:
        response = httpx.post(
            url,
            json={"chat_id": chat_id, "text": message},
            timeout=15,
        )
        if response.is_error:
            # Telegram's JSON description (for example, "chat not found") is
            # much more useful than only exposing HTTP 400.
            log.warning(
                "Telegram delivery failed: status=%s body=%s",
                response.status_code,
                response.text[:1000],
            )
            return False
        return True
    except httpx.HTTPError as exc:  # pragma: no cover - network only
        log.warning("Telegram delivery failed: %s", exc)
        return False
