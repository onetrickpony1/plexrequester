from http import HTTPStatus
from http.server import ThreadingHTTPServer, BaseHTTPRequestHandler
from http.cookies import SimpleCookie
from pathlib import Path
from urllib import request, parse, error
from http.cookiejar import CookieJar
import base64
import difflib
import hashlib
import json
import mimetypes
import os
import re
import shutil
import secrets
import socket
import sqlite3
import tempfile
import threading
import time

from plex_requester import api as api_service
from plex_requester import auth as auth_service
from plex_requester import config as config_service
from plex_requester import discord as discord_service
from plex_requester import plex as plex_service
from plex_requester import qbittorrent as qbittorrent_service
from plex_requester import requests as requests_service
from plex_requester import storage as storage_service
from plex_requester import tmdb as tmdb_service


BASE_DIR = Path(__file__).resolve().parent
STATIC_DIR = BASE_DIR / "static"
REQUEST_LOCK = threading.RLock()
NOTIFICATION_OUTBOX_LOCK = threading.RLock()
PLEX_ANALYSIS_CACHE_LOCK = plex_service.PLEX_ANALYSIS_CACHE_LOCK
PLEX_ANALYSIS_CACHE = plex_service.PLEX_ANALYSIS_CACHE
PLEX_ANALYSIS_CACHE_SECONDS = plex_service.PLEX_ANALYSIS_CACHE_SECONDS
MAX_TORRENT_FILE_SIZE = 10 * 1024 * 1024
DEFAULT_APP_VERSION = config_service.DEFAULT_APP_VERSION
DEFAULT_SERVER_PORT = config_service.DEFAULT_SERVER_PORT
DISCORD_EMBED_MAX_FIELDS = 25
DISCORD_EMBED_MAX_CHARACTERS = 6000
DISCORD_REMINDER_FIELDS_CHARACTER_BUDGET = 5400
NOTIFICATION_RETRY_BASE_SECONDS = 15
NOTIFICATION_RETRY_MAX_SECONDS = 60 * 60
NOTIFICATION_SENT_RETENTION_SECONDS = 30 * 24 * 60 * 60
NOTIFICATION_OUTBOX_MAX_COMPLETED = 1000
DEFAULT_ADMIN_REMINDER_INTERVAL_MINUTES = 60
MIN_ADMIN_REMINDER_INTERVAL_MINUTES = 1
MAX_ADMIN_REMINDER_INTERVAL_MINUTES = 7 * 24 * 60
DESTINATION_FULL_PERCENT = 90
USER_DATA_FILES = storage_service.USER_DATA_FILES


def user_data_dir():
    return storage_service.user_data_dir(os.environ)


def user_data_path(file_name):
    return storage_service.user_data_path(file_name, BASE_DIR, os.environ)


def atomic_write_json(path, payload):
    return storage_service.atomic_write_json(path, payload)


MagnetAlreadyExists = qbittorrent_service.MagnetAlreadyExists
def configured_server_port(config):
    return config_service.configured_server_port(config)


def load_config():
    return config_service.load_config(BASE_DIR, user_data_path, os.environ)


QbittorrentClient = qbittorrent_service.QbittorrentClient
magnet_hash = qbittorrent_service.magnet_hash
qbit_add_torrent_hash = qbittorrent_service.qbit_add_torrent_hash
torrent_info_hash = qbittorrent_service.torrent_info_hash
decode_torrent_upload = qbittorrent_service.decode_torrent_upload
validate_subfolder_name = storage_service.validate_subfolder_name
MEDIA_FILE_EXTENSIONS = qbittorrent_service.MEDIA_FILE_EXTENSIONS
validate_download_name = qbittorrent_service.validate_download_name
media_file_extension = qbittorrent_service.media_file_extension
renamed_file_path = qbittorrent_service.renamed_file_path
record_rename_history = qbittorrent_service.record_rename_history
torrent_item_path = qbittorrent_service.torrent_item_path
top_level_folder_names = qbittorrent_service.top_level_folder_names
rename_content_when_ready = qbittorrent_service.rename_content_when_ready
destination_path = storage_service.destination_path
join_destination_path = storage_service.join_destination_path
folder_path = storage_service.folder_path
list_subfolders = storage_service.list_subfolders
destination_paths = storage_service.destination_paths


def disk_usage_for_path(path):
    return storage_service.disk_usage_for_path(path)


def destination_directory_choices(destination):
    return storage_service.destination_directory_choices(destination, disk_usage_for_path)


find_destination_parent_folder = storage_service.find_destination_parent_folder


def destination_base_path(destination, path_index=None):
    return storage_service.destination_base_path(destination, path_index, destination_directory_choices)


directory_size = storage_service.directory_size
storage_summary = storage_service.storage_summary

def request_store_path():
    return user_data_path("requests.json")


def load_requests():
    path = request_store_path()
    if not path.exists():
        return []
    try:
        with path.open("r", encoding="utf-8") as handle:
            data = json.load(handle)
        return data if isinstance(data, list) else []
    except (OSError, json.JSONDecodeError):
        return []


def save_requests(items):
    atomic_write_json(request_store_path(), items)


def fulfillment_state_path():
    return user_data_path("request-fulfillment-state.json")


def load_fulfillment_state():
    path = fulfillment_state_path()
    if not path.exists():
        return {}
    try:
        with path.open("r", encoding="utf-8") as handle:
            data = json.load(handle)
        return data if isinstance(data, dict) else {}
    except (OSError, json.JSONDecodeError):
        return {}


def save_fulfillment_state(state):
    atomic_write_json(fulfillment_state_path(), state)


def notification_outbox_path():
    return user_data_path("notification-outbox.json")


def load_notification_outbox():
    path = notification_outbox_path()
    if not path.exists():
        return []
    try:
        with path.open("r", encoding="utf-8") as handle:
            data = json.load(handle)
        return data if isinstance(data, list) else []
    except (OSError, json.JSONDecodeError):
        return []


def save_notification_outbox(items):
    atomic_write_json(notification_outbox_path(), items)


request_quality = requests_service.request_quality
quality_satisfies_request = requests_service.quality_satisfies_request
int_value = plex_service.int_value
media_resolution_height = plex_service.media_resolution_height
media_item_bitrate_kbps = plex_service.media_item_bitrate_kbps
media_bitrate = plex_service.media_bitrate
video_stream_for_media = plex_service.video_stream_for_media
media_analysis_complete = plex_service.media_analysis_complete
classify_media_quality = plex_service.classify_media_quality
bitrate_label = plex_service.bitrate_label
average_episode_bitrate = plex_service.average_episode_bitrate
media_quality_summary = plex_service.media_quality_summary
media_rows_for_library_item_connection = plex_service.media_rows_for_library_item_connection
media_rows_for_library_item = plex_service.media_rows_for_library_item
quality_warning = plex_service.quality_warning
strict_plex_matches = plex_service.strict_plex_matches
plex_match_for_tmdb = plex_service.plex_match_for_tmdb
plex_analysis_cache_key = plex_service.plex_analysis_cache_key
plex_database_path = plex_service.plex_database_path
snapshot_plex_database = plex_service.snapshot_plex_database
normalize_search_text = plex_service.normalize_search_text
parse_library_query = plex_service.parse_library_query
library_match_score = plex_service.library_match_score
library_match_threshold = plex_service.library_match_threshold
library_match_label = plex_service.library_match_label
row_to_library_item = plex_service.row_to_library_item
sqlite_rows_to_dicts = plex_service.sqlite_rows_to_dicts
sqlite_table_columns = plex_service.sqlite_table_columns
sqlite_table_exists = plex_service.sqlite_table_exists
fetch_optional_rows = plex_service.fetch_optional_rows
search_plex_database = plex_service.search_plex_database
plex_item_details = plex_service.plex_item_details

def plex_analysis_for_tmdb(config, tmdb_item):
    return plex_service.plex_analysis_for_tmdb(
        config, tmdb_item, plex_match_for_tmdb, media_rows_for_library_item
    )


def library_warning_for_request(config, tmdb_item, requested_quality):
    return plex_service.library_warning_for_request(
        config, tmdb_item, requested_quality, plex_analysis_for_tmdb
    )


def current_request_plex_status(config, item):
    return plex_service.current_request_plex_status(config, item, plex_analysis_for_tmdb)


request_fulfillment_from_history = requests_service.request_fulfillment_from_history
requests_service.configure_backend(globals())
initialize_request_fulfillment_state = requests_service.initialize_request_fulfillment_state
manually_fulfill_request = requests_service.manually_fulfill_request
cached_request_fulfillment = requests_service.cached_request_fulfillment
requests_for_display = requests_service.requests_for_display
requests_with_fulfillment = requests_service.requests_with_fulfillment
request_item = requests_service.request_item
add_request = requests_service.add_request
complete_request_creation = requests_service.complete_request_creation
discord_webhook_url = discord_service.discord_webhook_url
secondary_discord_webhook_url = discord_service.secondary_discord_webhook_url
admin_reminder_webhook_url = discord_service.admin_reminder_webhook_url
admin_reminder_interval_minutes = discord_service.admin_reminder_interval_minutes
admin_reminder_interval_seconds = discord_service.admin_reminder_interval_seconds
normalize_requester_name = discord_service.normalize_requester_name
validate_discord_user_id = discord_service.validate_discord_user_id
validate_discord_webhook_url = discord_service.validate_discord_webhook_url
clean_discord_user_mappings = discord_service.clean_discord_user_mappings
discord_user_id_for_requester = discord_service.discord_user_id_for_requester
request_display_title = discord_service.request_display_title
tmdb_url_for_item = discord_service.tmdb_url_for_item
tmdb_poster_url_for_item = discord_service.tmdb_poster_url_for_item
discord_request_embed = discord_service.discord_request_embed
discord_fulfillment_detail = discord_service.discord_fulfillment_detail
discord_fulfillment_embed = discord_service.discord_fulfillment_embed
discord_waiting_time = discord_service.discord_waiting_time
discord_admin_reminder_field = discord_service.discord_admin_reminder_field
discord_embed_character_count = discord_service.discord_embed_character_count
discord_admin_reminder_embed = discord_service.discord_admin_reminder_embed
discord_admin_reminder_embeds = discord_service.discord_admin_reminder_embeds

discord_service.configure_backend(globals())
send_discord_webhook = discord_service.send_discord_webhook
notification_target_url = discord_service.notification_target_url
notification_job_id = discord_service.notification_job_id
notification_retry_delay = discord_service.notification_retry_delay
prune_notification_outbox = discord_service.prune_notification_outbox
process_notification_outbox = discord_service.process_notification_outbox
queue_discord_notification = discord_service.queue_discord_notification
queue_request_notifications = discord_service.queue_request_notifications
request_notification_identity = discord_service.request_notification_identity
notify_request_created = discord_service.notify_request_created
notify_request_fulfilled = discord_service.notify_request_fulfilled
notify_admin_unfulfilled_requests = discord_service.notify_admin_unfulfilled_requests
send_due_admin_reminders = discord_service.send_due_admin_reminders


fulfillment_check_interval = requests_service.fulfillment_check_interval
fulfillment_monitor_loop = requests_service.fulfillment_monitor_loop
delete_request = requests_service.delete_request
set_request_reminder_muted = requests_service.set_request_reminder_muted
qbit_client_from_config = qbittorrent_service.qbit_client_from_config
qbit_state_error = qbittorrent_service.qbit_state_error
qbit_torrent_filters = qbittorrent_service.qbit_torrent_filters
public_qbit_status = qbittorrent_service.public_qbit_status

def qbit_status_summary(config):
    return qbittorrent_service.qbit_status_summary(config, qbit_client_from_config)


def config_for_save(config):
    return config_service.config_for_save(config)


def save_config(config):
    path = Path(config.get("_save_config_path") or config.get("_config_path") or user_data_path("config.json"))
    atomic_write_json(path, config_for_save(config))
    config["_config_path"] = str(path)
    config["_save_config_path"] = str(path)
    config["_using_example_config"] = False


def admin_pin(config):
    return auth_service.admin_pin(config)


def pin_matches(config, value):
    return auth_service.pin_matches(config, value)


def role_from_pin(config, value):
    return auth_service.role_from_pin(config, value)


admin_pin_is_valid = auth_service.admin_pin_is_valid
login_rate_limit_key = auth_service.login_rate_limit_key
login_retry_after = auth_service.login_retry_after
record_failed_login = auth_service.record_failed_login
clear_failed_logins = auth_service.clear_failed_logins
ADMIN_PIN_MIN_LENGTH = auth_service.ADMIN_PIN_MIN_LENGTH
ADMIN_PIN_MAX_LENGTH = auth_service.ADMIN_PIN_MAX_LENGTH
AUTH_MAX_FAILED_ATTEMPTS = auth_service.AUTH_MAX_FAILED_ATTEMPTS
AUTH_FAILURE_WINDOW = auth_service.AUTH_FAILURE_WINDOW
AUTH_LOCKOUT_SECONDS = auth_service.AUTH_LOCKOUT_SECONDS
AUTH_COOKIE_NAME = auth_service.AUTH_COOKIE_NAME
AUTH_SESSION_TTL = auth_service.AUTH_SESSION_TTL
AUTH_REFRESH_AFTER = auth_service.AUTH_REFRESH_AFTER


def auth_store_path():
    return user_data_path("auth-sessions.json")


def load_auth_sessions():
    path = auth_store_path()
    if not path.exists():
        return {}
    try:
        with path.open("r", encoding="utf-8") as handle:
            data = json.load(handle)
        return data if isinstance(data, dict) else {}
    except (OSError, json.JSONDecodeError):
        return {}


def save_auth_sessions(sessions):
    atomic_write_json(auth_store_path(), sessions)


def prune_auth_sessions(sessions):
    return auth_service.prune_auth_sessions(sessions)


def create_auth_session(role):
    return auth_service.create_auth_session(role, load_auth_sessions, save_auth_sessions)


def session_cookie_header(token):
    return auth_service.session_cookie_header(token)


def expired_session_cookie_header():
    return auth_service.expired_session_cookie_header()


destination_id = config_service.destination_id
editable_config = config_service.editable_config
apply_editable_config = config_service.apply_editable_config

tmdb_api_key = tmdb_service.tmdb_api_key
split_tmdb_query = tmdb_service.split_tmdb_query
clean_folder_name = tmdb_service.clean_folder_name
tmdb_folder_name = tmdb_service.tmdb_folder_name
tmdb_request = tmdb_service.tmdb_request
normalize_tmdb_item = tmdb_service.normalize_tmdb_item
search_tmdb = tmdb_service.search_tmdb

api_service.configure_backend(globals())
AppHandler = api_service.AppHandler
AppServer = api_service.AppServer


def start_parent_process_monitor(app_server):
    """Stop a packaged backend if its native launcher disappears unexpectedly."""
    parent_value = str(os.environ.get("PLEX_REQUESTER_PARENT_PID", "")).strip()
    if os.name != "nt" or not parent_value.isdigit():
        return None
    parent_pid = int(parent_value)
    if parent_pid <= 0:
        return None

    def wait_for_parent():
        import ctypes

        synchronize = 0x00100000
        infinite = 0xFFFFFFFF
        kernel32 = ctypes.windll.kernel32
        handle = kernel32.OpenProcess(synchronize, False, parent_pid)
        if not handle:
            return
        try:
            kernel32.WaitForSingleObject(handle, infinite)
        finally:
            kernel32.CloseHandle(handle)
        app_server.shutdown()

    monitor = threading.Thread(
        target=wait_for_parent,
        daemon=True,
        name="PlexRequesterParentMonitor",
    )
    monitor.start()
    return monitor


def main():
    config = load_config()
    host = os.environ.get("APP_HOST", "0.0.0.0")
    port = int(os.environ.get("APP_PORT", configured_server_port(config)))
    server = AppServer((host, port), AppHandler, config)
    start_parent_process_monitor(server)
    print(f"Plex Requester listening on http://{host}:{port}")
    print("Use the device's current Tailscale hostname or IP from another device.")
    server.serve_forever()


if __name__ == "__main__":
    main()
