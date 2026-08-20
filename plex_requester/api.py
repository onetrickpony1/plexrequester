"""HTTP API handlers and threaded application server."""

from functools import wraps
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer


_backend_namespace = None


def _sync_backend():
    if _backend_namespace is None:
        raise RuntimeError("The API backend has not been configured.")
    for name, value in _backend_namespace.items():
        if not name.startswith("__"):
            globals()[name] = value


def configure_backend(namespace):
    """Bind the live compatibility facade used by API handlers."""
    global _backend_namespace
    _backend_namespace = namespace
    _sync_backend()


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
        if parsed.path == "/api/subfolders/parent-match":
            if not self.require_admin():
                return
            return self.send_json(self.parent_folder_match_response(parsed.query))
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

    def parent_folder_match_response(self, query):
        params = parse.parse_qs(query)
        destination_id = params.get("destinationId", [""])[0]
        parent_name = params.get("name", [""])[0]
        destinations = {item["id"]: item for item in self.server.config["destinations"]}
        destination = destinations.get(destination_id)
        if not destination:
            return {"match": None, "error": "Choose one of the configured destinations."}
        try:
            return {"match": find_destination_parent_folder(destination, parent_name)}
        except ValueError as exc:
            return {"match": None, "error": str(exc)}

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



def _live_backend_method(method):
    @wraps(method)
    def call(*args, **kwargs):
        _sync_backend()
        return method(*args, **kwargs)
    return call


for _handler_class in (AppHandler, AppServer):
    for _name, _method in list(vars(_handler_class).items()):
        if callable(_method) and not _name.startswith("__"):
            setattr(_handler_class, _name, _live_backend_method(_method))
