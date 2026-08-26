"""What the settings panel claims must match what the app will actually do.

Both bugs pinned here were found by reading the running app's own /api/config
rather than by reasoning about the code, and both made the UI state something
false with total confidence. That is the worst failure mode for a settings
screen, so they get tests.
"""
from __future__ import annotations

import pytest

from server.llm.registry import CATALOG, survey
from server.price_source import resolve


# --------------------------------------------------------------------------
# LLM_MODEL is scoped to the provider you are using
# --------------------------------------------------------------------------

def test_model_override_applies_only_to_the_active_provider(monkeypatch):
    """LLM_MODEL used to be pasted onto all twelve rows.

    Setting a local model made the panel report that Anthropic runs
    'qwen2.5:7b' and that Groq runs 'qwen2.5:7b' — neither of which could
    possibly be true, and both of which appear on the screen the tutorial
    tells people to check when something is misconfigured.
    """
    monkeypatch.setenv("LLM_PROVIDER", "ollama")
    monkeypatch.setenv("LLM_MODEL", "qwen2.5:7b")

    rows = {r["key"]: r["model"] for r in survey()}

    assert rows["ollama"] == "qwen2.5:7b"
    assert rows["anthropic"] == CATALOG["anthropic"].default_model
    assert rows["groq"] == CATALOG["groq"].default_model
    assert "qwen2.5:7b" not in [v for k, v in rows.items() if k != "ollama"]


def test_without_an_override_every_row_shows_its_own_default(monkeypatch):
    monkeypatch.delenv("LLM_MODEL", raising=False)
    monkeypatch.setenv("LLM_PROVIDER", "groq")

    for row in survey():
        assert row["model"] == CATALOG[row["key"]].default_model


def test_providers_do_not_all_report_the_same_model(monkeypatch):
    """A blunt guard: the catalogue is diverse, so the survey must be too."""
    monkeypatch.setenv("LLM_PROVIDER", "ollama")
    monkeypatch.setenv("LLM_MODEL", "qwen2.5:7b")

    models = [r["model"] for r in survey()]
    assert len(set(models)) > 5, f"survey collapsed to {set(models)}"


# --------------------------------------------------------------------------
# The price source is decided once, not once per call site
# --------------------------------------------------------------------------

@pytest.fixture
def no_kite(monkeypatch):
    from server import kite_client
    monkeypatch.setattr(kite_client.SESSION, "is_live", lambda: False)


@pytest.fixture
def live_kite(monkeypatch):
    from server import kite_client
    monkeypatch.setattr(kite_client.SESSION, "is_live", lambda: True)


def test_empty_price_source_is_automatic_not_empty(monkeypatch, no_kite):
    """`PRICE_SOURCE=` is what .env.example ships.

    os.getenv(..., "yfinance") does not fire on an empty value — only on a
    missing one — so the config endpoint returned "" and the settings panel
    rendered a blank where the data source should be.
    """
    monkeypatch.setenv("PRICE_SOURCE", "")
    assert resolve() == ("yfinance", False)


def test_absent_price_source_follows_the_session(monkeypatch, live_kite):
    """The old default said "yfinance" even with a live broker session."""
    monkeypatch.delenv("PRICE_SOURCE", raising=False)
    assert resolve() == ("kite", False)


def test_absent_price_source_falls_back_without_a_session(monkeypatch, no_kite):
    monkeypatch.delenv("PRICE_SOURCE", raising=False)
    assert resolve() == ("yfinance", False)


def test_env_pins_the_source_against_the_session(monkeypatch, live_kite):
    monkeypatch.setenv("PRICE_SOURCE", "yfinance")
    assert resolve() == ("yfinance", True)


def test_an_explicit_request_beats_everything(monkeypatch, live_kite):
    monkeypatch.setenv("PRICE_SOURCE", "yfinance")
    assert resolve("kite") == ("kite", True)


def test_config_endpoint_and_scanner_cannot_disagree(monkeypatch, live_kite):
    """The actual defect: two call sites, two different answers.

    /api/config said one thing while the scanner did another. They now share a
    resolver, so this asserts they return the identical tuple.
    """
    monkeypatch.delenv("PRICE_SOURCE", raising=False)

    from server.routes.health import config
    from server.routes.scan import ScanBody, _resolve

    reported = config()["price_source"]
    _spec, used = _resolve(ScanBody())
    assert reported == used == "kite"
