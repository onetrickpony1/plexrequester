# Plex Requester

Plex Requester is a lightweight, self-hosted web app for collecting movie and TV requests and sending magnet links or `.torrent` files to qBittorrent. It includes TMDb lookup, Plex library checks, request fulfillment tracking, configurable download destinations, Discord notifications, and a qBittorrent monitoring dashboard.

The current default version label is **v9.1**. Administrators can edit the label from the Config tab; it is displayed beside the Plex Requester title for all users and cached locally to prevent a stale-version flash during refresh. Versions increment only when project documents, source code, or documentation are edited.

Every Windows release build now runs Python syntax checks and the complete automated backend test suite before packaging. A failed check stops the build without replacing the existing release executable.

For portable project context, coding preferences, compatibility rules, and a future-release checklist, see [CODEX_HANDOFF.md](CODEX_HANDOFF.md).

The backend uses only the Python standard library. Its focused modules live under `plex_requester/`; `server.py` remains the small compatibility facade and executable entry point, so existing commands and integrations continue to work. The frontend is plain HTML, CSS, and JavaScript, so there is no package installation or build step.

## Features

### Requests

- Search TMDb for movies and TV shows.
- Submit requests for `1080p`, `4K`, or `REMUX`.
- Submit a free-form request when TMDb has no match.
- Warn when a requested title already exists in Plex or exists at another quality.
- Automatically check Plex for fulfilled requests and wait for complete bitrate, resolution, and codec analysis before sending the fulfillment notification.
- Fulfill requests when Plex contains the requested quality or a higher tier (`1080p` < `4K` < `REMUX`).
- Include the analyzed movie bitrate, or average bitrate across a TV show's discovered episodes, in the fulfillment details.
- Refresh the visible request list every five seconds using cached fulfillment state while Plex reconciliation runs in the background.
- Mark requests fulfilled manually as an administrator.
- Send optional Discord notifications for new and fulfilled requests.
- Persist Discord notifications before delivery and retry temporary failures with bounded exponential backoff.
- Send a polished Discord summary of all open, unmuted requests using an administrator-configurable reminder interval.
- Automatically paginate large Discord reminder summaries within Discord's field and character limits.
- Let administrators mute or unmute reminders on individual requests.
- Mention a mapped Discord user when their request is created and fulfilled without enabling arbitrary mentions.

### Downloads

- Add magnet links to qBittorrent.
- Upload `.torrent` files up to 10 MB.
- Detect duplicate torrents by info hash.
- Choose from preset movie, TV, or custom download destinations.
- Configure multiple directories within a movie or TV destination and choose the exact directory when adding a download.
- Automatically prefer the fullest configured directory below 90% usage, moving to the next fullest eligible directory as drives fill.
- When adding a TV season, automatically scan every configured TV directory and prefer the drive containing that show's existing parent folder.
- Browse existing nested folders for configured destinations.
- Create multiple new folder levels before adding a download.
- Generate Plex-friendly names from TMDb, including season names such as `The Office (2005) S01`.
- Rename a torrent's single root folder or media file through qBittorrent so it can continue seeding.

Uploaded torrent metadata is forwarded unchanged. Private flags, tracker URLs, passkeys, source fields, and the torrent info hash are preserved.

### qBittorrent dashboard

- Start or pause all torrents as an administrator.
- View current download and upload speeds.
- View total session download, total session upload, and session ratio.
- View torrent size, progress, status, seeds, peers, speeds, ETA, and ratio.
- Search torrents by name.
- Sort ascending or descending by:
  - Name
  - Size
  - Progress
  - Status
  - Seeds
  - Peers
  - Download speed
  - Upload speed
  - ETA
  - Ratio
- Filter by Downloading, Seeding, Completed, Running, Stopped, Active, Inactive, or Stalled.
- Switch to all torrents or leave filters off to retain the original current-downloads view.
- Refresh automatically every five seconds while the tab is open.

### Plex and storage

- Search a read-only snapshot of the Plex SQLite database.
- Inspect Plex metadata, media parts, streams, tags, relationships, seasons, and episodes.
- Classify library media as `1080p`, `4K`, or `REMUX` when the available metadata permits it.
- View configured movie and TV folder sizes and destination-drive usage.

## Requirements

- qBittorrent with its Web UI enabled.
- A modern web browser.
- Python 3.9 or newer only when running from source; the standalone Windows executable includes Python.
- Optional: a TMDb API key or API read access token.
- Optional: access to the Plex library SQLite database.
- Optional: a Discord webhook.
- Optional: Tailscale or another private network for remote access.

The standalone Windows executable includes the Python runtime, backend, configuration template, and web assets. Running `server.py` directly remains supported anywhere the configured filesystem paths and qBittorrent instance are reachable.

## Quick start

### Standalone Windows executable

Download `Plex Requester_vX.X.exe` from the GitHub release and run it from any writable location. No source checkout or Python installation is required. On first launch it creates `%LOCALAPPDATA%\Plex Requester\config.json` from the bundled safe template, then starts the management window and server. Existing AppData files are reused without being overwritten.

Use the native backend window or edit the AppData `config.json` to replace the administrator PIN before exposing the service. The same window can save the TMDb key and server port; the administrator Config tab manages the supported qBittorrent, Plex, destination, and Discord settings.

### Running from source

1. Create the user data folder and copy the example configuration:

   ```powershell
   New-Item -ItemType Directory -Force "$env:LOCALAPPDATA\Plex Requester"
   Copy-Item config.example.json "$env:LOCALAPPDATA\Plex Requester\config.json"
   ```

2. Edit `%LOCALAPPDATA%\Plex Requester\config.json` with your qBittorrent credentials, admin PIN, and destination paths.

3. Validate the configuration:

   ```powershell
   python check_config.py
   ```

4. Start Plex Requester:

   ```powershell
   python server.py
   ```

   On Windows, you can alternatively run:

   ```powershell
   .\start.ps1
   ```

   or run `build_exe.bat` and launch the generated versioned executable as described under [Windows launcher](#windows-launcher).

5. Open [http://localhost:8003](http://localhost:8003).

By default, the server listens on `0.0.0.0:8003`. From another device, use the server's LAN or Tailscale address:

```text
http://<server-hostname-or-ip>:8003
```

## Configuration

The default configuration path is `%LOCALAPPDATA%\Plex Requester\config.json`. A safe starting structure is shown below. The example `change-this-pin` value is deliberately rejected by the backend until it is replaced:

```json
{
  "qbittorrent": {
    "url": "http://127.0.0.1:8080",
    "username": "admin",
    "password": "change-me"
  },
  "server": {
    "port": 8003
  },
  "plex": {
    "databasePath": "C:/Users/YourName/AppData/Local/Plex Media Server/Plug-in Support/Databases/com.plexapp.plugins.library.db"
  },
  "tmdb": {
    "apiKey": ""
  },
  "notifications": {
    "discordWebhookUrl": "",
    "secondaryDiscordWebhookUrl": "",
    "adminReminderWebhookUrl": "",
    "adminReminderIntervalMinutes": 60,
    "discordUserMappings": {
      "Matthew": "123456789012345678"
    }
  },
  "adminPin": "change-this-pin",
  "destinations": [
    {
      "id": "movies",
      "label": "Movies",
      "path": "G:/Media/Movies",
      "paths": [
        "G:/Media/Movies",
        "F:/Media/Movies"
      ]
    },
    {
      "id": "tv",
      "label": "TV Shows",
      "path": "G:/Media/TV Shows",
      "paths": [
        "G:/Media/TV Shows",
        "F:/Media/TV Shows"
      ],
      "browseSubfolders": true
    }
  ]
}
```

### Destination options

Each destination requires:

- `id`: a unique internal identifier.
- `label`: the name shown in the Download tab.
- `path`: the legacy/fallback save path passed to older Plex Requester versions. v7.5 and later keep this equal to the first item in `paths`.
- `paths`: optional list of one or more directories for this media type. Older configurations containing only `path` remain valid.
- `browseSubfolders`: optional; when `true`, existing child folders can be selected from the page.

For Windows paths, use forward slashes:

```json
"path": "D:/Media/Movies"
```

or escape every backslash:

```json
"path": "D:\\Media\\Movies"
```

The web Config tab lets an administrator change the qBittorrent URL, Plex database path, destinations, and Discord webhooks. Other credentials and API keys should be managed in `config.json`, with environment variables, or through the Windows launcher where supported. The Windows backend window includes an **Administrator PIN** field that writes `adminPin` to `%LOCALAPPDATA%\Plex Requester\config.json`, signs out existing admin sessions, and restarts the backend. PINs must contain 8 to 128 characters. The bundled example value and existing PINs shorter than eight characters cannot authenticate; replace them from the backend window after upgrading.

When a destination contains multiple paths, the Download tab shows a compact directory selector with both the percentage used and remaining free space in GB. Its default is the directory with the highest drive usage below 90%. Once that drive reaches 90%, the next fullest directory below 90% becomes the default. If every drive is at least 90% full, the least-full available drive is selected as a safe fallback. The chosen index is validated against the configured list by the server; arbitrary paths are not accepted from the browser.

When an administrator selects a TMDb TV result for a season, Plex Requester scans the top level of every configured TV path for an exact, case-insensitive match to the show's Plex-style parent folder (for example, `The Office (2005)`). If found, that directory and existing folder are selected automatically, overriding the drive-usage default so the new season stays with the show. If no exact parent exists, the normal drive-fullness rule remains in effect and the parent folder is suggested for creation.

## Environment variables

Configuration can be overridden without editing `config.json`:

| Variable | Purpose | Default |
| --- | --- | --- |
| `APP_HOST` | HTTP bind address | `0.0.0.0` |
| `APP_PORT` | HTTP port | `8003` |
| `APP_CONFIG` | Explicit configuration-file override | `%LOCALAPPDATA%\Plex Requester\config.json` |
| `PLEX_REQUESTER_DATA_DIR` | User-data directory override | `%LOCALAPPDATA%\Plex Requester` |
| `QBIT_URL` | qBittorrent Web UI URL | Value from config |
| `QBIT_USERNAME` | qBittorrent username | Value from config |
| `QBIT_PASSWORD` | qBittorrent password | Value from config |
| `PLEX_DATABASE_PATH` | Plex SQLite database path | Value from config |
| `TMDB_API_KEY` | TMDb API key or read token | Value from config |
| `DISCORD_WEBHOOK_URL` | Discord webhook | Value from config |
| `DISCORD_ADMIN_REMINDER_WEBHOOK_URL` | Separate webhook for unfulfilled-request reminders | Value from config |
| `ADMIN_REMINDER_INTERVAL_MINUTES` | First reminder delay and repeat interval | `60`, minimum `1`, maximum `10080` |
| `ADMIN_PIN` | Administrator PIN | Value from config |
| `FULFILLMENT_CHECK_SECONDS` | Plex fulfillment interval | `15`, minimum `15` |

Example:

```powershell
$env:APP_PORT = "8085"
$env:ADMIN_PIN = "your-private-pin"
python server.py
```

## Access levels

The site opens in standard visitor mode.

Visitors can:

- Search and submit requests.
- View the request list.
- Search and inspect the Plex library.
- View storage information.
- View the qBittorrent dashboard.

For visitors, this tab is called **Status** and is limited to current downloads with name, progress, size, download speed, and ETA. For administrators, it is called **qBittorrent** and provides the complete dashboard with transfer totals, filters, sorting, seeding statistics, and session controls.

Administrators can additionally:

- Add magnet links and torrent files.
- Start or pause the qBittorrent session.
- Mark requests fulfilled or delete them from the interface.
- Mute or unmute Discord reminders for individual requests.
- Edit supported configuration values.

Admin sessions are stored in an HTTP-only cookie and expire after seven days. Use the Login button to enter the configured PIN. Five failed attempts by the same client or Cloudflare Access identity trigger a 15-minute lockout; a successful login clears earlier failures.

## TMDb setup

Add an API key or read access token under `tmdb.apiKey`, set `TMDB_API_KEY`, or use the Windows launcher's `Save TMDb Key` control.

TMDb lookup is used for request search, posters, summaries, release years, and suggested download names. The key is handled by the backend and is not returned to the browser.

## Plex setup

Set `plex.databasePath` to Plex's `com.plexapp.plugins.library.db` file. A typical Windows location is:

```text
C:\Users\YourName\AppData\Local\Plex Media Server\Plug-in Support\Databases\com.plexapp.plugins.library.db
```

Plex Requester does not write to this database. For each operation, it:

1. Opens the source database read-only.
2. Creates a temporary SQLite snapshot.
3. Queries the snapshot.
4. Deletes the snapshot.

The fulfillment monitor checks pending TMDb-backed requests after startup and then every 15 seconds by default. A title remains pending after first appearing in Plex until every discovered media item has bitrate, resolution, and video-codec metadata. Once analysis is complete, fulfillment details include the movie bitrate or, for TV, the average bitrate across the discovered episodes. Plex bitrate values are normalized whether a database version stores `media_items.bitrate` in bits per second or kilobits per second; `media_streams.bitrate` is also converted from bits per second before Mbps display and REMUX classification.

## Discord notifications

Use the administrator Config tab to set up to two Discord webhooks for new-request and fulfillment notifications. The second webhook is optional; when configured, it receives the same polished request and fulfillment messages as the first webhook. Each destination has independent persisted delivery and retry state.

Web assets and API responses are served with cache prevention, and release asset URLs include the application version. This prevents browsers and reverse proxies such as Cloudflare from retaining an older Config script that cannot save newly introduced settings.

Use the same Config tab to set a separate admin reminder Discord webhook. The Config tab's **Request reminder interval (minutes)** setting controls both the first reminder delay and subsequent repeats; it defaults to 60 minutes and accepts 1 through 10080 minutes. When a reminder is due, Discord summaries cover every open, unmuted request with its requester, requested quality, and waiting time. Large summaries are automatically divided into numbered parts that stay within Discord's field and character limits. Waiting times use days after 24 hours. Administrators can mute or unmute an individual request from the Requests tab. Reminder messages disable Discord mention parsing.

New-request, fulfillment, and reminder notifications use structured Discord embeds with Plex-themed colors. Notifications can include:

- New request title, requester, desired quality, and TMDb link.
- Plex duplicate or quality warnings.
- Fulfillment title, requester, and detected quality.
- A requester-specific Discord mention on both creation and fulfillment when an administrator has mapped the entered requester name to a Discord user ID.

Requester mappings can be managed from the administrator Config page. Matching ignores case and surrounding whitespace. Mentions remain globally disabled in webhook payloads except for the single validated Discord user ID resolved from the administrator-managed mapping.

Every request, fulfillment, and reminder notification is written atomically to `notification-outbox.json` before its first delivery attempt. Temporary failures retain the attempt count and error, then retry after 15 seconds with exponential backoff capped at one hour. Sent jobs are retained for 30 days to prevent the same event from being queued twice. The two request/fulfillment destinations use separate jobs, so one Discord server can retry without duplicating delivery to the other. Pending jobs resolve the currently configured primary, secondary, or reminder webhook when delivered, so webhook URLs and tokens are not duplicated into the outbox. Delivery is at least once: an exceptional process or machine failure after Discord accepts a message but before the sent state reaches disk can cause that message to be retried.

## Download naming and seeding

Suggested names follow these patterns:

```text
GoodFellas (1990)
The Office (2005)
The Office (2005) S01
```

The name is first passed to qBittorrent as the torrent name. Plex Requester then waits for qBittorrent to expose the torrent contents:

- A single root folder is renamed through qBittorrent.
- A single loose media file is renamed while retaining its extension.
- Torrents with multiple root items are left unchanged.

Because renaming happens through qBittorrent, its file mappings remain valid and the torrent can continue seeding.

## Private tracker considerations

Torrent files are decoded only for validation and raw info-hash calculation. They are not rewritten or saved by Plex Requester.

Private torrent files commonly contain personal tracker passkeys. Keep the browser-to-app and app-to-qBittorrent connections on localhost, Tailscale, or HTTPS. Ordinary HTTP over an untrusted LAN can expose the uploaded torrent contents and embedded passkey.

## Windows launcher

The generated standalone executable provides a management window that:

- Starts and stops the embedded standalone backend without using a system Python installation.
- Displays backend logs.
- Opens the website.
- Saves the administrator PIN and revokes old admin sessions when it changes.
- Saves the TMDb key; Discord webhooks are managed from the administrator Config page.
- Configures the HTTP port used locally and through Tailscale, then restarts the server.
- Displays torrent rename history.
- Stops the server when the window closes.

The release executable is intentionally excluded from source control because it is generated from `PlexRequesterLauncher.cs` plus a PyInstaller-packaged backend. Install PyInstaller in the build environment, then build and validate it from the project directory:

```powershell
python -m pip install pyinstaller
```

```bat
build_exe.bat
```

The build script verifies PyInstaller, the .NET Framework C# compiler, and all required inputs. It packages the Python backend and web assets, embeds that package in the native management window, verifies that the output is non-empty, and does not replace an existing release executable when either stage fails. It reads `app.version` from `APP_CONFIG` when that override is set, otherwise from `%LOCALAPPDATA%\Plex Requester\config.json`. A valid version produces `Plex Requester_vX.X.exe`; if the configuration or version is missing or invalid, it produces `Plex Requester.exe` without a version suffix.

The resulting executable does not need Python, `server.py`, or the `static` directory beside it. It keeps an automatically managed copy of its embedded backend under `%LOCALAPPDATA%\Plex Requester\runtime` and PyInstaller expands that backend's Python runtime into a temporary directory while running. Persistent application data remains in the other established AppData files.

## Local data files

Plex Requester stores mutable application data in `%LOCALAPPDATA%\Plex Requester`:

| File | Contents |
| --- | --- |
| `config.json` | Credentials, API keys, paths, and application settings |
| `requests.json` | Current media requests |
| `request-fulfillment-state.json` | Automatic and manual fulfillment history |
| `auth-sessions.json` | Active administrator session tokens |
| `notification-outbox.json` | Pending, failed, and recently sent Discord notification jobs |
| `rename-history.jsonl` | Successful qBittorrent content renames |
| `plex-requester.log` | Windows launcher and backend operational log |
| `runtime/` | Automatically managed backend extracted from the standalone release EXE |

On first access after upgrading, `config.json`, `requests.json`, `request-fulfillment-state.json`, `auth-sessions.json`, `notification-outbox.json`, `rename-history.jsonl`, and `plex-requester.log` are copied from the application directory when the corresponding AppData file does not already exist. Existing AppData files are never overwritten. File names and JSON formats are unchanged, so these files can also be copied directly into or out of the AppData folder. `APP_CONFIG` remains available when an explicit alternate configuration path is required.

Writes to `config.json`, `requests.json`, `request-fulfillment-state.json`, `auth-sessions.json`, and `notification-outbox.json` are flushed to a temporary file in the same directory and atomically replace the previous file only after the complete JSON document is safely written. If a write is interrupted, the previous valid file remains in place and the incomplete temporary file is cleaned up on the handled failure path. The Windows launcher uses the same replacement approach when creating or editing `config.json`.

Back up the files you need, restrict their filesystem permissions, and do not commit secrets to source control.

## Testing

Run the unit tests:

```powershell
python -m unittest -v
```

Check Python syntax without starting the server:

```powershell
python -m py_compile server.py check_config.py test_server.py
```

## Troubleshooting

### qBittorrent connection refused

```text
Could not reach qBittorrent ... No connection could be made because the target machine actively refused it
```

- Start qBittorrent.
- Enable its Web UI.
- Confirm the configured host and port.
- If qBittorrent runs on another device or in a container, do not use `127.0.0.1`; use an address reachable from the Plex Requester host.

### qBittorrent HTTP 401

- Confirm the Web UI username and password.
- Confirm you edited `config.json`, not only `config.example.json`.
- Check qBittorrent's Web UI authentication and host-header settings.

### Start or Pause returns endpoint errors

Plex Requester uses qBittorrent's newer `start` and `stop` API endpoints and automatically falls back to the older `resume` and `pause` endpoints. Restart Plex Requester after updating the source so the running Python process loads the current implementation.

### Plex database path does not exist

- Run `python check_config.py`.
- Confirm the Plex Media Server user and Plex Requester process can read the database and its directory.
- Use forward slashes or escaped backslashes in JSON paths.

### TMDb search is unavailable

- Add a valid TMDb API key or read access token.
- Restart the Python server after editing `config.json` directly.
- Confirm the server can reach TMDb over HTTPS.

### Uploaded torrent appears to fail but is added

Current qBittorrent versions may return a JSON success object rather than the older `Ok.` response. The current Plex Requester code supports both formats. Restart the app after updating it.

## Project structure

```text
Plex Requester/
├── server.py                    Compatibility facade and executable entry point
├── plex_requester/
│   ├── api.py                   HTTP routes and threaded server
│   ├── auth.py                  PIN, session, and cookie handling
│   ├── config.py                Configuration defaults and validation
│   ├── discord.py               Webhook formatting, queueing, and delivery
│   ├── plex.py                  Plex snapshots, search, and media analysis
│   ├── qbittorrent.py           qBittorrent API and torrent handling
│   ├── requests.py              Request and fulfillment workflows
│   ├── storage.py               Atomic persistence and destination storage
│   └── tmdb.py                  TMDb lookup and media naming
├── check_config.py              Configuration validator
├── test_server.py               Backend and compatibility unit tests
├── config.example.json          Configuration template
├── .gitignore                   Private-data and generated-file exclusions
├── build_exe.bat                Validated standalone two-stage build
├── start.ps1                    PowerShell startup script
├── PlexRequesterLauncher.cs     Native standalone management window
├── PlexRequesterIcon.ico        Windows application icon
└── static/
    ├── index.html               Application markup
    ├── app.js                   Browser behavior
    └── styles.css               Application styling
```

## Security notes

- Set a unique administrator PIN of at least eight characters in the backend window before exposing the app.
- Keep `config.json`, auth sessions, tracker passkeys, and webhook URLs private.
- Prefer localhost, Tailscale, a VPN, or an HTTPS reverse proxy for remote access.
- The built-in HTTP server does not provide TLS.
- Expose the service only to trusted users and networks.
