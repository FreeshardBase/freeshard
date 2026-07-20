import json
import logging
from typing import TYPE_CHECKING

from shard_core.database import database
from shard_core.service.freeshard_controller import call_freeshard_controller
from shard_core.settings import settings

if TYPE_CHECKING:
    from shard_core.service.disk import DiskUsage

log = logging.getLogger(__name__)

KV_KEY_DISK_FULL_NOTIFIED = "disk_full_notification_sent"

# The active language is fixed to English for now; the German template is kept
# ready so a language switch is a one-line change once it is needed.
ACTIVE_LANGUAGE = "en"

_TEMPLATES = {
    "en": {
        "subject": "Your Freeshard is running low on disk space",
        "body": [
            "Hello,",
            "Your Freeshard has used {used_percent:.0f}% of its disk space.",
            "When the disk fills up, apps may stop working correctly and backups "
            "may fail. Please free up space or expand your storage.",
            "You will not receive another disk space warning until usage drops "
            "back below the threshold.",
            "— Your Freeshard",
        ],
    },
    "de": {
        "subject": "Der Speicherplatz deines Freeshards wird knapp",
        "body": [
            "Hallo,",
            "Dein Freeshard hat {used_percent:.0f}% seines Speicherplatzes belegt.",
            "Wenn der Speicher voll ist, funktionieren Apps möglicherweise nicht "
            "mehr richtig und Backups können fehlschlagen. Bitte gib Speicher frei "
            "oder erweitere deinen Speicher.",
            "Du erhältst erst wieder eine Warnung, wenn die Belegung unter den "
            "Schwellwert fällt.",
            "— Dein Freeshard",
        ],
    },
}


async def check_disk_full(usage: "DiskUsage") -> None:
    """Send a one-off email when disk usage crosses the configured threshold.

    Deduplicated via a persistent flag in the kv_store: the email is sent once
    when usage rises above the threshold and re-armed only after usage falls
    back below it.
    """
    config = settings().event_notifications.disk_full
    if not config.enabled:
        return
    if usage.total_gb <= 0:
        return

    used_percent = (usage.total_gb - usage.free_gb) / usage.total_gb * 100
    over_threshold = used_percent >= config.threshold_percent
    already_notified = await _was_notified()

    if over_threshold and not already_notified:
        try:
            await _send_disk_full_email(used_percent)
        except Exception as e:
            log.error(f"failed to send disk-full notification email: {e}")
            return
        await database.set_value(KV_KEY_DISK_FULL_NOTIFIED, True)
    elif not over_threshold and already_notified:
        await database.set_value(KV_KEY_DISK_FULL_NOTIFIED, False)


async def _was_notified() -> bool:
    try:
        return bool(await database.get_value(KV_KEY_DISK_FULL_NOTIFIED))
    except KeyError:
        return False


async def _send_disk_full_email(used_percent: float) -> None:
    template = _TEMPLATES[ACTIVE_LANGUAGE]
    payload = {
        "subject": template["subject"],
        "body": [line.format(used_percent=used_percent) for line in template["body"]],
    }
    response = await call_freeshard_controller(
        "api/email_relay",
        method="POST",
        body=json.dumps(payload).encode(),
    )
    response.raise_for_status()
    log.info(f"sent disk-full notification email (disk {used_percent:.0f}% full)")
