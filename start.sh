#!/usr/bin/env bash
# ===========================================================================
#  varsity-algo  -  one-step start for macOS and Linux
#
#    chmod +x start.sh && ./start.sh
#
#  Checks what you have, installs what is missing, builds the app, runs it.
#  Safe to re-run. Everything after the first run is fast.
# ===========================================================================
set -uo pipefail
cd "$(dirname "$0")"

say()  { printf '  %s\n' "$*"; }
ok()   { printf '  \033[32m[ok]\033[0m %s\n' "$*"; }
work() { printf '  \033[36m[..]\033[0m %s\n' "$*"; }
warn() { printf '  \033[33m[!]\033[0m  %s\n' "$*"; }
die()  { printf '  \033[31m[X]\033[0m  %s\n' "$*"; exit 1; }

echo
echo "  varsity-algo"
echo "  ============"
echo

# --- Python ---------------------------------------------------------------
PYBIN=""
for c in python3.12 python3.11 python3 python; do
  if command -v "$c" >/dev/null 2>&1; then
    v=$("$c" -c 'import sys;print(sys.version_info>=(3,11))' 2>/dev/null || echo False)
    [ "$v" = "True" ] && { PYBIN="$c"; break; }
  fi
done
[ -n "$PYBIN" ] || die "Python 3.11+ not found. Install it from https://www.python.org/downloads/"
ok "Python $("$PYBIN" -c 'import sys;print(".".join(map(str,sys.version_info[:3])))')"

# --- virtual environment --------------------------------------------------
if [ ! -x ".venv/bin/python" ]; then
  work "creating virtual environment"
  "$PYBIN" -m venv .venv || die "Could not create the virtual environment. On Debian/Ubuntu: sudo apt install python3-venv"
fi
PY=".venv/bin/python"
ok "virtual environment"

# --- python packages ------------------------------------------------------
# A hash marker means a re-run is instant unless requirements.txt changed.
REQHASH=$( (shasum -a 256 requirements.txt 2>/dev/null || sha256sum requirements.txt) | cut -d' ' -f1 )
if [ ! -f ".venv/.installed" ] || [ "$(cat .venv/.installed)" != "$REQHASH" ]; then
  work "installing Python packages (a few minutes the first time)"
  "$PY" -m pip install --upgrade pip --quiet
  "$PY" -m pip install -r requirements.txt --quiet \
    || die "Installing Python packages failed. Scroll up for the real error."
  echo "$REQHASH" > .venv/.installed
fi
ok "Python packages"

# --- frontend -------------------------------------------------------------
if [ ! -f "web/dist/index.html" ]; then
  if command -v npm >/dev/null 2>&1; then
    work "building the dashboard (first time only)"
    ( cd web && npm install --silent --no-audit --no-fund && npm run build ) \
      || die "The dashboard build failed. Scroll up for the error."
  else
    warn "Node.js not found - skipping the dashboard build."
    warn "The app will still run, but only the API at /docs."
    warn "Install Node 20.19+ or 22.12+ from https://nodejs.org/ and re-run."
  fi
fi
[ -f "web/dist/index.html" ] && ok "dashboard" || warn "dashboard not built - API only"

# --- .env -----------------------------------------------------------------
[ -f .env ] || { cp .env.example .env; ok "created .env  (edit it later to add keys)"; }

# --- go -------------------------------------------------------------------
echo
say "Open  http://127.0.0.1:8000"
say "Press Ctrl+C to stop."
echo
( sleep 2; (command -v open >/dev/null && open http://127.0.0.1:8000) \
        || (command -v xdg-open >/dev/null && xdg-open http://127.0.0.1:8000) ) >/dev/null 2>&1 &
exec "$PY" -m uvicorn server.main:app --port 8000
