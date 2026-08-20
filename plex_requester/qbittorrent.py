"""qBittorrent Web API, torrent parsing, and content renaming."""

from http import HTTPStatus
from http.cookiejar import CookieJar
from pathlib import Path
from urllib import error, parse, request
import base64
import hashlib
import json
import re
import secrets
import threading
import time

from . import storage


BASE_DIR = Path(__file__).resolve().parent.parent
MAX_TORRENT_FILE_SIZE = 10 * 1024 * 1024


class MagnetAlreadyExists(RuntimeError):
    def __init__(self, torrent_hash):
        super().__init__("This magnet link is already present in qBittorrent.")
        self.torrent_hash = torrent_hash


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
    history_path = storage.user_data_path("rename-history.jsonl", BASE_DIR)
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


def qbit_status_summary(config, client_provider=None):
    client_provider = client_provider or qbit_client_from_config
    client = client_provider(config)
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




