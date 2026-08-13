import base64
import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from unittest import mock

import server


class ServerPortConfigTests(unittest.TestCase):
    def test_configured_server_port_accepts_valid_port(self):
        self.assertEqual(server.configured_server_port({"server": {"port": 9443}}), 9443)

    def test_configured_server_port_accepts_numeric_string(self):
        self.assertEqual(server.configured_server_port({"server": {"port": "8085"}}), 8085)

    def test_configured_server_port_rejects_invalid_values(self):
        for value in (0, 65536, "invalid", None):
            self.assertEqual(
                server.configured_server_port({"server": {"port": value}}),
                server.DEFAULT_SERVER_PORT,
            )

    def test_parent_monitor_is_disabled_without_packaged_launcher_environment(self):
        with mock.patch.dict(server.os.environ, {}, clear=True):
            self.assertIsNone(server.start_parent_process_monitor(mock.Mock()))

    def test_parent_monitor_rejects_invalid_parent_pid(self):
        with mock.patch.dict(server.os.environ, {"PLEX_REQUESTER_PARENT_PID": "invalid"}, clear=False):
            self.assertIsNone(server.start_parent_process_monitor(mock.Mock()))


class UserDataStorageTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.root = Path(self.temp_dir.name)
        self.legacy_dir = self.root / "legacy"
        self.data_dir = self.root / "appdata" / "Plex Requester"
        self.legacy_dir.mkdir()
        self.base_patch = mock.patch.object(server, "BASE_DIR", self.legacy_dir)
        self.env_patch = mock.patch.dict(
            server.os.environ,
            {"PLEX_REQUESTER_DATA_DIR": str(self.data_dir)},
            clear=False,
        )
        self.base_patch.start()
        self.env_patch.start()

    def tearDown(self):
        self.env_patch.stop()
        self.base_patch.stop()
        self.temp_dir.cleanup()

    def test_requested_data_files_use_user_appdata_directory(self):
        self.assertEqual(server.request_store_path(), self.data_dir / "requests.json")
        self.assertEqual(server.fulfillment_state_path(), self.data_dir / "request-fulfillment-state.json")
        self.assertEqual(server.user_data_path("rename-history.jsonl"), self.data_dir / "rename-history.jsonl")
        self.assertEqual(server.user_data_path("config.json"), self.data_dir / "config.json")
        self.assertEqual(server.auth_store_path(), self.data_dir / "auth-sessions.json")

    def test_legacy_file_is_migrated_once(self):
        legacy = self.legacy_dir / "requests.json"
        legacy.write_text('[{"id": "old"}]', encoding="utf-8")
        target = server.request_store_path()
        self.assertEqual(target.read_text(encoding="utf-8"), '[{"id": "old"}]')

        legacy.write_text('[{"id": "changed"}]', encoding="utf-8")
        self.assertEqual(server.request_store_path().read_text(encoding="utf-8"), '[{"id": "old"}]')

    def test_existing_appdata_file_is_not_overwritten(self):
        self.data_dir.mkdir(parents=True)
        (self.legacy_dir / "request-fulfillment-state.json").write_text('{"legacy": true}', encoding="utf-8")
        target = self.data_dir / "request-fulfillment-state.json"
        target.write_text('{"current": true}', encoding="utf-8")
        self.assertEqual(server.fulfillment_state_path().read_text(encoding="utf-8"), '{"current": true}')


class AppVersionConfigTests(unittest.TestCase):
    def payload(self, version="v7.2"):
        return {
            "app": {"version": version},
            "qbittorrent": {"url": "http://localhost:8080"},
            "plex": {"databasePath": ""},
            "destinations": [{"id": "movies", "label": "Movies", "path": "D:/Movies"}],
            "discordUserMappings": [],
        }

    def test_version_is_exposed_to_admin_config(self):
        self.assertEqual(
            server.editable_config({"app": {"version": "v6.0"}})["app"]["version"],
            "v6.0",
        )

    def test_version_is_saved_from_admin_config(self):
        config = {"notifications": {}}
        server.apply_editable_config(config, self.payload("v6.1"))
        self.assertEqual(config["app"]["version"], "v6.1")

    def test_empty_version_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "App version is required"):
            server.apply_editable_config({"notifications": {}}, self.payload("  "))

    def test_older_admin_payload_preserves_current_version(self):
        config = {"app": {"version": "v7.0"}, "notifications": {}}
        payload = self.payload()
        payload.pop("app")
        server.apply_editable_config(config, payload)
        self.assertEqual(config["app"]["version"], "v7.0")

    def test_missing_admin_pin_does_not_authenticate_empty_input(self):
        self.assertEqual(server.role_from_pin({}, ""), "")
        self.assertFalse(server.pin_matches({}, ""))


class TorrentUploadTests(unittest.TestCase):
    def setUp(self):
        self.info = b"d4:name8:test.mkv6:lengthi12345ee"
        self.torrent = b"d8:announce14:http://tracker4:info" + self.info + b"e"

    def test_torrent_info_hash_uses_raw_info_dictionary(self):
        self.assertEqual(server.torrent_info_hash(self.torrent), hashlib.sha1(self.info).hexdigest())

    def test_decode_torrent_upload(self):
        name, data = server.decode_torrent_upload({
            "torrentFileName": "example.torrent",
            "torrentData": base64.b64encode(self.torrent).decode("ascii"),
        })
        self.assertEqual(name, "example.torrent")
        self.assertEqual(data, self.torrent)

    def test_decode_rejects_wrong_extension(self):
        with self.assertRaisesRegex(ValueError, r"\.torrent"):
            server.decode_torrent_upload({
                "torrentFileName": "example.txt",
                "torrentData": base64.b64encode(self.torrent).decode("ascii"),
            })

    def test_decode_rejects_invalid_bencode(self):
        with self.assertRaisesRegex(ValueError, "valid .torrent"):
            server.decode_torrent_upload({
                "torrentFileName": "example.torrent",
                "torrentData": base64.b64encode(b"not a torrent").decode("ascii"),
            })

    def test_qbit_add_accepts_legacy_success_response(self):
        self.assertEqual(server.qbit_add_torrent_hash("Ok.", "fallback"), "fallback")

    def test_qbit_add_accepts_json_success_response(self):
        torrent_id = "579919592114f92e5f15a7a16a4ca600ff307c5d"
        response = json.dumps({
            "added_torrent_ids": [torrent_id],
            "failure_count": 0,
            "pending_count": 0,
            "success_count": 1,
        })
        self.assertEqual(server.qbit_add_torrent_hash(response, "fallback"), torrent_id)

    def test_qbit_add_rejects_json_failure_response(self):
        response = json.dumps({
            "added_torrent_ids": [],
            "failure_count": 1,
            "pending_count": 0,
            "success_count": 0,
        })
        with self.assertRaisesRegex(RuntimeError, "rejected"):
            server.qbit_add_torrent_hash(response, "fallback")

    def test_qbit_filter_groups(self):
        downloading, current = server.qbit_torrent_filters({
            "state": "downloading", "progress": 0.5, "size": 100, "amount_left": 50,
            "dlspeed": 20, "upspeed": 0,
        })
        self.assertTrue(current)
        self.assertTrue({"downloading", "running", "active"}.issubset(downloading))

        stopped, current = server.qbit_torrent_filters({
            "state": "pausedDL", "progress": 0.5, "size": 100, "amount_left": 50,
            "dlspeed": 0, "upspeed": 0,
        })
        self.assertTrue(current)
        self.assertIn("stopped", stopped)
        self.assertIn("inactive", stopped)
        self.assertNotIn("downloading", stopped)

        seeding, current = server.qbit_torrent_filters({
            "state": "stalledUP", "progress": 1, "size": 100, "amount_left": 0,
            "dlspeed": 0, "upspeed": 0,
        })
        self.assertFalse(current)
        self.assertTrue({"seeding", "completed", "running", "inactive", "stalled"}.issubset(seeding))

    def test_qbit_status_includes_completed_torrents_and_totals(self):
        client = mock.Mock()
        client.torrents_info.return_value = [{
            "hash": "abc", "name": "Finished", "progress": 1, "size": 100,
            "amount_left": 0, "dlspeed": 0, "upspeed": 10, "eta": 0,
            "ratio": 2, "state": "uploading", "num_seeds": 4, "num_leechs": 2,
            "added_on": 123,
        }]
        client.transfer_info.return_value = {
            "dl_info_speed": 20, "up_info_speed": 10,
            "dl_info_data": 1000, "up_info_data": 250,
            "connection_status": "connected",
        }
        with mock.patch.object(server, "qbit_client_from_config", return_value=client):
            result = server.qbit_status_summary({})
        self.assertEqual(len(result["items"]), 1)
        self.assertEqual(result["items"][0]["numSeeds"], 4)
        self.assertEqual(result["transfer"]["totalDownload"], 1000)
        self.assertEqual(result["transfer"]["totalUpload"], 250)
        self.assertEqual(result["transfer"]["ratio"], 0.25)

    def test_session_controls_pause_and_resume_all(self):
        client = server.QbittorrentClient("http://localhost", "user", "pass")
        client.ensure_authenticated_for_write = mock.Mock()
        client._request = mock.Mock(return_value="Ok.")
        client.set_session_paused(True)
        client._request.assert_called_with("POST", "/api/v2/torrents/stop", {"hashes": "all"})
        client.set_session_paused(False)
        client._request.assert_called_with("POST", "/api/v2/torrents/start", {"hashes": "all"})

    def test_session_controls_fall_back_for_older_qbittorrent(self):
        client = server.QbittorrentClient("http://localhost", "user", "pass")
        client.ensure_authenticated_for_write = mock.Mock()
        client._request = mock.Mock(side_effect=[
            RuntimeError("qBittorrent returned HTTP 404: Endpoint does not exist"),
            "Ok.",
        ])
        client.set_session_paused(True)
        self.assertEqual(client._request.call_args_list, [
            mock.call("POST", "/api/v2/torrents/stop", {"hashes": "all"}),
            mock.call("POST", "/api/v2/torrents/pause", {"hashes": "all"}),
        ])


class DiscordRequesterMentionTests(unittest.TestCase):
    discord_id = "123456789012345678"

    def config(self, mappings=None):
        notifications = {
            "discordWebhookUrl": "https://discord.invalid/webhook",
        }
        if mappings is not None:
            notifications["discordUserMappings"] = mappings
        return {"notifications": notifications}

    def item(self, requester="Matthew"):
        return {
            "requester": requester,
            "customTitle": "Example Movie",
            "quality": "1080p",
            "tmdb": None,
            "libraryWarning": "",
        }

    def webhook_payload(self, config, item):
        response = mock.MagicMock()
        response.__enter__.return_value.read.return_value = b""
        with mock.patch.object(server.request, "urlopen", return_value=response) as urlopen:
            server.notify_request_created(config, item)
        request_object = urlopen.call_args.args[0]
        return json.loads(request_object.data.decode("utf-8"))

    def editable_payload(self, mappings):
        return {
            "qbittorrent": {"url": "http://localhost:8080"},
            "plex": {"databasePath": ""},
            "destinations": [{"id": "movies", "label": "Movies", "path": "D:/Movies"}],
            "discordUserMappings": mappings,
        }

    def test_mapped_requester_produces_restricted_mention(self):
        payload = self.webhook_payload(
            self.config({"Matthew": self.discord_id}),
            self.item("Matthew"),
        )
        self.assertIn(f"Notify: <@{self.discord_id}>", payload["content"])
        self.assertIn("Requester: Matthew", payload["content"])
        self.assertEqual(payload["allowed_mentions"], {"parse": [], "users": [self.discord_id]})

    def test_mapping_is_case_insensitive_and_whitespace_trimmed(self):
        config = self.config({"Matthew": self.discord_id})
        self.assertEqual(server.discord_user_id_for_requester(config, "mAtThEw"), self.discord_id)
        self.assertEqual(server.discord_user_id_for_requester(config, "  Matthew  "), self.discord_id)

    def test_unmapped_requester_sends_without_a_mention(self):
        payload = self.webhook_payload(
            self.config({"Matthew": self.discord_id}),
            self.item("John"),
        )
        self.assertNotIn("<@", payload["content"])
        self.assertEqual(payload["allowed_mentions"], {"parse": []})

    def test_requester_markup_cannot_trigger_arbitrary_mention(self):
        attacker_id = "987654321098765432"
        payload = self.webhook_payload(
            self.config({"Matthew": self.discord_id}),
            self.item(f"<@{attacker_id}>"),
        )
        self.assertIn(f"Requester: <@{attacker_id}>", payload["content"])
        self.assertEqual(payload["allowed_mentions"], {"parse": []})

    def test_invalid_discord_id_cannot_be_saved(self):
        config = {"notifications": {}}
        with self.assertRaisesRegex(ValueError, "15 to 20 digit"):
            server.apply_editable_config(config, self.editable_payload([
                {"requesterName": "Matthew", "discordUserId": "not-a-number"},
            ]))

    def test_duplicate_normalized_requester_cannot_be_saved(self):
        config = {"notifications": {}}
        with self.assertRaisesRegex(ValueError, "Duplicate requester name"):
            server.apply_editable_config(config, self.editable_payload([
                {"requesterName": "Matthew", "discordUserId": self.discord_id},
                {"requesterName": "  matthew  ", "discordUserId": "987654321098765432"},
            ]))

    def test_existing_config_without_mappings_still_works(self):
        config = self.config()
        self.assertEqual(server.discord_user_id_for_requester(config, "Matthew"), "")
        self.assertEqual(server.editable_config(config)["discordUserMappings"], [])

    def test_mapped_fulfillment_notification_mentions_same_requester(self):
        response = mock.MagicMock()
        response.__enter__.return_value.read.return_value = b""
        with mock.patch.object(server.request, "urlopen", return_value=response) as urlopen:
            result = server.notify_request_fulfilled(
                self.config({"Matthew": self.discord_id}),
                self.item("Matthew"),
                {"message": "Fulfilled: 1080p."},
            )
        payload = json.loads(urlopen.call_args.args[0].data.decode("utf-8"))
        self.assertTrue(result)
        self.assertEqual(payload["allowed_mentions"], {"parse": [], "users": [self.discord_id]})
        self.assertIn(f"Notify: <@{self.discord_id}>", payload["content"])
        self.assertIn("Requester: Matthew", payload["content"])

    def test_unmapped_fulfillment_notification_keeps_mentions_disabled(self):
        response = mock.MagicMock()
        response.__enter__.return_value.read.return_value = b""
        with mock.patch.object(server.request, "urlopen", return_value=response) as urlopen:
            result = server.notify_request_fulfilled(
                self.config({"Matthew": self.discord_id}),
                self.item("John"),
                {"message": "Fulfilled: 1080p."},
            )
        payload = json.loads(urlopen.call_args.args[0].data.decode("utf-8"))
        self.assertTrue(result)
        self.assertEqual(payload["allowed_mentions"], {"parse": []})
        self.assertNotIn("<@", payload["content"])

    def test_admin_config_save_stops_before_reading_body_when_unauthorized(self):
        handler = object.__new__(server.AppHandler)
        handler.require_admin = mock.Mock(return_value=False)
        handler.read_json_body = mock.Mock()
        handler.admin_config_save()
        handler.read_json_body.assert_not_called()


class PublicLibraryAccessTests(unittest.TestCase):
    def handler_for_path(self, path):
        handler = object.__new__(server.AppHandler)
        handler.path = path
        handler.require_admin = mock.Mock(return_value=False)
        handler.send_json = mock.Mock()
        return handler

    def test_library_search_does_not_require_admin(self):
        handler = self.handler_for_path("/api/library/search?q=Example&type=movie")
        handler.library_search_response = mock.Mock(return_value={"items": []})
        handler.do_GET()
        handler.require_admin.assert_not_called()
        handler.library_search_response.assert_called_once()
        handler.send_json.assert_called_once_with({"items": []})

    def test_library_item_details_do_not_require_admin(self):
        handler = self.handler_for_path("/api/library/item?id=123")
        handler.library_item_response = mock.Mock(return_value={"metadata": {"id": 123}})
        handler.do_GET()
        handler.require_admin.assert_not_called()
        handler.library_item_response.assert_called_once()
        handler.send_json.assert_called_once_with({"metadata": {"id": 123}})


class RequestRefreshPerformanceTests(unittest.TestCase):
    def test_request_display_uses_cached_state_without_plex_lookup(self):
        item = {
            "id": "request-1",
            "requester": "Matthew",
            "customTitle": "Example",
            "quality": "1080p",
        }
        history = {
            "request-1": {
                "lastState": "open",
                "lastMessage": "Not in Plex yet.",
            },
        }
        with (
            mock.patch.object(server, "load_requests", return_value=[item]),
            mock.patch.object(server, "load_fulfillment_state", return_value=history),
            mock.patch.object(server, "current_request_plex_status") as plex_status,
        ):
            result = server.requests_for_display()
        plex_status.assert_not_called()
        self.assertEqual(result[0]["fulfillment"]["state"], "open")

    def test_new_request_is_saved_without_waiting_for_plex_analysis(self):
        payload = {
            "requester": "Matthew",
            "quality": "1080p",
            "tmdbItem": {"id": 1, "type": "movie", "title": "Example", "year": "2026"},
        }
        with (
            mock.patch.object(server, "load_requests", return_value=[]),
            mock.patch.object(server, "save_requests") as save_requests,
            mock.patch.object(server, "library_warning_for_request") as library_warning,
        ):
            item = server.add_request({}, payload, "127.0.0.1")
        library_warning.assert_not_called()
        save_requests.assert_called_once()
        self.assertEqual(item["libraryWarning"], "")

    def test_repeated_plex_analysis_uses_memory_cache(self):
        config = {"plex": {"databasePath": ""}}
        tmdb_item = {"id": 1, "type": "movie", "title": "Example", "year": "2026"}
        match = {"id": 10, "type": "movie", "title": "Example", "year": "2026"}
        with server.PLEX_ANALYSIS_CACHE_LOCK:
            server.PLEX_ANALYSIS_CACHE.clear()
        with (
            mock.patch.object(server, "plex_match_for_tmdb", return_value=match) as plex_match,
            mock.patch.object(server, "media_rows_for_library_item", return_value=([], [])) as media_rows,
        ):
            first = server.plex_analysis_for_tmdb(config, tmdb_item)
            second = server.plex_analysis_for_tmdb(config, tmdb_item)
        self.assertIs(first, second)
        plex_match.assert_called_once()
        media_rows.assert_called_once()


class QbittorrentRoleViewTests(unittest.TestCase):
    def full_status(self):
        return {
            "ok": True,
            "transfer": {"totalUpload": 500, "totalDownload": 1000, "ratio": 0.5},
            "items": [
                {
                    "name": "Downloading",
                    "progress": 0.5,
                    "size": 100,
                    "dlspeed": 20,
                    "upspeed": 5,
                    "eta": 30,
                    "ratio": 1.2,
                    "numSeeds": 4,
                    "numPeers": 2,
                    "state": "downloading",
                    "hash": "abc",
                    "current": True,
                },
                {
                    "name": "Completed",
                    "progress": 1,
                    "size": 200,
                    "dlspeed": 0,
                    "upspeed": 10,
                    "eta": 0,
                    "ratio": 3,
                    "current": False,
                },
            ],
        }

    def test_public_status_contains_only_current_download_fields(self):
        result = server.public_qbit_status(self.full_status())
        self.assertNotIn("transfer", result)
        self.assertEqual(len(result["items"]), 1)
        self.assertEqual(set(result["items"][0]), {
            "name", "progress", "size", "dlspeed", "eta", "current",
        })

    def test_handler_returns_simple_status_for_visitor_and_full_status_for_admin(self):
        handler = object.__new__(server.AppHandler)
        handler.server = mock.Mock(config={})
        full_status = self.full_status()
        with mock.patch.object(server, "qbit_status_summary", return_value=full_status):
            handler.current_role = mock.Mock(return_value="")
            self.assertEqual(handler.qbit_status_response(), server.public_qbit_status(full_status))
            handler.current_role = mock.Mock(return_value="admin")
            self.assertIs(handler.qbit_status_response(), full_status)


if __name__ == "__main__":
    unittest.main()
