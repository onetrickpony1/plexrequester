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


BASE_DIR = Path(__file__).resolve().parent
STATIC_DIR = BASE_DIR / "static"
REQUEST_LOCK = threading.RLock()
PLEX_ANALYSIS_CACHE_LOCK = threading.RLock()
PLEX_ANALYSIS_CACHE = {}
PLEX_ANALYSIS_CACHE_SECONDS = 60
MAX_TORRENT_FILE_SIZE = 10 * 1024 * 1024
DEFAULT_APP_VERSION = "v8.1"
DEFAULT_SERVER_PORT = 8003
DEFAULT_ADMIN_REMINDER_INTERVAL_MINUTES = 60
MIN_ADMIN_REMINDER_INTERVAL_MINUTES = 1
MAX_ADMIN_REMINDER_INTERVAL_MINUTES = 7 * 24 * 60
DESTINATION_FULL_PERCENT = 90
USER_DATA_FILES = (
    "config.json",
    "requests.json",
    "request-fulfillment-state.json",
    "auth-sessions.json",
    "rename-history.jsonl",
    "plex-requester.log",
)


def user_data_dir():
    override = str(os.environ.get("PLEX_REQUESTER_DATA_DIR", "")).strip()
    if override:
        return Path(override).expanduser()
    local_app_data = str(os.environ.get("LOCALAPPDATA", "")).strip()
    if local_app_data:
        return Path(local_app_data) / "Plex Requester"
    return Path.home() / "AppData" / "Local" / "Plex Requester"


def user_data_path(file_name):
    data_dir = user_data_dir()
    data_dir.mkdir(parents=True, exist_ok=True)
    target = data_dir / file_name
    legacy = BASE_DIR / file_name
    if not target.exists() and legacy.exists() and legacy.resolve() != target.resolve():
        shutil.copy2(legacy, target)
        print(f"Migrated {file_name} to {target}", flush=True)
    return target


class MagnetAlreadyExists(RuntimeError):
    def __init__(self, torrent_hash):
        super().__init__("This magnet link is already present in qBittorrent.")
        self.torrent_hash = torrent_hash


def configured_server_port(config):
    server_config = config.get("server", {})
    if not isinstance(server_config, dict):
        return DEFAULT_SERVER_PORT
    try:
        port = int(server_config.get("port", DEFAULT_SERVER_PORT))
    except (TypeError, ValueError):
        return DEFAULT_SERVER_PORT
    return port if 1 <= port <= 65535 else DEFAULT_SERVER_PORT


def load_config():
    configured_path = str(os.environ.get("APP_CONFIG", "")).strip()
    if configured_path:
        config_path = Path(configured_path)
        if not config_path.is_absolute():
            config_path = BASE_DIR / config_path
        save_config_path = config_path
    else:
        config_path = user_data_path("config.json")
        save_config_path = config_path

    using_example = False
    if not config_path.exists():
        config_path = BASE_DIR / "config.example.json"
        using_example = True

    with config_path.open("r", encoding="utf-8") as handle:
        config = json.load(handle)

    qbit = config.setdefault("qbittorrent", {})
    qbit["url"] = os.environ.get("QBIT_URL", qbit.get("url", "http://127.0.0.1:8080")).rstrip("/")
    qbit["username"] = os.environ.get("QBIT_USERNAME", qbit.get("username", "admin"))
    qbit["password"] = os.environ.get("QBIT_PASSWORD", qbit.get("password", ""))
    plex = config.setdefault("plex", {})
    plex["databasePath"] = os.environ.get("PLEX_DATABASE_PATH", plex.get("databasePath", ""))
    tmdb = config.setdefault("tmdb", {})
    tmdb["apiKey"] = os.environ.get("TMDB_API_KEY", tmdb.get("apiKey", ""))
    notifications = config.setdefault("notifications", {})
    notifications["discordWebhookUrl"] = os.environ.get(
        "DISCORD_WEBHOOK_URL",
        notifications.get("discordWebhookUrl", ""),
    )
    notifications["adminReminderWebhookUrl"] = os.environ.get(
        "DISCORD_ADMIN_REMINDER_WEBHOOK_URL",
        notifications.get("adminReminderWebhookUrl", ""),
    )
    notifications["adminReminderIntervalMinutes"] = os.environ.get(
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
    config["adminPin"] = str(os.environ.get("ADMIN_PIN", config.get("adminPin", "")))
    config.setdefault("destinations", [])
    config["_config_path"] = str(config_path)
    config["_save_config_path"] = str(save_config_path)
    config["_using_example_config"] = using_example
    return config


class QbittorrentClient:
    def __init__(self, base_url, username, password):
        self.base_url = base_url.rstrip("/")
        self.username = username
        self.password = password
        parsed = parse.urlparse(self.base_url)
        self.origin = f"{parsed.scheme}://{parsed.netloc}"
        self.cookies = CookieJar()
        self.opener = request.build_opener(request.HTTPCookieProcessor(self.cookies))

    def _request(self, method, path, data=None):
        headers = {
            "User-Agent": "Mozilla/5.0 TailscaleMagnetDrop/1.0",
            "Accept": "application/json, text/plain, */*",
            "Referer": f"{self.origin}/",
        }

        body = None
        if data is not None:
            body = parse.urlencode(data).encode("utf-8")
            headers["Content-Type"] = "application/x-www-form-urlencoded"
            headers["Origin"] = self.origin

        req = request.Request(f"{self.base_url}{path}", data=body, headers=headers, method=method)
        try:
            with self.opener.open(req, timeout=15) as response:
                return response.read().decode("utf-8", errors="replace")
        except error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")
            if exc.code == HTTPStatus.UNAUTHORIZED:
                detail = detail or "unauthorized"
                raise RuntimeError(
                    f"qBittorrent returned HTTP 401: {detail}. "
                    "The Web UI rejected the configured credentials or session cookie."
                ) from exc
            raise RuntimeError(f"qBittorrent returned HTTP {exc.code}: {detail or exc.reason}") from exc
        except error.URLError as exc:
            raise RuntimeError(f"Could not reach qBittorrent at {self.base_url}: {exc.reason}") from exc

    def _multipart_request(self, path, fields, file_name, file_data):
        boundary = "----PlexRequester" + secrets.token_hex(16)
        chunks = []
        for name, value in fields.items():
            chunks.extend([
                f"--{boundary}\r\n".encode("ascii"),
                f'Content-Disposition: form-data; name="{name}"\r\n\r\n'.encode("ascii"),
                str(value).encode("utf-8"),
                b"\r\n",
            ])

        safe_name = re.sub(r'[^A-Za-z0-9._ -]', "_", Path(file_name).name) or "upload.torrent"
        chunks.extend([
            f"--{boundary}\r\n".encode("ascii"),
            f'Content-Disposition: form-data; name="torrents"; filename="{safe_name}"\r\n'.encode("ascii"),
            b"Content-Type: application/x-bittorrent\r\n\r\n",
            file_data,
            b"\r\n",
            f"--{boundary}--\r\n".encode("ascii"),
        ])
        headers = {
            "User-Agent": "Mozilla/5.0 TailscaleMagnetDrop/1.0",
            "Accept": "application/json, text/plain, */*",
            "Referer": f"{self.origin}/",
            "Origin": self.origin,
            "Content-Type": f"multipart/form-data; boundary={boundary}",
        }
        req = request.Request(
            f"{self.base_url}{path}",
            data=b"".join(chunks),
            headers=headers,
            method="POST",
        )
        try:
            with self.opener.open(req, timeout=30) as response:
                return response.read().decode("utf-8", errors="replace")
        except error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")
            if exc.code == HTTPStatus.UNAUTHORIZED:
                raise RuntimeError(
                    "qBittorrent returned HTTP 401: unauthorized. "
                    "The Web UI rejected the configured credentials or session cookie."
                ) from exc
            raise RuntimeError(f"qBittorrent returned HTTP {exc.code}: {detail or exc.reason}") from exc
        except error.URLError as exc:
            raise RuntimeError(f"Could not reach qBittorrent at {self.base_url}: {exc.reason}") from exc

    def _get_json(self, path):
        response = self._request("GET", path)
        return json.loads(response)

    def login(self):
        result = self._request(
            "POST",
            "/api/v2/auth/login",
            {"username": self.username, "password": self.password},
        )
        reply = result.strip()
        if reply != "Ok.":
            if not reply:
                reply = "empty response"
            raise RuntimeError(
                "qBittorrent login failed. "
                f"qBittorrent replied: {reply}. "
                "Check the Web UI username/password and qBittorrent Web UI security settings."
            )

    def add_magnet(self, magnet_link, destination, download_name=None):
        self.ensure_authenticated_for_write()
        torrent_hash = magnet_hash(magnet_link)
        if torrent_hash and self.has_torrent(torrent_hash):
            raise MagnetAlreadyExists(torrent_hash)

        payload = {
            "urls": magnet_link,
            "savepath": destination,
        }
        if download_name:
            payload["rename"] = download_name

        self._request(
            "POST",
            "/api/v2/torrents/add",
            payload,
        )
        if torrent_hash and download_name:
            self.rename_download_file_later(torrent_hash, download_name)

    def add_torrent_file(self, file_name, file_data, destination, download_name=None):
        self.ensure_authenticated_for_write()
        torrent_hash = torrent_info_hash(file_data)
        if self.has_torrent(torrent_hash):
            raise MagnetAlreadyExists(torrent_hash)

        fields = {"savepath": destination}
        if download_name:
            fields["rename"] = download_name
        result = self._multipart_request(
            "/api/v2/torrents/add",
            fields,
            file_name,
            file_data,
        )
        torrent_hash = qbit_add_torrent_hash(result, torrent_hash)
        if download_name:
            self.rename_download_file_later(torrent_hash, download_name)

    def torrent_files(self, torrent_hash):
        return self._get_json("/api/v2/torrents/files?" + parse.urlencode({"hash": torrent_hash}))

    def torrents_info(self):
        query = parse.urlencode({"sort": "added_on", "reverse": "true"})
        return self._get_json("/api/v2/torrents/info?" + query)

    def transfer_info(self):
        return self._get_json("/api/v2/transfer/info")

    def set_session_paused(self, paused):
        self.ensure_authenticated_for_write()
        endpoint = "/api/v2/torrents/stop" if paused else "/api/v2/torrents/start"
        legacy_endpoint = "/api/v2/torrents/pause" if paused else "/api/v2/torrents/resume"
        try:
            self._request("POST", endpoint, {"hashes": "all"})
        except RuntimeError as exc:
            if "HTTP 404" not in str(exc):
                raise
            self._request("POST", legacy_endpoint, {"hashes": "all"})

    def rename_file(self, torrent_hash, old_path, new_path):
        self._request(
            "POST",
            "/api/v2/torrents/renameFile",
            {
                "hash": torrent_hash,
                "oldPath": old_path,
                "newPath": new_path,
            },
        )

    def rename_folder(self, torrent_hash, old_path, new_path):
        self._request(
            "POST",
            "/api/v2/torrents/renameFolder",
            {
                "hash": torrent_hash,
                "oldPath": old_path,
                "newPath": new_path,
            },
        )

    def rename_download_file_later(self, torrent_hash, download_name):
        config = {
            "url": self.base_url,
            "username": self.username,
            "password": self.password,
        }
        thread = threading.Thread(
            target=rename_content_when_ready,
            args=(config, torrent_hash, download_name),
            daemon=True,
        )
        thread.start()

    def app_version(self):
        if not self.has_session_or_bypass():
            self.login()
        return self._request("GET", "/api/v2/app/version")

    def has_torrent(self, torrent_hash):
        wanted = torrent_hash.lower()
        torrents = self._get_json("/api/v2/torrents/info")
        return any(str(torrent.get("hash", "")).lower() == wanted for torrent in torrents)

    def has_session_or_bypass(self):
        try:
            self._request("GET", "/api/v2/app/version")
            return True
        except RuntimeError:
            return False

    def ensure_authenticated_for_write(self):
        try:
            self.login()
        except RuntimeError as login_error:
            if self.has_session_or_bypass():
                return
            raise login_error


def magnet_hash(magnet_link):
    parsed = parse.urlparse(magnet_link)
    params = parse.parse_qs(parsed.query)
    for value in params.get("xt", []):
        prefix = "urn:btih:"
        if not value.lower().startswith(prefix):
            continue

        raw_hash = value[len(prefix):].strip()
        if len(raw_hash) == 40:
            return raw_hash.lower()
        if len(raw_hash) == 32:
            try:
                return base64.b32decode(raw_hash.upper()).hex()
            except ValueError:
                return None
    return None


def qbit_add_torrent_hash(response, fallback_hash):
    text = str(response or "").strip()
    if not text or text == "Ok.":
        return fallback_hash

    try:
        result = json.loads(text)
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"qBittorrent rejected the torrent file: {text}") from exc

    if not isinstance(result, dict):
        raise RuntimeError(f"qBittorrent rejected the torrent file: {text}")

    failure_count = int(result.get("failure_count") or 0)
    success_count = int(result.get("success_count") or 0)
    pending_count = int(result.get("pending_count") or 0)
    added_ids = result.get("added_torrent_ids") or []
    if failure_count == 0 and (success_count > 0 or pending_count > 0 or added_ids):
        for torrent_id in added_ids:
            candidate = str(torrent_id or "").lower()
            if re.fullmatch(r"[0-9a-f]{40}", candidate):
                return candidate
        return fallback_hash

    raise RuntimeError(f"qBittorrent rejected the torrent file: {text}")


def _bencode_value_end(data, index):
    if index >= len(data):
        raise ValueError("Torrent file contains incomplete bencoded data.")
    marker = data[index:index + 1]
    if marker == b"i":
        end = data.find(b"e", index + 1)
        if end < 0 or not re.fullmatch(rb"-?(0|[1-9][0-9]*)", data[index + 1:end]):
            raise ValueError("Torrent file contains an invalid integer.")
        return end + 1
    if marker in {b"l", b"d"}:
        cursor = index + 1
        while cursor < len(data) and data[cursor:cursor + 1] != b"e":
            cursor = _bencode_value_end(data, cursor)
        if cursor >= len(data):
            raise ValueError("Torrent file contains an incomplete list or dictionary.")
        return cursor + 1
    if marker.isdigit():
        colon = data.find(b":", index)
        if colon < 0 or not data[index:colon].isdigit():
            raise ValueError("Torrent file contains an invalid byte string.")
        length = int(data[index:colon])
        end = colon + 1 + length
        if end > len(data):
            raise ValueError("Torrent file contains an incomplete byte string.")
        return end
    raise ValueError("Torrent file is not valid bencoded data.")


def _bencode_string(data, index):
    colon = data.find(b":", index)
    if colon < 0 or not data[index:colon].isdigit():
        raise ValueError("Torrent file contains an invalid dictionary key.")
    length = int(data[index:colon])
    start = colon + 1
    end = start + length
    if end > len(data):
        raise ValueError("Torrent file contains an incomplete dictionary key.")
    return data[start:end], end


def torrent_info_hash(data):
    if not data or data[:1] != b"d":
        raise ValueError("The uploaded file is not a valid .torrent file.")
    cursor = 1
    while cursor < len(data) and data[cursor:cursor + 1] != b"e":
        key, cursor = _bencode_string(data, cursor)
        value_start = cursor
        cursor = _bencode_value_end(data, cursor)
        if key == b"info":
            if data[value_start:value_start + 1] != b"d":
                raise ValueError("The torrent file contains an invalid info dictionary.")
            return hashlib.sha1(data[value_start:cursor]).hexdigest()
    raise ValueError("The torrent file does not contain an info dictionary.")


def decode_torrent_upload(payload):
    file_name = Path(str(payload.get("torrentFileName", "")).strip()).name
    encoded = str(payload.get("torrentData", "")).strip()
    if not file_name.lower().endswith(".torrent"):
        raise ValueError("Choose a .torrent file.")
    if not encoded:
        raise ValueError("The uploaded torrent file is empty.")
    try:
        file_data = base64.b64decode(encoded, validate=True)
    except (ValueError, TypeError) as exc:
        raise ValueError("The uploaded torrent file could not be decoded.") from exc
    if len(file_data) > MAX_TORRENT_FILE_SIZE:
        raise ValueError("Torrent files must be 10 MB or smaller.")
    torrent_info_hash(file_data)
    return file_name, file_data


def validate_subfolder_name(subfolder_name):
    cleaned = str(subfolder_name or "").strip()
    if not cleaned:
        raise ValueError("Enter a subfolder name, or turn off the subfolder option.")
    if cleaned in {".", ".."} or "/" in cleaned or "\\" in cleaned:
        raise ValueError("Subfolder name cannot contain slashes or path traversal.")
    if re.search(r'[<>:"|?*\x00-\x1f]', cleaned):
        raise ValueError('Subfolder name cannot contain these characters: < > : " | ? *')
    return cleaned


MEDIA_FILE_EXTENSIONS = {
    ".avi", ".m2ts", ".m4v", ".mkv", ".mov", ".mp4", ".mpeg", ".mpg", ".ts", ".webm", ".wmv",
}


def validate_download_name(download_name):
    cleaned = str(download_name or "").strip()
    if not cleaned:
        return ""
    if cleaned in {".", ".."} or "/" in cleaned or "\\" in cleaned:
        raise ValueError("Download name cannot contain slashes or path traversal.")
    if re.search(r'[<>:"|?*\x00-\x1f]', cleaned):
        raise ValueError('Download name cannot contain these characters: < > : " | ? *')
    return cleaned.rstrip(" .")


def media_file_extension(path):
    return Path(str(path or "")).suffix.lower()


def renamed_file_path(old_path, download_name):
    directory = str(old_path or "").replace("\\", "/").rsplit("/", 1)
    extension = media_file_extension(old_path)
    cleaned_name = validate_download_name(download_name)
    filename = cleaned_name if media_file_extension(cleaned_name) in MEDIA_FILE_EXTENSIONS else cleaned_name + extension
    if len(directory) == 2:
        return directory[0] + "/" + filename
    return filename


def record_rename_history(torrent_hash, old_path, new_path):
    entry = {
        "time": int(time.time()),
        "hash": torrent_hash,
        "originalPath": old_path,
        "newPath": new_path,
    }
    history_path = user_data_path("rename-history.jsonl")
    with history_path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(entry) + "\n")


def torrent_item_path(item):
    return str(item.get("name", "")).replace("\\", "/").strip("/")


def top_level_folder_names(files):
    folders = set()
    root_files = []
    for item in files:
        path = torrent_item_path(item)
        if not path:
            continue
        parts = path.split("/", 1)
        if len(parts) == 2:
            folders.add(parts[0])
        else:
            root_files.append(path)
    return folders, root_files


def rename_content_when_ready(qbit_config, torrent_hash, download_name):
    client = QbittorrentClient(qbit_config["url"], qbit_config["username"], qbit_config["password"])
    try:
        client.ensure_authenticated_for_write()
        for _ in range(24):
            files = client.torrent_files(torrent_hash)
            folders, root_files = top_level_folder_names(files)
            if len(folders) == 1 and not root_files:
                old_folder = next(iter(folders))
                new_folder = validate_download_name(download_name)
                if old_folder and new_folder and old_folder != new_folder:
                    client.rename_folder(torrent_hash, old_folder, new_folder)
                    record_rename_history(torrent_hash, old_folder, new_folder)
                    print(f"Renamed torrent folder through qBittorrent: {old_folder} -> {new_folder}")
                return
            if len(folders) > 1 or (folders and root_files):
                print("Skipped rename because the torrent has multiple top-level items.")
                return

            media_files = [
                item for item in files
                if media_file_extension(item.get("name")) in MEDIA_FILE_EXTENSIONS
            ]
            if len(media_files) == 1:
                old_path = media_files[0].get("name", "")
                new_path = renamed_file_path(old_path, download_name)
                if old_path and new_path and old_path != new_path:
                    client.rename_file(torrent_hash, old_path, new_path)
                    record_rename_history(torrent_hash, old_path, new_path)
                    print(f"Renamed torrent file through qBittorrent: {old_path} -> {new_path}")
                return
            if len(media_files) > 1:
                print("Skipped file rename because the torrent contains multiple root media files.")
                return
            time.sleep(5)
        print("Skipped rename because qBittorrent did not expose torrent files in time.")
    except Exception as exc:
        print(f"Could not rename torrent content through qBittorrent: {exc}")


def destination_path(base_path, use_subfolder, subfolder_name):
    if not use_subfolder:
        return base_path

    return join_destination_path(base_path, [validate_subfolder_name(subfolder_name)])


def join_destination_path(base_path, subfolders):
    separator = "\\" if "\\" in base_path and "/" not in base_path else "/"
    cleaned = [validate_subfolder_name(folder) for folder in subfolders if str(folder or "").strip()]
    if not cleaned:
        return base_path
    return base_path.rstrip("/\\") + separator + separator.join(cleaned)


def folder_path(base_path, subfolders=None):
    path = Path(base_path)
    for subfolder in subfolders or []:
        path = path / validate_subfolder_name(subfolder)
    return path


def list_subfolders(base_path, parent_subfolders=None):
    path = folder_path(base_path, parent_subfolders)
    if not path.exists() or not path.is_dir():
        return []

    return sorted(
        item.name
        for item in path.iterdir()
        if item.is_dir() and not item.name.startswith(".")
    )


def destination_paths(destination):
    raw_paths = destination.get("paths")
    if not isinstance(raw_paths, list):
        raw_paths = [destination.get("path", "")]
    paths = []
    seen = set()
    for value in raw_paths:
        path = str(value or "").strip()
        normalized = path.rstrip("/\\").casefold()
        if not path or normalized in seen:
            continue
        seen.add(normalized)
        paths.append(path)
    legacy_path = str(destination.get("path", "")).strip()
    if not paths and legacy_path:
        paths.append(legacy_path)
    return paths


def disk_usage_for_path(path):
    try:
        usage = shutil.disk_usage(path)
    except OSError:
        anchor = Path(path).anchor
        if not anchor:
            return None
        try:
            usage = shutil.disk_usage(anchor)
        except OSError:
            return None
    percent = (usage.used / usage.total * 100) if usage.total else 0
    return {
        "total": usage.total,
        "used": usage.used,
        "free": usage.free,
        "percent": percent,
    }


def destination_directory_choices(destination):
    choices = []
    for index, path in enumerate(destination_paths(destination)):
        usage = disk_usage_for_path(path)
        choices.append({
            "index": index,
            "label": path,
            "usagePercent": round(usage["percent"], 1) if usage else None,
            "eligible": bool(usage and usage["percent"] < DESTINATION_FULL_PERCENT),
            "default": False,
        })
    eligible = [choice for choice in choices if choice["eligible"]]
    known = [choice for choice in choices if choice["usagePercent"] is not None]
    if eligible:
        selected = max(eligible, key=lambda choice: choice["usagePercent"])
    elif known:
        selected = min(known, key=lambda choice: choice["usagePercent"])
    else:
        selected = choices[0] if choices else None
    if selected:
        selected["default"] = True
    return choices


def destination_base_path(destination, path_index=None):
    paths = destination_paths(destination)
    if not paths:
        raise ValueError("The selected destination has no configured directories.")
    if path_index is None or str(path_index).strip() == "":
        choices = destination_directory_choices(destination)
        selected = next((choice for choice in choices if choice["default"]), choices[0])
        return paths[selected["index"]]
    try:
        index = int(path_index)
    except (TypeError, ValueError) as exc:
        raise ValueError("Choose one of the configured destination directories.") from exc
    if index < 0 or index >= len(paths):
        raise ValueError("Choose one of the configured destination directories.")
    return paths[index]


def directory_size(path):
    root = Path(path)
    if not root.exists() or not root.is_dir():
        return None

    total = 0
    for current_root, _, files in os.walk(root):
        for filename in files:
            file_path = Path(current_root) / filename
            try:
                total += file_path.stat().st_size
            except OSError:
                pass
    return total


def storage_summary(config):
    destinations = config.get("destinations", [])
    movie_destination = next((item for item in destinations if "film" in item.get("id", "").lower() or "movie" in item.get("id", "").lower()), None)
    tv_destination = next((item for item in destinations if "tv" in item.get("id", "").lower()), None)
    disk_roots = set()

    rows = []
    for key, destination in (("movies", movie_destination), ("tvShows", tv_destination)):
        if not destination:
            rows.append({"key": key, "label": "Movies" if key == "movies" else "TV Shows", "bytes": None, "exists": False})
            continue

        paths = destination_paths(destination)
        sizes = [directory_size(path) for path in paths]
        size = sum(value for value in sizes if value is not None) if any(value is not None for value in sizes) else None
        for path in paths:
            drive_root = Path(path).anchor
            if drive_root:
                disk_roots.add(drive_root.casefold())
        rows.append({
            "key": key,
            "label": destination["label"],
            "bytes": size,
            "exists": size is not None,
        })

    free = total = used = None
    disk_error = None
    if disk_roots:
        errors = []
        for disk_path in sorted(disk_roots):
            try:
                usage = shutil.disk_usage(disk_path)
                total = (total or 0) + usage.total
                used = (used or 0) + usage.used
                free = (free or 0) + usage.free
            except OSError as exc:
                errors.append(str(exc))
        if errors:
            disk_error = "; ".join(errors)
    else:
        disk_error = "No destination drive is configured."

    return {
        "folders": rows,
        "disk": {
            "totalBytes": total,
            "usedBytes": used,
            "freeBytes": free,
            "error": disk_error,
        },
    }


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
    with request_store_path().open("w", encoding="utf-8") as handle:
        json.dump(items, handle, indent=2)
        handle.write("\n")


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
    with fulfillment_state_path().open("w", encoding="utf-8") as handle:
        json.dump(state, handle, indent=2)
        handle.write("\n")


def request_quality(value):
    quality = str(value or "1080p").strip()
    if quality not in {"1080p", "4K", "REMUX"}:
        return "1080p"
    return quality


def int_value(value):
    try:
        return int(float(value or 0))
    except (TypeError, ValueError):
        return 0


def media_resolution_height(item):
    height = int_value(item.get("height"))
    if height:
        return height

    resolution = str(item.get("video_resolution") or item.get("display_aspect_ratio") or "").lower()
    match = re.search(r"(\d{3,4})", resolution)
    return int(match.group(1)) if match else 0


def media_bitrate(item, stream_rows):
    bitrate = int_value(item.get("bitrate"))
    media_id = item.get("id")
    for stream in stream_rows:
        if str(stream.get("media_item_id")) == str(media_id):
            bitrate = max(bitrate, int_value(stream.get("bitrate")))
    return bitrate


def video_stream_for_media(item, stream_rows):
    media_id = item.get("id")
    candidates = [
        stream for stream in stream_rows
        if str(stream.get("media_item_id")) == str(media_id)
    ]
    video_candidates = [
        stream for stream in candidates
        if str(stream.get("stream_type", stream.get("stream_type_id", ""))).lower() in {"1", "video"}
    ]
    return video_candidates[0] if video_candidates else {}


def media_analysis_complete(media_items, stream_rows):
    if not media_items:
        return False

    for item in media_items:
        stream = video_stream_for_media(item, stream_rows)
        codec = stream.get("codec") or item.get("video_codec") or item.get("codec")
        if not media_bitrate(item, stream_rows):
            return False
        if not (media_resolution_height(item) or int_value(item.get("width"))):
            return False
        if not codec:
            return False
    return True


def classify_media_quality(media_items, stream_rows):
    qualities = set()
    for item in media_items:
        height = media_resolution_height(item)
        width = int_value(item.get("width"))
        bitrate = media_bitrate(item, stream_rows)

        if bitrate >= 30000:
            qualities.add("REMUX")
        if height >= 2000 or width >= 3800:
            qualities.add("4K")
        elif height >= 1000 or width >= 1800:
            qualities.add("1080p")
    return qualities


def bitrate_label(value):
    bitrate = int_value(value)
    if not bitrate:
        return ""
    return f"{round(bitrate / 1000, 1):g} Mbps"


def average_episode_bitrate(media_items, stream_rows):
    episode_bitrates = {}
    for item in media_items:
        episode_id = str(item.get("metadata_item_id") or item.get("id") or "")
        bitrate = media_bitrate(item, stream_rows)
        if episode_id and bitrate:
            episode_bitrates[episode_id] = max(episode_bitrates.get(episode_id, 0), bitrate)
    values = list(episode_bitrates.values())
    return round(sum(values) / len(values)) if values else 0


def media_quality_summary(media_items, stream_rows, average_bitrate=False):
    if not media_items:
        return ""

    best = max(
        media_items,
        key=lambda item: (
            media_bitrate(item, stream_rows),
            int_value(item.get("width")),
            int_value(item.get("height")),
        ),
    )
    stream = video_stream_for_media(best, stream_rows)
    parts = []
    height = media_resolution_height(best)
    width = int_value(best.get("width"))
    bitrate = average_episode_bitrate(media_items, stream_rows) if average_bitrate else media_bitrate(best, stream_rows)
    codec = stream.get("codec") or best.get("video_codec") or best.get("codec")

    if media_bitrate(best, stream_rows) >= 30000:
        parts.append("REMUX")
    elif height >= 2000 or width >= 3800:
        parts.append("4K")
    elif height >= 1000 or width >= 1800:
        parts.append("1080p")

    label = bitrate_label(bitrate)
    if label:
        parts.append(f"{label} average" if average_bitrate else label)
    if codec:
        parts.append(str(codec).upper())
    return " - ".join(parts)


def media_rows_for_library_item_connection(connection, item):
    item_id = item.get("id")

    if item.get("type") == "show":
        media_rows = connection.execute(
            """
            SELECT media.*
            FROM metadata_items season
            JOIN metadata_items episode ON episode.parent_id = season.id
            JOIN media_items media ON media.metadata_item_id = episode.id
            WHERE season.parent_id = ?
              AND season.metadata_type = 3
              AND episode.metadata_type = 4
              AND season.deleted_at IS NULL
              AND episode.deleted_at IS NULL
            """,
            (item_id,),
        ).fetchall()
    else:
        media_rows = connection.execute(
            "SELECT * FROM media_items WHERE metadata_item_id = ?",
            (item_id,),
        ).fetchall()

    media_items = sqlite_rows_to_dicts(media_rows)
    media_ids = [row.get("id") for row in media_items if row.get("id") is not None]
    stream_rows = []
    if media_ids and sqlite_table_exists(connection, "media_streams"):
        columns = sqlite_table_columns(connection, "media_streams")
        if "media_item_id" in columns:
            placeholders = ",".join("?" for _ in media_ids)
            stream_rows = sqlite_rows_to_dicts(
                connection.execute(
                    f"SELECT * FROM media_streams WHERE media_item_id IN ({placeholders})",
                    media_ids,
                ).fetchall()
            )
    return media_items, stream_rows


def media_rows_for_library_item(database_path, item):
    if not database_path or not database_path.exists():
        return [], []

    snapshot_path = snapshot_plex_database(database_path)
    connection = None
    try:
        connection = sqlite3.connect(snapshot_path)
        connection.row_factory = sqlite3.Row
        return media_rows_for_library_item_connection(connection, item)
    finally:
        try:
            connection.close()
        except Exception:
            pass
        try:
            snapshot_path.unlink(missing_ok=True)
        except OSError:
            pass


def quality_warning(requested_quality, qualities, match_title="", match_year="", quality_summary=""):
    matched = f"{match_title} ({match_year})" if match_title and match_year else match_title
    detail = quality_summary or ", ".join(sorted(qualities, key=lambda value: ["1080p", "4K", "REMUX"].index(value)))
    if requested_quality in qualities:
        suffix = f": {detail}" if detail else f" as {requested_quality}"
        return f"Found in Plex{f' - {matched}' if matched else ''}{suffix}. Please check first."
    if qualities:
        return f"Title appears to be in Plex, but at a different quality: {detail}."
    return "Already appears to be in Plex, but quality could not be confirmed. Please check first."


def strict_plex_matches(items, tmdb_title, tmdb_year):
    wanted_title = normalize_search_text(tmdb_title)
    wanted_year = str(tmdb_year or "").strip()
    matches = []

    for item in items:
        item_title = normalize_search_text(item.get("title", ""))
        item_year = str(item.get("year") or "").strip()
        if item_title != wanted_title:
            continue
        if wanted_year and item_year and item_year != wanted_year:
            continue
        matches.append(item)

    return matches


def plex_match_for_tmdb(config, tmdb_item):
    if not isinstance(tmdb_item, dict):
        return None

    title = str(tmdb_item.get("title", "")).strip()
    year = tmdb_item.get("year")
    media_type = "show" if tmdb_item.get("type") == "tv" else "movie"
    if not title:
        return None

    query = f"{title} {year}" if year else title
    try:
        result = search_plex_database(plex_database_path(config), query, media_type, limit=5)
    except (OSError, sqlite3.DatabaseError):
        return None

    items = result.get("items", [])
    items = strict_plex_matches(items, title, year)
    if not items:
        return None
    return items[0]


def plex_analysis_cache_key(config, tmdb_item):
    database_path = plex_database_path(config)
    database_fingerprint = []
    if database_path:
        for path in (database_path, Path(f"{database_path}-wal"), Path(f"{database_path}-shm")):
            try:
                stat = path.stat()
                database_fingerprint.append((stat.st_mtime_ns, stat.st_size))
            except OSError:
                database_fingerprint.append((0, 0))
    return (
        str(database_path or ""),
        tuple(database_fingerprint),
        str(tmdb_item.get("type") or ""),
        str(tmdb_item.get("id") or ""),
        normalize_search_text(tmdb_item.get("title") or ""),
        str(tmdb_item.get("year") or ""),
    )


def plex_analysis_for_tmdb(config, tmdb_item):
    if not isinstance(tmdb_item, dict):
        return {"match": None, "qualities": set(), "summary": "", "analyzed": False}
    cache_key = plex_analysis_cache_key(config, tmdb_item)
    now = time.monotonic()
    with PLEX_ANALYSIS_CACHE_LOCK:
        cached = PLEX_ANALYSIS_CACHE.get(cache_key)
        if cached and now - cached["createdAt"] < PLEX_ANALYSIS_CACHE_SECONDS:
            return cached["analysis"]

    match = plex_match_for_tmdb(config, tmdb_item)
    qualities = set()
    summary = ""
    analyzed = False
    if match:
        try:
            media_items, stream_rows = media_rows_for_library_item(plex_database_path(config), match)
            analyzed = media_analysis_complete(media_items, stream_rows)
            if analyzed:
                qualities = classify_media_quality(media_items, stream_rows)
                summary = media_quality_summary(
                    media_items,
                    stream_rows,
                    average_bitrate=match.get("type") == "show",
                )
        except (OSError, sqlite3.DatabaseError):
            pass
    analysis = {"match": match, "qualities": qualities, "summary": summary, "analyzed": analyzed}
    with PLEX_ANALYSIS_CACHE_LOCK:
        for key, entry in list(PLEX_ANALYSIS_CACHE.items()):
            if now - entry["createdAt"] >= PLEX_ANALYSIS_CACHE_SECONDS:
                PLEX_ANALYSIS_CACHE.pop(key, None)
        PLEX_ANALYSIS_CACHE[cache_key] = {"createdAt": now, "analysis": analysis}
    return analysis


def library_warning_for_request(config, tmdb_item, requested_quality):
    analysis = plex_analysis_for_tmdb(config, tmdb_item)
    match = analysis["match"]
    if not match:
        return ""

    return quality_warning(
        requested_quality,
        analysis["qualities"],
        match.get("title", ""),
        match.get("year", ""),
        analysis["summary"],
    )


def current_request_plex_status(config, item):
    tmdb_item = item.get("tmdb")
    if not isinstance(tmdb_item, dict):
        return None

    requested_quality = request_quality(item.get("quality"))
    analysis = plex_analysis_for_tmdb(config, tmdb_item)
    match = analysis["match"]
    if not match:
        return {
            "state": "open",
            "message": "Not in Plex yet.",
        }

    if not analysis.get("analyzed"):
        return {
            "state": "open",
            "message": "In Plex; waiting for Plex media analysis.",
        }

    qualities = analysis["qualities"]
    summary = analysis["summary"]

    if requested_quality in qualities:
        return {
            "state": "fulfilled",
            "message": f"Fulfilled: {summary or requested_quality}.",
        }
    if qualities:
        return {
            "state": "partial",
            "message": f"In Plex at different quality: {summary or ', '.join(sorted(qualities))}.",
        }
    return {
        "state": "open",
        "message": "In Plex; waiting for complete quality details.",
    }


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
    quality_line = quality
    if detail.lower() == quality.lower() or detail.lower().startswith(f"{quality.lower()} -"):
        quality_line = detail
    elif detail:
        quality_line = f"{quality} - {detail}"
    return quality_line.rstrip(".")


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


def discord_admin_reminder_embed(config, items, now=None):
    count = len(items)
    fields = []
    for item in items:
        fields.append({
            "name": request_display_title(item)[:256],
            "value": "\n".join([
                f"**Requester:** {str(item.get('requester') or 'Unknown')[:160]}",
                f"**Quality:** {str(item.get('quality') or '1080p')[:80]}",
                f"**Waiting:** {discord_waiting_time(item, now)}",
            ])[:1024],
            "inline": False,
        })
    interval = admin_reminder_interval_minutes(config)
    return {
        "title": "Unfulfilled Plex Requests",
        "description": f"{count} unmuted request{'s are' if count != 1 else ' is'} still waiting to be fulfilled.",
        "color": 0xE5A00D,
        "fields": fields,
        "footer": {
            "text": f"Reminder schedule: every {interval} minute{'s' if interval != 1 else ''} • Muted requests are excluded",
        },
    }


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


def send_discord_message(config, content="", allowed_user_id="", embeds=None):
    return send_discord_webhook(
        discord_webhook_url(config),
        content,
        allowed_user_id,
        embeds,
    )


def notify_request_created(config, item):
    try:
        discord_user_id = discord_user_id_for_requester(config, item.get("requester"))
        send_discord_message(
            config,
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
        return send_discord_message(
            config,
            f"<@{validate_discord_user_id(discord_user_id)}> your request is now available on Plex."
            if discord_user_id else "",
            discord_user_id,
            [discord_fulfillment_embed(item, fulfillment)],
        )
    except Exception as exc:
        print(f"Could not send Discord fulfillment notification: {exc}", flush=True)
        return False


def notify_admin_unfulfilled_requests(config, items, now=None):
    url = admin_reminder_webhook_url(config)
    if not url or not items:
        return False
    try:
        return send_discord_webhook(
            url,
            embeds=[discord_admin_reminder_embed(config, items, now)],
        )
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
    ):
        for _item, entry in active_requests:
            entry["lastAdminReminderAt"] = now
            entry["updatedAt"] = now
        changed = True
    return changed


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


def qbit_client_from_config(config):
    qbit_config = config["qbittorrent"]
    return QbittorrentClient(
        qbit_config["url"],
        qbit_config["username"],
        qbit_config["password"],
    )


def qbit_state_error(state):
    state = str(state or "")
    if state in {"error", "missingFiles", "unknown"}:
        return state
    return ""


def qbit_torrent_filters(torrent):
    state_lower = str(torrent.get("state") or "").lower()
    progress = float(torrent.get("progress") or 0)
    amount_left = int(torrent.get("amount_left") or 0)
    dlspeed = int(torrent.get("dlspeed") or 0)
    upspeed = int(torrent.get("upspeed") or 0)
    completed = progress >= 1 or (int(torrent.get("size") or 0) > 0 and amount_left <= 0)
    stopped = state_lower.startswith("paused") or state_lower.startswith("stopped")
    stalled = state_lower.startswith("stalled")
    downloading = not completed and not stopped and (
        "downloading" in state_lower
        or state_lower.endswith("dl")
        or state_lower in {"metadl", "forceddl"}
    )
    seeding = completed and not stopped and (
        "uploading" in state_lower
        or state_lower.endswith("up")
        or state_lower == "forcedup"
    )
    active = dlspeed > 0 or upspeed > 0
    current = not (completed and dlspeed <= 0 and not state_lower.startswith("down"))

    filters = []
    for name, matches in (
        ("downloading", downloading),
        ("seeding", seeding),
        ("completed", completed),
        ("running", not stopped),
        ("stopped", stopped),
        ("active", active),
        ("inactive", not active),
        ("stalled", stalled),
    ):
        if matches:
            filters.append(name)
    return filters, current


def qbit_status_summary(config):
    client = qbit_client_from_config(config)
    client.ensure_authenticated_for_write()
    torrents = client.torrents_info()
    transfer = {}
    try:
        transfer = client.transfer_info()
    except RuntimeError:
        transfer = {}

    items = []
    for torrent in torrents:
        progress = float(torrent.get("progress") or 0)
        amount_left = int(torrent.get("amount_left") or 0)
        dlspeed = int(torrent.get("dlspeed") or 0)
        state = str(torrent.get("state") or "")
        filters, current = qbit_torrent_filters(torrent)

        items.append({
            "hash": torrent.get("hash", ""),
            "name": torrent.get("name", "Unnamed"),
            "progress": progress,
            "dlspeed": dlspeed,
            "upspeed": int(torrent.get("upspeed") or 0),
            "eta": int(torrent.get("eta") or -1),
            "ratio": float(torrent.get("ratio") or 0),
            "state": state,
            "error": qbit_state_error(state),
            "size": int(torrent.get("size") or 0),
            "amountLeft": amount_left,
            "numSeeds": int(torrent.get("num_seeds") or 0),
            "numPeers": int(torrent.get("num_leechs") or 0),
            "addedOn": int(torrent.get("added_on") or 0),
            "filters": filters,
            "current": current,
        })

    items.sort(key=lambda item: item["addedOn"], reverse=True)
    total_download = int(transfer.get("dl_info_data") or 0)
    total_upload = int(transfer.get("up_info_data") or 0)
    return {
        "ok": True,
        "items": items,
        "transfer": {
            "dlspeed": int(transfer.get("dl_info_speed") or 0),
            "upspeed": int(transfer.get("up_info_speed") or 0),
            "connectionStatus": transfer.get("connection_status", ""),
            "totalDownload": total_download,
            "totalUpload": total_upload,
            "ratio": total_upload / total_download if total_download > 0 else 0,
        },
    }


def public_qbit_status(result):
    return {
        "ok": bool(result.get("ok")),
        "items": [
            {
                "name": item.get("name", "Unnamed"),
                "progress": item.get("progress", 0),
                "size": item.get("size", 0),
                "dlspeed": item.get("dlspeed", 0),
                "eta": item.get("eta", -1),
                "current": True,
            }
            for item in result.get("items", [])
            if item.get("current")
        ],
    }


def config_for_save(config):
    return {
        key: value
        for key, value in config.items()
        if not key.startswith("_")
    }


def save_config(config):
    path = Path(config.get("_save_config_path") or config.get("_config_path") or user_data_path("config.json"))
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        json.dump(config_for_save(config), handle, indent=2)
        handle.write("\n")
    config["_config_path"] = str(path)
    config["_save_config_path"] = str(path)
    config["_using_example_config"] = False


def admin_pin(config):
    return str(config.get("adminPin", "")).strip()


def pin_matches(config, value):
    configured_pin = admin_pin(config)
    return bool(configured_pin) and str(value or "") == configured_pin


def role_from_pin(config, value):
    pin = str(value or "")
    if pin_matches(config, pin):
        return "admin"
    return ""


AUTH_COOKIE_NAME = "plex_requester_token"
AUTH_SESSION_TTL = 7 * 24 * 60 * 60
AUTH_REFRESH_AFTER = 24 * 60 * 60


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
    with auth_store_path().open("w", encoding="utf-8") as handle:
        json.dump(sessions, handle, indent=2)
        handle.write("\n")


def prune_auth_sessions(sessions):
    now = int(time.time())
    changed = False
    for token, session in list(sessions.items()):
        if not isinstance(session, dict) or int(session.get("expiresAt") or 0) <= now:
            sessions.pop(token, None)
            changed = True
    return changed


def create_auth_session(role):
    sessions = load_auth_sessions()
    prune_auth_sessions(sessions)
    token = secrets.token_urlsafe(32)
    now = int(time.time())
    sessions[token] = {
        "role": role,
        "createdAt": now,
        "expiresAt": now + AUTH_SESSION_TTL,
    }
    save_auth_sessions(sessions)
    return token


def session_cookie_header(token):
    return (
        f"{AUTH_COOKIE_NAME}={token}; Path=/; Max-Age={AUTH_SESSION_TTL}; "
        "HttpOnly; SameSite=Lax"
    )


def expired_session_cookie_header():
    return f"{AUTH_COOKIE_NAME}=; Path=/; Max-Age=0; HttpOnly; SameSite=Lax"


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


def tmdb_api_key(config):
    return str(config.get("tmdb", {}).get("apiKey", "")).strip()


def split_tmdb_query(query):
    years = re.findall(r"\b(?:19|20)\d{2}\b", query)
    without_year = re.sub(r"\b(?:19|20)\d{2}\b", " ", query)
    title = re.sub(r"\s+", " ", without_year).strip()
    if years and title:
        return title, years[-1]
    return str(query or "").strip(), None


def clean_folder_name(value):
    cleaned = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "", str(value or ""))
    cleaned = re.sub(r"\s+", " ", cleaned).strip(" .")
    return cleaned or "Untitled"


def tmdb_folder_name(title, year, season=None):
    base = clean_folder_name(title)
    if year:
        base = f"{base} ({year})"
    if season is not None:
        base = f"{base} S{int(season):02d}"
    return base


def tmdb_request(config, endpoint, params):
    api_key = tmdb_api_key(config)
    if not api_key:
        raise RuntimeError("Save a TMDb API key in the Plex Requester log window first.")

    query_params = {
        "language": "en-US",
        "include_adult": "false",
        **params,
    }
    headers = {
        "Accept": "application/json",
        "User-Agent": "PlexRequester/1.0",
    }

    key = api_key.removeprefix("Bearer ").strip()
    if api_key.startswith("Bearer ") or "." in key or len(key) > 40:
        headers["Authorization"] = f"Bearer {key}"
    else:
        query_params["api_key"] = key

    url = "https://api.themoviedb.org/3" + endpoint + "?" + parse.urlencode(query_params)
    req = request.Request(url, headers=headers, method="GET")
    try:
        with request.urlopen(req, timeout=15) as response:
            return json.loads(response.read().decode("utf-8", errors="replace"))
    except error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        try:
            parsed = json.loads(detail)
            message = parsed.get("status_message") or detail
        except json.JSONDecodeError:
            message = detail or exc.reason
        if exc.code == HTTPStatus.UNAUTHORIZED:
            raise RuntimeError("TMDb rejected the saved API key.") from exc
        raise RuntimeError(f"TMDb returned HTTP {exc.code}: {message}") from exc
    except error.URLError as exc:
        raise RuntimeError(f"Could not reach TMDb: {exc.reason}") from exc


def normalize_tmdb_item(item, media_type):
    if media_type == "movie":
        title = item.get("title") or item.get("original_title") or "Untitled"
        date = item.get("release_date") or ""
    else:
        title = item.get("name") or item.get("original_name") or "Untitled"
        date = item.get("first_air_date") or ""
    year = date[:4] if re.match(r"^\d{4}", date) else ""
    folder = tmdb_folder_name(title, year)
    return {
        "id": item.get("id"),
        "type": media_type,
        "title": title,
        "year": year,
        "date": date,
        "overview": item.get("overview") or "",
        "posterPath": item.get("poster_path") or "",
        "popularity": item.get("popularity") or 0,
        "voteAverage": item.get("vote_average") or 0,
        "folderName": folder,
        "seasonFolderName": tmdb_folder_name(title, year, 1) if media_type == "tv" else "",
    }


def search_tmdb(config, query, media_type):
    query = str(query or "").strip()
    if len(query) < 2:
        return {"configured": bool(tmdb_api_key(config)), "items": []}

    title, year = split_tmdb_query(query)
    if not title:
        title = query
    search_types = ["movie", "tv"] if media_type == "all" else [media_type]
    items = []

    for search_type in search_types:
        endpoint = "/search/movie" if search_type == "movie" else "/search/tv"
        params = {"query": title, "page": "1"}
        if year:
            params["primary_release_year" if search_type == "movie" else "first_air_date_year"] = year
        response = tmdb_request(config, endpoint, params)
        for item in response.get("results", [])[:8]:
            items.append(normalize_tmdb_item(item, search_type))

    items.sort(key=lambda item: item.get("popularity", 0), reverse=True)
    return {"configured": True, "items": items[:12]}


def plex_database_path(config):
    value = str(config.get("plex", {}).get("databasePath", "")).strip()
    if not value:
        return None
    return Path(value)


def snapshot_plex_database(database_path):
    source_uri = "file:" + parse.quote(str(database_path.resolve()).replace("\\", "/"), safe="/:") + "?mode=ro"
    temp = tempfile.NamedTemporaryFile(prefix="plex-requester-", suffix=".db", delete=False)
    temp_path = Path(temp.name)
    temp.close()

    source = None
    target = None
    try:
        source = sqlite3.connect(source_uri, uri=True)
        target = sqlite3.connect(temp_path)
        source.backup(target)
        target.close()
        source.close()
        return temp_path
    except Exception:
        if target:
            target.close()
        if source:
            source.close()
        try:
            temp_path.unlink(missing_ok=True)
        except OSError:
            pass
        raise


def normalize_search_text(value):
    text = str(value or "").lower()
    text = re.sub(r"[^a-z0-9]+", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def parse_library_query(query):
    years = re.findall(r"\b(?:19|20)\d{2}\b", query)
    title_without_years = re.sub(r"\b(?:19|20)\d{2}\b", " ", query)
    normalized_without_years = normalize_search_text(title_without_years)
    if years and normalized_without_years:
        return normalized_without_years, set(years)
    return normalize_search_text(query), set()


def library_match_score(row, query_title, query_years):
    title = normalize_search_text(row["title"])
    if not query_title and not query_years:
        return 1.0

    score = 0.0
    if query_title:
        ratio = difflib.SequenceMatcher(None, query_title, title).ratio()
        query_tokens = set(query_title.split())
        title_tokens = set(title.split())
        token_score = len(query_tokens & title_tokens) / max(len(query_tokens), 1)

        shorter = min(len(query_title), len(title))
        if query_title == title:
            score += 1.0
        elif shorter >= 3 and (query_title in title or title in query_title):
            score += 0.82
        else:
            score += max(ratio * 0.72, token_score * 0.78)

    if query_years:
        year = str(row["year"] or "")
        if year in query_years:
            score += 0.35
        else:
            score -= 0.2

    return score


def library_match_threshold(query_title, query_years):
    if not query_title and not query_years:
        return 0.0
    token_count = len(query_title.split()) if query_title else 0
    if token_count <= 1:
        return 0.48
    return 0.62


def library_match_label(row, query_title, score):
    if not query_title:
        return ""
    title = normalize_search_text(row["title"])
    return "Exact" if title == query_title else "Similar"


def row_to_library_item(row, match_label="", quality_summary=""):
    return {
        "id": row["id"],
        "title": row["title"],
        "year": row["year"],
        "type": "movie" if row["metadata_type"] == 1 else "show",
        "library": row["library_name"],
        "originallyAvailableAt": row["originally_available_at"],
        "episodeCount": row["episode_count"],
        "fileCount": row["file_count"],
        "sampleFile": row["sample_file"],
        "match": match_label,
        "qualitySummary": quality_summary,
    }


def sqlite_rows_to_dicts(rows):
    return [{key: row[key] for key in row.keys()} for row in rows]


def sqlite_table_columns(connection, table_name):
    return [row[1] for row in connection.execute(f"PRAGMA table_info({table_name})").fetchall()]


def sqlite_table_exists(connection, table_name):
    row = connection.execute(
        "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = ?",
        (table_name,),
    ).fetchone()
    return bool(row)


def fetch_optional_rows(connection, table_name, where_sql, params):
    if not sqlite_table_exists(connection, table_name):
        return []
    return sqlite_rows_to_dicts(connection.execute(f"SELECT * FROM {table_name} WHERE {where_sql}", params).fetchall())


def search_plex_database(database_path, query="", media_type="all", limit=80):
    if not database_path or not database_path.exists():
        return {
            "configured": bool(database_path),
            "items": [],
            "error": "Plex database path is not configured or does not exist.",
        }

    snapshot_path = snapshot_plex_database(database_path)
    try:
        connection = sqlite3.connect(snapshot_path)
        connection.row_factory = sqlite3.Row
        params = []
        filters = ["mi.metadata_type IN (1, 2)", "mi.deleted_at IS NULL"]

        if media_type == "movie":
            filters.append("mi.metadata_type = 1")
        elif media_type == "show":
            filters.append("mi.metadata_type = 2")

        sql = f"""
            SELECT
                mi.id,
                mi.title,
                mi.year,
                mi.originally_available_at,
                mi.metadata_type,
                ls.name AS library_name,
                COUNT(DISTINCT ep.id) AS episode_count,
                COUNT(DISTINCT parts.id) AS file_count,
                MIN(parts.file) AS sample_file
            FROM metadata_items mi
            LEFT JOIN library_sections ls ON ls.id = mi.library_section_id
            LEFT JOIN metadata_items season
                ON mi.metadata_type = 2
                AND season.parent_id = mi.id
                AND season.metadata_type = 3
                AND season.deleted_at IS NULL
            LEFT JOIN metadata_items ep
                ON mi.metadata_type = 2
                AND ep.parent_id = season.id
                AND ep.metadata_type = 4
                AND ep.deleted_at IS NULL
            LEFT JOIN media_items media ON media.metadata_item_id = mi.id
            LEFT JOIN media_parts parts ON parts.media_item_id = media.id
            WHERE {" AND ".join(filters)}
            GROUP BY mi.id
            ORDER BY lower(mi.title), mi.year
        """

        rows = connection.execute(sql, params).fetchall()
        query_title, query_years = parse_library_query(query)
        match_labels = {}
        if query_title or query_years:
            scored_rows = [
                (library_match_score(row, query_title, query_years), row)
                for row in rows
            ]
            threshold = library_match_threshold(query_title, query_years)
            scored_rows = [(score, row) for score, row in scored_rows if score >= threshold]
            scored_rows.sort(
                key=lambda item: (
                    library_match_label(item[1], query_title, item[0]) != "Exact",
                    -item[0],
                    normalize_search_text(item[1]["title"]),
                    item[1]["year"] or 0,
                )
            )
            match_labels = {
                row["id"]: library_match_label(row, query_title, score)
                for score, row in scored_rows
            }
            rows = [row for _, row in scored_rows[: int(limit)]]
        else:
            rows = rows[: int(limit)]

        quality_summaries = {}
        for row in rows:
            item = {
                "id": row["id"],
                "type": "movie" if row["metadata_type"] == 1 else "show",
            }
            try:
                media_items, stream_rows = media_rows_for_library_item_connection(connection, item)
                quality_summaries[row["id"]] = media_quality_summary(media_items, stream_rows)
            except sqlite3.DatabaseError:
                quality_summaries[row["id"]] = ""

        return {
            "configured": True,
            "items": [
                row_to_library_item(
                    row,
                    match_labels.get(row["id"], ""),
                    quality_summaries.get(row["id"], ""),
                )
                for row in rows
            ],
        }
    finally:
        try:
            connection.close()
        except Exception:
            pass
        try:
            snapshot_path.unlink(missing_ok=True)
        except OSError:
            pass


def plex_item_details(database_path, item_id):
    if not database_path or not database_path.exists():
        return {
            "configured": bool(database_path),
            "error": "Plex database path is not configured or does not exist.",
        }

    snapshot_path = snapshot_plex_database(database_path)
    try:
        connection = sqlite3.connect(snapshot_path)
        connection.row_factory = sqlite3.Row

        item = connection.execute("SELECT * FROM metadata_items WHERE id = ?", (item_id,)).fetchone()
        if not item:
            return {"configured": True, "error": "Plex item was not found."}

        item_dict = {key: item[key] for key in item.keys()}
        details = {
            "configured": True,
            "metadata": item_dict,
            "librarySection": None,
            "parents": [],
            "children": [],
            "mediaItems": [],
            "mediaParts": [],
            "tags": [],
            "relatedTables": {},
        }

        library_section_id = item_dict.get("library_section_id")
        if library_section_id is not None and sqlite_table_exists(connection, "library_sections"):
            row = connection.execute("SELECT * FROM library_sections WHERE id = ?", (library_section_id,)).fetchone()
            if row:
                details["librarySection"] = {key: row[key] for key in row.keys()}

        parent_id = item_dict.get("parent_id")
        while parent_id:
            parent = connection.execute("SELECT * FROM metadata_items WHERE id = ?", (parent_id,)).fetchone()
            if not parent:
                break
            parent_dict = {key: parent[key] for key in parent.keys()}
            details["parents"].append(parent_dict)
            parent_id = parent_dict.get("parent_id")

        direct_children = connection.execute(
            "SELECT * FROM metadata_items WHERE parent_id = ? AND deleted_at IS NULL ORDER BY metadata_type, \"index\", title",
            (item_id,),
        ).fetchall()
        details["children"] = sqlite_rows_to_dicts(direct_children)

        if item_dict.get("metadata_type") == 2:
            episode_rows = connection.execute(
                """
                SELECT ep.*
                FROM metadata_items season
                JOIN metadata_items ep ON ep.parent_id = season.id
                WHERE season.parent_id = ?
                  AND season.metadata_type = 3
                  AND ep.metadata_type = 4
                  AND season.deleted_at IS NULL
                  AND ep.deleted_at IS NULL
                ORDER BY season."index", ep."index", ep.title
                """,
                (item_id,),
            ).fetchall()
            details["episodes"] = sqlite_rows_to_dicts(episode_rows)

        details["mediaItems"] = fetch_optional_rows(connection, "media_items", "metadata_item_id = ?", (item_id,))
        media_item_ids = [row["id"] for row in details["mediaItems"] if "id" in row]
        if media_item_ids and sqlite_table_exists(connection, "media_parts"):
            placeholders = ",".join("?" for _ in media_item_ids)
            details["mediaParts"] = sqlite_rows_to_dicts(
                connection.execute(
                    f"SELECT * FROM media_parts WHERE media_item_id IN ({placeholders})",
                    media_item_ids,
                ).fetchall()
            )

        if sqlite_table_exists(connection, "taggings"):
            taggings_columns = sqlite_table_columns(connection, "taggings")
            metadata_column = "metadata_item_id" if "metadata_item_id" in taggings_columns else None
            if metadata_column:
                taggings = fetch_optional_rows(connection, "taggings", f"{metadata_column} = ?", (item_id,))
                details["relatedTables"]["taggings"] = taggings
                tag_ids = [row.get("tag_id") for row in taggings if row.get("tag_id") is not None]
                if tag_ids and sqlite_table_exists(connection, "tags"):
                    placeholders = ",".join("?" for _ in tag_ids)
                    details["tags"] = sqlite_rows_to_dicts(
                        connection.execute(f"SELECT * FROM tags WHERE id IN ({placeholders})", tag_ids).fetchall()
                    )

        for table_name in ("metadata_item_settings", "statistics_media", "media_streams"):
            if not sqlite_table_exists(connection, table_name):
                continue
            columns = sqlite_table_columns(connection, table_name)
            if "metadata_item_id" in columns:
                details["relatedTables"][table_name] = fetch_optional_rows(
                    connection,
                    table_name,
                    "metadata_item_id = ?",
                    (item_id,),
                )
            elif table_name == "media_streams" and media_item_ids and "media_item_id" in columns:
                placeholders = ",".join("?" for _ in media_item_ids)
                details["relatedTables"][table_name] = sqlite_rows_to_dicts(
                    connection.execute(
                        f"SELECT * FROM media_streams WHERE media_item_id IN ({placeholders})",
                        media_item_ids,
                    ).fetchall()
                )

        return details
    finally:
        try:
            connection.close()
        except Exception:
            pass
        try:
            snapshot_path.unlink(missing_ok=True)
        except OSError:
            pass


class AppHandler(BaseHTTPRequestHandler):
    server_version = "PlexRequester/1.0"

    def do_GET(self):
        parsed = parse.urlparse(self.path)
        if parsed.path == "/":
            return self.serve_file(STATIC_DIR / "index.html")
        if parsed.path == "/api/auth/me":
            return self.auth_me()
        if parsed.path.startswith("/static/"):
            target = (STATIC_DIR / parsed.path.removeprefix("/static/")).resolve()
            if not str(target).startswith(str(STATIC_DIR.resolve())):
                return self.send_error(HTTPStatus.FORBIDDEN)
            return self.serve_file(target)
        if parsed.path == "/api/config":
            return self.send_json(self.public_config())
        if parsed.path == "/api/requests":
            return self.send_json({"items": requests_for_display()})
        if parsed.path == "/api/subfolders":
            if not self.require_admin():
                return
            return self.send_json(self.subfolders_response(parsed.query))
        if parsed.path == "/api/library/search":
            return self.send_json(self.library_search_response(parsed.query))
        if parsed.path == "/api/library/item":
            return self.send_json(self.library_item_response(parsed.query))
        if parsed.path == "/api/storage":
            return self.send_json(storage_summary(self.server.config))
        if parsed.path == "/api/qbit/status":
            return self.send_json(self.qbit_status_response())
        if parsed.path == "/api/tmdb/search":
            return self.send_json(self.tmdb_search_response(parsed.query))
        return self.send_error(HTTPStatus.NOT_FOUND)

    def subfolders_response(self, query):
        params = parse.parse_qs(query)
        destination_id = params.get("destinationId", [""])[0]
        parent = params.get("parent", [""])[0]
        parent_parts = [part for part in parent.split("/") if part]
        destinations = {item["id"]: item for item in self.server.config["destinations"]}
        destination = destinations.get(destination_id)
        if not destination or not destination.get("browseSubfolders"):
            return {"subfolders": []}
        try:
            base_path = destination_base_path(destination, params.get("pathIndex", [""])[0])
        except ValueError as exc:
            return {"subfolders": [], "error": str(exc)}
        return {"subfolders": list_subfolders(base_path, parent_parts)}

    def library_search_response(self, query):
        params = parse.parse_qs(query)
        search = params.get("q", [""])[0]
        media_type = params.get("type", ["all"])[0]
        if media_type not in {"all", "movie", "show"}:
            media_type = "all"
        try:
            return search_plex_database(plex_database_path(self.server.config), search, media_type)
        except sqlite3.DatabaseError as exc:
            return {
                "configured": True,
                "items": [],
                "error": f"Could not read the Plex database snapshot: {exc}",
            }

    def library_item_response(self, query):
        params = parse.parse_qs(query)
        try:
            item_id = int(params.get("id", ["0"])[0])
        except ValueError:
            return {"error": "Invalid Plex item id."}
        try:
            return plex_item_details(plex_database_path(self.server.config), item_id)
        except sqlite3.DatabaseError as exc:
            return {
                "configured": True,
                "error": f"Could not read the Plex database snapshot: {exc}",
            }

    def tmdb_search_response(self, query):
        params = parse.parse_qs(query)
        search = params.get("q", [""])[0]
        media_type = params.get("type", ["all"])[0]
        if media_type not in {"all", "movie", "tv"}:
            media_type = "all"
        try:
            return search_tmdb(self.server.config, search, media_type)
        except RuntimeError as exc:
            return {
                "configured": bool(tmdb_api_key(self.server.config)),
                "items": [],
                "error": str(exc),
            }

    def qbit_status_response(self):
        try:
            result = qbit_status_summary(self.server.config)
            return result if self.current_role() == "admin" else public_qbit_status(result)
        except RuntimeError as exc:
            return {"ok": False, "items": [], "error": str(exc)}

    def do_POST(self):
        parsed = parse.urlparse(self.path)
        if parsed.path == "/api/auth/login":
            return self.auth_login()
        if parsed.path == "/api/auth/logout":
            return self.auth_logout()
        if parsed.path == "/api/admin/config/load":
            return self.admin_config_load()
        if parsed.path == "/api/admin/config/save":
            return self.admin_config_save()
        if parsed.path == "/api/requests/fulfill":
            return self.mark_request_fulfilled()
        if parsed.path == "/api/requests/reminder-mute":
            return self.set_request_reminder_mute()
        if parsed.path == "/api/qbit/session":
            return self.qbit_session_action()
        if parsed.path == "/api/requests":
            return self.create_request()
        if parsed.path not in {"/api/magnets", "/api/torrents"}:
            return self.send_error(HTTPStatus.NOT_FOUND)
        if not self.require_admin():
            return

        try:
            payload = self.read_json_body()
            is_torrent_upload = parsed.path == "/api/torrents"
            magnet = str(payload.get("magnet", "")).strip()
            torrent_file = decode_torrent_upload(payload) if is_torrent_upload else None
            destination_id = str(payload.get("destinationId", "")).strip()
            destination_path_index = payload.get("destinationPathIndex")
            download_name = validate_download_name(payload.get("downloadName", ""))
            use_subfolder = bool(payload.get("useSubfolder"))
            subfolder_name = str(payload.get("subfolderName", "")).strip()
            existing_subfolder = str(payload.get("existingSubfolder", "")).strip()
            existing_subfolder_path = payload.get("existingSubfolderPath", [])
            new_subfolders = payload.get("newSubfolders", [])

            if not is_torrent_upload and not magnet.startswith("magnet:?"):
                return self.send_json({"error": "Paste a valid magnet link."}, HTTPStatus.BAD_REQUEST)

            destinations = {item["id"]: item for item in self.server.config["destinations"]}
            destination = destinations.get(destination_id)
            if not destination:
                return self.send_json({"error": "Choose one of the preset destinations."}, HTTPStatus.BAD_REQUEST)
            base_path = destination_base_path(destination, destination_path_index)

            if not isinstance(new_subfolders, list):
                return self.send_json({"error": "New folders must be sent as a list."}, HTTPStatus.BAD_REQUEST)

            new_subfolders = [str(part).strip() for part in new_subfolders if str(part or "").strip()]

            if destination.get("browseSubfolders"):
                available_subfolders = list_subfolders(base_path)
                if isinstance(existing_subfolder_path, list) and existing_subfolder_path:
                    existing_subfolder_path = [str(part).strip() for part in existing_subfolder_path if str(part).strip()]
                    if not self.existing_subfolder_path_is_valid(base_path, existing_subfolder_path):
                        return self.send_json({"error": "Choose one of the listed TV show folders."}, HTTPStatus.BAD_REQUEST)
                    save_path = join_destination_path(base_path, existing_subfolder_path + new_subfolders)
                elif existing_subfolder:
                    if existing_subfolder not in available_subfolders:
                        return self.send_json({"error": "Choose one of the listed TV show folders."}, HTTPStatus.BAD_REQUEST)
                    save_path = join_destination_path(base_path, [existing_subfolder] + new_subfolders)
                elif new_subfolders:
                    save_path = join_destination_path(base_path, new_subfolders)
                elif available_subfolders and not use_subfolder:
                    return self.send_json({"error": "Choose a TV show folder or create new folders."}, HTTPStatus.BAD_REQUEST)
                else:
                    save_path = destination_path(base_path, use_subfolder, subfolder_name)
            else:
                if new_subfolders:
                    save_path = join_destination_path(base_path, new_subfolders)
                else:
                    save_path = destination_path(base_path, use_subfolder, subfolder_name)

            qbit_config = self.server.config["qbittorrent"]
            client = QbittorrentClient(
                qbit_config["url"],
                qbit_config["username"],
                qbit_config["password"],
            )
            if is_torrent_upload:
                client.add_torrent_file(torrent_file[0], torrent_file[1], save_path, download_name)
            else:
                client.add_magnet(magnet, save_path, download_name)

            self.send_json(
                {
                    "ok": True,
                    "message": (
                        f"Torrent file sent to qBittorrent for {destination['label']}."
                        if is_torrent_upload
                        else f"Magnet link sent to qBittorrent for {destination['label']}."
                    ),
                    "destination": destination["label"],
                    "path": save_path,
                    "downloadName": download_name,
                }
            )
        except MagnetAlreadyExists as exc:
            self.send_json(
                {
                    "ok": False,
                    "duplicate": True,
                    "error": str(exc),
                    "hash": exc.torrent_hash,
                },
                HTTPStatus.CONFLICT,
            )
        except json.JSONDecodeError:
            self.send_json({"error": "The request body was not valid JSON."}, HTTPStatus.BAD_REQUEST)
        except ValueError as exc:
            self.send_json({"error": str(exc)}, HTTPStatus.BAD_REQUEST)
        except RuntimeError as exc:
            self.send_json({"error": str(exc)}, HTTPStatus.BAD_GATEWAY)
        except Exception as exc:
            self.send_json({"error": f"Unexpected server error: {exc}"}, HTTPStatus.INTERNAL_SERVER_ERROR)

    def do_DELETE(self):
        parsed = parse.urlparse(self.path)
        if parsed.path != "/api/requests":
            return self.send_error(HTTPStatus.NOT_FOUND)

        params = parse.parse_qs(parsed.query)
        request_id = params.get("id", [""])[0]
        if not delete_request(request_id):
            return self.send_json({"error": "Request not found."}, HTTPStatus.NOT_FOUND)
        self.send_json({"ok": True})

    def auth_token(self):
        cookie_header = self.headers.get("Cookie", "")
        if not cookie_header:
            return ""
        cookie = SimpleCookie()
        try:
            cookie.load(cookie_header)
        except Exception:
            return ""
        morsel = cookie.get(AUTH_COOKIE_NAME)
        return morsel.value if morsel else ""

    def current_session(self):
        token = self.auth_token()
        if not token:
            return None
        sessions = load_auth_sessions()
        changed = prune_auth_sessions(sessions)
        session = sessions.get(token)
        if changed:
            try:
                save_auth_sessions(sessions)
            except OSError as exc:
                print(f"Could not save auth sessions: {exc}", flush=True)
        if not isinstance(session, dict):
            return None
        role = session.get("role")
        if role not in {"admin", "user"}:
            return None
        return {"token": token, "role": role, "expiresAt": int(session.get("expiresAt") or 0)}

    def current_role(self):
        session = self.current_session()
        return session.get("role") if session else ""

    def require_admin(self):
        if self.current_role() == "admin":
            return True
        self.send_json({"error": "Admin PIN required."}, HTTPStatus.FORBIDDEN)
        return False

    def refresh_session_if_needed(self, session):
        if not session:
            return None
        now = int(time.time())
        if int(session.get("expiresAt") or 0) - now > AUTH_REFRESH_AFTER:
            return None
        sessions = load_auth_sessions()
        stored = sessions.get(session["token"])
        if not isinstance(stored, dict):
            return None
        stored["expiresAt"] = now + AUTH_SESSION_TTL
        try:
            save_auth_sessions(sessions)
        except OSError as exc:
            print(f"Could not refresh auth session: {exc}", flush=True)
            return None
        return session_cookie_header(session["token"])

    def auth_me(self):
        session = self.current_session()
        if not session:
            return self.send_json({"authenticated": False, "role": ""})
        headers = []
        cookie = self.refresh_session_if_needed(session)
        if cookie:
            headers.append(("Set-Cookie", cookie))
        self.send_json(
            {
                "authenticated": True,
                "role": session["role"],
            },
            headers=headers,
        )

    def auth_login(self):
        try:
            payload = self.read_json_body()
            role = role_from_pin(self.server.config, payload.get("pin"))
            if not role:
                return self.send_json({"error": "Wrong PIN."}, HTTPStatus.UNAUTHORIZED)
            token = create_auth_session(role)
            self.send_json(
                {
                    "ok": True,
                    "role": role,
                },
                headers=[("Set-Cookie", session_cookie_header(token))],
            )
        except json.JSONDecodeError:
            self.send_json({"error": "Invalid JSON."}, HTTPStatus.BAD_REQUEST)
        except OSError as exc:
            self.send_json({"error": f"Could not save login session: {exc}"}, HTTPStatus.INTERNAL_SERVER_ERROR)

    def auth_logout(self):
        token = self.auth_token()
        if token:
            sessions = load_auth_sessions()
            sessions.pop(token, None)
            try:
                save_auth_sessions(sessions)
            except OSError as exc:
                print(f"Could not save auth sessions: {exc}", flush=True)
        self.send_json(
            {"ok": True},
            headers=[("Set-Cookie", expired_session_cookie_header())],
        )

    def admin_config_load(self):
        if not self.require_admin():
            return
        try:
            self.send_json({"ok": True, "config": editable_config(self.server.config)})
        except json.JSONDecodeError:
            self.send_json({"error": "Invalid JSON."}, HTTPStatus.BAD_REQUEST)

    def admin_config_save(self):
        if not self.require_admin():
            return
        try:
            payload = self.read_json_body()
            apply_editable_config(self.server.config, payload.get("config", {}))
            save_config(self.server.config)
            self.send_json({"ok": True, "config": editable_config(self.server.config)})
        except json.JSONDecodeError:
            self.send_json({"error": "Invalid JSON."}, HTTPStatus.BAD_REQUEST)
        except ValueError as exc:
            self.send_json({"error": str(exc)}, HTTPStatus.BAD_REQUEST)
        except OSError as exc:
            self.send_json({"error": f"Could not save config.json: {exc}"}, HTTPStatus.INTERNAL_SERVER_ERROR)

    def mark_request_fulfilled(self):
        if not self.require_admin():
            return
        try:
            payload = self.read_json_body()
            request_id = str(payload.get("id", "")).strip()
            if not manually_fulfill_request(request_id):
                return self.send_json({"error": "Request not found."}, HTTPStatus.NOT_FOUND)
            self.send_json({"ok": True, "items": requests_for_display()})
        except json.JSONDecodeError:
            self.send_json({"error": "Invalid JSON."}, HTTPStatus.BAD_REQUEST)
        except OSError as exc:
            self.send_json({"error": f"Could not save fulfillment state: {exc}"}, HTTPStatus.INTERNAL_SERVER_ERROR)

    def set_request_reminder_mute(self):
        if not self.require_admin():
            return
        try:
            payload = self.read_json_body()
            request_id = str(payload.get("id", "")).strip()
            if not set_request_reminder_muted(request_id, bool(payload.get("muted"))):
                return self.send_json({"error": "Request not found."}, HTTPStatus.NOT_FOUND)
            self.send_json({"ok": True, "items": requests_for_display()})
        except json.JSONDecodeError:
            self.send_json({"error": "Invalid JSON."}, HTTPStatus.BAD_REQUEST)
        except OSError as exc:
            self.send_json({"error": f"Could not save request: {exc}"}, HTTPStatus.INTERNAL_SERVER_ERROR)

    def qbit_session_action(self):
        if not self.require_admin():
            return
        try:
            payload = self.read_json_body()
            action = str(payload.get("action") or "").strip().lower()
            if action not in {"start", "pause"}:
                return self.send_json({"error": "Choose start or pause."}, HTTPStatus.BAD_REQUEST)
            client = qbit_client_from_config(self.server.config)
            client.set_session_paused(action == "pause")
            self.send_json({"ok": True, "action": action})
        except json.JSONDecodeError:
            self.send_json({"error": "Invalid JSON."}, HTTPStatus.BAD_REQUEST)
        except RuntimeError as exc:
            self.send_json({"error": str(exc)}, HTTPStatus.BAD_GATEWAY)

    def create_request(self):
        try:
            payload = self.read_json_body()
            item = add_request(self.server.config, payload, self.client_address[0])
            self.send_json({"ok": True, "item": item, "warning": item.get("libraryWarning", "")})
            threading.Thread(
                target=complete_request_creation,
                args=(self.server.config, item),
                daemon=True,
                name=f"PlexRequesterNewRequest-{item.get('id')}",
            ).start()
        except json.JSONDecodeError:
            self.send_json({"error": "Invalid JSON."}, HTTPStatus.BAD_REQUEST)
        except ValueError as exc:
            self.send_json({"error": str(exc)}, HTTPStatus.BAD_REQUEST)
        except OSError as exc:
            self.send_json({"error": f"Could not save request: {exc}"}, HTTPStatus.INTERNAL_SERVER_ERROR)

    def read_json_body(self):
        length = int(self.headers.get("Content-Length", "0"))
        raw = self.rfile.read(length)
        return json.loads(raw.decode("utf-8"))

    def existing_subfolder_path_is_valid(self, base_path, subfolders):
        parent = []
        for subfolder in subfolders:
            if subfolder not in list_subfolders(base_path, parent):
                return False
            parent.append(subfolder)
        return True

    def public_config(self):
        is_admin = self.current_role() == "admin"
        return {
            "app": {
                "version": str(self.server.config.get("app", {}).get("version", DEFAULT_APP_VERSION)),
            },
            "destinations": [
                {
                    "id": item["id"],
                    "label": item["label"],
                    "browseSubfolders": bool(item.get("browseSubfolders")),
                    "directories": destination_directory_choices(item) if is_admin else [],
                }
                for item in self.server.config["destinations"]
            ],
            "server": {
                "host": socket.gethostname(),
                "port": self.server.server_port,
                "origin": f"http://{self.headers.get('Host', f'localhost:{self.server.server_port}')}",
            },
            "qbittorrent": {
                "configured": bool(self.server.config["qbittorrent"].get("url")),
            },
            "config": {
                "usingExample": self.server.config["_using_example_config"],
            },
            "plex": {
                "databaseConfigured": bool(plex_database_path(self.server.config)),
            },
            "tmdb": {
                "configured": bool(tmdb_api_key(self.server.config)),
            },
        }

    def serve_file(self, path):
        if not path.exists() or not path.is_file():
            return self.send_error(HTTPStatus.NOT_FOUND)

        content_type = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
        body = path.read_bytes()
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def send_json(self, payload, status=HTTPStatus.OK, headers=None):
        body = json.dumps(payload).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        for name, value in headers or []:
            self.send_header(name, value)
        self.end_headers()
        self.wfile.write(body)


class AppServer(ThreadingHTTPServer):
    def __init__(self, address, handler, config):
        super().__init__(address, handler)
        self.config = config
        self.fulfillment_stop_event = threading.Event()
        self.fulfillment_thread = threading.Thread(
            target=fulfillment_monitor_loop,
            args=(self.config, self.fulfillment_stop_event),
            daemon=True,
            name="PlexRequesterFulfillmentMonitor",
        )
        self.fulfillment_thread.start()

    def server_close(self):
        self.fulfillment_stop_event.set()
        super().server_close()


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
