const destinationsEl = document.querySelector("#destinations");
const form = document.querySelector("#magnetForm");
const message = document.querySelector("#message");
const submitButton = document.querySelector("#submitButton");
const configWarning = document.querySelector("#configWarning");
const appVersion = document.querySelector("#appVersion");
const downloadName = document.querySelector("#downloadName");
const magnetInput = document.querySelector("#magnet");
const torrentFile = document.querySelector("#torrentFile");
const useSubfolder = document.querySelector("#useSubfolder");
const subfolderField = document.querySelector("#subfolderField");
const newFolderList = document.querySelector("#newFolderList");
const addFolderButton = document.querySelector("#addFolderButton");
const folderSelect = document.querySelector("#folderSelect");
const folderLevels = document.querySelector("#folderLevels");
const folderSelectNote = document.querySelector("#folderSelectNote");
const destinationDirectoryField = document.querySelector("#destinationDirectoryField");
const destinationDirectory = document.querySelector("#destinationDirectory");
const loginPanel = document.querySelector("#loginPanel");
const siteContent = document.querySelector("#siteContent");
const loginPin = document.querySelector("#loginPin");
const loginButton = document.querySelector("#loginButton");
const loginMessage = document.querySelector("#loginMessage");
const mobilePinpad = document.querySelector("#mobilePinpad");
const logoutButton = document.querySelector("#logoutButton");
const requestTabButton = document.querySelector("#requestTabButton");
const downloadTabButton = document.querySelector("#downloadTabButton");
const libraryTabButton = document.querySelector("#libraryTabButton");
const storageTabButton = document.querySelector("#storageTabButton");
const qbitTabButton = document.querySelector("#qbitTabButton");
const qbitHeading = document.querySelector("#qbitHeading");
const configTabButton = document.querySelector("#configTabButton");
const requestPanel = document.querySelector("#requestPanel");
const downloadPanel = document.querySelector("#downloadPanel");
const libraryPanel = document.querySelector("#libraryPanel");
const storagePanel = document.querySelector("#storagePanel");
const qbitPanel = document.querySelector("#qbitPanel");
const configPanel = document.querySelector("#configPanel");
const librarySearchForm = document.querySelector("#librarySearchForm");
const librarySearch = document.querySelector("#librarySearch");
const libraryType = document.querySelector("#libraryType");
const libraryMessage = document.querySelector("#libraryMessage");
const libraryResults = document.querySelector("#libraryResults");
const refreshStorageButton = document.querySelector("#refreshStorageButton");
const storageMessage = document.querySelector("#storageMessage");
const storageGrid = document.querySelector("#storageGrid");
const refreshQbitButton = document.querySelector("#refreshQbitButton");
const startQbitButton = document.querySelector("#startQbitButton");
const pauseQbitButton = document.querySelector("#pauseQbitButton");
const qbitSearch = document.querySelector("#qbitSearch");
const qbitControls = document.querySelector("#qbitControls");
const qbitFilter = document.querySelector("#qbitFilter");
const qbitSort = document.querySelector("#qbitSort");
const qbitSortDirection = document.querySelector("#qbitSortDirection");
const qbitMessage = document.querySelector("#qbitMessage");
const qbitSummary = document.querySelector("#qbitSummary");
const qbitList = document.querySelector("#qbitList");
const configForm = document.querySelector("#configForm");
const configAppVersion = document.querySelector("#configAppVersion");
const configQbitUrl = document.querySelector("#configQbitUrl");
const configPlexPath = document.querySelector("#configPlexPath");
const configDiscordWebhook = document.querySelector("#configDiscordWebhook");
const configAdminReminderWebhook = document.querySelector("#configAdminReminderWebhook");
const configAdminReminderInterval = document.querySelector("#configAdminReminderInterval");
const configDestinations = document.querySelector("#configDestinations");
const addDestinationButton = document.querySelector("#addDestinationButton");
const configDiscordMappings = document.querySelector("#configDiscordMappings");
const addDiscordMappingButton = document.querySelector("#addDiscordMappingButton");
const saveConfigButton = document.querySelector("#saveConfigButton");
const configMessage = document.querySelector("#configMessage");
const requesterName = document.querySelector("#requesterName");
const requestSearch = document.querySelector("#requestSearch");
const requestQuality = document.querySelector("#requestQuality");
const requestMessage = document.querySelector("#requestMessage");
const requestResults = document.querySelector("#requestResults");
const requestList = document.querySelector("#requestList");
const tmdbStatus = document.querySelector("#tmdbStatus");
const tmdbSearch = document.querySelector("#tmdbSearch");
const tmdbType = document.querySelector("#tmdbType");
const tmdbSeason = document.querySelector("#tmdbSeason");
const tmdbMessage = document.querySelector("#tmdbMessage");
const tmdbResults = document.querySelector("#tmdbResults");
const appVersionStorageKey = "plexRequesterAppVersion";

let destinationConfig = [];
let folderRefreshTimer = null;
let librarySearchTimer = null;
let qbitRefreshTimer = null;
let librarySearchId = 0;
let qbitStatusId = 0;
let qbitItems = [];
let qbitSortAscending = true;
let requestSearchTimer = null;
let requestSearchId = 0;
let requestRefreshTimer = null;
let requestListLoadId = 0;
let tmdbSearchTimer = null;
let tmdbSearchId = 0;
let tmdbItems = [];
let authRole = "";
let adminConfigLoaded = false;

function cachedAppVersion() {
  try {
    return window.localStorage.getItem(appVersionStorageKey) || "";
  } catch {
    return "";
  }
}

function displayAppVersion(value) {
  const version = String(value || "").trim();
  appVersion.textContent = version;
  if (!version) return;
  try {
    window.localStorage.setItem(appVersionStorageKey, version);
  } catch {
    // The server-confirmed version still displays when browser storage is unavailable.
  }
}

displayAppVersion(cachedAppVersion());

function isAdmin() {
  return authRole === "admin";
}

function showMessage(text, type) {
  message.textContent = text;
  message.className = `message ${type}`;
  message.hidden = false;
}

function showLibraryMessage(text, type) {
  libraryMessage.textContent = text;
  libraryMessage.className = `message ${type}`;
  libraryMessage.hidden = false;
}

function showStorageMessage(text, type) {
  storageMessage.textContent = text;
  storageMessage.className = `message ${type}`;
  storageMessage.hidden = false;
}

function showQbitMessage(text, type) {
  qbitMessage.textContent = text;
  qbitMessage.className = `message ${type}`;
  qbitMessage.hidden = false;
}

function showConfigMessage(text, type) {
  configMessage.textContent = text;
  configMessage.className = `message ${type}`;
  configMessage.hidden = false;
}

function showLoginMessage(text, type) {
  loginMessage.textContent = text;
  loginMessage.className = `message ${type}`;
  loginMessage.hidden = false;
}

function showRequestMessage(text, type) {
  requestMessage.textContent = text;
  requestMessage.className = `message ${type}`;
  requestMessage.hidden = false;
}

function showTmdbMessage(text, type) {
  tmdbMessage.textContent = text;
  tmdbMessage.className = `message ${type}`;
  tmdbMessage.hidden = false;
}

function loadingCard(text = "Loading...") {
  const card = document.createElement("div");
  card.className = "loading-card";
  card.innerHTML = `<span class="spinner" aria-hidden="true"></span><span>${escapeHtml(text)}</span>`;
  return card;
}

function syncSubfolderField() {
  subfolderField.hidden = !useSubfolder.checked;

  if (useSubfolder.checked && newFolderList.children.length === 0) {
    addNewFolderInput();
  }

  if (!useSubfolder.checked) {
    newFolderList.innerHTML = "";
  }

  newFolderList.querySelectorAll("input").forEach((input) => {
    input.required = useSubfolder.checked;
  });

  folderLevels.querySelectorAll("select").forEach((select) => {
    select.required = !useSubfolder.checked && select.dataset.level === "0";
  });
}

function selectedDestination() {
  const checked = document.querySelector("[name='destinationId']:checked");
  if (!checked) return null;
  return destinationConfig.find((destination) => destination.id === checked.value) || null;
}

function syncDirectorySelect() {
  const destination = selectedDestination();
  const directories = destination?.directories || [];
  destinationDirectory.innerHTML = "";
  directories.forEach((directory) => {
    const usage = directory.usagePercent == null ? "usage unavailable" : `${directory.usagePercent}% full`;
    const option = new Option(`${directory.label} — ${usage}`, String(directory.index));
    option.selected = Boolean(directory.default);
    destinationDirectory.append(option);
  });
  destinationDirectoryField.hidden = directories.length <= 1;
}

function selectedDestinationPathIndex() {
  const destination = selectedDestination();
  const directories = destination?.directories || [];
  if (directories.length === 0) return "";
  return destinationDirectory.value || String((directories.find((item) => item.default) || directories[0]).index);
}

async function syncDestinationControls() {
  syncDirectorySelect();
  return syncFolderSelect();
}

async function syncFolderSelect() {
  const selected = selectedDestination();
  const showSelect = Boolean(selected && selected.browseSubfolders);
  folderSelect.hidden = !showSelect;
  folderLevels.innerHTML = "";
  stopFolderRefresh();

  if (!showSelect) {
    folderSelectNote.textContent = "";
    syncSubfolderField();
    return [];
  }

  const topLevelFolders = await loadSubfolders(selected.id, []);
  if (topLevelFolders.length === 0) {
    folderSelectNote.textContent = "No existing TV show folders were found. Check that the server can access the TV Shows path.";
    syncSubfolderField();
    return [];
  }

  folderSelectNote.textContent = `${topLevelFolders.length} folders found.`;
  addFolderLevel(selected, [], topLevelFolders, true);
  startFolderRefresh();
  syncSubfolderField();
  return topLevelFolders;
}

function startFolderRefresh() {
  stopFolderRefresh();
  folderRefreshTimer = window.setInterval(() => {
    const selected = selectedDestination();
    if (selected && selected.browseSubfolders && selectedFolderPath().length === 0) {
      syncFolderSelect();
    }
  }, 30000);
}

function stopFolderRefresh() {
  if (folderRefreshTimer) {
    window.clearInterval(folderRefreshTimer);
    folderRefreshTimer = null;
  }
}

function selectedFolderPath() {
  return Array.from(folderLevels.querySelectorAll("select"))
    .map((select) => select.value)
    .filter(Boolean);
}

function addFolderLevel(destination, parentPath, folders, required) {
  const select = document.createElement("select");
  select.required = required;
  select.dataset.level = String(parentPath.length);
  select.append(new Option(parentPath.length === 0 ? "Choose a TV show folder" : "Download directly here", ""));
  folders.forEach((folder) => {
    select.append(new Option(folder, folder));
  });

  select.addEventListener("change", async () => {
    removeDeeperLevels(parentPath.length);
    syncSubfolderField();
    if (!select.value) return;

    const nextPath = [...parentPath, select.value];
    const childFolders = await loadSubfolders(destination.id, nextPath);
    if (childFolders.length > 0) {
      addFolderLevel(destination, nextPath, childFolders, false);
    }
    syncSubfolderField();
  });

  folderLevels.append(select);
}

function removeDeeperLevels(level) {
  folderLevels.querySelectorAll("select").forEach((select) => {
    if (Number(select.dataset.level) > level) {
      select.remove();
    }
  });
}

async function loadSubfolders(destinationId, parentPath) {
  const params = new URLSearchParams({
    destinationId,
    parent: parentPath.join("/"),
    pathIndex: selectedDestinationPathIndex(),
  });
  const response = await fetch(`/api/subfolders?${params}`);
  if (!response.ok) return [];
  const result = await response.json();
  return result.subfolders || [];
}

function addNewFolderInput(value = "") {
  const row = document.createElement("div");
  row.className = "new-folder-row";

  const input = document.createElement("input");
  input.type = "text";
  input.name = "newSubfolder";
  input.autocomplete = "off";
  input.placeholder = newFolderList.children.length === 0 ? "e.g. The Office (2005)" : "e.g. The Office (2005) S01";
  input.value = value;
  input.required = useSubfolder.checked;

  const removeButton = document.createElement("button");
  removeButton.className = "icon-button";
  removeButton.type = "button";
  removeButton.textContent = "Remove";
  removeButton.addEventListener("click", () => {
    row.remove();
    syncSubfolderField();
  });

  row.append(input, removeButton);
  newFolderList.append(row);
}

function newFolderPath() {
  return Array.from(newFolderList.querySelectorAll("input"))
    .map((input) => input.value.trim())
    .filter(Boolean);
}

function renderDestinations(destinations) {
  destinationConfig = destinations;
  destinationsEl.innerHTML = "";

  destinations.forEach((destination, index) => {
    const id = `destination-${destination.id}`;
    const label = document.createElement("label");
    label.className = "destination";
    label.htmlFor = id;

    label.innerHTML = `
      <input id="${id}" type="radio" name="destinationId" value="${destination.id}" ${index === 0 ? "checked" : ""}>
      <span>
        <strong>${escapeHtml(destination.label)}</strong>
      </span>
    `;

    destinationsEl.append(label);
  });

  destinationsEl.querySelectorAll("[name='destinationId']").forEach((input) => {
    input.addEventListener("change", syncDestinationControls);
  });

  syncDestinationControls();
}

async function loadConfig() {
  const response = await fetch("/api/config");
  if (!response.ok) throw new Error("Could not load server config.");

  const config = await response.json();
  displayAppVersion(config.app?.version);
  renderDestinations(config.destinations);
  tmdbStatus.textContent = config.tmdb && config.tmdb.configured
    ? "TMDb lookup is configured from the Plex Requester log window."
    : "Save your TMDb API key in the Plex Requester log window to enable lookup.";

  if (config.config.usingExample) {
    configWarning.hidden = false;
    configWarning.textContent = "Using sample config.";
  }
}

function applyAuth(role) {
  authRole = role || "";
  const qbitLabel = isAdmin() ? "qBittorrent" : "Status";
  qbitTabButton.textContent = qbitLabel;
  qbitHeading.textContent = qbitLabel;
  document.body.dataset.role = authRole || "user";
  loginPanel.hidden = true;
  siteContent.hidden = false;
  logoutButton.hidden = false;
  logoutButton.textContent = isAdmin() ? "Logout" : "Login";
  document.querySelectorAll(".admin-only").forEach((element) => {
    element.hidden = !isAdmin();
  });
  document.querySelectorAll(".authenticated-only").forEach((element) => {
    element.hidden = !authRole;
  });

  const activeAdminPanel = !downloadPanel.hidden || !configPanel.hidden;
  if (!isAdmin() && activeAdminPanel) {
    activateTab("request");
  }
  syncRequestRefresh(!requestPanel.hidden);
  syncQbitRefresh(!qbitPanel.hidden);
  if (!qbitPanel.hidden) loadQbitStatus();
}

async function checkAuth() {
  const response = await fetch("/api/auth/me");
  const result = await response.json();
  if (!response.ok || !result.authenticated) {
    applyAuth("");
  } else {
    applyAuth(result.role);
  }
  await loadConfig();
  await loadRequests();
}

function showAdminLogin() {
  loginMessage.hidden = true;
  loginPin.value = "";
  loginPanel.hidden = false;
  siteContent.hidden = true;
  logoutButton.hidden = true;
  loginPin.focus();
}

async function login() {
  loginMessage.hidden = true;
  loginButton.disabled = true;
  try {
    const response = await fetch("/api/auth/login", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ pin: loginPin.value.trim() }),
    });
    const result = await response.json();
    if (!response.ok || result.error) {
      throw new Error(result.error || "Login failed.");
    }
    loginPin.value = "";
    applyAuth(result.role);
    await loadConfig();
    await loadRequests();
  } catch (error) {
    showLoginMessage(error.message, "error");
  } finally {
    loginButton.disabled = false;
  }
}

function handlePinpadPress(event) {
  const button = event.target.closest("button");
  if (!button) return;

  loginMessage.hidden = true;
  const digit = button.dataset.pin;
  const action = button.dataset.action;
  if (digit !== undefined) {
    loginPin.value = `${loginPin.value}${digit}`.slice(0, 12);
    return;
  }
  if (action === "clear") {
    loginPin.value = "";
    return;
  }
  if (action === "backspace") {
    loginPin.value = loginPin.value.slice(0, -1);
  }
}

async function logout() {
  try {
    await fetch("/api/auth/logout", { method: "POST" });
  } catch {
    // Logging out should clear the local UI even if the server is already gone.
  }
  adminConfigLoaded = false;
  syncQbitRefresh(false);
  requestList.innerHTML = "";
  requestResults.innerHTML = "";
  applyAuth("");
  await loadConfig();
  await loadRequests();
}

function handleAuthButton() {
  if (isAdmin()) {
    logout();
  } else {
    showAdminLogin();
  }
}

function activateTab(tabName) {
  if (!isAdmin() && ["download", "config"].includes(tabName)) {
    tabName = "request";
  }
  const downloadActive = tabName === "download";
  const libraryActive = tabName === "library";
  const storageActive = tabName === "storage";
  const qbitActive = tabName === "qbit";
  const configActive = tabName === "config";
  const requestActive = !downloadActive && !libraryActive && !storageActive && !qbitActive && !configActive;

  requestPanel.hidden = !requestActive;
  downloadPanel.hidden = !downloadActive;
  libraryPanel.hidden = !libraryActive;
  storagePanel.hidden = !storageActive;
  qbitPanel.hidden = !qbitActive;
  configPanel.hidden = !configActive;
  requestPanel.classList.toggle("active", requestActive);
  downloadPanel.classList.toggle("active", downloadActive);
  libraryPanel.classList.toggle("active", libraryActive);
  storagePanel.classList.toggle("active", storageActive);
  qbitPanel.classList.toggle("active", qbitActive);
  configPanel.classList.toggle("active", configActive);
  requestTabButton.classList.toggle("active", requestActive);
  downloadTabButton.classList.toggle("active", downloadActive);
  libraryTabButton.classList.toggle("active", libraryActive);
  storageTabButton.classList.toggle("active", storageActive);
  qbitTabButton.classList.toggle("active", qbitActive);
  configTabButton.classList.toggle("active", configActive);
  requestTabButton.setAttribute("aria-selected", String(requestActive));
  downloadTabButton.setAttribute("aria-selected", String(downloadActive));
  libraryTabButton.setAttribute("aria-selected", String(libraryActive));
  storageTabButton.setAttribute("aria-selected", String(storageActive));
  qbitTabButton.setAttribute("aria-selected", String(qbitActive));
  configTabButton.setAttribute("aria-selected", String(configActive));
  syncQbitRefresh(qbitActive);
  syncRequestRefresh(requestActive);

  if (libraryActive && libraryResults.children.length === 0) {
    searchLibrary();
  }

  if (storageActive && storageGrid.children.length === 0) {
    loadStorage();
  }

  if (qbitActive && qbitList.children.length === 0) {
    loadQbitStatus();
  }

  if (configActive && isAdmin() && !adminConfigLoaded) {
    loadAdminConfig();
  }

  if (requestActive && requestList.children.length === 0) {
    loadRequests();
  }
}

async function loadStorage() {
  storageMessage.hidden = true;
  storageGrid.innerHTML = "";
  refreshStorageButton.disabled = true;
  refreshStorageButton.textContent = "Refreshing...";

  try {
    const response = await fetch("/api/storage");
    if (!response.ok) {
      throw new Error("Could not load storage details.");
    }
    const result = await response.json();
    renderStorage(result);
  } catch (error) {
    showStorageMessage(error.message, "error");
  } finally {
    refreshStorageButton.disabled = false;
    refreshStorageButton.textContent = "Refresh";
  }
}

function renderStorage(result) {
  storageGrid.innerHTML = "";
  const folders = result.folders || [];
  folders.forEach((folder) => {
    storageGrid.append(storageCard(
      folder.label,
      folder.exists ? formatBytes(folder.bytes) : "Unavailable",
      folder.exists ? "Folder size" : "Path not found",
    ));
  });

  const disk = result.disk || {};
  storageGrid.append(storageCard(
    "Free Space",
    disk.freeBytes === null || disk.freeBytes === undefined ? "Unavailable" : formatBytes(disk.freeBytes),
    disk.error || `${formatBytes(disk.usedBytes)} used of ${formatBytes(disk.totalBytes)}`,
  ));

  if (disk.error) {
    showStorageMessage(disk.error, "error");
  }
}

function storageCard(title, value, note) {
  const card = document.createElement("article");
  card.className = "storage-card";
  card.innerHTML = `
    <span>${escapeHtml(title)}</span>
    <strong>${escapeHtml(value)}</strong>
    <small>${escapeHtml(note || "")}</small>
  `;
  return card;
}

function syncQbitRefresh(active) {
  if (qbitRefreshTimer) {
    window.clearInterval(qbitRefreshTimer);
    qbitRefreshTimer = null;
  }
  if (active) {
    qbitRefreshTimer = window.setInterval(loadQbitStatus, 5000);
  }
}

async function loadQbitStatus() {
  const statusId = ++qbitStatusId;
  qbitMessage.hidden = true;
  refreshQbitButton.disabled = true;

  try {
    const response = await fetch("/api/qbit/status");
    const result = await response.json();
    if (statusId !== qbitStatusId) return;
    if (!response.ok || result.error) {
      throw new Error(result.error || "Could not load qBittorrent status.");
    }
    renderQbitStatus(result);
  } catch (error) {
    if (statusId !== qbitStatusId) return;
    qbitSummary.innerHTML = "";
    qbitList.innerHTML = "";
    showQbitMessage(error.message, "error");
  } finally {
    if (statusId === qbitStatusId) {
      refreshQbitButton.disabled = false;
    }
  }
}

function renderQbitStatus(result) {
  qbitItems = result.items || [];
  const transfer = result.transfer || {};
  if (isAdmin()) {
    qbitSummary.innerHTML = `
      <span><small>Down Speed</small><strong>${formatSpeed(transfer.dlspeed)}</strong></span>
      <span><small>Up Speed</small><strong>${formatSpeed(transfer.upspeed)}</strong></span>
      <span><small>Total Download</small><strong>${formatBytes(transfer.totalDownload)}</strong></span>
      <span><small>Total Upload</small><strong>${formatBytes(transfer.totalUpload)}</strong></span>
      <span><small>Ratio</small><strong>${formatRatio(transfer.ratio)}</strong></span>
      ${transfer.connectionStatus ? `<span><small>Connection</small><strong>${escapeHtml(transfer.connectionStatus)}</strong></span>` : ""}
    `;
  }

  renderQbitItems();
}

function qbitSortValue(item, sort) {
  const values = {
    name: String(item.name || "").toLocaleLowerCase(),
    size: Number(item.size || 0),
    progress: Number(item.progress || 0),
    status: String(item.state || "").toLocaleLowerCase(),
    seeds: Number(item.numSeeds || 0),
    peers: Number(item.numPeers || 0),
    dlspeed: Number(item.dlspeed || 0),
    upspeed: Number(item.upspeed || 0),
    eta: Number(item.eta || 0),
    ratio: Number(item.ratio || 0),
  };
  return values[sort];
}

function renderQbitItems() {
  if (!isAdmin()) {
    qbitList.innerHTML = "";
    if (qbitItems.length === 0) {
      showQbitMessage("No current downloads.", "success");
      return;
    }
    qbitMessage.hidden = true;
    qbitItems.forEach((item) => qbitList.append(qbitCard(item)));
    return;
  }
  const selectedFilter = qbitFilter.value;
  const query = qbitSearch.value.trim().toLocaleLowerCase();
  const items = qbitItems
    .filter((item) => selectedFilter === "all"
      || (selectedFilter === "current" ? item.current : (item.filters || []).includes(selectedFilter)))
    .filter((item) => !query || String(item.name || "").toLocaleLowerCase().includes(query))
    .sort((left, right) => {
      const a = qbitSortValue(left, qbitSort.value);
      const b = qbitSortValue(right, qbitSort.value);
      const comparison = typeof a === "string" ? a.localeCompare(b, undefined, { numeric: true }) : a - b;
      return qbitSortAscending ? comparison : -comparison;
    });

  qbitList.innerHTML = "";
  if (items.length === 0) {
    showQbitMessage(query ? "No torrents match your search." : "No torrents match this view.", "success");
    return;
  }

  qbitMessage.hidden = true;
  items.forEach((item) => {
    qbitList.append(qbitCard(item));
  });
}

function qbitCard(item) {
  const progress = Math.max(0, Math.min(100, Number(item.progress || 0) * 100));
  const card = document.createElement("article");
  card.className = "qbit-item";
  if (item.error) {
    card.classList.add("has-error");
  }
  if (!isAdmin()) {
    card.innerHTML = `
      <div class="qbit-row">
        <strong>${escapeHtml(item.name || "Unnamed")}</strong>
        <span>${progress.toFixed(1)}%</span>
      </div>
      <div class="progress-bar"><span style="width: ${progress}%"></span></div>
      <div class="qbit-meta">
        <span>Size ${formatBytes(item.size)}</span>
        <span>Down ${formatSpeed(item.dlspeed)}</span>
        <span>ETA ${formatEta(item.eta)}</span>
      </div>
    `;
    return card;
  }
  card.innerHTML = `
    <div class="qbit-row">
      <strong>${escapeHtml(item.name || "Unnamed")}</strong>
      <span>${progress.toFixed(1)}%</span>
    </div>
    <div class="progress-bar"><span style="width: ${progress}%"></span></div>
    <div class="qbit-meta">
      <span>Size ${formatBytes(item.size)}</span>
      <span>Down ${formatSpeed(item.dlspeed)}</span>
      <span>Up ${formatSpeed(item.upspeed)}</span>
      <span>ETA ${formatEta(item.eta)}</span>
      <span>Ratio ${formatRatio(item.ratio)}</span>
      <span>Seeds ${Number(item.numSeeds || 0)}</span>
      <span>Peers ${Number(item.numPeers || 0)}</span>
      <span>${escapeHtml(item.state || "unknown")}</span>
    </div>
    ${item.error ? `<div class="qbit-error">${escapeHtml(item.error)}</div>` : ""}
  `;
  return card;
}

async function setQbitSession(action) {
  if (!isAdmin()) return;
  startQbitButton.disabled = true;
  pauseQbitButton.disabled = true;
  qbitMessage.hidden = true;
  try {
    const response = await fetch("/api/qbit/session", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ action }),
    });
    const result = await response.json();
    if (!response.ok || result.error) throw new Error(result.error || "Session action failed.");
    await loadQbitStatus();
    showQbitMessage(action === "pause" ? "qBittorrent session paused." : "qBittorrent session started.", "success");
  } catch (error) {
    showQbitMessage(error.message, "error");
  } finally {
    startQbitButton.disabled = false;
    pauseQbitButton.disabled = false;
  }
}

async function searchRequests() {
  const searchId = ++requestSearchId;
  requestMessage.hidden = true;
  requestResults.innerHTML = "";
  const query = requestSearch.value.trim();
  if (query.length < 2) return;

  requestResults.append(loadingCard("Searching..."));
  try {
    const params = new URLSearchParams({ q: query, type: "all" });
    const response = await fetch(`/api/tmdb/search?${params}`);
    const result = await response.json();
    if (searchId !== requestSearchId) return;
    if (result.error) throw new Error(result.error);
    renderRequestResults(result.items || []);
  } catch (error) {
    if (searchId !== requestSearchId) return;
    requestResults.querySelector(".loading-card")?.remove();
    showRequestMessage(error.message, "error");
  }
}

function renderRequestResults(items) {
  requestResults.innerHTML = "";
  requestResults.append(asIsRequestCard());
  const scroll = document.createElement("div");
  scroll.className = "suggestion-scroll";
  items.forEach((item) => {
    const card = document.createElement("article");
    card.className = "tmdb-result request-result";
    card.tabIndex = 0;
    card.setAttribute("role", "button");
    card.setAttribute("aria-label", `Request ${item.title}`);
    const year = item.year ? ` (${item.year})` : "";
    card.innerHTML = `
      <div>
        <strong>${escapeHtml(item.title)}${year}</strong>
        <small>${item.type === "tv" ? "TV Show" : "Movie"}</small>
        ${item.overview ? `<p>${escapeHtml(item.overview).slice(0, 180)}${item.overview.length > 180 ? "..." : ""}</p>` : ""}
      </div>
    `;
    card.addEventListener("click", () => submitRequest({ tmdbItem: item }));
    card.addEventListener("keydown", (event) => {
      if (event.key === "Enter" || event.key === " ") {
        event.preventDefault();
        submitRequest({ tmdbItem: item });
      }
    });
    scroll.append(card);
  });
  requestResults.append(scroll);
}

function asIsRequestCard() {
  const title = requestSearch.value.trim();
  const card = document.createElement("article");
  card.className = "tmdb-result request-result as-is-result";
  card.tabIndex = 0;
  card.setAttribute("role", "button");
  card.setAttribute("aria-label", `Request ${title || "as is"}`);
  card.innerHTML = `
    <div>
      <strong>${escapeHtml(title || "Send as is")}</strong>
      <small>No TMDb match</small>
    </div>
  `;
  const submit = () => {
    const customTitle = requestSearch.value.trim();
    if (!customTitle) {
      showRequestMessage("Enter a request.", "error");
      return;
    }
    submitRequest({ customTitle });
  };
  card.addEventListener("click", submit);
  card.addEventListener("keydown", (event) => {
    if (event.key === "Enter" || event.key === " ") {
      event.preventDefault();
      submit();
    }
  });
  return card;
}

async function submitRequest(extra) {
  requestMessage.hidden = true;
  requestResults.prepend(loadingCard("Sending..."));
  const payload = {
    requester: requesterName.value.trim(),
    quality: requestQuality.value,
    ...extra,
  };
  try {
    const response = await fetch("/api/requests", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });
    const result = await response.json();
    if (!response.ok || result.error) {
      throw new Error(result.error || "Request failed.");
    }
    requestSearch.value = "";
    requestResults.innerHTML = "";
    showRequestMessage(requestSavedMessage(result), result.warning ? "warning" : "success");
    if (result.item) {
      prependRequestItem(result.item);
    }
    window.setTimeout(loadRequests, 1000);
  } catch (error) {
    requestResults.querySelector(".loading-card")?.remove();
    showRequestMessage(error.message, "error");
  }
}

function requestSavedMessage(result) {
  const parts = ["Requested."];
  if (result.warning) {
    parts.push(result.warning);
  }
  if (requestQuality.value === "REMUX") {
    parts.push("REMUX requests are unlikely unless previously discussed.");
  }
  return parts.join(" ");
}

function scheduleRequestSearch() {
  window.clearTimeout(requestSearchTimer);
  requestSearchTimer = window.setTimeout(searchRequests, 300);
}

async function loadRequests() {
  const loadId = ++requestListLoadId;
  const response = await fetch("/api/requests");
  const result = await response.json();
  if (loadId !== requestListLoadId) return;
  renderRequestList(result.items || []);
}

function syncRequestRefresh(active) {
  if (requestRefreshTimer) {
    window.clearInterval(requestRefreshTimer);
    requestRefreshTimer = null;
  }
  if (active) {
    requestRefreshTimer = window.setInterval(loadRequests, 5000);
  }
}

function renderRequestList(items) {
  requestList.innerHTML = "";
  items.forEach((item) => requestList.append(requestCard(item)));
}

function prependRequestItem(item) {
  requestList.prepend(requestCard(item));
}

function requestCard(item) {
  const tmdb = item.tmdb || {};
  const title = tmdb.title || item.customTitle || "Request";
  const year = tmdb.year ? ` (${tmdb.year})` : "";
  const poster = tmdb.posterPath ? `https://image.tmdb.org/t/p/w185${tmdb.posterPath}` : "";
  const quality = item.quality || "1080p";
  const fulfillment = item.fulfillment || null;
  const card = document.createElement("article");
  card.className = "request-card";
  if (item.libraryWarning) {
    card.classList.add("has-warning");
  }
  if (fulfillment && fulfillment.state) {
    card.classList.add(`is-${fulfillment.state}`);
  }
  card.innerHTML = `
    ${poster ? `<img class="request-poster" src="${escapeHtml(poster)}" alt="">` : `<div class="request-poster"></div>`}
    <div>
      <strong>${escapeHtml(title)}${year}</strong>
      <small>${escapeHtml(item.requester || "Unknown")} &middot; ${formatRequestTime(item.requestedAt)} &middot; ${escapeHtml(quality)}</small>
      ${fulfillment ? `<small class="request-status ${escapeHtml(fulfillment.state)}">${escapeHtml(fulfillment.message)}</small>` : ""}
      ${item.reminderMuted && isAdmin() ? `<small class="request-reminder-muted">Admin reminders muted</small>` : ""}
      ${item.libraryWarning ? `<small class="request-warning">${escapeHtml(item.libraryWarning)}</small>` : ""}
      ${tmdb.overview ? `<small>${escapeHtml(tmdb.overview).slice(0, 180)}${tmdb.overview.length > 180 ? "..." : ""}</small>` : ""}
    </div>
    <div class="request-actions">
      ${isAdmin() && (!fulfillment || fulfillment.state !== "fulfilled") ? `<button class="icon-button request-fulfill" type="button">Fulfilled</button>` : ""}
      ${isAdmin() ? `<button class="icon-button request-reminder-mute" type="button">${item.reminderMuted ? "Unmute reminder" : "Mute reminder"}</button>` : ""}
      <button class="icon-button request-delete" type="button" aria-label="Delete request">Delete</button>
    </div>
  `;
  const deleteButton = card.querySelector(".request-delete");
  if (deleteButton) {
    deleteButton.addEventListener("click", () => deleteRequest(item.id));
  }
  const fulfillButton = card.querySelector(".request-fulfill");
  if (fulfillButton) {
    fulfillButton.addEventListener("click", () => markRequestFulfilled(item.id));
  }
  const reminderMuteButton = card.querySelector(".request-reminder-mute");
  if (reminderMuteButton) {
    reminderMuteButton.addEventListener("click", () => setRequestReminderMuted(item.id, !item.reminderMuted));
  }
  return card;
}

async function markRequestFulfilled(id) {
  if (!isAdmin()) return;
  try {
    const response = await fetch("/api/requests/fulfill", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ id }),
    });
    const result = await response.json();
    if (!response.ok || result.error) {
      throw new Error(result.error || "Update failed.");
    }
    renderRequestList(result.items || []);
  } catch (error) {
    showRequestMessage(error.message, "error");
  }
}

async function setRequestReminderMuted(id, muted) {
  if (!isAdmin()) return;
  try {
    const response = await fetch("/api/requests/reminder-mute", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ id, muted }),
    });
    const result = await response.json();
    if (!response.ok || result.error) {
      throw new Error(result.error || "Reminder update failed.");
    }
    renderRequestList(result.items || []);
  } catch (error) {
    showRequestMessage(error.message, "error");
  }
}

async function deleteRequest(id) {
  if (!isAdmin()) return;
  try {
    const response = await fetch(`/api/requests?id=${encodeURIComponent(id)}`, {
      method: "DELETE",
    });
    const result = await response.json();
    if (!response.ok || result.error) {
      throw new Error(result.error || "Delete failed.");
    }
    loadRequests();
  } catch (error) {
    showRequestMessage(error.message, "error");
  }
}

async function loadAdminConfig() {
  if (!isAdmin()) return;
  configMessage.hidden = true;
  try {
    const response = await fetch("/api/admin/config/load", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({}),
    });
    const result = await response.json();
    if (!response.ok || result.error) {
      throw new Error(result.error || "Could not load config.");
    }
    adminConfigLoaded = true;
    renderConfig(result.config);
  } catch (error) {
    showConfigMessage(error.message, "error");
  }
}

function renderConfig(config) {
  configAppVersion.value = config.app?.version || "v8.2";
  configQbitUrl.value = config.qbittorrent?.url || "";
  configPlexPath.value = config.plex?.databasePath || "";
  configDiscordWebhook.value = config.discordWebhookUrl || "";
  configAdminReminderWebhook.value = config.adminReminderWebhookUrl || "";
  configAdminReminderInterval.value = config.adminReminderIntervalMinutes || 60;
  configDestinations.innerHTML = "";
  (config.destinations || []).forEach((destination) => addConfigDestination(destination));
  configDiscordMappings.innerHTML = "";
  (config.discordUserMappings || []).forEach((mapping) => addDiscordMapping(mapping));
}

function addConfigDestination(destination = {}) {
  const row = document.createElement("div");
  row.className = "config-destination";
  row.dataset.destinationId = destination.id || "";
  row.innerHTML = `
    <input class="config-destination-label" type="text" placeholder="Label" value="${escapeHtml(destination.label || "")}">
    <div class="config-destination-paths"></div>
    <label class="check-row compact">
      <input class="config-destination-browse" type="checkbox" ${destination.browseSubfolders ? "checked" : ""}>
      <span>Browse</span>
    </label>
    <div class="config-destination-actions">
      <button class="secondary-button config-add-path" type="button">Add directory</button>
      <button class="icon-button config-remove-destination" type="button">Remove</button>
    </div>
  `;
  const paths = destination.paths?.length ? destination.paths : [destination.path || ""];
  paths.forEach((path) => addConfigDestinationPath(row, path));
  row.querySelector(".config-add-path").addEventListener("click", () => addConfigDestinationPath(row));
  row.querySelector(".config-remove-destination").addEventListener("click", () => row.remove());
  configDestinations.append(row);
}

function addConfigDestinationPath(destinationRow, value = "") {
  const paths = destinationRow.querySelector(".config-destination-paths");
  const row = document.createElement("div");
  row.className = "config-destination-path-row";
  row.innerHTML = `
    <input class="config-destination-path" type="text" placeholder="Directory path" value="${escapeHtml(value)}">
    <button class="icon-button" type="button">Remove</button>
  `;
  row.querySelector("button").addEventListener("click", () => {
    if (paths.children.length > 1) row.remove();
  });
  paths.append(row);
}

function addDiscordMapping(mapping = {}) {
  const row = document.createElement("div");
  row.className = "config-discord-mapping";
  row.innerHTML = `
    <input class="config-requester-name" type="text" placeholder="Requester name" value="${escapeHtml(mapping.requesterName || "")}">
    <input class="config-discord-user-id" type="text" inputmode="numeric" placeholder="Discord user ID" value="${escapeHtml(mapping.discordUserId || "")}">
    <button class="icon-button" type="button">Remove</button>
  `;
  row.querySelector("button").addEventListener("click", () => row.remove());
  configDiscordMappings.append(row);
}

function collectDiscordUserMappings() {
  const mappings = [];
  const names = new Set();
  configDiscordMappings.querySelectorAll(".config-discord-mapping").forEach((row) => {
    const requesterName = row.querySelector(".config-requester-name").value.trim();
    const discordUserId = row.querySelector(".config-discord-user-id").value.trim();
    if (!requesterName) throw new Error("Requester name is required for every Discord user mapping.");
    if (!discordUserId) throw new Error(`Discord user ID is required for ${requesterName}.`);
    if (!/^[1-9][0-9]{14,19}$/.test(discordUserId)) {
      throw new Error(`Discord user ID for ${requesterName} must be a 15 to 20 digit number.`);
    }
    const normalizedName = requesterName.toLocaleLowerCase();
    if (names.has(normalizedName)) throw new Error(`Duplicate requester name: ${requesterName}.`);
    names.add(normalizedName);
    mappings.push({ requesterName, discordUserId });
  });
  return mappings;
}

function collectConfig() {
  return {
    app: {
      version: configAppVersion.value.trim(),
    },
    qbittorrent: {
      url: configQbitUrl.value.trim(),
    },
    plex: {
      databasePath: configPlexPath.value.trim(),
    },
    discordUserMappings: collectDiscordUserMappings(),
    discordWebhookUrl: configDiscordWebhook.value.trim(),
    adminReminderWebhookUrl: configAdminReminderWebhook.value.trim(),
    adminReminderIntervalMinutes: Number(configAdminReminderInterval.value),
    destinations: Array.from(configDestinations.querySelectorAll(".config-destination")).map((row) => ({
      id: row.dataset.destinationId,
      label: row.querySelector(".config-destination-label").value.trim(),
      paths: Array.from(row.querySelectorAll(".config-destination-path")).map((input) => input.value.trim()).filter(Boolean),
      browseSubfolders: row.querySelector(".config-destination-browse").checked,
    })),
  };
}

async function saveConfig(event) {
  event.preventDefault();
  if (!isAdmin()) return;

  configMessage.hidden = true;
  saveConfigButton.disabled = true;
  saveConfigButton.textContent = "Saving...";
  try {
    const response = await fetch("/api/admin/config/save", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ config: collectConfig() }),
    });
    const result = await response.json();
    if (!response.ok || result.error) {
      throw new Error(result.error || "Save failed.");
    }
    renderConfig(result.config);
    showConfigMessage("Saved.", "success");
    await loadConfig();
  } catch (error) {
    showConfigMessage(error.message, "error");
  } finally {
    saveConfigButton.disabled = false;
    saveConfigButton.textContent = "Save";
  }
}

async function searchTmdb() {
  const searchId = ++tmdbSearchId;
  tmdbMessage.hidden = true;
  tmdbResults.innerHTML = "";
  const query = tmdbSearch.value.trim();
  if (query.length < 2) return;

  tmdbResults.append(loadingCard("Searching..."));
  const params = new URLSearchParams({
    q: query,
    type: tmdbType.value,
  });

  try {
    const response = await fetch(`/api/tmdb/search?${params}`);
    const result = await response.json();
    if (searchId !== tmdbSearchId) return;
    if (result.error) {
      tmdbResults.querySelector(".loading-card")?.remove();
      showTmdbMessage(result.error, "error");
      return;
    }
    renderTmdbResults(result.items || []);
  } catch (error) {
    if (searchId !== tmdbSearchId) return;
    tmdbResults.querySelector(".loading-card")?.remove();
    showTmdbMessage(error.message, "error");
  }
}

function renderTmdbResults(items) {
  tmdbItems = items;
  if (items.length === 0) {
    showTmdbMessage("No TMDb results found.", "error");
    return;
  }

  tmdbMessage.hidden = true;
  tmdbResults.innerHTML = "";
  items.forEach((item) => {
    const card = document.createElement("article");
    card.className = "tmdb-result";
    const year = item.year ? ` (${item.year})` : "";
    const typeLabel = item.type === "tv" ? "TV Show" : "Movie";
    const rating = item.voteAverage ? ` &middot; ${Number(item.voteAverage).toFixed(1)}/10` : "";
    const suggestedName = tmdbDownloadName(item);

    card.innerHTML = `
      <div>
        <strong>${escapeHtml(item.title)}${year}</strong>
        <small>${typeLabel}${rating} &middot; Name: ${escapeHtml(suggestedName)}</small>
        ${item.overview ? `<p>${escapeHtml(item.overview).slice(0, 220)}${item.overview.length > 220 ? "..." : ""}</p>` : ""}
      </div>
      <button class="secondary-button" type="button">Use Download Name</button>
    `;
    card.querySelector("button").addEventListener("click", () => useTmdbDownloadName(item));
    tmdbResults.append(card);
  });
}

function seasonFolderName(item) {
  const season = Math.max(1, Number(tmdbSeason.value || 1));
  const padded = String(season).padStart(2, "0");
  return `${item.folderName} S${padded}`;
}

function tmdbDownloadName(item) {
  return item.type === "tv" ? seasonFolderName(item) : item.folderName;
}

async function useTmdbDownloadName(item) {
  tmdbMessage.hidden = true;
  tmdbResults.prepend(loadingCard("Selecting..."));
  const wantedDestination = item.type === "tv" ? "tv" : "film";
  const destination = destinationConfig.find((option) => {
    const id = option.id.toLowerCase();
    const label = option.label.toLowerCase();
    return wantedDestination === "tv"
      ? id.includes("tv") || label.includes("tv")
      : id.includes("film") || id.includes("movie") || label.includes("film") || label.includes("movie");
  });

  let topLevelFolders = [];
  if (destination) {
    const radio = Array.from(document.querySelectorAll("[name='destinationId']"))
      .find((input) => input.value === destination.id);
    if (radio) {
      radio.checked = true;
      topLevelFolders = await syncFolderSelect();
    }
  }

  downloadName.value = tmdbDownloadName(item);
  if (item.type === "tv") {
    const parentFolder = item.folderName;
    const existingParent = topLevelFolders.some((folder) => folder.toLocaleLowerCase() === parentFolder.toLocaleLowerCase());
    useSubfolder.checked = true;
    newFolderList.innerHTML = "";
    addNewFolderInput(parentFolder);
    syncSubfolderField();
    showTmdbMessage(
      existingParent
        ? `Existing parent folder found. Download will use ${parentFolder}.`
        : `Parent folder ${parentFolder} will be created for this download.`,
      "success",
    );
  } else {
    showTmdbMessage("Download name filled in below.", "success");
  }
  tmdbResults.querySelector(".loading-card")?.remove();
}

function scheduleTmdbSearch() {
  window.clearTimeout(tmdbSearchTimer);
  tmdbSearchTimer = window.setTimeout(searchTmdb, 300);
}

function syncTmdbType() {
  tmdbSeason.hidden = tmdbType.value === "movie";
}

async function searchLibrary() {
  const searchId = ++librarySearchId;
  const selectedType = libraryType.value;
  libraryMessage.hidden = true;
  libraryResults.innerHTML = "";

  const params = new URLSearchParams({
    q: librarySearch.value.trim(),
    type: selectedType,
  });

  try {
    const response = await fetch(`/api/library/search?${params}`);
    const result = await response.json();
    if (searchId !== librarySearchId) return;

    if (result.error) {
      showLibraryMessage(result.error, "error");
      return;
    }

    renderLibraryResults(result.items || [], selectedType);
  } catch (error) {
    if (searchId !== librarySearchId) return;
    showLibraryMessage(error.message, "error");
  }
}

function renderLibraryResults(items, selectedType) {
  if (items.length === 0) {
    const emptyMessage = selectedType === "movie"
      ? "No matching movies found."
      : selectedType === "show"
        ? "No matching TV shows found."
        : "No matching movies or TV shows found.";
    showLibraryMessage(emptyMessage, "error");
    return;
  }

  libraryMessage.hidden = true;
  libraryMessage.textContent = "";
  libraryResults.innerHTML = "";
  items.forEach((item) => {
    const card = document.createElement("article");
    card.className = "library-item";
    card.tabIndex = 0;
    card.dataset.itemId = String(item.id);
    const year = item.year ? ` (${item.year})` : "";
    const detail = item.type === "show"
      ? `${item.episodeCount || 0} episodes`
      : `${item.fileCount || 0} files`;
    const library = item.library || "Plex";
    const match = item.match ? `<span class="match-label ${item.match === "Exact" ? "exact" : "similar"}">${escapeHtml(item.match)}</span>` : "";
    const quality = item.qualitySummary ? ` &middot; ${escapeHtml(item.qualitySummary)}` : "";

    card.innerHTML = `
      <div>
        <strong>${escapeHtml(item.title)}${year}${match}</strong>
        <small>${item.type === "show" ? "TV Show" : "Movie"} &middot; ${escapeHtml(library)} &middot; ${detail}${quality}</small>
      </div>
    `;
    card.addEventListener("click", () => toggleLibraryDetails(card, item.id));
    card.addEventListener("keydown", (event) => {
      if (event.key === "Enter" || event.key === " ") {
        event.preventDefault();
        toggleLibraryDetails(card, item.id);
      }
    });
    libraryResults.append(card);
  });
}

async function toggleLibraryDetails(card, itemId) {
  const existing = card.querySelector(".library-detail");
  if (existing) {
    existing.remove();
    card.classList.remove("expanded");
    return;
  }

  libraryResults.querySelectorAll(".library-detail").forEach((detail) => detail.remove());
  libraryResults.querySelectorAll(".library-item.expanded").forEach((item) => item.classList.remove("expanded"));

  card.classList.add("expanded");
  const detail = document.createElement("div");
  detail.className = "library-detail";
  detail.textContent = "Loading Plex database details...";
  card.append(detail);

  try {
    const response = await fetch(`/api/library/item?id=${encodeURIComponent(itemId)}`);
    const result = await response.json();
    if (result.error) {
      detail.textContent = result.error;
      return;
    }

    renderLibraryDetail(detail, result);
  } catch (error) {
    detail.textContent = error.message;
  }
}

function renderLibraryDetail(container, data) {
  const metadata = data.metadata || {};
  const library = data.librarySection || {};
  const files = data.mediaParts || [];
  const parents = data.parents || [];
  const children = data.children || [];
  const episodes = data.episodes || [];
  const tags = data.tags || [];
  const relatedTables = data.relatedTables || {};

  container.innerHTML = `
    <div class="detail-grid">
      ${detailSection("Overview", [
        ["Title", metadata.title],
        ["Original title", metadata.original_title],
        ["Year", metadata.year],
        ["Available", metadata.originally_available_at],
        ["Rating", metadata.rating],
        ["Audience rating", metadata.audience_rating],
        ["Content rating", metadata.content_rating],
        ["Studio", metadata.studio],
        ["Edition", metadata.edition_title],
      ])}
      ${detailSection("Library", [
        ["Library", library.name],
        ["Library type", library.section_type],
        ["Item id", metadata.id],
        ["Metadata type", metadata.metadata_type],
        ["GUID", metadata.guid],
        ["Added", formatUnixTime(metadata.added_at)],
        ["Updated", formatUnixTime(metadata.updated_at)],
      ])}
    </div>
    ${metadata.summary ? `<section class="detail-section"><h3>Summary</h3><p>${escapeHtml(metadata.summary)}</p></section>` : ""}
    ${renderFileSection(files)}
    ${renderRelationshipSection("Parents", parents)}
    ${renderRelationshipSection("Children", children)}
    ${renderRelationshipSection("Episodes", episodes)}
    ${renderTagsSection(tags)}
    ${renderExtraDataSection(metadata)}
    ${renderRelatedTablesSection(relatedTables)}
  `;
}

function detailSection(title, rows) {
  const visibleRows = rows.filter(([, value]) => value !== null && value !== undefined && value !== "");
  if (visibleRows.length === 0) return "";
  return `
    <section class="detail-section">
      <h3>${escapeHtml(title)}</h3>
      <dl class="detail-list">
        ${visibleRows.map(([label, value]) => `
          <div>
            <dt>${escapeHtml(label)}</dt>
            <dd>${escapeHtml(value)}</dd>
          </div>
        `).join("")}
      </dl>
    </section>
  `;
}

function renderFileSection(files) {
  if (!files.length) return "";
  return `
    <section class="detail-section">
      <h3>Files</h3>
      <div class="file-list">
        ${files.map((file) => `
          <div class="file-row">
            <strong>${escapeHtml(file.file || "Unknown file")}</strong>
            <small>${formatBytes(file.size)}${file.duration ? ` &middot; ${formatDuration(file.duration)}` : ""}</small>
          </div>
        `).join("")}
      </div>
    </section>
  `;
}

function renderRelationshipSection(title, items) {
  if (!items.length) return "";
  return `
    <section class="detail-section">
      <h3>${escapeHtml(title)} <span>${items.length}</span></h3>
      <div class="mini-list">
        ${items.slice(0, 40).map((item) => `
          <div>
            <strong>${escapeHtml(item.title || `Item ${item.id}`)}</strong>
            <small>${item.year ? escapeHtml(item.year) : ""}${item.metadata_type ? ` &middot; Type ${escapeHtml(item.metadata_type)}` : ""}</small>
          </div>
        `).join("")}
      </div>
      ${items.length > 40 ? `<p class="field-note">Showing first 40 of ${items.length}.</p>` : ""}
    </section>
  `;
}

function renderTagsSection(tags) {
  if (!tags.length) return "";
  return `
    <section class="detail-section">
      <h3>Tags</h3>
      <div class="tag-list">
        ${tags.map((tag) => `<span>${escapeHtml(tag.tag || tag.title || tag.name || tag.id)}</span>`).join("")}
      </div>
    </section>
  `;
}

function renderExtraDataSection(metadata) {
  const extraRows = Object.entries(metadata)
    .filter(([key, value]) => ![
      "id", "title", "original_title", "year", "originally_available_at", "rating",
      "audience_rating", "content_rating", "studio", "edition_title", "summary",
      "library_section_id", "metadata_type", "guid", "added_at", "updated_at",
    ].includes(key) && value !== null && value !== undefined && value !== "")
    .slice(0, 36);

  if (!extraRows.length) return "";
  return detailSection("More Metadata", extraRows.map(([key, value]) => [humanizeKey(key), value]));
}

function renderRelatedTablesSection(relatedTables) {
  const entries = Object.entries(relatedTables).filter(([, rows]) => Array.isArray(rows) && rows.length > 0);
  if (!entries.length) return "";
  return `
    <section class="detail-section">
      <h3>Related Database Rows</h3>
      <div class="mini-list">
        ${entries.map(([table, rows]) => `
          <div>
            <strong>${escapeHtml(table)}</strong>
            <small>${rows.length} rows available from read-only snapshot</small>
          </div>
        `).join("")}
      </div>
    </section>
  `;
}

function humanizeKey(key) {
  return String(key).replaceAll("_", " ").replace(/\b\w/g, (letter) => letter.toUpperCase());
}

function formatUnixTime(value) {
  if (!value) return "";
  const date = new Date(Number(value) * 1000);
  return Number.isNaN(date.getTime()) ? value : date.toLocaleString();
}

function formatRequestTime(value) {
  if (!value) return "";
  const date = new Date(Number(value) * 1000);
  return Number.isNaN(date.getTime()) ? "" : date.toLocaleString();
}

function formatBytes(value) {
  const bytes = Number(value || 0);
  if (!bytes) return "Size unknown";
  const units = ["B", "KB", "MB", "GB", "TB"];
  let size = bytes;
  let index = 0;
  while (size >= 1024 && index < units.length - 1) {
    size /= 1024;
    index += 1;
  }
  return `${size.toFixed(index === 0 ? 0 : 1)} ${units[index]}`;
}

function formatSpeed(value) {
  const bytes = Number(value || 0);
  if (!bytes) return "0 B/s";
  return `${formatBytes(bytes)}/s`;
}

function formatEta(value) {
  const seconds = Number(value);
  if (!Number.isFinite(seconds) || seconds < 0 || seconds >= 8640000) return "unknown";
  if (seconds < 60) return `${Math.round(seconds)}s`;
  const hours = Math.floor(seconds / 3600);
  const minutes = Math.floor((seconds % 3600) / 60);
  if (hours) return `${hours}h ${minutes}m`;
  return `${minutes}m`;
}

function formatRatio(value) {
  const ratio = Number(value || 0);
  return ratio.toFixed(2);
}

function formatDuration(value) {
  const seconds = Math.round(Number(value || 0) / 1000);
  if (!seconds) return "";
  const hours = Math.floor(seconds / 3600);
  const minutes = Math.floor((seconds % 3600) / 60);
  if (hours) return `${hours}h ${minutes}m`;
  return `${minutes}m`;
}

function scheduleLibrarySearch() {
  window.clearTimeout(librarySearchTimer);
  librarySearchTimer = window.setTimeout(searchLibrary, 250);
}

function escapeHtml(value) {
  return String(value ?? "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#039;");
}

function fileAsBase64(file) {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.addEventListener("load", () => resolve(String(reader.result).split(",", 2)[1] || ""));
    reader.addEventListener("error", () => reject(new Error("Could not read the torrent file.")));
    reader.readAsDataURL(file);
  });
}

form.addEventListener("submit", async (event) => {
  event.preventDefault();
  message.hidden = true;
  if (!isAdmin()) {
    showMessage("Admin login required.", "error");
    return;
  }
  const data = new FormData(form);
  const selectedFile = torrentFile.files[0] || null;
  const magnet = String(data.get("magnet") || "").trim();
  if (!magnet && !selectedFile) {
    showMessage("Paste a magnet link or choose a .torrent file.", "error");
    return;
  }
  if (magnet && selectedFile) {
    showMessage("Use either a magnet link or a .torrent file, not both.", "error");
    return;
  }
  if (selectedFile && (!selectedFile.name.toLowerCase().endsWith(".torrent") || selectedFile.size > 10 * 1024 * 1024)) {
    showMessage("Choose a .torrent file that is 10 MB or smaller.", "error");
    return;
  }

  submitButton.disabled = true;
  submitButton.querySelector("span").textContent = "Sending...";

  const payload = {
    magnet,
    destinationId: data.get("destinationId"),
    destinationPathIndex: selectedDestinationPathIndex(),
    downloadName: data.get("downloadName"),
    useSubfolder: data.get("useSubfolder") === "on",
    existingSubfolderPath: selectedFolderPath(),
    newSubfolders: newFolderPath(),
  };

  try {
    if (selectedFile) {
      payload.torrentFileName = selectedFile.name;
      payload.torrentData = await fileAsBase64(selectedFile);
    }
    const response = await fetch(selectedFile ? "/api/torrents" : "/api/magnets", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });

    const result = await response.json();
    if (!response.ok) {
      if (result.duplicate) {
        showMessage(result.error, "error");
        return;
      }
      throw new Error(result.error || "qBittorrent rejected the download.");
    }

    showMessage(`${result.message} Destination: ${result.path}`, "success");
    form.reset();
    const firstDestination = document.querySelector("[name='destinationId']");
    if (firstDestination) firstDestination.checked = true;
    newFolderList.innerHTML = "";
    syncDestinationControls();
    syncSubfolderField();
  } catch (error) {
    showMessage(error.message, "error");
  } finally {
    submitButton.disabled = false;
    submitButton.querySelector("span").textContent = "Add to Library";
  }
});

magnetInput.addEventListener("input", () => {
  if (magnetInput.value.trim() && torrentFile.value) torrentFile.value = "";
});
torrentFile.addEventListener("change", () => {
  const selectedFile = torrentFile.files[0];
  if (!selectedFile) return;
  magnetInput.value = "";
  if (!selectedFile.name.toLowerCase().endsWith(".torrent")) {
    showMessage("The selected file must have a .torrent extension.", "error");
  } else if (selectedFile.size > 10 * 1024 * 1024) {
    showMessage("Torrent files must be 10 MB or smaller.", "error");
  } else {
    message.hidden = true;
  }
});

useSubfolder.addEventListener("change", syncSubfolderField);
destinationDirectory.addEventListener("change", syncFolderSelect);
addFolderButton.addEventListener("click", () => {
  addNewFolderInput();
  syncSubfolderField();
});
requestTabButton.addEventListener("click", () => activateTab("request"));
downloadTabButton.addEventListener("click", () => activateTab("download"));
libraryTabButton.addEventListener("click", () => activateTab("library"));
storageTabButton.addEventListener("click", () => activateTab("storage"));
qbitTabButton.addEventListener("click", () => activateTab("qbit"));
configTabButton.addEventListener("click", () => activateTab("config"));
loginButton.addEventListener("click", login);
mobilePinpad.addEventListener("click", handlePinpadPress);
loginPin.addEventListener("keydown", (event) => {
  if (event.key === "Enter") {
    event.preventDefault();
    login();
  }
});
logoutButton.addEventListener("click", handleAuthButton);
requestSearch.addEventListener("input", scheduleRequestSearch);
requestSearch.addEventListener("keydown", (event) => {
  if (event.key === "Enter") {
    event.preventDefault();
    searchRequests();
  }
});
requestQuality.addEventListener("change", () => {
  if (requestQuality.value === "REMUX") {
    showRequestMessage("REMUX requests are unlikely unless previously discussed.", "warning");
  } else {
    requestMessage.hidden = true;
  }
});
librarySearchForm.addEventListener("submit", (event) => {
  event.preventDefault();
  searchLibrary();
});
librarySearch.addEventListener("input", scheduleLibrarySearch);
libraryType.addEventListener("change", () => {
  window.clearTimeout(librarySearchTimer);
  searchLibrary();
});
refreshStorageButton.addEventListener("click", loadStorage);
refreshQbitButton.addEventListener("click", loadQbitStatus);
startQbitButton.addEventListener("click", () => setQbitSession("start"));
pauseQbitButton.addEventListener("click", () => setQbitSession("pause"));
qbitSearch.addEventListener("input", renderQbitItems);
qbitFilter.addEventListener("change", renderQbitItems);
qbitSort.addEventListener("change", renderQbitItems);
qbitSortDirection.addEventListener("click", () => {
  qbitSortAscending = !qbitSortAscending;
  qbitSortDirection.textContent = qbitSortAscending ? "↑" : "↓";
  qbitSortDirection.setAttribute("aria-label", qbitSortAscending ? "Sort ascending" : "Sort descending");
  renderQbitItems();
});
addDestinationButton.addEventListener("click", () => addConfigDestination());
addDiscordMappingButton.addEventListener("click", () => addDiscordMapping());
configForm.addEventListener("submit", saveConfig);
tmdbSearch.addEventListener("input", scheduleTmdbSearch);
tmdbSearch.addEventListener("keydown", (event) => {
  if (event.key === "Enter") {
    event.preventDefault();
    searchTmdb();
  }
});
tmdbType.addEventListener("change", () => {
  window.clearTimeout(tmdbSearchTimer);
  syncTmdbType();
  searchTmdb();
});
tmdbSeason.addEventListener("input", () => {
  if (tmdbItems.length > 0) {
    renderTmdbResults(tmdbItems);
  }
});
syncSubfolderField();
syncTmdbType();

checkAuth().catch((error) => {
  showLoginMessage(error.message, "error");
});
