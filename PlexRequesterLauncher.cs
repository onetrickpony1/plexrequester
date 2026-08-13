using System;
using System.Collections;
using System.Collections.Generic;
using System.Diagnostics;
using System.Drawing;
using System.IO;
using System.Reflection;
using System.Security.Cryptography;
using System.Web.Script.Serialization;
using System.Windows.Forms;

public class PlexRequesterLauncher : Form
{
    private readonly TabControl mainTabs;
    private readonly TextBox logBox;
    private readonly ListView historyList;
    private readonly TextBox tmdbKeyBox;
    private readonly TextBox discordWebhookBox;
    private readonly Label serverPortLabel;
    private readonly NumericUpDown serverPortBox;
    private readonly Label statusLabel;
    private readonly Label tmdbKeyStatus;
    private readonly Label discordWebhookStatus;
    private readonly Button openButton;
    private readonly Button stopButton;
    private readonly Button saveTmdbKeyButton;
    private readonly Button saveDiscordWebhookButton;
    private readonly Button saveServerPortButton;
    private readonly Button refreshHistoryButton;
    private readonly Timer historyRefreshTimer;
    private Process serverProcess;
    private string appDir;
    private string dataDir;
    private string logPath;
    private string renameHistoryPath;
    private int serverPort;
    private bool stopping;

    [STAThread]
    public static int Main()
    {
        Application.EnableVisualStyles();
        Application.SetCompatibleTextRenderingDefault(false);
        Application.Run(new PlexRequesterLauncher());
        return 0;
    }

    public PlexRequesterLauncher()
    {
        Text = "Plex Requester Logs";
        Width = 920;
        Height = 740;
        MinimumSize = new Size(760, 560);
        StartPosition = FormStartPosition.CenterScreen;
        BackColor = Color.FromArgb(9, 13, 18);
        ForeColor = Color.FromArgb(238, 245, 248);

        appDir = AppDomain.CurrentDomain.BaseDirectory;
        dataDir = Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData), "Plex Requester");
        Directory.CreateDirectory(dataDir);
        foreach (string fileName in new[] { "config.json", "requests.json", "request-fulfillment-state.json", "auth-sessions.json", "rename-history.jsonl", "plex-requester.log" })
        {
            string legacyPath = Path.Combine(appDir, fileName);
            string dataPath = Path.Combine(dataDir, fileName);
            if (!File.Exists(dataPath) && File.Exists(legacyPath))
            {
                File.Copy(legacyPath, dataPath);
            }
        }
        EnsureInitialConfig();
        logPath = Path.Combine(dataDir, "plex-requester.log");
        renameHistoryPath = Path.Combine(dataDir, "rename-history.jsonl");
        serverPort = LoadConfiguredPort();
        try
        {
            Icon = Icon.ExtractAssociatedIcon(Application.ExecutablePath);
        }
        catch { }

        var header = new Label
        {
            Text = "Plex Requester",
            AutoSize = true,
            Font = new Font("Segoe UI", 22, FontStyle.Bold),
            Location = new Point(18, 18),
            ForeColor = Color.FromArgb(238, 245, 248)
        };

        statusLabel = new Label
        {
            Text = "Starting server...",
            AutoSize = true,
            Font = new Font("Segoe UI", 10, FontStyle.Regular),
            Location = new Point(22, 65),
            ForeColor = Color.FromArgb(157, 175, 183)
        };

        openButton = CreateButton("Open Website");
        openButton.Anchor = AnchorStyles.Top | AnchorStyles.Right;
        openButton.Location = new Point(ClientSize.Width - 292, 24);
        openButton.Click += delegate { OpenWebsite(); };

        stopButton = CreateButton("Stop Server");
        stopButton.Anchor = AnchorStyles.Top | AnchorStyles.Right;
        stopButton.Location = new Point(ClientSize.Width - 148, 24);
        stopButton.Click += delegate { Close(); };

        tmdbKeyStatus = new Label
        {
            Text = "TMDb key: checking config...",
            AutoSize = true,
            Font = new Font("Segoe UI", 9, FontStyle.Bold),
            Location = new Point(22, 100),
            ForeColor = Color.FromArgb(157, 175, 183)
        };

        tmdbKeyBox = new TextBox
        {
            Anchor = AnchorStyles.Top | AnchorStyles.Left | AnchorStyles.Right,
            BackColor = Color.FromArgb(11, 17, 23),
            BorderStyle = BorderStyle.FixedSingle,
            ForeColor = Color.FromArgb(238, 245, 248),
            Font = new Font("Segoe UI", 10, FontStyle.Regular),
            Location = new Point(22, 124),
            PasswordChar = '*',
            Size = new Size(ClientSize.Width - 190, 28)
        };
        tmdbKeyBox.KeyDown += delegate(object sender, KeyEventArgs args)
        {
            if (args.KeyCode == Keys.Enter)
            {
                args.SuppressKeyPress = true;
                SaveTmdbKey();
            }
        };

        saveTmdbKeyButton = CreateButton("Save TMDb Key");
        saveTmdbKeyButton.Anchor = AnchorStyles.Top | AnchorStyles.Right;
        saveTmdbKeyButton.Location = new Point(ClientSize.Width - 148, 119);
        saveTmdbKeyButton.Click += delegate { SaveTmdbKey(); };

        discordWebhookStatus = new Label
        {
            Text = "Discord: checking config...",
            AutoSize = true,
            Font = new Font("Segoe UI", 9, FontStyle.Bold),
            Location = new Point(22, 154),
            ForeColor = Color.FromArgb(157, 175, 183)
        };

        discordWebhookBox = new TextBox
        {
            Anchor = AnchorStyles.Top | AnchorStyles.Left | AnchorStyles.Right,
            BackColor = Color.FromArgb(11, 17, 23),
            BorderStyle = BorderStyle.FixedSingle,
            ForeColor = Color.FromArgb(238, 245, 248),
            Font = new Font("Segoe UI", 10, FontStyle.Regular),
            Location = new Point(22, 178),
            PasswordChar = '*',
            Size = new Size(ClientSize.Width - 190, 28)
        };
        discordWebhookBox.KeyDown += delegate(object sender, KeyEventArgs args)
        {
            if (args.KeyCode == Keys.Enter)
            {
                args.SuppressKeyPress = true;
                SaveDiscordWebhook();
            }
        };

        saveDiscordWebhookButton = CreateButton("Save Discord");
        saveDiscordWebhookButton.Anchor = AnchorStyles.Top | AnchorStyles.Right;
        saveDiscordWebhookButton.Location = new Point(ClientSize.Width - 148, 173);
        saveDiscordWebhookButton.Click += delegate { SaveDiscordWebhook(); };

        serverPortLabel = new Label
        {
            Text = "Server / Tailscale port",
            AutoSize = true,
            Font = new Font("Segoe UI", 9, FontStyle.Bold),
            Location = new Point(22, 218),
            ForeColor = Color.FromArgb(157, 175, 183)
        };

        serverPortBox = new NumericUpDown
        {
            BackColor = Color.FromArgb(11, 17, 23),
            BorderStyle = BorderStyle.FixedSingle,
            ForeColor = Color.FromArgb(238, 245, 248),
            Font = new Font("Segoe UI", 10, FontStyle.Regular),
            Location = new Point(188, 212),
            Minimum = 1,
            Maximum = 65535,
            Size = new Size(110, 28),
            Value = serverPort
        };
        serverPortBox.KeyDown += delegate(object sender, KeyEventArgs args)
        {
            if (args.KeyCode == Keys.Enter)
            {
                args.SuppressKeyPress = true;
                SaveServerPort();
            }
        };

        saveServerPortButton = CreateButton("Save Port");
        saveServerPortButton.Anchor = AnchorStyles.Top | AnchorStyles.Right;
        saveServerPortButton.Location = new Point(ClientSize.Width - 148, 207);
        saveServerPortButton.Click += delegate { SaveServerPort(); };

        mainTabs = new TabControl
        {
            Anchor = AnchorStyles.Top | AnchorStyles.Bottom | AnchorStyles.Left | AnchorStyles.Right,
            Location = new Point(22, 258),
            Size = new Size(ClientSize.Width - 44, ClientSize.Height - 280),
            Font = new Font("Segoe UI", 9, FontStyle.Bold)
        };

        var logTab = new TabPage("Logs")
        {
            BackColor = Color.FromArgb(9, 13, 18),
            ForeColor = Color.FromArgb(238, 245, 248)
        };

        var historyTab = new TabPage("History")
        {
            BackColor = Color.FromArgb(9, 13, 18),
            ForeColor = Color.FromArgb(238, 245, 248)
        };

        logBox = new TextBox
        {
            BackColor = Color.FromArgb(11, 17, 23),
            BorderStyle = BorderStyle.FixedSingle,
            Dock = DockStyle.Fill,
            ForeColor = Color.FromArgb(238, 245, 248),
            Font = new Font("Consolas", 10, FontStyle.Regular),
            Multiline = true,
            ReadOnly = true,
            ScrollBars = ScrollBars.Vertical,
            WordWrap = false
        };

        refreshHistoryButton = CreateButton("Refresh");
        refreshHistoryButton.Anchor = AnchorStyles.Top | AnchorStyles.Right;
        refreshHistoryButton.Location = new Point(historyTab.Width - 144, 10);
        refreshHistoryButton.Click += delegate { LoadRenameHistory(); };

        historyList = new ListView
        {
            Anchor = AnchorStyles.Top | AnchorStyles.Bottom | AnchorStyles.Left | AnchorStyles.Right,
            BackColor = Color.FromArgb(11, 17, 23),
            BorderStyle = BorderStyle.FixedSingle,
            ForeColor = Color.FromArgb(238, 245, 248),
            Font = new Font("Segoe UI", 9, FontStyle.Regular),
            FullRowSelect = true,
            GridLines = false,
            HeaderStyle = ColumnHeaderStyle.Nonclickable,
            Location = new Point(8, 56),
            Size = new Size(historyTab.ClientSize.Width - 16, historyTab.ClientSize.Height - 64),
            View = View.Details
        };
        historyList.Columns.Add("Time", 150);
        historyList.Columns.Add("File", 220);
        historyList.Columns.Add("Original name", 320);
        historyList.Columns.Add("Hash", 260);

        logTab.Controls.Add(logBox);
        historyTab.Controls.Add(refreshHistoryButton);
        historyTab.Controls.Add(historyList);
        historyTab.Resize += delegate { LayoutHistoryTab(historyTab); };
        mainTabs.TabPages.Add(logTab);
        mainTabs.TabPages.Add(historyTab);

        Controls.Add(header);
        Controls.Add(statusLabel);
        Controls.Add(openButton);
        Controls.Add(stopButton);
        Controls.Add(tmdbKeyStatus);
        Controls.Add(tmdbKeyBox);
        Controls.Add(saveTmdbKeyButton);
        Controls.Add(discordWebhookStatus);
        Controls.Add(discordWebhookBox);
        Controls.Add(saveDiscordWebhookButton);
        Controls.Add(serverPortLabel);
        Controls.Add(serverPortBox);
        Controls.Add(saveServerPortButton);
        Controls.Add(mainTabs);

        historyRefreshTimer = new Timer
        {
            Interval = 10000
        };
        historyRefreshTimer.Tick += delegate { LoadRenameHistory(); };

        Resize += delegate { LayoutControls(); };
        Load += delegate
        {
            UpdateTmdbKeyStatus();
            UpdateDiscordWebhookStatus();
            LoadRenameHistory();
            historyRefreshTimer.Start();
            StartServer();
        };
        FormClosing += delegate
        {
            historyRefreshTimer.Stop();
            StopServer();
        };
    }

    private Button CreateButton(string text)
    {
        return new Button
        {
            Text = text,
            Width = 126,
            Height = 38,
            BackColor = Color.FromArgb(229, 160, 13),
            FlatStyle = FlatStyle.Flat,
            Font = new Font("Segoe UI", 9, FontStyle.Bold),
            ForeColor = Color.Black
        };
    }

    private void LayoutControls()
    {
        openButton.Location = new Point(ClientSize.Width - 292, 24);
        stopButton.Location = new Point(ClientSize.Width - 148, 24);
        tmdbKeyBox.Size = new Size(ClientSize.Width - 190, 28);
        saveTmdbKeyButton.Location = new Point(ClientSize.Width - 148, 119);
        discordWebhookBox.Size = new Size(ClientSize.Width - 190, 28);
        saveDiscordWebhookButton.Location = new Point(ClientSize.Width - 148, 173);
        saveServerPortButton.Location = new Point(ClientSize.Width - 148, 207);
        mainTabs.Size = new Size(ClientSize.Width - 44, ClientSize.Height - 280);
        if (mainTabs.TabPages.Count > 1)
        {
            LayoutHistoryTab(mainTabs.TabPages[1]);
        }
    }

    private void LayoutHistoryTab(TabPage historyTab)
    {
        refreshHistoryButton.Location = new Point(historyTab.ClientSize.Width - 134, 10);
        historyList.Size = new Size(historyTab.ClientSize.Width - 16, historyTab.ClientSize.Height - 64);
        historyList.Columns[0].Width = 150;
        historyList.Columns[1].Width = Math.Max(180, historyList.ClientSize.Width / 5);
        historyList.Columns[2].Width = Math.Max(260, historyList.ClientSize.Width / 3);
        historyList.Columns[3].Width = Math.Max(180, historyList.ClientSize.Width / 5);
    }

    private int LoadConfiguredPort()
    {
        try
        {
            string configPath = Path.Combine(dataDir, "config.json");
            string sourcePath = File.Exists(configPath) ? configPath : Path.Combine(appDir, "config.example.json");
            if (!File.Exists(sourcePath))
            {
                return 8003;
            }

            var serializer = new JavaScriptSerializer();
            var config = serializer.Deserialize<Dictionary<string, object>>(File.ReadAllText(sourcePath));
            if (config.ContainsKey("server") && config["server"] is Dictionary<string, object>)
            {
                var server = (Dictionary<string, object>)config["server"];
                int configuredPort;
                if (server.ContainsKey("port") && int.TryParse(Convert.ToString(server["port"]), out configuredPort) && configuredPort >= 1 && configuredPort <= 65535)
                {
                    return configuredPort;
                }
            }
        }
        catch
        {
        }
        return 8003;
    }

    private void EnsureInitialConfig()
    {
        string configPath = Path.Combine(dataDir, "config.json");
        if (File.Exists(configPath))
        {
            return;
        }

        using (Stream source = Assembly.GetExecutingAssembly().GetManifestResourceStream("PlexRequesterConfigExample.json"))
        {
            if (source == null)
            {
                throw new InvalidOperationException("The embedded configuration template is missing.");
            }
            using (var target = new FileStream(configPath, FileMode.CreateNew, FileAccess.Write, FileShare.None))
            {
                source.CopyTo(target);
            }
        }
    }

    private string EnsureBackendExecutable()
    {
        string runtimeDir = Path.Combine(dataDir, "runtime");
        Directory.CreateDirectory(runtimeDir);
        string backendPath = Path.Combine(runtimeDir, "PlexRequesterBackend.exe");
        string temporaryPath = backendPath + ".new";

        using (Stream source = Assembly.GetExecutingAssembly().GetManifestResourceStream("PlexRequesterBackend.exe"))
        {
            if (source == null)
            {
                throw new InvalidOperationException("The embedded Plex Requester backend is missing.");
            }
            using (var target = new FileStream(temporaryPath, FileMode.Create, FileAccess.Write, FileShare.None))
            {
                source.CopyTo(target);
            }
        }

        bool replace = !File.Exists(backendPath) || !FilesMatch(temporaryPath, backendPath);
        if (replace)
        {
            File.Copy(temporaryPath, backendPath, true);
        }
        File.Delete(temporaryPath);
        return backendPath;
    }

    private static bool FilesMatch(string firstPath, string secondPath)
    {
        var firstInfo = new FileInfo(firstPath);
        var secondInfo = new FileInfo(secondPath);
        if (firstInfo.Length != secondInfo.Length)
        {
            return false;
        }
        using (SHA256 algorithm = SHA256.Create())
        using (FileStream first = File.OpenRead(firstPath))
        using (FileStream second = File.OpenRead(secondPath))
        {
            byte[] firstHash = algorithm.ComputeHash(first);
            byte[] secondHash = algorithm.ComputeHash(second);
            return StructuralComparisons.StructuralEqualityComparer.Equals(firstHash, secondHash);
        }
    }

    private void StartServer()
    {
        string backendPath;
        try
        {
            backendPath = EnsureBackendExecutable();
        }
        catch (Exception ex)
        {
            AppendLog("Could not prepare the standalone backend: " + ex.Message);
            SetStatus("Backend preparation failed.");
            stopButton.Text = "Close";
            return;
        }

        var start = new ProcessStartInfo
        {
            FileName = backendPath,
            Arguments = "",
            WorkingDirectory = dataDir,
            UseShellExecute = false,
            CreateNoWindow = true,
            RedirectStandardOutput = true,
            RedirectStandardError = true
        };
        start.EnvironmentVariables["APP_PORT"] = serverPort.ToString();
        start.EnvironmentVariables["PLEX_REQUESTER_PARENT_PID"] = Process.GetCurrentProcess().Id.ToString();

        try
        {
            AppendLog("Plex Requester");
            AppendLog("Serving at http://127.0.0.1:" + serverPort);
            AppendLog("Close this window to stop the server.");
            AppendLog("");

            serverProcess = Process.Start(start);
            if (serverProcess == null)
            {
                AppendLog("Python did not start.");
                SetStatus("Python did not start.");
                return;
            }

            serverProcess.EnableRaisingEvents = true;
            serverProcess.OutputDataReceived += delegate(object sender, DataReceivedEventArgs args) { AppendLog(args.Data); };
            serverProcess.ErrorDataReceived += delegate(object sender, DataReceivedEventArgs args) { AppendLog(args.Data); };
            serverProcess.Exited += delegate
            {
                if (IsDisposed || !IsHandleCreated)
                {
                    return;
                }

                BeginInvoke((Action)delegate
                {
                    if (!stopping)
                    {
                        SetStatus("Server stopped.");
                        stopButton.Text = "Close";
                    }
                });
            };
            serverProcess.BeginOutputReadLine();
            serverProcess.BeginErrorReadLine();
            SetStatus("Server running at http://127.0.0.1:" + serverPort);
        }
        catch (Exception ex)
        {
            AppendLog(ex.ToString());
            SetStatus("Server failed to start.");
            stopButton.Text = "Close";
        }
    }

    private void StopServer()
    {
        stopping = true;
        SetStatus("Stopping server...");
        KillServerProcess();
    }

    private void RestartServer()
    {
        bool wasRunning = serverProcess != null && !serverProcess.HasExited;
        if (!wasRunning)
        {
            return;
        }

        stopping = true;
        SetStatus("Restarting server...");
        KillServerProcess();
        stopping = false;
        serverProcess = null;
        StartServer();
    }

    private void KillServerProcess()
    {
        try
        {
            if (serverProcess != null && !serverProcess.HasExited)
            {
                serverProcess.Kill();
                serverProcess.WaitForExit(1500);
            }
        }
        catch (Exception ex)
        {
            AppendLog(ex.Message);
        }
    }

    private void SaveTmdbKey()
    {
        string key = tmdbKeyBox.Text.Trim();
        if (key.Length == 0)
        {
            AppendLog("Paste a TMDb API key before saving.");
            return;
        }

        try
        {
            string configPath = Path.Combine(dataDir, "config.json");
            string sourcePath = File.Exists(configPath) ? configPath : Path.Combine(appDir, "config.example.json");
            var serializer = new JavaScriptSerializer();
            serializer.MaxJsonLength = int.MaxValue;
            Dictionary<string, object> config;

            if (File.Exists(sourcePath))
            {
                config = serializer.Deserialize<Dictionary<string, object>>(File.ReadAllText(sourcePath));
            }
            else
            {
                config = new Dictionary<string, object>();
            }

            var tmdb = new Dictionary<string, object>();
            if (config.ContainsKey("tmdb") && config["tmdb"] is Dictionary<string, object>)
            {
                tmdb = (Dictionary<string, object>)config["tmdb"];
            }
            tmdb["apiKey"] = key;
            config["tmdb"] = tmdb;

            File.WriteAllText(configPath, serializer.Serialize(config));
            tmdbKeyBox.Text = "";
            UpdateTmdbKeyStatus();
            AppendLog("TMDb API key saved to config.json.");
            RestartServer();
        }
        catch (Exception ex)
        {
            AppendLog("Could not save TMDb API key: " + ex.Message);
        }
    }

    private void SaveDiscordWebhook()
    {
        string webhookUrl = discordWebhookBox.Text.Trim();

        try
        {
            string configPath = Path.Combine(dataDir, "config.json");
            string sourcePath = File.Exists(configPath) ? configPath : Path.Combine(appDir, "config.example.json");
            var serializer = new JavaScriptSerializer();
            serializer.MaxJsonLength = int.MaxValue;
            Dictionary<string, object> config;

            if (File.Exists(sourcePath))
            {
                config = serializer.Deserialize<Dictionary<string, object>>(File.ReadAllText(sourcePath));
            }
            else
            {
                config = new Dictionary<string, object>();
            }

            var notifications = new Dictionary<string, object>();
            if (config.ContainsKey("notifications") && config["notifications"] is Dictionary<string, object>)
            {
                notifications = (Dictionary<string, object>)config["notifications"];
            }
            notifications["discordWebhookUrl"] = webhookUrl;
            config["notifications"] = notifications;

            File.WriteAllText(configPath, serializer.Serialize(config));
            discordWebhookBox.Text = "";
            UpdateDiscordWebhookStatus();
            AppendLog(webhookUrl.Length > 0 ? "Discord webhook saved to config.json." : "Discord webhook cleared.");
            RestartServer();
        }
        catch (Exception ex)
        {
            AppendLog("Could not save Discord webhook: " + ex.Message);
        }
    }

    private void SaveServerPort()
    {
        int selectedPort = Decimal.ToInt32(serverPortBox.Value);
        try
        {
            string configPath = Path.Combine(dataDir, "config.json");
            string sourcePath = File.Exists(configPath) ? configPath : Path.Combine(appDir, "config.example.json");
            var serializer = new JavaScriptSerializer();
            serializer.MaxJsonLength = int.MaxValue;
            Dictionary<string, object> config;

            if (File.Exists(sourcePath))
            {
                config = serializer.Deserialize<Dictionary<string, object>>(File.ReadAllText(sourcePath));
            }
            else
            {
                config = new Dictionary<string, object>();
            }

            var server = new Dictionary<string, object>();
            if (config.ContainsKey("server") && config["server"] is Dictionary<string, object>)
            {
                server = (Dictionary<string, object>)config["server"];
            }
            server["port"] = selectedPort;
            config["server"] = server;

            File.WriteAllText(configPath, serializer.Serialize(config));
            serverPort = selectedPort;
            AppendLog("Server / Tailscale port saved: " + serverPort);
            RestartServer();
        }
        catch (Exception ex)
        {
            AppendLog("Could not save server port: " + ex.Message);
            serverPortBox.Value = serverPort;
        }
    }

    private void UpdateTmdbKeyStatus()
    {
        try
        {
            string configPath = Path.Combine(dataDir, "config.json");
            if (!File.Exists(configPath))
            {
                tmdbKeyStatus.Text = "TMDb key: not configured";
                return;
            }

            var serializer = new JavaScriptSerializer();
            var config = serializer.Deserialize<Dictionary<string, object>>(File.ReadAllText(configPath));
            bool configured = false;
            if (config.ContainsKey("tmdb") && config["tmdb"] is Dictionary<string, object>)
            {
                var tmdb = (Dictionary<string, object>)config["tmdb"];
                configured = tmdb.ContainsKey("apiKey") && Convert.ToString(tmdb["apiKey"]).Trim().Length > 0;
            }
            tmdbKeyStatus.Text = configured ? "TMDb key: configured" : "TMDb key: not configured";
        }
        catch
        {
            tmdbKeyStatus.Text = "TMDb key: config could not be read";
        }
    }

    private void UpdateDiscordWebhookStatus()
    {
        try
        {
            string configPath = Path.Combine(dataDir, "config.json");
            if (!File.Exists(configPath))
            {
                discordWebhookStatus.Text = "Discord: not configured";
                return;
            }

            var serializer = new JavaScriptSerializer();
            var config = serializer.Deserialize<Dictionary<string, object>>(File.ReadAllText(configPath));
            bool configured = false;
            if (config.ContainsKey("notifications") && config["notifications"] is Dictionary<string, object>)
            {
                var notifications = (Dictionary<string, object>)config["notifications"];
                configured = notifications.ContainsKey("discordWebhookUrl") && Convert.ToString(notifications["discordWebhookUrl"]).Trim().Length > 0;
            }
            discordWebhookStatus.Text = configured ? "Discord: configured" : "Discord: not configured";
        }
        catch
        {
            discordWebhookStatus.Text = "Discord: config could not be read";
        }
    }

    private void LoadRenameHistory()
    {
        if (IsDisposed || !IsHandleCreated)
        {
            return;
        }

        if (historyList.InvokeRequired)
        {
            BeginInvoke((Action)(() => LoadRenameHistory()));
            return;
        }

        historyList.BeginUpdate();
        historyList.Items.Clear();

        try
        {
            if (!File.Exists(renameHistoryPath))
            {
                var empty = new ListViewItem("No history yet.");
                empty.SubItems.Add("");
                empty.SubItems.Add("");
                empty.SubItems.Add("");
                historyList.Items.Add(empty);
                return;
            }

            var serializer = new JavaScriptSerializer();
            string[] lines = File.ReadAllLines(renameHistoryPath);
            int shown = 0;

            for (int index = lines.Length - 1; index >= 0 && shown < 200; index--)
            {
                string line = lines[index].Trim();
                if (line.Length == 0)
                {
                    continue;
                }

                Dictionary<string, object> item;
                try
                {
                    item = serializer.Deserialize<Dictionary<string, object>>(line);
                }
                catch
                {
                    continue;
                }

                string oldPath = ValueText(item, "originalPath");
                string newPath = ValueText(item, "newPath");
                string hash = ValueText(item, "hash");
                string time = FormatUnixTime(ValueText(item, "time"));

                var row = new ListViewItem(time);
                row.SubItems.Add(FileName(newPath));
                row.SubItems.Add(FileName(oldPath));
                row.SubItems.Add(hash);
                historyList.Items.Add(row);
                shown++;
            }

            if (shown == 0)
            {
                var empty = new ListViewItem("No history yet.");
                empty.SubItems.Add("");
                empty.SubItems.Add("");
                empty.SubItems.Add("");
                historyList.Items.Add(empty);
            }
        }
        catch (Exception ex)
        {
            var row = new ListViewItem("Could not read history.");
            row.SubItems.Add("");
            row.SubItems.Add(ex.Message);
            row.SubItems.Add("");
            historyList.Items.Add(row);
        }
        finally
        {
            historyList.EndUpdate();
        }
    }

    private string ValueText(Dictionary<string, object> item, string key)
    {
        if (!item.ContainsKey(key) || item[key] == null)
        {
            return "";
        }
        return Convert.ToString(item[key]);
    }

    private string FormatUnixTime(string value)
    {
        long seconds;
        if (!long.TryParse(value, out seconds) || seconds <= 0)
        {
            return "";
        }
        try
        {
            DateTime timestamp = new DateTime(1970, 1, 1, 0, 0, 0, DateTimeKind.Utc)
                .AddSeconds(seconds)
                .ToLocalTime();
            return timestamp.ToString("g");
        }
        catch
        {
            return "";
        }
    }

    private string FileName(string path)
    {
        if (String.IsNullOrWhiteSpace(path))
        {
            return "";
        }

        string normalized = path.Replace('\\', '/');
        int slash = normalized.LastIndexOf('/');
        return slash >= 0 ? normalized.Substring(slash + 1) : normalized;
    }

    private void OpenWebsite()
    {
        try
        {
            Process.Start(new ProcessStartInfo
            {
                FileName = "http://127.0.0.1:" + serverPort,
                UseShellExecute = true
            });
        }
        catch (Exception ex)
        {
            AppendLog(ex.Message);
        }
    }

    private void SetStatus(string text)
    {
        if (IsDisposed || !IsHandleCreated)
        {
            return;
        }

        if (statusLabel.InvokeRequired)
        {
            BeginInvoke((Action)(() => SetStatus(text)));
            return;
        }
        statusLabel.Text = text;
    }

    private void AppendLog(string line)
    {
        if (line == null)
        {
            return;
        }

        if (IsDisposed || !IsHandleCreated)
        {
            return;
        }

        if (logBox.InvokeRequired)
        {
            BeginInvoke((Action)(() => AppendLog(line)));
            return;
        }

        string entry = line + Environment.NewLine;
        logBox.AppendText(entry);
        try
        {
            File.AppendAllText(logPath, entry);
        }
        catch
        {
        }
    }
}
