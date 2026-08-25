@echo off
REM ===========================================================================
REM  varsity-algo  -  one-step start for Windows
REM
REM  Double-click this file. It checks what you have, installs what is missing,
REM  builds the app, and opens it in your browser.
REM
REM  Safe to run again any time. Everything after the first run is fast.
REM ===========================================================================
setlocal EnableDelayedExpansion
cd /d "%~dp0"
title varsity-algo

echo.
echo   varsity-algo
echo   ============
echo.

REM --- Python ---------------------------------------------------------------
where python >nul 2>&1
if errorlevel 1 (
  echo   [X] Python is not installed, or not on your PATH.
  echo.
  echo       Install Python 3.11 or newer from:
  echo         https://www.python.org/downloads/
  echo.
  echo       IMPORTANT: on the first installer screen, tick
  echo         "Add python.exe to PATH"
  echo       Then close this window and run start.bat again.
  echo.
  pause
  exit /b 1
)
for /f "tokens=2" %%v in ('python --version 2^>^&1') do set PYVER=%%v
echo   [ok] Python !PYVER!

REM --- virtual environment --------------------------------------------------
if not exist ".venv\Scripts\python.exe" (
  echo   [..] creating virtual environment
  python -m venv .venv
  if errorlevel 1 (
    echo   [X] Could not create the virtual environment.
    echo       Try running:  python -m pip install --upgrade virtualenv
    pause
    exit /b 1
  )
)
set PY=.venv\Scripts\python.exe
echo   [ok] virtual environment

REM --- python packages ------------------------------------------------------
REM  A marker file records which requirements.txt we installed, so a re-run is
REM  instant unless the file actually changed.
set NEED_PIP=1
if exist ".venv\.installed" (
  for /f %%a in ('certutil -hashfile requirements.txt MD5 ^| find /v ":" ^| find /v "CertUtil"') do set REQHASH=%%a
  set /p OLDHASH=<.venv\.installed
  if "!REQHASH!"=="!OLDHASH!" set NEED_PIP=0
)
if "!NEED_PIP!"=="1" (
  echo   [..] installing Python packages ^(a few minutes the first time^)
  %PY% -m pip install --upgrade pip --quiet
  %PY% -m pip install -r requirements.txt --quiet
  if errorlevel 1 (
    echo   [X] Installing Python packages failed.
    echo       Scroll up for the real error. The usual cause is no internet,
    echo       or a corporate proxy blocking pypi.org
    pause
    exit /b 1
  )
  for /f %%a in ('certutil -hashfile requirements.txt MD5 ^| find /v ":" ^| find /v "CertUtil"') do echo %%a> .venv\.installed
)
echo   [ok] Python packages

REM --- frontend -------------------------------------------------------------
REM  Node is only needed to BUILD the dashboard. If a build already exists, or
REM  Node is missing, we fall back to the API-only mode rather than failing.
if exist "web\dist\index.html" goto :haveweb

where npm >nul 2>&1
if errorlevel 1 (
  echo   [!] Node.js not found - skipping the dashboard build.
  echo       The app will still run, but only the API at /docs.
  echo       Install Node 20.19+ or 22.12+ from https://nodejs.org/
  echo       then run start.bat again.
  goto :haveweb
)
echo   [..] building the dashboard ^(first time only^)
pushd web
call npm install --silent --no-audit --no-fund
if errorlevel 1 (
  echo   [X] npm install failed. Scroll up for the error.
  popd
  pause
  exit /b 1
)
call npm run build
if errorlevel 1 (
  echo   [X] The dashboard build failed. Scroll up for the error.
  popd
  pause
  exit /b 1
)
popd
:haveweb
if exist "web\dist\index.html" (echo   [ok] dashboard) else (echo   [!] dashboard not built - API only)

REM --- .env -----------------------------------------------------------------
if not exist ".env" (
  copy /y ".env.example" ".env" >nul
  echo   [ok] created .env  ^(edit it later to add keys^)
)

REM --- go -------------------------------------------------------------------
echo.
echo   Starting. Your browser will open in a moment.
echo   Leave this window open. Press Ctrl+C here to stop.
echo.
start "" http://127.0.0.1:8000
%PY% -m uvicorn server.main:app --port 8000

echo.
echo   Server stopped.
pause
