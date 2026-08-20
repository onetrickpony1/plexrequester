"""Discord configuration validation and polished embed formatting."""

from functools import wraps
import re
import time
from urllib import parse


DISCORD_EMBED_MAX_FIELDS = 25
DISCORD_EMBED_MAX_CHARACTERS = 6000
DISCORD_REMINDER_FIELDS_CHARACTER_BUDGET = 5400
DEFAULT_ADMIN_REMINDER_INTERVAL_MINUTES = 60
MIN_ADMIN_REMINDER_INTERVAL_MINUTES = 1
MAX_ADMIN_REMINDER_INTERVAL_MINUTES = 7 * 24 * 60


def int_value(value):
    try:
        return int(float(value or 0))
    except (TypeError, ValueError):
        return 0


def discord_webhook_url(config):
    return str(config.get("notifications", {}).get("discordWebhookUrl", "")).strip()


def admin_reminder_webhook_url(config):
    return str(config.get("notifications", {}).get("adminReminderWebhookUrl", "")).strip()


def admin_reminder_interval_minutes(config):
    value = config.get("notifications", {}).get(
        "adminReminderIntervalMinutes",
        DEFAULT_ADMIN_REMINDER_INTERVAL_MINUTES,
    )
    try:
        minutes = int(value)
    except (TypeError, ValueError):
        return DEFAULT_ADMIN_REMINDER_INTERVAL_MINUTES
    if not MIN_ADMIN_REMINDER_INTERVAL_MINUTES <= minutes <= MAX_ADMIN_REMINDER_INTERVAL_MINUTES:
        return DEFAULT_ADMIN_REMINDER_INTERVAL_MINUTES
    return minutes


def admin_reminder_interval_seconds(config):
    return admin_reminder_interval_minutes(config) * 60


def normalize_requester_name(value):
    return str(value or "").strip().casefold()


def validate_discord_user_id(value):
    discord_id = str(value or "").strip()
    if not re.fullmatch(r"[1-9][0-9]{14,19}", discord_id):
        raise ValueError("Discord user ID must be a 15 to 20 digit numeric snowflake ID.")
    if int(discord_id) > 18446744073709551615:
        raise ValueError("Discord user ID is outside the valid snowflake range.")
    return discord_id


def validate_discord_webhook_url(value):
    url = str(value or "").strip()
    if not url:
        return ""
    parsed = parse.urlparse(url)
    allowed_hosts = {"discord.com", "discordapp.com", "canary.discord.com", "ptb.discord.com"}
    if parsed.scheme != "https" or parsed.hostname not in allowed_hosts or "/api/webhooks/" not in parsed.path:
        raise ValueError("Admin reminder webhook must be a valid HTTPS Discord webhook URL.")
    return url


def clean_discord_user_mappings(value):
    if value is None:
        return {}
    if isinstance(value, dict):
        entries = [
            {"requesterName": requester_name, "discordUserId": discord_id}
            for requester_name, discord_id in value.items()
        ]
    elif isinstance(value, list):
        entries = value
    else:
        raise ValueError("Discord user mappings must be a list.")

    cleaned = {}
    normalized_names = set()
    for entry in entries:
        if not isinstance(entry, dict):
            raise ValueError("Each Discord user mapping must contain a requester name and Discord user ID.")
        requester_name = str(entry.get("requesterName", "")).strip()
        discord_id = str(entry.get("discordUserId", "")).strip()
        if not requester_name:
            raise ValueError("Requester name is required for every Discord user mapping.")
        if not discord_id:
            raise ValueError(f"Discord user ID is required for {requester_name}.")
        normalized_name = normalize_requester_name(requester_name)
        if normalized_name in normalized_names:
            raise ValueError(f"Duplicate requester name in Discord mappings: {requester_name}.")
        normalized_names.add(normalized_name)
        cleaned[requester_name] = validate_discord_user_id(discord_id)
    return cleaned


def discord_user_id_for_requester(config, requester_name):
    wanted = normalize_requester_name(requester_name)
    if not wanted:
        return ""
    mappings = config.get("notifications", {}).get("discordUserMappings", {})
    if not isinstance(mappings, dict):
        return ""
    for configured_name, configured_id in mappings.items():
        if normalize_requester_name(configured_name) != wanted:
            continue
        try:
            return validate_discord_user_id(configured_id)
        except ValueError:
            return ""
    return ""


def request_display_title(item):
    tmdb_item = item.get("tmdb")
    if isinstance(tmdb_item, dict) and tmdb_item.get("title"):
        year = tmdb_item.get("year")
        return f"{tmdb_item.get('title')} ({year})" if year else str(tmdb_item.get("title"))
    return str(item.get("customTitle") or "Request").strip()


def tmdb_url_for_item(item):
    tmdb_item = item.get("tmdb")
    if isinstance(tmdb_item, dict) and tmdb_item.get("id"):
        media_type = "tv" if tmdb_item.get("type") == "tv" else "movie"
        return f"https://www.themoviedb.org/{media_type}/{tmdb_item.get('id')}"
    return ""


def tmdb_poster_url_for_item(item):
    tmdb_item = item.get("tmdb")
    poster_path = str(tmdb_item.get("posterPath") or "").strip() if isinstance(tmdb_item, dict) else ""
    return f"https://image.tmdb.org/t/p/w342{poster_path}" if poster_path.startswith("/") else ""


def discord_request_embed(item):
    title = request_display_title(item)[:300]
    tmdb_url = tmdb_url_for_item(item)
    tmdb_item = item.get("tmdb") if isinstance(item.get("tmdb"), dict) else {}
    overview = str(tmdb_item.get("overview") or "").strip()
    warning = str(item.get("libraryWarning") or "").strip()
    fields = [
        {
            "name": "Requester",
            "value": str(item.get("requester") or "Unknown")[:1024],
            "inline": True,
        },
        {
            "name": "Requested quality",
            "value": str(item.get("quality") or "1080p")[:1024],
            "inline": True,
        },
        {
            "name": "Status",
            "value": "Waiting to be added to Plex",
            "inline": False,
        },
    ]
    if warning:
        fields.append({"name": "Library note", "value": warning[:1024], "inline": False})
    embed = {
        "title": "New Plex Request",
        "description": f"**{title}**" + (f"\n\n{overview[:500]}" if overview else ""),
        "color": 0xE5A00D,
        "fields": fields,
        "footer": {"text": "Plex Requester • Request received"},
    }
    if tmdb_url:
        embed["url"] = tmdb_url
    poster_url = tmdb_poster_url_for_item(item)
    if poster_url:
        embed["thumbnail"] = {"url": poster_url}
    return embed


def discord_fulfillment_detail(item, fulfillment):
    quality = str(item.get("quality") or "1080p").strip()
    detail = str(fulfillment.get("message") or "").strip()
    if detail.startswith("Fulfilled:"):
        detail = detail[len("Fulfilled:"):].strip()
    detail = detail.rstrip(".")
    return (detail or quality).rstrip(".")


def discord_fulfillment_embed(item, fulfillment):
    tmdb_url = tmdb_url_for_item(item)
    embed = {
        "title": "Now Available on Plex",
        "description": f"**{request_display_title(item)[:300]}**",
        "color": 0x57F287,
        "fields": [
            {
                "name": "Requester",
                "value": str(item.get("requester") or "Unknown")[:1024],
                "inline": True,
            },
            {
                "name": "Requested quality",
                "value": str(item.get("quality") or "1080p")[:1024],
                "inline": True,
            },
            {
                "name": "Plex media details",
                "value": discord_fulfillment_detail(item, fulfillment)[:1024],
                "inline": False,
            },
        ],
        "footer": {"text": "Plex Requester • Ready to watch"},
    }
    if tmdb_url:
        embed["url"] = tmdb_url
    poster_url = tmdb_poster_url_for_item(item)
    if poster_url:
        embed["thumbnail"] = {"url": poster_url}
    return embed


def discord_waiting_time(item, now=None):
    now = int(time.time()) if now is None else int(now)
    requested_at = int_value(item.get("requestedAt"))
    age_seconds = max(0, now - requested_at) if requested_at else 0
    age_minutes = max(1, age_seconds // 60)
    if age_minutes >= 24 * 60:
        days, remaining_minutes = divmod(age_minutes, 24 * 60)
        hours, minutes = divmod(remaining_minutes, 60)
        parts = [f"{days}d"]
        if hours:
            parts.append(f"{hours}h")
        if minutes:
            parts.append(f"{minutes}m")
        return " ".join(parts)
    if age_minutes >= 60:
        hours, minutes = divmod(age_minutes, 60)
        return f"{hours}h {minutes}m" if minutes else f"{hours}h"
    return f"{age_minutes}m"


def discord_admin_reminder_field(item, now=None):
    return {
        "name": request_display_title(item)[:256],
        "value": "\n".join([
            f"**Requester:** {str(item.get('requester') or 'Unknown')[:160]}",
            f"**Quality:** {str(item.get('quality') or '1080p')[:80]}",
            f"**Waiting:** {discord_waiting_time(item, now)}",
        ])[:1024],
        "inline": False,
    }


def discord_embed_character_count(embed):
    total = len(str(embed.get("title") or "")) + len(str(embed.get("description") or ""))
    footer = embed.get("footer")
    if isinstance(footer, dict):
        total += len(str(footer.get("text") or ""))
    author = embed.get("author")
    if isinstance(author, dict):
        total += len(str(author.get("name") or ""))
    for field in embed.get("fields") or []:
        if isinstance(field, dict):
            total += len(str(field.get("name") or ""))
            total += len(str(field.get("value") or ""))
    return total


def discord_admin_reminder_embed(
    config,
    items,
    now=None,
    page_number=1,
    page_count=1,
    total_count=None,
):
    total_count = len(items) if total_count is None else int(total_count)
    count = len(items)
    page_text = f" Part {page_number} of {page_count}." if page_count > 1 else ""
    interval = admin_reminder_interval_minutes(config)
    embed = {
        "title": "Unfulfilled Plex Requests",
        "description": (
            f"{total_count} unmuted request{'s are' if total_count != 1 else ' is'} still waiting to be fulfilled."
            f"{page_text}"
        ),
        "color": 0xE5A00D,
        "fields": [discord_admin_reminder_field(item, now) for item in items],
        "footer": {
            "text": (
                f"Reminder schedule: every {interval} minute{'s' if interval != 1 else ''}"
                f" • {count} request{'s' if count != 1 else ''} in this message"
                " • Muted requests are excluded"
            ),
        },
    }
    if len(embed["fields"]) > DISCORD_EMBED_MAX_FIELDS:
        raise ValueError("Discord reminder embed exceeds the 25-field limit.")
    if discord_embed_character_count(embed) > DISCORD_EMBED_MAX_CHARACTERS:
        raise ValueError("Discord reminder embed exceeds the 6000-character limit.")
    return embed


def discord_admin_reminder_embeds(config, items, now=None):
    items = list(items or [])
    if not items:
        return []
    batches = []
    batch = []
    field_characters = 0
    for item in items:
        field = discord_admin_reminder_field(item, now)
        item_characters = len(field["name"]) + len(field["value"])
        if batch and (
            len(batch) >= DISCORD_EMBED_MAX_FIELDS
            or field_characters + item_characters > DISCORD_REMINDER_FIELDS_CHARACTER_BUDGET
        ):
            batches.append(batch)
            batch = []
            field_characters = 0
        batch.append(item)
        field_characters += item_characters
    if batch:
        batches.append(batch)
    return [
        discord_admin_reminder_embed(
            config,
            batch_items,
            now,
            page_number=index + 1,
            page_count=len(batches),
            total_count=len(items),
        )
        for index, batch_items in enumerate(batches)
    ]
_backend_namespace = None


def _sync_backend():
    if _backend_namespace is None:
        raise RuntimeError("The Discord backend has not been configured.")
    for name, value in _backend_namespace.items():
        if not name.startswith("__"):
            globals()[name] = value


def configure_backend(namespace):
    global _backend_namespace
    _backend_namespace = namespace
    _sync_backend()


def _live_backend_function(function):
    @wraps(function)
    def call(*args, **kwargs):
        _sync_backend()
        return function(*args, **kwargs)
    return call


def send_discord_webhook(url, content="", allowed_user_id="", embeds=None):
    url = str(url or "").strip()
    if not url:
        return False
    allowed_mentions = {"parse": []}
    if allowed_user_id:
        allowed_mentions["users"] = [validate_discord_user_id(allowed_user_id)]
    payload = {"allowed_mentions": allowed_mentions}
    if content:
        payload["content"] = str(content)[:2000]
    if embeds:
        payload["embeds"] = list(embeds)[:10]
    req = request.Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "Content-Type": "application/json",
            "User-Agent": "PlexRequester/1.0",
        },
        method="POST",
    )
    with request.urlopen(req, timeout=10) as response:
        response.read()
    return True


def notification_target_url(config, target):
    if target == "primary":
        return discord_webhook_url(config)
    if target == "admin-reminder":
        return admin_reminder_webhook_url(config)
    return ""


def notification_job_id(idempotency_key):
    return hashlib.sha256(str(idempotency_key).encode("utf-8")).hexdigest()


def notification_retry_delay(attempts):
    exponent = max(0, min(int(attempts or 1) - 1, 12))
    return min(NOTIFICATION_RETRY_MAX_SECONDS, NOTIFICATION_RETRY_BASE_SECONDS * (2 ** exponent))


def prune_notification_outbox(items, now=None):
    now = int(time.time()) if now is None else int(now)
    retained = []
    completed = []
    cutoff = now - NOTIFICATION_SENT_RETENTION_SECONDS
    for item in items:
        if not isinstance(item, dict):
            continue
        if item.get("status") == "sent":
            if int_value(item.get("sentAt")) >= cutoff:
                completed.append(item)
        else:
            retained.append(item)
    completed.sort(key=lambda item: int_value(item.get("sentAt")), reverse=True)
    completed = completed[:NOTIFICATION_OUTBOX_MAX_COMPLETED]
    result = retained + completed
    result.sort(key=lambda item: int_value(item.get("createdAt")))
    return result


def process_notification_outbox(config, now=None, job_ids=None, max_jobs=5):
    now = int(time.time()) if now is None else int(now)
    wanted_ids = set(job_ids or [])
    sent = 0
    failed = 0
    with NOTIFICATION_OUTBOX_LOCK:
        items = prune_notification_outbox(load_notification_outbox(), now)
        processed = 0
        for item in items:
            if processed >= max(1, int(max_jobs or 1)):
                break
            if wanted_ids and item.get("id") not in wanted_ids:
                continue
            if item.get("status") not in {"pending", "failed"}:
                continue
            if int_value(item.get("nextAttemptAt")) > now:
                continue
            processed += 1
            item["attempts"] = int_value(item.get("attempts")) + 1
            item["lastAttemptAt"] = now
            save_notification_outbox(items)
            try:
                webhook_url = notification_target_url(config, item.get("target"))
                if not webhook_url:
                    raise RuntimeError("The configured Discord webhook is empty.")
                delivered = send_discord_webhook(
                    webhook_url,
                    item.get("content", ""),
                    item.get("allowedUserId", ""),
                    item.get("embeds") or None,
                )
                if not delivered:
                    raise RuntimeError("Discord webhook delivery was not accepted.")
                item["status"] = "sent"
                item["sentAt"] = now
                item["nextAttemptAt"] = 0
                item["lastError"] = ""
                sent += 1
            except Exception as exc:
                item["status"] = "failed"
                item["lastError"] = str(exc)[:1000]
                item["nextAttemptAt"] = now + notification_retry_delay(item["attempts"])
                failed += 1
                print(
                    f"Discord notification delivery failed; retry scheduled: {exc}",
                    flush=True,
                )
            save_notification_outbox(items)
    return {"sent": sent, "failed": failed}


def queue_discord_notification(
    config,
    target,
    idempotency_key,
    content="",
    allowed_user_id="",
    embeds=None,
    now=None,
):
    if not notification_target_url(config, target):
        return False
    now = int(time.time()) if now is None else int(now)
    job_id = notification_job_id(idempotency_key)
    with NOTIFICATION_OUTBOX_LOCK:
        items = prune_notification_outbox(load_notification_outbox(), now)
        existing = next((item for item in items if item.get("id") == job_id), None)
        if existing is None:
            items.append({
                "id": job_id,
                "idempotencyKey": str(idempotency_key)[:500],
                "target": target,
                "content": str(content)[:2000],
                "allowedUserId": str(allowed_user_id or ""),
                "embeds": list(embeds or [])[:10],
                "status": "pending",
                "attempts": 0,
                "createdAt": now,
                "lastAttemptAt": 0,
                "nextAttemptAt": now,
                "sentAt": 0,
                "lastError": "",
            })
            save_notification_outbox(items)
        elif existing.get("status") == "sent":
            return True
    process_notification_outbox(config, now=now, job_ids={job_id}, max_jobs=1)
    return True


def request_notification_identity(item):
    request_id = str(item.get("id") or "").strip()
    if request_id:
        return request_id
    fallback = {
        "requestedAt": int_value(item.get("requestedAt")),
        "requester": str(item.get("requester") or ""),
        "title": request_display_title(item),
    }
    return notification_job_id(json.dumps(fallback, sort_keys=True))


def notify_request_created(config, item):
    try:
        discord_user_id = discord_user_id_for_requester(config, item.get("requester"))
        return queue_discord_notification(
            config,
            "primary",
            f"request-created:{request_notification_identity(item)}",
            f"<@{validate_discord_user_id(discord_user_id)}> your request has been received."
            if discord_user_id else "",
            discord_user_id,
            [discord_request_embed(item)],
        )
    except Exception as exc:
        print(f"Could not send Discord notification: {exc}", flush=True)


def notify_request_fulfilled(config, item, fulfillment):
    try:
        discord_user_id = discord_user_id_for_requester(config, item.get("requester"))
        return queue_discord_notification(
            config,
            "primary",
            f"request-fulfilled:{request_notification_identity(item)}",
            f"<@{validate_discord_user_id(discord_user_id)}> your request is now available on Plex."
            if discord_user_id else "",
            discord_user_id,
            [discord_fulfillment_embed(item, fulfillment)],
        )
    except Exception as exc:
        print(f"Could not send Discord fulfillment notification: {exc}", flush=True)
        return False


def notify_admin_unfulfilled_requests(config, items, now=None, notification_key=""):
    url = admin_reminder_webhook_url(config)
    if not url or not items:
        return False
    try:
        now = int(time.time()) if now is None else int(now)
        if not notification_key:
            identities = [request_notification_identity(item) for item in items]
            notification_key = f"admin-reminder:{now}:{notification_job_id('|'.join(identities))}"
        embeds = discord_admin_reminder_embeds(config, items, now)
        for index, embed in enumerate(embeds):
            if not queue_discord_notification(
                config,
                "admin-reminder",
                f"{notification_key}:part:{index + 1}",
                embeds=[embed],
                now=now,
            ):
                return False
        return True
    except Exception as exc:
        print(f"Could not send Discord admin reminder: {exc}", flush=True)
        return False


def send_due_admin_reminders(config, items, history, now=None):
    if not admin_reminder_webhook_url(config):
        return False
    now = int(time.time()) if now is None else int(now)
    reminder_interval = admin_reminder_interval_seconds(config)
    changed = False
    active_requests = []
    reminder_due = False
    for item in items:
        if bool(item.get("reminderMuted")):
            continue
        request_id = str(item.get("id") or "")
        if not request_id:
            continue
        entry = history.get(request_id)
        if not isinstance(entry, dict):
            entry = {
                "lastState": "open",
                "lastMessage": "Not in Plex yet.",
                "firstSeenAt": int_value(item.get("requestedAt")) or now,
                "updatedAt": now,
            }
            history[request_id] = entry
            changed = True
        if entry.get("manualFulfilledAt") or entry.get("fulfilledAt"):
            continue
        if str(entry.get("lastState") or "") in {"fulfilled", "present"}:
            continue
        requested_at = int_value(item.get("requestedAt")) or int_value(entry.get("firstSeenAt")) or now
        last_reminder_at = int_value(entry.get("lastAdminReminderAt"))
        active_requests.append((item, entry))
        if now - requested_at >= reminder_interval and (
            not last_reminder_at or now - last_reminder_at >= reminder_interval
        ):
            reminder_due = True
    if reminder_due and notify_admin_unfulfilled_requests(
        config,
        [item for item, _entry in active_requests],
        now,
        notification_key=(
            f"admin-reminder:{now}:"
            f"{notification_job_id('|'.join(request_notification_identity(item) for item, _entry in active_requests))}"
        ),
    ):
        for _item, entry in active_requests:
            entry["lastAdminReminderAt"] = now
            entry["updatedAt"] = now
        changed = True
    return changed


send_discord_webhook = _live_backend_function(send_discord_webhook)
notification_target_url = _live_backend_function(notification_target_url)
notification_job_id = _live_backend_function(notification_job_id)
notification_retry_delay = _live_backend_function(notification_retry_delay)
prune_notification_outbox = _live_backend_function(prune_notification_outbox)
process_notification_outbox = _live_backend_function(process_notification_outbox)
queue_discord_notification = _live_backend_function(queue_discord_notification)
request_notification_identity = _live_backend_function(request_notification_identity)
notify_request_created = _live_backend_function(notify_request_created)
notify_request_fulfilled = _live_backend_function(notify_request_fulfilled)
notify_admin_unfulfilled_requests = _live_backend_function(notify_admin_unfulfilled_requests)
send_due_admin_reminders = _live_backend_function(send_due_admin_reminders)

