@echo off
REM Double-click this to start both servers in their own windows.
REM Each window has its own log and its own Ctrl+C, so when something breaks
REM it is obvious which half broke.
start "varsity-algo API" cmd /k "cd /d %~dp0 && .venv\Scripts\activate.bat && python -m uvicorn server.main:app --reload --port 8000"
timeout /t 3 /nobreak >nul
start "varsity-algo WEB" cmd /k "cd /d %~dp0web && npm run dev"
echo.
echo   Backend  http://127.0.0.1:8000
echo   Frontend http://localhost:5173   <-- open this one
echo.
echo   Close both windows to stop.
timeout /t 8
