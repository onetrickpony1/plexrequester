"""Configuration loading, defaults, and persistence primitives."""

import json
import os
import re
from pathlib import Path

from .discord import (
    MAX_ADMIN_REMINDER_INTERVAL_MINUTES,
    MIN_ADMIN_REMINDER_INTERVAL_MINUTES,
    admin_reminder_interval_minutes,
    admin_reminder_webhook_url,
    clean_discord_user_mappings,
    discord_webhook_url,
    validate_discord_webhook_url,
)
from .storage import destination_paths


DEFAULT_APP_VERSION = "v8.6"
DEFAULT_SERVER_PORT = 8003
DEFAULT_ADMIN_REMINDER_INTERVAL_MINUTES = 60


def configured_server_port(config):
    server_config = config.get("server", {})
    if not isinstance(server_config, dict):
        return DEFAULT_SERVER_PORT
    try:
        port = int(server_config.get("port", DEFAULT_SERVER_PORT))
    except (TypeError, ValueError):
        return DEFAULT_SERVER_PORT
    return port if 1 <= port <= 65535 else DEFAULT_SERVER_PORT


def load_config(base_dir, user_data_path, environ=None):
    environ = os.environ if environ is None else environ
    base_dir = Path(base_dir)
    configured_path = str(environ.get("APP_CONFIG", "")).strip()
    if configured_path:
        config_path = Path(configured_path)
        if not config_path.is_absolute():
            config_path = base_dir / config_path
        save_config_path = config_path
    else:
        config_path = user_data_path("config.json")
        save_config_path = config_path

    using_example = False
    if not config_path.exists():
        config_path = base_dir / "config.example.json"
        using_example = True

    with config_path.open("r", encoding="utf-8") as handle:
        config = json.load(handle)

    qbit = config.setdefault("qbittorrent", {})
    qbit["url"] = environ.get("QBIT_URL", qbit.get("url", "http://127.0.0.1:8080")).rstrip("/")
    qbit["username"] = environ.get("QBIT_USERNAME", qbit.get("username", "admin"))
    qbit["password"] = environ.get("QBIT_PASSWORD", qbit.get("password", ""))
    plex = config.setdefault("plex", {})
    plex["databasePath"] = environ.get("PLEX_DATABASE_PATH", plex.get("databasePath", ""))
    tmdb = config.setdefault("tmdb", {})
    tmdb["apiKey"] = environ.get("TMDB_API_KEY", tmdb.get("apiKey", ""))
    notifications = config.setdefault("notifications", {})
    notifications["discordWebhookUrl"] = environ.get(
        "DISCORD_WEBHOOK_URL", notifications.get("discordWebhookUrl", "")
    )
    notifications["adminReminderWebhookUrl"] = environ.get(
        "DISCORD_ADMIN_REMINDER_WEBHOOK_URL", notifications.get("adminReminderWebhookUrl", "")
    )
    notifications["adminReminderIntervalMinutes"] = environ.get(
        "ADMIN_REMINDER_INTERVAL_MINUTES",
        notifications.get("adminReminderIntervalMinutes", DEFAULT_ADMIN_REMINDER_INTERVAL_MINUTES),
    )
    notifications.setdefault("discordUserMappings", {})
    app = config.setdefault("app", {})
    if not isinstance(app, dict):
        app = {}
        config["app"] = app
    app.setdefault("version", DEFAULT_APP_VERSION)
    server_config = config.setdefault("server", {})
    if not isinstance(server_config, dict):
        server_config = {}
        config["server"] = server_config
    server_config["port"] = configured_server_port(config)
    config["adminPin"] = str(environ.get("ADMIN_PIN", config.get("adminPin", "")))
    config.setdefault("destinations", [])
    config["_config_path"] = str(config_path)
    config["_save_config_path"] = str(save_config_path)
    config["_using_example_config"] = using_example
    return config


def config_for_save(config):
    return {key: value for key, value in config.items() if not key.startswith("_")}


def destination_id(label, used):
    base = re.sub(r"[^a-z0-9]+", "_", str(label or "destination").lower()).strip("_") or "destination"
    candidate = base
    index = 2
    while candidate in used:
        candidate = f"{base}_{index}"
        index += 1
    used.add(candidate)
    return candidate


def editable_config(config):
    discord_mappings = config.get("notifications", {}).get("discordUserMappings", {})
    if not isinstance(discord_mappings, dict):
        discord_mappings = {}
    return {
        "app": {
            "version": str(config.get("app", {}).get("version", DEFAULT_APP_VERSION)),
        },
        "qbittorrent": {
            "url": config.get("qbittorrent", {}).get("url", ""),
        },
        "plex": {
            "databasePath": config.get("plex", {}).get("databasePath", ""),
        },
        "discordUserMappings": [
            {
                "requesterName": requester_name,
                "discordUserId": discord_id,
            }
            for requester_name, discord_id in discord_mappings.items()
        ],
        "discordWebhookUrl": discord_webhook_url(config),
        "adminReminderWebhookUrl": admin_reminder_webhook_url(config),
        "adminReminderIntervalMinutes": admin_reminder_interval_minutes(config),
        "destinations": [
            {
                "id": item.get("id", ""),
                "label": item.get("label", ""),
                "path": destination_paths(item)[0] if destination_paths(item) else "",
                "paths": destination_paths(item),
                "browseSubfolders": bool(item.get("browseSubfolders")),
            }
            for item in config.get("destinations", [])
        ],
    }


def apply_editable_config(config, payload):
    app = payload.get("app", {})
    qbit = payload.get("qbittorrent", {})
    plex = payload.get("plex", {})
    destinations = payload.get("destinations", [])
    discord_mappings = clean_discord_user_mappings(payload.get("discordUserMappings", []))
    notifications = config.setdefault("notifications", {})
    current_webhook = notifications.get("discordWebhookUrl", "")
    webhook = (
        validate_discord_webhook_url(payload.get("discordWebhookUrl"))
        if "discordWebhookUrl" in payload
        else current_webhook
    )
    current_reminder_webhook = notifications.get("adminReminderWebhookUrl", "")
    reminder_webhook = validate_discord_webhook_url(
        payload.get("adminReminderWebhookUrl", current_reminder_webhook)
    )
    current_reminder_interval = notifications.get(
        "adminReminderIntervalMinutes",
        DEFAULT_ADMIN_REMINDER_INTERVAL_MINUTES,
    )
    try:
        reminder_interval = int(payload.get("adminReminderIntervalMinutes", current_reminder_interval))
    except (TypeError, ValueError) as exc:
        raise ValueError("Admin reminder interval must be a whole number of minutes.") from exc
    if not MIN_ADMIN_REMINDER_INTERVAL_MINUTES <= reminder_interval <= MAX_ADMIN_REMINDER_INTERVAL_MINUTES:
        raise ValueError("Admin reminder interval must be between 1 and 10080 minutes.")

    qbit_url = str(qbit.get("url", "")).strip().rstrip("/")
    current_version = config.get("app", {}).get("version", DEFAULT_APP_VERSION)
    app_version = str(app["version"] if "version" in app else current_version).strip()
    if not app_version:
        raise ValueError("App version is required.")
    if len(app_version) > 32 or any(ord(character) < 32 for character in app_version):
        raise ValueError("App version must be 32 characters or fewer and contain plain text only.")
    if not qbit_url:
        raise ValueError("qBittorrent URL is required.")
    if not isinstance(destinations, list) or not destinations:
        raise ValueError("At least one destination is required.")

    config.setdefault("app", {})["version"] = app_version
    config.setdefault("qbittorrent", {})["url"] = qbit_url
    config.setdefault("plex", {})["databasePath"] = str(plex.get("databasePath", "")).strip()
    notifications["discordUserMappings"] = discord_mappings
    notifications["discordWebhookUrl"] = webhook
    notifications["adminReminderWebhookUrl"] = reminder_webhook
    notifications["adminReminderIntervalMinutes"] = reminder_interval

    used = set()
    cleaned_destinations = []
    for item in destinations:
        if not isinstance(item, dict):
            continue
        label = str(item.get("label", "")).strip()
        raw_paths = item.get("paths") if isinstance(item.get("paths"), list) else [item.get("path", "")]
        paths = destination_paths({"paths": raw_paths})
        if not label or not paths:
            raise ValueError("Destination label and at least one path are required.")
        raw_id = str(item.get("id", "")).strip()
        item_id = raw_id if raw_id and raw_id not in used else destination_id(label, used)
        used.add(item_id)
        cleaned_destinations.append({
            "id": item_id,
            "label": label,
            "path": paths[0],
            "paths": paths,
            "browseSubfolders": bool(item.get("browseSubfolders")),
        })

    config["destinations"] = cleaned_destinations
