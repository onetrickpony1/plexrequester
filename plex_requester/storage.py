"""Crash-safe runtime storage and AppData path handling."""

import json
import os
import re
import shutil
import tempfile
from pathlib import Path


USER_DATA_FILES = (
    "config.json",
    "requests.json",
    "request-fulfillment-state.json",
    "auth-sessions.json",
    "notification-outbox.json",
    "rename-history.jsonl",
    "plex-requester.log",
)


def user_data_dir(environ=None):
    environ = os.environ if environ is None else environ
    override = str(environ.get("PLEX_REQUESTER_DATA_DIR", "")).strip()
    if override:
        return Path(override).expanduser()
    local_app_data = str(environ.get("LOCALAPPDATA", "")).strip()
    if local_app_data:
        return Path(local_app_data) / "Plex Requester"
    return Path.home() / "AppData" / "Local" / "Plex Requester"


def user_data_path(file_name, base_dir, environ=None):
    data_dir = user_data_dir(environ)
    data_dir.mkdir(parents=True, exist_ok=True)
    target = data_dir / file_name
    legacy = Path(base_dir) / file_name
    if not target.exists() and legacy.exists() and legacy.resolve() != target.resolve():
        shutil.copy2(legacy, target)
        print(f"Migrated {file_name} to {target}", flush=True)
    return target


def atomic_write_json(path, payload):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary_path = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            newline="\n",
            prefix=f".{path.name}.",
            suffix=".tmp",
            dir=str(path.parent),
            delete=False,
        ) as handle:
            temporary_path = Path(handle.name)
            json.dump(payload, handle, indent=2)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary_path, path)
        temporary_path = None
    finally:
        if temporary_path is not None:
            try:
                temporary_path.unlink(missing_ok=True)
            except OSError:
                pass


def load_json(path, default, expected_type):
    path = Path(path)
    if not path.exists():
        return default
    try:
        with path.open("r", encoding="utf-8") as handle:
            value = json.load(handle)
        return value if isinstance(value, expected_type) else default
    except (OSError, json.JSONDecodeError):
        return default

DESTINATION_FULL_PERCENT = 90


def validate_subfolder_name(subfolder_name):
    cleaned = str(subfolder_name or "").strip()
    if not cleaned:
        raise ValueError("Enter a subfolder name, or turn off the subfolder option.")
    if cleaned in {".", ".."} or "/" in cleaned or "\\" in cleaned:
        raise ValueError("Subfolder name cannot contain slashes or path traversal.")
    if re.search(r'[<>:"|?*\x00-\x1f]', cleaned):
        raise ValueError('Subfolder name cannot contain these characters: < > : " | ? *')
    return cleaned


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


def destination_directory_choices(destination, usage_provider=None):
    usage_provider = usage_provider or disk_usage_for_path
    choices = []
    for index, path in enumerate(destination_paths(destination)):
        usage = usage_provider(path)
        choices.append({
            "index": index,
            "label": path,
            "usagePercent": round(usage["percent"], 1) if usage else None,
            "freeBytes": usage["free"] if usage else None,
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


def find_destination_parent_folder(destination, parent_name):
    wanted = validate_subfolder_name(parent_name).casefold()
    for path_index, base_path in enumerate(destination_paths(destination)):
        for folder in list_subfolders(base_path):
            if folder.casefold() == wanted:
                return {
                    "pathIndex": path_index,
                    "directory": base_path,
                    "folder": folder,
                }
    return None


def destination_base_path(destination, path_index=None, choices_provider=None):
    paths = destination_paths(destination)
    if not paths:
        raise ValueError("The selected destination has no configured directories.")
    if path_index is None or str(path_index).strip() == "":
        choices_provider = choices_provider or destination_directory_choices
        choices = choices_provider(destination)
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
