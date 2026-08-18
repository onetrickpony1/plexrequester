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
        self.assertEqual(server.notification_outbox_path(), self.data_dir / "notification-outbox.json")

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

    def test_atomic_json_write_replaces_complete_file_and_cleans_temporary_file(self):
        target = self.data_dir / "requests.json"
        server.atomic_write_json(target, [{"id": "new"}])
        self.assertEqual(json.loads(target.read_text(encoding="utf-8")), [{"id": "new"}])
        self.assertTrue(target.read_text(encoding="utf-8").endswith("\n"))
        self.assertEqual(list(target.parent.glob(f".{target.name}.*.tmp")), [])

    def test_atomic_json_write_preserves_original_when_serialization_fails(self):
        target = self.data_dir / "requests.json"
        target.parent.mkdir(parents=True)
        original = '[{"id": "original"}]\n'
        target.write_text(original, encoding="utf-8")

        def interrupted_dump(_payload, handle, indent=None):
            handle.write('{"incomplete":')
            handle.flush()
            raise OSError("simulated interrupted write")

        with (
            mock.patch.object(server.json, "dump", side_effect=interrupted_dump),
            self.assertRaisesRegex(OSError, "simulated interrupted write"),
        ):
            server.atomic_write_json(target, [{"id": "replacement"}])

        self.assertEqual(target.read_text(encoding="utf-8"), original)
        self.assertEqual(list(target.parent.glob(f".{target.name}.*.tmp")), [])

    def test_all_json_stores_use_atomic_writer(self):
        config_path = self.data_dir / "config.json"
        config = {"_save_config_path": str(config_path), "app": {"version": "v8.3"}}
        with mock.patch.object(server, "atomic_write_json") as atomic_write:
            server.save_requests([{"id": "one"}])
            server.save_fulfillment_state({"one": {"lastState": "open"}})
            server.save_auth_sessions({"token": {"role": "admin"}})
            server.save_notification_outbox([{"id": "notification"}])
            server.save_config(config)

        self.assertEqual(atomic_write.call_count, 5)
        self.assertEqual(
            [call.args[0].name for call in atomic_write.call_args_list],
            [
                "requests.json",
                "request-fulfillment-state.json",
                "auth-sessions.json",
                "notification-outbox.json",
                "config.json",
            ],
        )


class AppVersionConfigTests(unittest.TestCase):
    def payload(self, version="v8.3"):
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


class MultiDirectoryDestinationTests(unittest.TestCase):
    def usage(self, percent):
        return {"total": 1000, "used": percent * 10, "free": (100 - percent) * 10, "percent": percent}

    def test_old_single_path_destination_remains_supported(self):
        destination = {"id": "movies", "path": "G:/Movies"}
        self.assertEqual(server.destination_paths(destination), ["G:/Movies"])
        self.assertEqual(server.destination_base_path(destination, 0), "G:/Movies")

    def test_fullest_directory_below_ninety_percent_is_default(self):
        destination = {"paths": ["G:/Movies", "F:/Movies", "H:/Movies"]}
        usages = [self.usage(89), self.usage(70), self.usage(95)]
        with mock.patch.object(server, "disk_usage_for_path", side_effect=usages):
            choices = server.destination_directory_choices(destination)
        self.assertEqual(next(choice["index"] for choice in choices if choice["default"]), 0)

    def test_next_fullest_directory_is_used_after_ninety_percent(self):
        destination = {"paths": ["G:/Movies", "F:/Movies", "H:/Movies"]}
        usages = [self.usage(91), self.usage(70), self.usage(95)]
        with mock.patch.object(server, "disk_usage_for_path", side_effect=usages):
            choices = server.destination_directory_choices(destination)
        self.assertEqual(next(choice["index"] for choice in choices if choice["default"]), 1)

    def test_least_full_directory_is_safe_fallback_when_all_are_over_threshold(self):
        destination = {"paths": ["G:/Movies", "F:/Movies", "H:/Movies"]}
        usages = [self.usage(91), self.usage(96), self.usage(94)]
        with mock.patch.object(server, "disk_usage_for_path", side_effect=usages):
            choices = server.destination_directory_choices(destination)
        self.assertEqual(next(choice["index"] for choice in choices if choice["default"]), 0)

    def test_selected_directory_index_is_validated(self):
        destination = {"paths": ["G:/Movies", "F:/Movies"]}
        self.assertEqual(server.destination_base_path(destination, "1"), "F:/Movies")
        with self.assertRaisesRegex(ValueError, "configured destination directories"):
            server.destination_base_path(destination, "2")

    def test_admin_config_saves_multiple_paths_and_legacy_first_path(self):
        config = {"notifications": {}}
        payload = {
            "app": {"version": "v8.3"},
            "qbittorrent": {"url": "http://localhost:8080"},
            "plex": {"databasePath": ""},
            "discordUserMappings": [],
            "destinations": [{
                "id": "movies",
                "label": "Movies",
                "paths": ["G:/Movies", "F:/Movies"],
            }],
        }
        server.apply_editable_config(config, payload)
        self.assertEqual(config["destinations"][0]["paths"], ["G:/Movies", "F:/Movies"])
        self.assertEqual(config["destinations"][0]["path"], "G:/Movies")

    def test_editable_config_supplies_paths_for_old_config(self):
        config = {"destinations": [{"id": "tv", "label": "TV", "path": "F:/TV"}]}
        editable = server.editable_config(config)
        self.assertEqual(editable["destinations"][0]["paths"], ["F:/TV"])


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

    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.env_patch = mock.patch.dict(
            server.os.environ,
            {"PLEX_REQUESTER_DATA_DIR": self.temp_dir.name},
            clear=False,
        )
        self.env_patch.start()

    def tearDown(self):
        self.env_patch.stop()
        self.temp_dir.cleanup()

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
        self.assertIn(f"<@{self.discord_id}>", payload["content"])
        self.assertIn("request has been received", payload["content"])
        self.assertEqual(payload["allowed_mentions"], {"parse": [], "users": [self.discord_id]})
        embed = payload["embeds"][0]
        self.assertEqual(embed["title"], "New Plex Request")
        self.assertEqual(embed["fields"][0]["value"], "Matthew")
        self.assertEqual(embed["color"], 0xE5A00D)

    def test_mapping_is_case_insensitive_and_whitespace_trimmed(self):
        config = self.config({"Matthew": self.discord_id})
        self.assertEqual(server.discord_user_id_for_requester(config, "mAtThEw"), self.discord_id)
        self.assertEqual(server.discord_user_id_for_requester(config, "  Matthew  "), self.discord_id)

    def test_unmapped_requester_sends_without_a_mention(self):
        payload = self.webhook_payload(
            self.config({"Matthew": self.discord_id}),
            self.item("John"),
        )
        self.assertNotIn("content", payload)
        self.assertEqual(payload["allowed_mentions"], {"parse": []})
        self.assertEqual(payload["embeds"][0]["fields"][0]["value"], "John")

    def test_requester_markup_cannot_trigger_arbitrary_mention(self):
        attacker_id = "987654321098765432"
        payload = self.webhook_payload(
            self.config({"Matthew": self.discord_id}),
            self.item(f"<@{attacker_id}>"),
        )
        self.assertNotIn("content", payload)
        self.assertEqual(payload["embeds"][0]["fields"][0]["value"], f"<@{attacker_id}>")
        self.assertEqual(payload["allowed_mentions"], {"parse": []})

    def test_request_embed_includes_tmdb_context_and_library_note(self):
        item = self.item("Matthew")
        item["tmdb"] = {
            "id": 123,
            "type": "movie",
            "title": "Example Movie",
            "year": 2026,
            "overview": "A polished overview.",
            "posterPath": "/poster.jpg",
        }
        item["libraryWarning"] = "A lower-quality copy is already in Plex."
        embed = server.discord_request_embed(item)
        self.assertEqual(embed["url"], "https://www.themoviedb.org/movie/123")
        self.assertEqual(embed["thumbnail"]["url"], "https://image.tmdb.org/t/p/w342/poster.jpg")
        self.assertIn("A polished overview.", embed["description"])
        self.assertEqual(embed["fields"][-1]["name"], "Library note")

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
        self.assertEqual(
            server.editable_config(config)["discordWebhookUrl"],
            "https://discord.invalid/webhook",
        )

    def test_admin_config_saves_request_webhook(self):
        config = self.config()
        payload = self.editable_payload([])
        payload["discordWebhookUrl"] = "https://discord.com/api/webhooks/456/request-token"
        server.apply_editable_config(config, payload)
        self.assertEqual(
            config["notifications"]["discordWebhookUrl"],
            "https://discord.com/api/webhooks/456/request-token",
        )

    def test_older_admin_payload_preserves_request_webhook(self):
        config = self.config()
        server.apply_editable_config(config, self.editable_payload([]))
        self.assertEqual(
            config["notifications"]["discordWebhookUrl"],
            "https://discord.invalid/webhook",
        )

    def test_invalid_request_webhook_is_rejected(self):
        config = self.config()
        payload = self.editable_payload([])
        payload["discordWebhookUrl"] = "https://example.com/not-discord"
        with self.assertRaisesRegex(ValueError, "valid HTTPS Discord webhook"):
            server.apply_editable_config(config, payload)

    def test_older_admin_payload_preserves_reminder_webhook(self):
        config = self.config()
        config["notifications"]["adminReminderWebhookUrl"] = "https://discord.com/api/webhooks/123/token"
        server.apply_editable_config(config, self.editable_payload([]))
        self.assertEqual(
            config["notifications"]["adminReminderWebhookUrl"],
            "https://discord.com/api/webhooks/123/token",
        )

    def test_invalid_reminder_webhook_is_rejected(self):
        config = self.config()
        payload = self.editable_payload([])
        payload["adminReminderWebhookUrl"] = "https://example.com/not-discord"
        with self.assertRaisesRegex(ValueError, "valid HTTPS Discord webhook"):
            server.apply_editable_config(config, payload)

    def test_admin_reminder_webhook_disables_mentions(self):
        response = mock.MagicMock()
        response.__enter__.return_value.read.return_value = b""
        config = self.config()
        config["notifications"]["adminReminderWebhookUrl"] = "https://discord.com/api/webhooks/123/token"
        with mock.patch.object(server.request, "urlopen", return_value=response) as urlopen:
            result = server.notify_admin_unfulfilled_requests(
                config,
                [{"requester": "<@987654321098765432>", "customTitle": "Example", "requestedAt": 1}],
                now=3601,
            )
        payload = json.loads(urlopen.call_args.args[0].data.decode("utf-8"))
        self.assertTrue(result)
        self.assertEqual(payload["allowed_mentions"], {"parse": []})
        self.assertEqual(payload["embeds"][0]["title"], "Unfulfilled Plex Requests")
        self.assertIn("<@987654321098765432>", payload["embeds"][0]["fields"][0]["value"])
        self.assertEqual(urlopen.call_args.args[0].full_url, config["notifications"]["adminReminderWebhookUrl"])

    def test_reminder_summary_paginates_after_twenty_five_fields(self):
        response = mock.MagicMock()
        response.__enter__.return_value.read.return_value = b""
        config = self.config()
        config["notifications"]["adminReminderWebhookUrl"] = "https://discord.com/api/webhooks/123/token"
        items = [
            {"id": str(index), "requester": f"User {index}", "customTitle": f"Movie {index}", "requestedAt": 1}
            for index in range(26)
        ]
        with mock.patch.object(server.request, "urlopen", return_value=response) as urlopen:
            self.assertTrue(server.notify_admin_unfulfilled_requests(config, items, now=3601))
        self.assertEqual(urlopen.call_count, 2)
        payloads = [
            json.loads(call.args[0].data.decode("utf-8"))
            for call in urlopen.call_args_list
        ]
        self.assertEqual([len(payload["embeds"][0]["fields"]) for payload in payloads], [25, 1])
        self.assertIn("Part 1 of 2", payloads[0]["embeds"][0]["description"])
        self.assertIn("Part 2 of 2", payloads[1]["embeds"][0]["description"])

    def test_reminder_pages_stay_within_discord_character_limit(self):
        config = self.config()
        items = [
            {
                "id": str(index),
                "requester": "R" * 500,
                "customTitle": f"{index}-" + ("T" * 500),
                "quality": "Q" * 500,
                "requestedAt": 1,
            }
            for index in range(30)
        ]
        embeds = server.discord_admin_reminder_embeds(config, items, now=3601)
        self.assertGreater(len(embeds), 1)
        self.assertEqual(sum(len(embed["fields"]) for embed in embeds), len(items))
        for embed in embeds:
            self.assertLessEqual(len(embed["fields"]), server.DISCORD_EMBED_MAX_FIELDS)
            self.assertLessEqual(
                server.discord_embed_character_count(embed),
                server.DISCORD_EMBED_MAX_CHARACTERS,
            )

    def test_waiting_time_uses_days_after_twenty_four_hours(self):
        item = {"requestedAt": 1}
        self.assertEqual(server.discord_waiting_time(item, now=3601), "1h")
        self.assertEqual(server.discord_waiting_time(item, now=165661), "1d 22h 1m")

    def test_due_reminders_send_one_summary_of_all_open_unmuted_requests(self):
        config = self.config()
        config["notifications"]["adminReminderWebhookUrl"] = "https://discord.com/api/webhooks/123/token"
        items = [
            {"id": "one", "requestedAt": 1, "customTitle": "One", "reminderMuted": False},
            {"id": "two", "requestedAt": 3500, "customTitle": "Two", "reminderMuted": False},
            {"id": "muted", "requestedAt": 1, "customTitle": "Muted", "reminderMuted": True},
        ]
        history = {}
        with mock.patch.object(server, "notify_admin_unfulfilled_requests", return_value=True) as notify:
            changed = server.send_due_admin_reminders(config, items, history, now=3601)
        self.assertTrue(changed)
        notify.assert_called_once()
        self.assertEqual([item["id"] for item in notify.call_args.args[1]], ["one", "two"])
        self.assertEqual(history["one"]["lastAdminReminderAt"], 3601)
        self.assertEqual(history["two"]["lastAdminReminderAt"], 3601)
        self.assertNotIn("muted", history)

    def test_reminder_waits_one_hour_and_is_throttled_for_another_hour(self):
        config = self.config()
        config["notifications"]["adminReminderWebhookUrl"] = "https://discord.com/api/webhooks/123/token"
        item = {"id": "one", "requestedAt": 100, "customTitle": "One"}
        history = {"one": {"lastState": "open", "lastAdminReminderAt": 3700}}
        with mock.patch.object(server, "notify_admin_unfulfilled_requests") as notify:
            self.assertFalse(server.send_due_admin_reminders(config, [item], history, now=7299))
            notify.assert_not_called()

    def test_reminder_interval_defaults_to_sixty_minutes_for_old_config(self):
        self.assertEqual(server.admin_reminder_interval_minutes({"notifications": {}}), 60)

    def test_configured_reminder_interval_controls_first_and_repeat_delay(self):
        config = self.config()
        config["notifications"].update({
            "adminReminderWebhookUrl": "https://discord.com/api/webhooks/123/token",
            "adminReminderIntervalMinutes": 30,
        })
        item = {"id": "one", "requestedAt": 100, "customTitle": "One"}
        history = {"one": {"lastState": "open"}}
        with mock.patch.object(server, "notify_admin_unfulfilled_requests", return_value=True) as notify:
            self.assertTrue(server.send_due_admin_reminders(config, [item], history, now=1900))
            notify.assert_called_once()
            notify.reset_mock()
            self.assertFalse(server.send_due_admin_reminders(config, [item], history, now=3699))
            notify.assert_not_called()

    def test_admin_config_saves_reminder_interval(self):
        config = self.config()
        payload = self.editable_payload([])
        payload["adminReminderIntervalMinutes"] = 45
        server.apply_editable_config(config, payload)
        self.assertEqual(config["notifications"]["adminReminderIntervalMinutes"], 45)
        self.assertEqual(server.editable_config(config)["adminReminderIntervalMinutes"], 45)

    def test_invalid_admin_reminder_interval_is_rejected(self):
        config = self.config()
        payload = self.editable_payload([])
        payload["adminReminderIntervalMinutes"] = 0
        with self.assertRaisesRegex(ValueError, "between 1 and 10080"):
            server.apply_editable_config(config, payload)

    def test_muting_request_is_persisted(self):
        items = [{"id": "one", "customTitle": "One"}]
        with (
            mock.patch.object(server, "load_requests", return_value=items),
            mock.patch.object(server, "save_requests") as save_requests,
        ):
            self.assertTrue(server.set_request_reminder_muted("one", True))
        self.assertTrue(items[0]["reminderMuted"])
        save_requests.assert_called_once_with(items)

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
        self.assertIn(f"<@{self.discord_id}>", payload["content"])
        self.assertIn("now available on Plex", payload["content"])
        embed = payload["embeds"][0]
        self.assertEqual(embed["title"], "Now Available on Plex")
        self.assertEqual(embed["fields"][0]["value"], "Matthew")
        self.assertEqual(embed["fields"][2]["value"], "1080p")
        self.assertEqual(embed["color"], 0x57F287)

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
        self.assertNotIn("content", payload)
        self.assertEqual(payload["embeds"][0]["fields"][0]["value"], "John")

    def test_admin_config_save_stops_before_reading_body_when_unauthorized(self):
        handler = object.__new__(server.AppHandler)
        handler.require_admin = mock.Mock(return_value=False)
        handler.read_json_body = mock.Mock()
        handler.admin_config_save()
        handler.read_json_body.assert_not_called()

    def test_reminder_mute_stops_before_reading_body_when_unauthorized(self):
        handler = object.__new__(server.AppHandler)
        handler.require_admin = mock.Mock(return_value=False)
        handler.read_json_body = mock.Mock()
        handler.set_request_reminder_mute()
        handler.read_json_body.assert_not_called()


class NotificationOutboxTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.env_patch = mock.patch.dict(
            server.os.environ,
            {"PLEX_REQUESTER_DATA_DIR": self.temp_dir.name},
            clear=False,
        )
        self.env_patch.start()
        self.config = {
            "notifications": {
                "discordWebhookUrl": "https://discord.com/api/webhooks/123/secret-token",
            },
        }

    def tearDown(self):
        self.env_patch.stop()
        self.temp_dir.cleanup()

    def response(self):
        response = mock.MagicMock()
        response.__enter__.return_value.read.return_value = b""
        return response

    def test_failed_delivery_is_persisted_with_exponential_retry_metadata(self):
        with mock.patch.object(server.request, "urlopen", side_effect=OSError("Discord unavailable")):
            queued = server.queue_discord_notification(
                self.config,
                "primary",
                "request-created:one",
                embeds=[{"title": "New request"}],
                now=100,
            )
        self.assertTrue(queued)
        jobs = server.load_notification_outbox()
        self.assertEqual(len(jobs), 1)
        self.assertEqual(jobs[0]["status"], "failed")
        self.assertEqual(jobs[0]["attempts"], 1)
        self.assertEqual(jobs[0]["nextAttemptAt"], 115)
        self.assertIn("Discord unavailable", jobs[0]["lastError"])

    def test_failed_delivery_retries_when_due_and_becomes_sent(self):
        with mock.patch.object(server.request, "urlopen", side_effect=OSError("temporary failure")):
            server.queue_discord_notification(
                self.config,
                "primary",
                "request-fulfilled:one",
                content="Ready",
                now=100,
            )

        with mock.patch.object(server.request, "urlopen", return_value=self.response()) as urlopen:
            self.assertEqual(server.process_notification_outbox(self.config, now=114), {"sent": 0, "failed": 0})
            urlopen.assert_not_called()
            self.assertEqual(server.process_notification_outbox(self.config, now=115), {"sent": 1, "failed": 0})
            urlopen.assert_called_once()

        job = server.load_notification_outbox()[0]
        self.assertEqual(job["status"], "sent")
        self.assertEqual(job["attempts"], 2)
        self.assertEqual(job["sentAt"], 115)
        self.assertEqual(job["lastError"], "")

    def test_idempotency_key_prevents_duplicate_delivery(self):
        with mock.patch.object(server.request, "urlopen", return_value=self.response()) as urlopen:
            for _index in range(2):
                self.assertTrue(server.queue_discord_notification(
                    self.config,
                    "primary",
                    "request-created:same-request",
                    content="Created",
                    now=100,
                ))
        self.assertEqual(urlopen.call_count, 1)
        self.assertEqual(len(server.load_notification_outbox()), 1)

    def test_outbox_does_not_duplicate_webhook_secret(self):
        with mock.patch.object(server.request, "urlopen", side_effect=OSError("offline")):
            server.queue_discord_notification(
                self.config,
                "primary",
                "request-created:secret-check",
                content="Created",
                now=100,
            )
        raw = server.notification_outbox_path().read_text(encoding="utf-8")
        self.assertNotIn("secret-token", raw)
        self.assertIn('"target": "primary"', raw)

    def test_retry_delay_is_bounded(self):
        self.assertEqual(server.notification_retry_delay(1), 15)
        self.assertEqual(server.notification_retry_delay(2), 30)
        self.assertEqual(server.notification_retry_delay(3), 60)
        self.assertEqual(server.notification_retry_delay(100), 3600)


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
    def test_quality_ladder_accepts_requested_tier_or_higher(self):
        expectations = [
            ("1080p", {"1080p"}, True),
            ("1080p", {"4K"}, True),
            ("1080p", {"REMUX"}, True),
            ("4K", {"1080p"}, False),
            ("4K", {"4K"}, True),
            ("4K", {"REMUX", "1080p"}, True),
            ("REMUX", {"1080p", "4K"}, False),
            ("REMUX", {"REMUX", "4K"}, True),
        ]
        for requested, available, expected in expectations:
            with self.subTest(requested=requested, available=available):
                self.assertEqual(
                    server.quality_satisfies_request(requested, available),
                    expected,
                )

    def test_detected_item_waits_until_plex_analysis_is_complete(self):
        item = {
            "quality": "1080p",
            "tmdb": {"id": 1, "type": "movie", "title": "Example", "year": "2026"},
        }
        analysis = {
            "match": {"id": 10, "type": "movie", "title": "Example", "year": "2026"},
            "qualities": set(),
            "summary": "",
            "analyzed": False,
        }
        with mock.patch.object(server, "plex_analysis_for_tmdb", return_value=analysis):
            result = server.current_request_plex_status({}, item)
        self.assertEqual(result["state"], "open")
        self.assertIn("waiting for Plex media analysis", result["message"])

    def test_analyzed_item_is_fulfilled_with_mbps_details(self):
        item = {
            "quality": "1080p",
            "tmdb": {"id": 1, "type": "movie", "title": "Example", "year": "2026"},
        }
        analysis = {
            "match": {"id": 10, "type": "movie", "title": "Example", "year": "2026"},
            "qualities": {"1080p"},
            "summary": "1080p - 12.5 Mbps - H264",
            "analyzed": True,
        }
        with mock.patch.object(server, "plex_analysis_for_tmdb", return_value=analysis):
            result = server.current_request_plex_status({}, item)
        self.assertEqual(result["state"], "fulfilled")
        self.assertEqual(result["message"], "Fulfilled: 1080p - 12.5 Mbps - H264.")

    def test_higher_quality_item_fulfills_lower_quality_request(self):
        item = {
            "quality": "1080p",
            "tmdb": {"id": 1, "type": "movie", "title": "Example", "year": "2026"},
        }
        analysis = {
            "match": {"id": 10, "type": "movie", "title": "Example", "year": "2026"},
            "qualities": {"4K"},
            "summary": "4K - 48 Mbps - HEVC",
            "analyzed": True,
        }
        with mock.patch.object(server, "plex_analysis_for_tmdb", return_value=analysis):
            result = server.current_request_plex_status({}, item)
        self.assertEqual(result["state"], "fulfilled")
        self.assertEqual(result["message"], "Fulfilled: 4K - 48 Mbps - HEVC.")
        self.assertEqual(
            server.discord_fulfillment_detail(item, result),
            "4K - 48 Mbps - HEVC",
        )

    def test_lower_quality_item_does_not_fulfill_higher_quality_request(self):
        item = {
            "quality": "4K",
            "tmdb": {"id": 1, "type": "movie", "title": "Example", "year": "2026"},
        }
        analysis = {
            "match": {"id": 10, "type": "movie", "title": "Example", "year": "2026"},
            "qualities": {"1080p"},
            "summary": "1080p - 12.5 Mbps - H264",
            "analyzed": True,
        }
        with mock.patch.object(server, "plex_analysis_for_tmdb", return_value=analysis):
            result = server.current_request_plex_status({}, item)
        self.assertEqual(result["state"], "partial")
        self.assertIn("different quality", result["message"])

    def test_media_analysis_requires_bitrate_resolution_and_codec(self):
        complete = {"id": 1, "bitrate": 12500, "width": 1920, "height": 1080, "video_codec": "h264"}
        self.assertTrue(server.media_analysis_complete([complete], []))
        for missing in ("bitrate", "width", "height", "video_codec"):
            incomplete = dict(complete)
            incomplete.pop(missing)
            if missing in {"width", "height"}:
                incomplete.pop("width" if missing == "height" else "height", None)
            self.assertFalse(server.media_analysis_complete([incomplete], []))

    def test_movie_summary_reports_mbps(self):
        media = [{"id": 1, "bitrate": 12500, "width": 1920, "height": 1080, "video_codec": "h264"}]
        self.assertEqual(server.media_quality_summary(media, []), "1080p - 12.5 Mbps - H264")

    def test_tv_summary_reports_average_episode_mbps(self):
        media = [
            {"id": 1, "metadata_item_id": 101, "bitrate": 8000, "width": 1920, "height": 1080, "video_codec": "h264"},
            {"id": 2, "metadata_item_id": 102, "bitrate": 12000, "width": 1920, "height": 1080, "video_codec": "h264"},
        ]
        self.assertEqual(
            server.media_quality_summary(media, [], average_bitrate=True),
            "1080p - 10 Mbps average - H264",
        )

    def test_tv_average_counts_each_episode_once_when_it_has_multiple_versions(self):
        media = [
            {"id": 1, "metadata_item_id": 101, "bitrate": 8000},
            {"id": 2, "metadata_item_id": 101, "bitrate": 10000},
            {"id": 3, "metadata_item_id": 102, "bitrate": 12000},
        ]
        self.assertEqual(server.average_episode_bitrate(media, []), 11000)

    def test_fulfillment_monitor_defaults_to_fastest_interval(self):
        with mock.patch.dict(server.os.environ, {}, clear=True):
            self.assertEqual(server.fulfillment_check_interval(), 15)

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
