"""Request validation, construction, and fulfillment state transitions."""

from functools import wraps
import secrets
import time


def request_quality(value):
    quality = str(value or "1080p").strip()
    if quality not in {"1080p", "4K", "REMUX"}:
        return "1080p"
    return quality


def quality_satisfies_request(requested_quality, available_qualities):
    ranks = {"1080p": 1, "4K": 2, "REMUX": 3}
    requested_rank = ranks[request_quality(requested_quality)]
    if isinstance(available_qualities, str):
        available_qualities = {available_qualities}
    available_rank = max(
        (ranks.get(str(quality), 0) for quality in (available_qualities or [])),
        default=0,
    )
    return available_rank >= requested_rank


def request_fulfillment_from_history(item, current, history):
    request_id = str(item.get("id") or "")
    if not request_id:
        return current, False

    manual = history.get(request_id)
    if isinstance(manual, dict) and manual.get("manualFulfilledAt"):
        return {
            "state": "fulfilled",
            "message": "Fulfilled manually.",
            "manual": True,
        }, False

    if not current:
        return None, False

    def present_status():
        message = str(current.get("message") or "In Plex.")
        if message.startswith("Fulfilled:"):
            message = "In Plex:" + message[len("Fulfilled:"):]
        return {
            "state": "present",
            "message": message,
        }

    previous = history.get(request_id)
    if not isinstance(previous, dict):
        history[request_id] = {
            "lastState": current.get("state", ""),
            "lastMessage": current.get("message", ""),
            "firstSeenAt": int(time.time()),
            "updatedAt": int(time.time()),
        }
        if current.get("state") == "fulfilled":
            return present_status(), True
        return current, True

    previous_state = str(previous.get("lastState") or "")
    current_state = str(current.get("state") or "")
    current_message = str(current.get("message") or "")
    changed = previous_state != current_state or str(previous.get("lastMessage") or "") != current_message
    previous["lastMessage"] = current_message

    if current_state == "fulfilled":
        if previous.get("fulfilledAt"):
            previous["lastState"] = current_state
            previous["updatedAt"] = int(time.time())
            return current, changed
        if previous_state in {"open", "partial"}:
            previous["lastState"] = current_state
            previous["fulfilledAt"] = int(time.time())
            previous["updatedAt"] = int(time.time())
            return current, True
        previous["lastState"] = current_state
        previous["updatedAt"] = int(time.time())
        return present_status(), changed

    previous["lastState"] = current_state
    previous["updatedAt"] = int(time.time())
    return current, changed


def cached_request_fulfillment(item, history_entry):
    if not isinstance(history_entry, dict):
        return None
    if history_entry.get("manualFulfilledAt"):
        return {"state": "fulfilled", "message": "Fulfilled manually.", "manual": True}
    state = str(history_entry.get("lastState") or "")
    if state not in {"open", "partial", "fulfilled", "present"}:
        return None
    message = str(history_entry.get("lastMessage") or "").strip()
    if not message:
        message = {
            "open": "Not in Plex yet.",
            "partial": "In Plex at a different quality.",
            "fulfilled": "Fulfilled: in Plex.",
            "present": "In Plex.",
        }[state]
    if state == "fulfilled" and not history_entry.get("fulfilledAt"):
        state = "present"
        if message.startswith("Fulfilled:"):
            message = "In Plex:" + message[len("Fulfilled:"):]
    return {"state": state, "message": message}


def request_item(config, payload, client_address):
    requester = str(payload.get("requester", "")).strip() or "Unknown"
    tmdb_item = payload.get("tmdbItem")
    custom_title = str(payload.get("customTitle", "")).strip()
    if not tmdb_item and not custom_title:
        raise ValueError("Choose a result or enter a request.")

    quality = request_quality(payload.get("quality"))
    item = {
        "id": f"{time.time_ns()}-{secrets.token_hex(3)}",
        "requestedAt": int(time.time()),
        "requester": requester,
        "requesterAddress": client_address,
        "quality": quality,
        "customTitle": custom_title,
        "libraryWarning": "",
        "reminderMuted": False,
        "tmdb": None,
    }
    if isinstance(tmdb_item, dict):
        item["tmdb"] = {
            "id": tmdb_item.get("id"),
            "type": tmdb_item.get("type"),
            "title": tmdb_item.get("title"),
            "year": tmdb_item.get("year"),
            "date": tmdb_item.get("date"),
            "overview": tmdb_item.get("overview"),
            "posterPath": tmdb_item.get("posterPath"),
            "voteAverage": tmdb_item.get("voteAverage"),
        }
    return item
_backend_namespace = None


def _sync_backend():
    if _backend_namespace is None:
        raise RuntimeError("The requests backend has not been configured.")
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


def initialize_request_fulfillment_state(config, item):
    current = current_request_plex_status(config, item)
    if not current:
        return
    request_id = str(item.get("id") or "")
    if not request_id:
        return
    history = load_fulfillment_state()
    if request_id in history:
        return
    history[request_id] = {
        "lastState": current.get("state", ""),
        "lastMessage": current.get("message", ""),
        "firstSeenAt": int(time.time()),
        "updatedAt": int(time.time()),
    }
    save_fulfillment_state(history)


def manually_fulfill_request(request_id):
    request_id = str(request_id or "").strip()
    if not request_id:
        return False
    with REQUEST_LOCK:
        if not any(str(item.get("id") or "") == request_id for item in load_requests()):
            return False
        history = load_fulfillment_state()
        now = int(time.time())
        entry = history.get(request_id)
        if not isinstance(entry, dict):
            entry = {
                "firstSeenAt": now,
            }
        entry["lastState"] = "fulfilled"
        entry["lastMessage"] = "Fulfilled manually."
        entry["manualFulfilledAt"] = now
        entry["updatedAt"] = now
        history[request_id] = entry
        save_fulfillment_state(history)
    return True


def requests_for_display():
    with REQUEST_LOCK:
        items = load_requests()
        history = load_fulfillment_state()
    enriched = []
    for item in items:
        copy = dict(item)
        entry = history.get(str(copy.get("id") or ""))
        fulfillment = cached_request_fulfillment(copy, entry)
        if fulfillment:
            copy["fulfillment"] = fulfillment
        enriched.append(copy)
    return enriched


def requests_with_fulfillment(config):
    process_notification_outbox(config)
    with REQUEST_LOCK:
        source_items = load_requests()
        history = load_fulfillment_state()

    enriched = []
    fulfilled_request_ids = set()
    history_changed = False
    for item in source_items:
        copy = dict(item)
        current = current_request_plex_status(config, copy)
        fulfillment, changed = request_fulfillment_from_history(copy, current, history)
        history_changed = history_changed or changed
        if fulfillment:
            copy["fulfillment"] = fulfillment
            entry = history.get(str(copy.get("id") or ""))
            if (
                fulfillment.get("state") == "fulfilled"
                and isinstance(entry, dict)
                and (entry.get("fulfilledAt") or entry.get("manualFulfilledAt"))
                and not entry.get("fulfillmentNotifiedAt")
            ):
                if notify_request_fulfilled(config, copy, fulfillment):
                    entry["fulfillmentNotifiedAt"] = int(time.time())
                    history_changed = True
            if (
                fulfillment.get("state") == "fulfilled"
                and isinstance(entry, dict)
                and entry.get("fulfillmentNotifiedAt")
            ):
                fulfilled_request_ids.add(str(copy.get("id") or ""))
                continue
        enriched.append(copy)

    history_changed = send_due_admin_reminders(config, source_items, history) or history_changed

    with REQUEST_LOCK:
        if history_changed:
            try:
                latest_history = load_fulfillment_state()
                for request_id, entry in history.items():
                    latest_entry = latest_history.get(request_id)
                    if (
                        isinstance(latest_entry, dict)
                        and latest_entry.get("manualFulfilledAt")
                        and not entry.get("manualFulfilledAt")
                    ):
                        continue
                    if (
                        isinstance(latest_entry, dict)
                        and int(latest_entry.get("updatedAt") or 0) > int(entry.get("updatedAt") or 0)
                    ):
                        continue
                    latest_history[request_id] = entry
                save_fulfillment_state(latest_history)
            except OSError as exc:
                print(f"Could not save request fulfillment state: {exc}", flush=True)
        if fulfilled_request_ids:
            try:
                remaining = [
                    item for item in load_requests()
                    if str(item.get("id") or "") not in fulfilled_request_ids
                ]
                save_requests(remaining)
            except OSError as exc:
                print(f"Could not save fulfilled request cleanup: {exc}", flush=True)
    return enriched


def add_request(config, payload, client_address):
    item = request_item(config, payload, client_address)
    with REQUEST_LOCK:
        items = load_requests()
        items.insert(0, item)
        save_requests(items[:200])
    return item


def complete_request_creation(config, item):
    completed_item = dict(item)
    completed_item["libraryWarning"] = library_warning_for_request(
        config,
        completed_item.get("tmdb"),
        completed_item.get("quality"),
    )
    with REQUEST_LOCK:
        items = load_requests()
        request_found = False
        for stored_item in items:
            if str(stored_item.get("id") or "") == str(completed_item.get("id") or ""):
                stored_item["libraryWarning"] = completed_item["libraryWarning"]
                request_found = True
                break
        if not request_found:
            return
        save_requests(items)
        try:
            initialize_request_fulfillment_state(config, completed_item)
        except OSError as exc:
            print(f"Could not initialize request fulfillment state: {exc}", flush=True)
    notify_request_created(config, completed_item)


def fulfillment_check_interval():
    raw = os.environ.get("FULFILLMENT_CHECK_SECONDS", "15")
    try:
        value = int(raw)
    except ValueError:
        value = 15
    return max(15, value)


def fulfillment_monitor_loop(config, stop_event):
    interval = fulfillment_check_interval()
    print(f"Fulfillment monitor checking every {interval} seconds.", flush=True)
    delay = 10
    while not stop_event.wait(delay):
        delay = interval
        try:
            requests_with_fulfillment(config)
        except Exception as exc:
            print(f"Fulfillment monitor error: {exc}", flush=True)


def delete_request(request_id):
    request_id = str(request_id or "").strip()
    with REQUEST_LOCK:
        items = load_requests()
        remaining = [item for item in items if str(item.get("id", "")) != request_id]
        if len(remaining) == len(items):
            return False
        save_requests(remaining)
    return True


def set_request_reminder_muted(request_id, muted):
    request_id = str(request_id or "").strip()
    if not request_id:
        return False
    with REQUEST_LOCK:
        items = load_requests()
        for item in items:
            if str(item.get("id") or "") != request_id:
                continue
            item["reminderMuted"] = bool(muted)
            save_requests(items)
            return True
    return False


initialize_request_fulfillment_state = _live_backend_function(initialize_request_fulfillment_state)
manually_fulfill_request = _live_backend_function(manually_fulfill_request)
requests_for_display = _live_backend_function(requests_for_display)
requests_with_fulfillment = _live_backend_function(requests_with_fulfillment)
add_request = _live_backend_function(add_request)
complete_request_creation = _live_backend_function(complete_request_creation)
fulfillment_check_interval = _live_backend_function(fulfillment_check_interval)
fulfillment_monitor_loop = _live_backend_function(fulfillment_monitor_loop)
delete_request = _live_backend_function(delete_request)
set_request_reminder_muted = _live_backend_function(set_request_reminder_muted)


