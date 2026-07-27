from __future__ import annotations

import logging

import httpx

log = logging.getLogger(__name__)


def send(settings, message: str) -> bool:
    if not settings.telegram_token or not settings.telegram_chat_id:
        log.info("Telegram not configured; skipping alert delivery")
        return False
    url = f"https://api.telegram.org/bot{settings.telegram_token}/sendMessage"
    try:
        response = httpx.post(url, json={"chat_id": settings.telegram_chat_id, "text": message}, timeout=15)
        response.raise_for_status()
        return True
    except httpx.HTTPError as exc:  # pragma: no cover - network only
        log.warning("Telegram delivery failed: %s", exc)
        return False
