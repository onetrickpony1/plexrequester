$ErrorActionPreference = "Stop"

$appDir = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $appDir
$dataDir = Join-Path $env:LOCALAPPDATA "Plex Requester"
$configPath = Join-Path $dataDir "config.json"

New-Item -ItemType Directory -Path $dataDir -Force | Out-Null
if (-not (Test-Path $configPath)) {
  if (Test-Path "$appDir\config.json") {
    Copy-Item "$appDir\config.json" $configPath
    Write-Host "Migrated config.json to $configPath."
  } else {
    Copy-Item "$appDir\config.example.json" $configPath
    Write-Host "Created $configPath from config.example.json. Edit it with your qBittorrent credentials and destination paths."
  }
}

python "$appDir\server.py"
