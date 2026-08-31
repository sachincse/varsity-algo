"""Port pre-flight, and open the browser only once the server answers.

Both launchers use this, so Windows and Unix behave identically.

Two problems it solves, both found by running start.bat on a clean clone:

1. The launchers opened the browser immediately, then started uvicorn. uvicorn
   needs a second or two to bind, so the first thing a new user saw was a
   connection-refused page — for a tool whose entire pitch is "double-click and
   it opens". start.sh slept two seconds and hoped; that is a guess, not a
   check.

2. If something already held port 8000, uvicorn died with
   "[Errno 10048] error while attempting to bind on address" and the window
   closed. The overwhelmingly likely cause is the app already running in
   another window, which that message never mentions.

Standard library only — this runs before requirements.txt is guaranteed
installed.
"""
from __future__ import annotations

import argparse
import socket
import sys
import time
import webbrowser

HOST = "127.0.0.1"


def is_listening(host: str, port: int, timeout: float = 0.35) -> bool:
    """True if something already accepts connections on this port."""
    try:
        with socket.create_connection((host, port), timeout):
            return True
    except OSError:
        return False


def can_bind(host: str, port: int) -> bool:
    """True if a server could take this port right now.

    Checked by binding rather than by connecting: a port held by another
    process refuses a connection while still preventing a bind, and connecting
    alone would call that free and hand the user the errno this exists to avoid.

    SO_REUSEADDR is set because UVICORN SETS IT. Without it this check is
    stricter than the server it is guarding: stop the app and start it again
    within a minute and the old socket is still in TIME_WAIT, so a plain bind
    fails even though uvicorn would have started fine. That turned an ordinary
    restart into a refusal, and CI caught it doing exactly that — the second
    launcher run died on a port the first run had already released.

    The check must model the real bind, not a stricter one.
    """
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        s.bind((host, port))
        return True
    except OSError:
        return False
    finally:
        s.close()


def explain_busy(port: int) -> str:
    ours = is_listening(HOST, port)
    lines = [f"  [X] Port {port} is already in use."]
    if ours:
        lines += [
            "",
            "      Something is already answering there. Almost always this is",
            "      varsity-algo itself, still running in another window.",
            "",
            f"      Open http://{HOST}:{port} - if the dashboard loads, you are",
            "      already running and can just use that window.",
        ]
    else:
        lines += [
            "",
            "      The port is held but not answering, so it is probably a",
            "      half-dead process rather than the app.",
        ]
    lines += [
        "",
        "      To find what is holding it:",
        f"        Windows   netstat -ano | findstr :{port}",
        "                  taskkill /F /PID <the number in the last column>",
        f"        macOS/Linux   lsof -i :{port}",
        "                      kill <pid>",
        "",
        "      Note: the redirect URL registered with your Kite Connect app",
        f"      points at port {port}, so moving to another port means editing",
        "      the app at developers.kite.trade to match.",
    ]
    return "\n".join(lines)


def wait_then_open(port: int, timeout: float) -> int:
    """Poll until the server answers, then open the browser.

    Runs in the background while uvicorn starts in the foreground, so a slow
    import or a cold virtualenv delays the browser rather than greeting the
    user with an error page.
    """
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if is_listening(HOST, port):
            try:
                webbrowser.open(f"http://{HOST}:{port}")
            except Exception:
                # No browser, no DISPLAY, headless CI. The server is up and the
                # URL is already on screen, so this is not worth a traceback in
                # the middle of the launcher's output.
                pass
            return 0
        time.sleep(0.25)
    # Silent by design: the server failed to start, and uvicorn is already
    # printing the real reason in the foreground. A second complaint from a
    # background helper would only bury it.
    return 1


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--port", type=int, default=8000)
    ap.add_argument("--check", action="store_true",
                    help="exit non-zero, with an explanation, if the port is taken")
    ap.add_argument("--open", action="store_true",
                    help="wait for the server to answer, then open a browser")
    ap.add_argument("--timeout", type=float, default=90.0,
                    help="how long --open waits before giving up")
    args = ap.parse_args()

    if args.check:
        if can_bind(HOST, args.port):
            return 0
        print(explain_busy(args.port))
        return 1

    if args.open:
        return wait_then_open(args.port, args.timeout)

    ap.print_help()
    return 2


if __name__ == "__main__":
    sys.exit(main())
