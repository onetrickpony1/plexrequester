# Codex Handoff: Working Rules and Plex Requester Context

Use this document as standing context when working with me in a new Codex account, task, or checkout. Read it before changing the project. If the repository has changed since this was written, inspect the current code and tests first, then preserve the intent below while adapting to the current implementation.

## How I want Codex to work

- Inspect and understand the existing code before implementing a request. Do not replace working behavior unnecessarily.
- When I ask for a feature or fix, implement it, verify it in proportion to its risk, and clearly summarize the result.
- Make reasonable, conservative assumptions when the intent is clear. Ask only when a missing choice would materially change the result or create risk.
- Preserve unrelated local changes and user data. Never solve an update by wiping configuration or runtime files.
- Treat security and privacy as requirements. Do not hardcode real credentials, API keys, PINs, tokens, webhooks, private URLs, session data, or personally identifying mappings in source-controlled files.
- Keep desktop and mobile usability in mind. In particular, test file inputs and responsive layouts for iOS-compatible behavior when they are affected.
- Make efficient use of desktop width and avoid layouts that cause needless scrolling, while retaining a usable mobile layout.
- Prefer clear user-facing errors. Successful responses from an external service must not be shown as failures merely because their response format changed.
- Keep documentation, examples, tests, and build scripts aligned with behavior whenever a change affects them.

## Versioning rule

- Increment the Plex Requester version by `0.1` whenever project source code or project documentation is edited.
- Do not increment the version for read-only investigation, explanations, or answers that make no file changes.
- Carry the version normally after `.9`: for example, `v5.9` becomes `v6.0`.
- The version for the changes that created this document was `v7.1`; the current code may be newer.
- Keep the default version in source, the safe example configuration, the README, frontend fallback text, and the live AppData configuration consistent when applicable.
- The administrator can edit the displayed version from the Config tab. Do not overwrite a deliberate later value without first understanding why it differs.
- The Windows build output should be named `Plex Requester_vX.X.exe` when a valid configured version can be read. If no valid version is available, build `Plex Requester.exe` without a version suffix. Release executables must include Python, the backend, and web assets so they run without loose source files or a system Python installation.

## Backward-compatibility rule

AppData backward compatibility is a standing priority for every update.

- Existing installations must continue working when newly introduced configuration fields are absent. Supply safe defaults in code.
- Prefer additive schema changes. Do not rename, remove, or reinterpret existing fields or files without a migration path.
- Preserve unknown configuration fields when saving settings so a newer or customized configuration is not silently stripped.
- Never overwrite an existing AppData file as part of automatic migration.
- Keep file names and JSON shapes copy-and-paste compatible whenever practical.
- When a data migration is unavoidable, make it one-way safe, idempotent, and tolerant of the old format. Back up material data before transforming it.
- Tests for a new configuration field should cover missing/old configurations as well as the new format.
- At the end of a change, explicitly report whether AppData compatibility was affected and mention any downgrade caveat.

## Plex Requester: purpose

Plex Requester is a lightweight self-hosted web application that lets users request movies and TV shows, check the Plex library, and submit magnet links or `.torrent` files to qBittorrent. It includes TMDb lookup, fulfillment tracking, Discord notifications, storage and rename tools, and role-specific qBittorrent monitoring.

The backend uses Python's standard library. The frontend uses plain HTML, CSS, and JavaScript. A C# Windows launcher provides the backend GUI and starts the Python server.

## Roles and intended access

- The Library tab is public and must be available to non-admin users.
- Request submission is available to normal users.
- Administrative configuration and privileged download controls remain admin-only.
- For non-admin users, the qBittorrent area is called **Status**, not qBittorrent.
- The non-admin Status page is intentionally simple: show current downloads with only name, size, download speed, and ETA. Do not expose upload/download totals, ratio statistics, filters, sorting controls, session controls, or add-download controls there.
- The admin qBittorrent page retains the full dashboard and controls.

## qBittorrent behavior

Admins can add downloads using either magnet links or `.torrent` files.

- `.torrent` uploads must work with the iOS file picker. Do not use a browser `accept` restriction that causes iOS to disable valid `.torrent` files; validate the extension/content and size in JavaScript and again on the server.
- The current upload size limit is 10 MB.
- Duplicate torrents are detected using the torrent info hash.
- Do not modify, sanitize, rebuild, or discard torrent metadata in a way that could break private trackers. Pass the original `.torrent` payload to qBittorrent.
- Accept both qBittorrent's older `Ok.` success response and newer JSON success responses.
- Admin status filters include: Downloading, Seeding, Completed, Running, Stopped, Active, Inactive, and Stalled. Filters can be turned off so the user can see the browser-session list of newly added torrents until they finish.
- Admin sorting includes: Name, Size, Progress, Status, Seeds, Peers, Down Speed, Up Speed, ETA, and Ratio. Search is also available.
- Admin session controls include Start Session and Pause Session. qBittorrent API-version differences should be handled so a missing endpoint does not turn an ordinary pause operation into an unexplained HTTP 404.
- Admin statistics include current speeds, total downloaded, total uploaded, ratio, and connection state.

## Requests, TMDb, and destinations

- Requests can be TMDb-backed or free-form and can specify quality.
- Avoid slow page refreshes caused by synchronous Plex scans. Serve cached request/fulfillment state quickly and perform expensive reconciliation in the background.
- The visible request list should refresh promptly; current behavior targets a five-second refresh interval.
- When a TV result such as `American Vandal (2017)` is selected with season 2, scan the configured TV shows destination for the presumed parent folder.
- Precheck **Add subfolder** and fill it with the exact show parent name whether that parent already exists or needs to be created. If it exists, write into that same parent folder.
- Keep the user in control: they can edit the suggested folder name or uncheck the option.
- The actual download/request name can remain season-specific; the suggested parent folder is show-specific.
- Handle name collisions safely. Do not silently overwrite an existing media folder or file.

## Discord notifications

- Discord can notify when a request is created and when that request is fulfilled.
- If a requester is mapped to a Discord user, mention that same user for both events.
- Do not allow arbitrary user-provided mention syntax. Only mention IDs from the administrator-controlled mapping.

## Runtime data and secrets

Mutable and sensitive data belongs under:

```text
%LOCALAPPDATA%\Plex Requester
```

The `PLEX_REQUESTER_DATA_DIR` environment variable can override the data directory. `APP_CONFIG` can override the configuration-file path.

Expected runtime files include:

- `config.json`
- `auth-sessions.json`
- `requests.json`
- `request-fulfillment-state.json`
- `rename-history.jsonl`
- `plex-requester.log`
- `runtime/` for the standalone launcher's automatically managed embedded backend

Important rules:

- Repository examples must contain placeholders only.
- There must be no fallback hardcoded administrator PIN. A missing PIN must not authenticate an empty input.
- Legacy copies in the application directory may be copied into AppData only when the corresponding AppData destination does not exist.
- Existing AppData always wins and is never overwritten by that migration.
- Runtime data, `.torrent` files, secrets, keys, environment files, generated executables, caches, logs, and editor artifacts should remain excluded from Git.
- Before publishing to GitHub, scan tracked files for secrets and inspect `git status`.

## Server and launcher

- The default Plex Requester web port is `8003`.
- The server/Tailscale port is configurable from the Windows backend GUI and stored as `server.port` in AppData `config.json`.
- Older configurations without `server.port` must continue to use port 8003.
- The standalone launcher must use the selected port consistently for its embedded backend, status text, logs, and **Open Website** action.
- A direct `APP_PORT` environment override remains supported when running the Python server outside the launcher.
- `build_exe.bat` must verify PyInstaller, the C# compiler, and its inputs; package the Python runtime, backend, and web assets; embed that package into the native launcher; verify that a non-empty single release executable was produced; and preserve the previous executable if either build stage fails.

## UI expectations

- Show the configured version next to the **Plex Requester** title for all users.
- Avoid flashing a stale hardcoded version during refresh. The initial HTML should not contain an obsolete visible version; use the last server-confirmed cached value until current configuration arrives.
- Keep the admin interface information-rich without exposing those controls to regular users.
- Use available desktop space with a wider responsive container and sensible columns. Collapse cleanly on mobile.
- Preserve accessibility basics: useful labels, keyboard-operable controls, and understandable status/error text.

## Verification checklist for future changes

Before calling an edit complete:

1. Inspect the current implementation and any uncommitted changes.
2. Make the smallest coherent change that satisfies the request.
3. Increment the version once if files were edited.
4. Update defaults, examples, documentation, and tests that are directly affected.
5. Run the Python test suite.
6. If the launcher changed, compile it with warnings treated as errors.
7. If web behavior changed, test both admin and non-admin views and check a mobile-sized viewport when relevant.
8. Confirm old AppData files still load when new keys are absent.
9. Confirm no secrets or generated runtime data were introduced into source control.
10. Report what changed, what was tested, the resulting version, and any compatibility caveat.

## Current baseline when this handoff was written

- Version when this handoff was created: `v7.1`
- Default web port: `8003`
- AppData directory: `%LOCALAPPDATA%\Plex Requester`
- Test suite baseline before this document: 39 passing tests
- Build names follow the current configured version: `Plex Requester_vX.X.exe`

This baseline is historical context, not a reason to revert later changes. In a future checkout, trust the newest valid code and configuration after reconciling them with the standing rules above.
