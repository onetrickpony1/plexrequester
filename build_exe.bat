@echo off
setlocal EnableExtensions

cd /d "%~dp0"

set "SOURCE=PlexRequesterLauncher.cs"
set "ICON=PlexRequesterIcon.ico"
set "OUTPUT=Plex Requester.exe"
set "TEMP_OUTPUT=Plex Requester.build.exe"
set "CSC=%WINDIR%\Microsoft.NET\Framework64\v4.0.30319\csc.exe"
set "VERSION="

for /f "usebackq delims=" %%V in (`powershell.exe -NoProfile -ExecutionPolicy Bypass -Command "$path=$env:APP_CONFIG; if ([string]::IsNullOrWhiteSpace($path)) { $path=Join-Path $env:LOCALAPPDATA 'Plex Requester\config.json' } elseif (-not [IO.Path]::IsPathRooted($path)) { $path=Join-Path (Get-Location) $path }; if (Test-Path -LiteralPath $path) { try { $value=[string](ConvertFrom-Json -InputObject ([IO.File]::ReadAllText($path))).app.version; if ($value -match '^v?([0-9]+\.[0-9]+)$') { Write-Output ('v'+$Matches[1]) } } catch {} }"`) do set "VERSION=%%V"

if defined VERSION (
  set "OUTPUT=Plex Requester_%VERSION%.exe"
  echo Using configured app version: %VERSION%
) else (
  echo No valid app version found. Building without a version suffix.
)

if not exist "%CSC%" set "CSC=%WINDIR%\Microsoft.NET\Framework\v4.0.30319\csc.exe"

if not exist "%CSC%" (
  echo ERROR: The .NET Framework C# compiler could not be found.
  echo Install or enable .NET Framework 4.x, then run this file again.
  exit /b 1
)

if not exist "%SOURCE%" (
  echo ERROR: Required source file is missing: %SOURCE%
  exit /b 1
)

if not exist "%ICON%" (
  echo ERROR: Required icon file is missing: %ICON%
  exit /b 1
)

if exist "%TEMP_OUTPUT%" del /q "%TEMP_OUTPUT%"

echo Compiling %SOURCE%...
"%CSC%" /nologo /target:winexe /optimize+ /warn:4 /warnaserror+ /out:"%TEMP_OUTPUT%" /win32icon:"%ICON%" /reference:System.dll /reference:System.Drawing.dll /reference:System.Windows.Forms.dll /reference:System.Web.Extensions.dll "%SOURCE%"

if errorlevel 1 (
  echo.
  echo ERROR: Compilation failed. %OUTPUT% was not changed.
  if exist "%TEMP_OUTPUT%" del /q "%TEMP_OUTPUT%"
  exit /b 1
)

if not exist "%TEMP_OUTPUT%" (
  echo ERROR: The compiler reported success but did not create an executable.
  exit /b 1
)

for %%I in ("%TEMP_OUTPUT%") do if %%~zI LEQ 0 (
  echo ERROR: The generated executable is empty.
  del /q "%TEMP_OUTPUT%"
  exit /b 1
)

move /y "%TEMP_OUTPUT%" "%OUTPUT%" >nul
if errorlevel 1 (
  echo ERROR: Could not replace %OUTPUT%. Close it if it is currently running.
  if exist "%TEMP_OUTPUT%" del /q "%TEMP_OUTPUT%"
  exit /b 1
)

for %%I in ("%OUTPUT%") do echo Build succeeded: %%~fI ^(%%~zI bytes^)
exit /b 0
