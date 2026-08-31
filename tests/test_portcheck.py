"""The port pre-flight must model the real bind, not a stricter one.

A guard that refuses more than the thing it guards is a bug wearing a safety
jacket. This one shipped that way: it tested bindability WITHOUT SO_REUSEADDR
while uvicorn sets it, so a socket still in TIME_WAIT — the completely normal
state a second after you stop the app — read as "port in use" and the launcher
refused to start. CI found it by restarting the app the way a person would.

Both directions matter and each would pass a test that only checked the other:

  * a LISTENING port must be refused, or the pre-flight is useless and the user
    gets the raw errno it exists to replace;
  * a just-CLOSED port must be accepted, or an ordinary restart is blocked.
"""
from __future__ import annotations

import socket
import subprocess
import sys
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parent.parent / "tools" / "portcheck.py"


def check(port: int) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(SCRIPT), "--port", str(port), "--check"],
        capture_output=True, text=True, timeout=60)


@pytest.fixture
def listening():
    """A real listening socket on an OS-assigned port."""
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    s.listen(1)
    yield s.getsockname()[1]
    s.close()


def free_port() -> int:
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    p = s.getsockname()[1]
    s.close()
    return p


def test_a_listening_port_is_refused(listening):
    r = check(listening)
    assert r.returncode != 0
    assert "already in use" in r.stdout


def test_the_message_names_the_port(listening):
    """A pre-flight that says 'a port is busy' without saying which one is
    barely better than the errno."""
    assert str(listening) in check(listening).stdout


def test_a_free_port_is_accepted():
    r = check(free_port())
    assert r.returncode == 0, r.stdout


def test_restarting_immediately_after_stopping_is_allowed():
    """The regression this file exists for.

    Bind, listen, close — which is exactly what stopping the server does — then
    immediately ask whether the port is usable. uvicorn sets SO_REUSEADDR so it
    would start fine; the check must agree, or it blocks a restart that would
    have worked.
    """
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.listen(1)
    s.close()

    r = check(port)
    assert r.returncode == 0, (
        "a port that was just released must be usable again — the check is "
        f"stricter than uvicorn:\n{r.stdout}")


def test_the_two_cases_are_actually_distinguished(listening):
    """Guards against 'always refuse' and 'always accept', either of which
    would satisfy one of the tests above on its own."""
    busy = check(listening).returncode
    idle = check(free_port()).returncode
    assert busy != 0 and idle == 0, (
        f"busy={busy} idle={idle} — the check is not discriminating")
