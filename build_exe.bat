@echo off
setlocal EnableExtensions

cd /d "%~dp0"

set "SOURCE=PlexRequesterLauncher.cs"
set "BACKEND_SOURCE=server.py"
set "ICON=PlexRequesterIcon.ico"
set "OUTPUT=Plex Requester.exe"
set "TEMP_OUTPUT=Plex Requester.build.exe"
set "DIST_DIR=.standalone-dist"
set "WORK_DIR=.standalone-build"
set "BACKEND_OUTPUT=%DIST_DIR%\PlexRequesterBackend.exe"
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
  echo ERROR: Required launcher source is missing: %SOURCE%
  exit /b 1
)
if not exist "%BACKEND_SOURCE%" (
  echo ERROR: Required backend source is missing: %BACKEND_SOURCE%
  exit /b 1
)
if not exist "static\index.html" (
  echo ERROR: Required web assets are missing from static\
  exit /b 1
)
if not exist "config.example.json" (
  echo ERROR: Required safe configuration template is missing: config.example.json
  exit /b 1
)
if not exist "%ICON%" (
  echo ERROR: Required icon is missing: %ICON%
  exit /b 1
)

echo Running automated pre-build checks...
python -m compileall -q "%BACKEND_SOURCE%" plex_requester test_server.py
if errorlevel 1 (
  echo ERROR: Python syntax checks failed. The existing release executable was not changed.
  exit /b 1
)
python -m unittest -v
if errorlevel 1 (
  echo ERROR: Automated backend tests failed. The existing release executable was not changed.
  exit /b 1
)

python -m PyInstaller --version >nul 2>&1
if errorlevel 1 (
  echo ERROR: PyInstaller is not installed for this Python interpreter.
  echo Install it with: python -m pip install pyinstaller
  exit /b 1
)

if exist "%DIST_DIR%" rmdir /s /q "%DIST_DIR%"
if exist "%WORK_DIR%" rmdir /s /q "%WORK_DIR%"
if exist "%TEMP_OUTPUT%" del /q "%TEMP_OUTPUT%"

echo Packaging the Python backend and web assets...
python -m PyInstaller --noconfirm --clean --onefile --console --name "PlexRequesterBackend" --add-data "%CD%\static;static" --add-data "%CD%\config.example.json;." --distpath "%DIST_DIR%" --workpath "%WORK_DIR%" --specpath "%WORK_DIR%" "%CD%\%BACKEND_SOURCE%"
if errorlevel 1 (
  echo.
  echo ERROR: Backend packaging failed. %OUTPUT% was not changed.
  exit /b 1
)
if not exist "%BACKEND_OUTPUT%" (
  echo ERROR: PyInstaller reported success but did not create the standalone backend.
  exit /b 1
)
for %%I in ("%BACKEND_OUTPUT%") do if %%~zI LEQ 0 (
  echo ERROR: The packaged backend is empty.
  exit /b 1
)

echo Compiling the native launcher with the backend embedded...
"%CSC%" /nologo /target:winexe /optimize+ /warn:4 /warnaserror+ /out:"%TEMP_OUTPUT%" /win32icon:"%ICON%" /resource:"%BACKEND_OUTPUT%",PlexRequesterBackend.exe /resource:"config.example.json",PlexRequesterConfigExample.json /reference:System.dll /reference:System.Drawing.dll /reference:System.Windows.Forms.dll /reference:System.Web.Extensions.dll "%SOURCE%"
if errorlevel 1 (
  echo.
  echo ERROR: Launcher compilation failed. %OUTPUT% was not changed.
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
echo This one executable includes the native launcher, Python runtime, backend, and web assets.
exit /b 0
