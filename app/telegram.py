import logging, httpx
log=logging.getLogger(__name__)
def send(settings, message):
    if not settings.telegram_token or not settings.telegram_chat_id:
        log.info("Telegram not configured; skipping alert")
        return False
    url=f"https://api.telegram.org/bot{settings.telegram_token}/sendMessage"
    r=httpx.post(url,json={"chat_id":settings.telegram_chat_id,"text":message},timeout=15); r.raise_for_status(); return True
