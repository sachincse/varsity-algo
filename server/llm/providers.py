"""Concrete providers: Anthropic via its own SDK, everything else via the
OpenAI-compatible chat-completions shape.
"""
from __future__ import annotations

import json
import os

from .base import LLMError, Provider


# ==========================================================================
# Anthropic — official SDK, never an OpenAI-compatible shim
# ==========================================================================
class AnthropicProvider:
    name = "anthropic"

    def __init__(self, model: str | None = None, api_key: str | None = None):
        self.model = model or os.getenv("ANTHROPIC_MODEL", "claude-opus-5")
        self._key = api_key or os.getenv("ANTHROPIC_API_KEY")

    def is_configured(self) -> bool:
        # An unset ANTHROPIC_API_KEY does not mean there are no credentials:
        # the SDK also resolves ANTHROPIC_AUTH_TOKEN and an `ant auth login`
        # profile on disk. Only report unconfigured if the SDK is absent.
        try:
            import anthropic  # noqa: F401
        except ImportError:
            return False
        return bool(self._key or os.getenv("ANTHROPIC_AUTH_TOKEN")
                    or os.path.isdir(os.path.expanduser("~/.config/anthropic")))

    def generate(self, system: str, messages: list[dict], schema: dict):
        import anthropic

        client = anthropic.Anthropic(**({"api_key": self._key} if self._key else {}))
        try:
            resp = client.messages.create(
                model=self.model,
                max_tokens=8000,
                system=system,
                messages=messages,
                thinking={"type": "adaptive"},
                output_config={
                    "effort": "medium",
                    "format": {"type": "json_schema", "schema": _strictify(schema)},
                },
            )
        except anthropic.AuthenticationError as e:
            raise LLMError("Anthropic rejected the API key. Check "
                           "ANTHROPIC_API_KEY in your .env.") from e
        except anthropic.RateLimitError as e:
            raise LLMError("Anthropic rate limit hit. Wait a moment and retry.") from e
        except anthropic.APIStatusError as e:
            raise LLMError(f"Anthropic error {e.status_code}: {e.message}") from e
        except anthropic.APIConnectionError as e:
            raise LLMError("Could not reach the Anthropic API. Check your "
                           "network connection.") from e

        if resp.stop_reason == "refusal":
            raise LLMError("Claude declined this request.")

        text = next((b.text for b in resp.content if b.type == "text"), "")
        usage = {"input_tokens": resp.usage.input_tokens,
                 "output_tokens": resp.usage.output_tokens}
        return text, usage


# ==========================================================================
# Everything else — OpenAI-compatible chat completions
# ==========================================================================
class OpenAICompatProvider:
    """One adapter for every provider that speaks /v1/chat/completions.

    Structured output support varies, so this degrades in three steps:
      1. json_schema response_format (strict), where supported
      2. json_object response_format (valid JSON, unconstrained shape)
      3. nothing — rely on the prompt, and let base.extract_json cope
    """

    def __init__(self, name: str, base_url: str, model: str,
                 api_key: str | None = None, key_env: str | None = None,
                 json_mode: str = "json_object", api_key_optional: bool = False):
        self.name = name
        self.base_url = base_url
        self.model = model
        self.key_env = key_env
        self.json_mode = json_mode          # "json_schema" | "json_object" | "none"
        self.api_key_optional = api_key_optional
        self._key = api_key or (os.getenv(key_env) if key_env else None)

    def is_configured(self) -> bool:
        try:
            import openai  # noqa: F401
        except ImportError:
            return False
        if self._key:
            return True
        if not self.api_key_optional:
            return False
        # A local endpoint needs no key, but "no key required" is not the same
        # as "running". Probe it, so the setup panel does not claim Ollama is
        # ready when nothing is listening on the port.
        return self._local_server_up()

    def _installed(self) -> list[str]:
        """Model ids this server currently holds, or [] if it will not say."""
        try:
            import httpx
            r = httpx.get(f"{self.base_url.rstrip('/')}/models", timeout=3.0)
            return sorted(m["id"] for m in r.json().get("data", []))
        except Exception:
            return []

    def _unknown_model_help(self) -> str:
        """A local server and a hosted API fail this way for opposite reasons.

        Hosted: the id was retired or misspelled, so the fix is to go read the
        provider's model list. Local: the id is fine, you simply have not
        downloaded it — and sending someone to browse a model list points them
        somewhere that cannot help. Ollama and LM Studio both answer /models,
        so name what is actually installed rather than making them go look.
        """
        if not self.api_key_optional:
            return (f"{self.name} does not know the model '{self.model}'. "
                    f"Model ids change often — check the provider's model list "
                    f"and update LLM_MODEL in your .env.")

        fix = (f"Download it with:  ollama pull {self.model}"
               if self.name == "ollama" else
               "Load the model in LM Studio, or set LLM_MODEL to one below.")
        have = self._installed()
        listing = ("\n\nAlready installed:\n  " + "\n  ".join(have)) if have else ""
        return (f"{self.name} is running, but '{self.model}' is not installed "
                f"on it. {fix}{listing}")

    def _local_server_up(self) -> bool:
        return _probe(self.base_url)

    def generate(self, system: str, messages: list[dict], schema: dict):
        import openai

        client = openai.OpenAI(
            base_url=self.base_url,
            api_key=self._key or "not-needed",
            timeout=120.0,
            max_retries=2,
        )
        payload = {
            "model": self.model,
            "messages": [{"role": "system", "content": system}] + messages,
            "temperature": 0,
            "max_tokens": 4000,
        }
        if self.json_mode == "json_schema":
            payload["response_format"] = {
                "type": "json_schema",
                "json_schema": {"name": "strategy", "strict": True,
                                "schema": _strictify(schema)},
            }
        elif self.json_mode == "json_object":
            payload["response_format"] = {"type": "json_object"}

        try:
            resp = client.chat.completions.create(**payload)
        except openai.AuthenticationError as e:
            hint = f" Set {self.key_env} in your .env." if self.key_env else ""
            raise LLMError(f"{self.name} rejected the API key.{hint}") from e
        except openai.NotFoundError as e:
            raise LLMError(self._unknown_model_help()) from e
        except openai.RateLimitError as e:
            raise LLMError(f"{self.name} rate limit hit. Wait and retry, or "
                           f"switch provider.") from e
        except openai.InternalServerError as e:
            raise LLMError(
                f"{self.name} returned a server error for '{self.model}' "
                f"(often 'model is overloaded'). Nothing is wrong on your side "
                f"— retry shortly, or set LLM_MODEL to a different model.") from e
        except openai.APITimeoutError as e:
            # Must precede APIConnectionError — APITimeoutError subclasses it,
            # so the broader handler would otherwise report a slow model as an
            # unreachable host and send people to debug their network.
            raise LLMError(
                f"{self.name} did not answer within 120s using "
                f"'{self.model}'. The host is reachable, so it is the model "
                f"being slow or overloaded, not your connection. Try a "
                f"smaller/faster model, or another provider.") from e
        except openai.APIConnectionError as e:
            extra = ""
            if "localhost" in self.base_url or "127.0.0.1" in self.base_url:
                extra = (" Is the local server running? For Ollama, run "
                         "`ollama serve` and `ollama list` to confirm.")
            raise LLMError(f"Could not reach {self.name} at {self.base_url}.{extra}") from e
        except openai.BadRequestError as e:
            # Several providers advertise json_schema and then reject it. Fall
            # back one rung rather than failing the user's request.
            if self.json_mode == "json_schema":
                self.json_mode = "json_object"
                return self.generate(system, messages, schema)
            if self.json_mode == "json_object":
                self.json_mode = "none"
                return self.generate(system, messages, schema)
            raise LLMError(f"{self.name} rejected the request: {e}") from e

        choice = resp.choices[0]
        text = choice.message.content or ""
        if not text.strip():
            # Reasoning models bill thinking against max_tokens. Hit the cap
            # while still thinking and the API returns finish_reason='length'
            # with completion_tokens=0 and no content at all — which reads as
            # "the model said nothing" unless you name the real cause.
            if choice.finish_reason == "length":
                raise LLMError(
                    f"{self.name} hit the output limit before writing anything "
                    f"— '{self.model}' is a reasoning model and spent the whole "
                    f"budget thinking. Raise max_tokens, or pick a "
                    f"non-reasoning model.")
            raise LLMError(
                f"{self.name} returned an empty response for '{self.model}' "
                f"(finish_reason={choice.finish_reason!r}).")
        usage = {}
        if resp.usage:
            usage = {"input_tokens": resp.usage.prompt_tokens,
                     "output_tokens": resp.usage.completion_tokens}
        return text, usage


# --------------------------------------------------------------------------
# Probing a local endpoint means a TCP connect, and a closed port on Windows
# can sit on the timeout rather than refusing immediately. /api/config asks
# about every provider, so an uncached probe made a page-load call take over a
# second. Cache the answer briefly — a local server does not start and stop
# between two clicks.
_PROBE_TTL = 15.0
_probe_cache: dict[str, tuple[float, bool]] = {}


def _probe(base_url: str, timeout: float = 0.15) -> bool:
    import socket
    import time
    from urllib.parse import urlparse

    now = time.time()
    hit = _probe_cache.get(base_url)
    if hit and now - hit[0] < _PROBE_TTL:
        return hit[1]

    u = urlparse(base_url)
    host = u.hostname or "127.0.0.1"
    port = u.port or (443 if u.scheme == "https" else 80)
    try:
        with socket.create_connection((host, port), timeout=timeout):
            up = True
    except OSError:
        up = False
    _probe_cache[base_url] = (now, up)
    return up


def _strictify(schema: dict) -> dict:
    """Make a pydantic JSON Schema acceptable to strict structured-output modes.

    Strict modes generally require ``additionalProperties: false`` on every
    object and every property listed in ``required``. Pydantic omits both for
    optional fields, so they are added here. Nullable optionals stay nullable —
    the field must be present, but may be null.
    """
    import copy
    s = copy.deepcopy(schema)

    def walk(node):
        if isinstance(node, dict):
            if node.get("type") == "object" and "properties" in node:
                node["additionalProperties"] = False
                node["required"] = list(node["properties"].keys())
            for v in node.values():
                walk(v)
        elif isinstance(node, list):
            for v in node:
                walk(v)

    walk(s)
    for defn in s.get("$defs", {}).values():
        walk(defn)
    return s
