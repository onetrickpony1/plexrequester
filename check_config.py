from pathlib import Path
import json
import os
import sys


default_config_path = Path(
    os.environ.get("LOCALAPPDATA", Path.home() / "AppData" / "Local")
) / "Plex Requester" / "config.json"
config_path = Path(sys.argv[1]) if len(sys.argv) > 1 else default_config_path

try:
    with config_path.open("r", encoding="utf-8") as handle:
        config = json.load(handle)
except FileNotFoundError:
    print(f"Missing config file: {config_path}")
    sys.exit(1)
except json.JSONDecodeError as exc:
    print(f"Invalid JSON in {config_path}: line {exc.lineno}, column {exc.colno}: {exc.msg}")
    print("Tip: Windows paths need doubled backslashes, or use forward slashes.")
    print(r'Example: "C:\\Downloads\\Movies" or "C:/Downloads/Movies"')
    sys.exit(1)

errors = []
admin_pin = str(config.get("adminPin", "")).strip()
if admin_pin.casefold() == "change-this-pin":
    errors.append("adminPin still contains the insecure example value")
elif len(admin_pin) < 8:
    errors.append("adminPin must contain at least 8 characters")
elif len(admin_pin) > 128:
    errors.append("adminPin must contain no more than 128 characters")

qbit = config.get("qbittorrent", {})
if not qbit.get("url"):
    errors.append("qbittorrent.url is missing")
if not qbit.get("username"):
    errors.append("qbittorrent.username is missing")
if "password" not in qbit:
    errors.append("qbittorrent.password is missing")

plex = config.get("plex", {})
if plex.get("databasePath"):
    plex_path = Path(plex["databasePath"])
    if not plex_path.exists():
        errors.append(f"plex.databasePath does not exist: {plex_path}")

destinations = config.get("destinations")
if not isinstance(destinations, list) or not destinations:
    errors.append("destinations must be a non-empty list")
else:
    seen = set()
    for index, destination in enumerate(destinations, start=1):
        label = destination.get("label", f"destination #{index}") if isinstance(destination, dict) else f"destination #{index}"
        if not isinstance(destination, dict):
            errors.append(f"{label} must be an object")
            continue
        for key in ("id", "label", "path"):
            if not destination.get(key):
                errors.append(f"{label} is missing {key}")
        if destination.get("id") in seen:
            errors.append(f"{label} has a duplicate id: {destination.get('id')}")
        seen.add(destination.get("id"))

if errors:
    print("Config has problems:")
    for error in errors:
        print(f"- {error}")
    sys.exit(1)

print(f"Config OK: {config_path}")
print(f"qBittorrent: {qbit['url']} as {qbit['username']}")
print(f"Destinations: {len(destinations)}")
if plex.get("databasePath"):
    print(f"Plex database: {plex['databasePath']}")
else:
    print("Plex database: not configured")
