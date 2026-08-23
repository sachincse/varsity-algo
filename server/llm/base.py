"""Provider-neutral interface for turning English into a validated strategy.

Two families sit behind this interface and they are deliberately NOT unified at
the wire level:

  Anthropic  uses the official ``anthropic`` SDK. Claude is not called through
             an OpenAI-compatible shim — the shim loses structured outputs,
             thinking, and correct error types, and there is no reason to give
             those up.
  Everything else speaks the OpenAI chat-completions shape, which is the de
             facto standard for Groq, Together, OpenRouter, DeepSeek,
             Fireworks, Cerebras, vLLM, LM Studio and Ollama. One adapter
             covers all of them; only base_url, key and model id change.

Every provider returns the same thing: a validated ``FlatStrategy``, or an
error. No provider ever returns code, and nothing returned is executed.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import Protocol

from pydantic import ValidationError

from core.nl import FlatStrategy


class LLMError(RuntimeError):
    """Anything that stopped us getting a usable strategy out of a model."""


@dataclass
class LLMResult:
    strategy: FlatStrategy
    provider: str
    model: str
    raw: str = ""
    repaired: bool = False
    usage: dict = field(default_factory=dict)


class Provider(Protocol):
    name: str
    model: str

    def is_configured(self) -> bool: ...

    def generate(self, system: str, messages: list[dict],
                 schema: dict) -> tuple[str, dict]:
        """Return (raw_json_text, usage)."""
        ...


# --------------------------------------------------------------------------
# Parsing and repair
# --------------------------------------------------------------------------
_FENCE = re.compile(r"```(?:json)?\s*(.*?)```", re.S)


def extract_json(text: str) -> str:
    """Pull a JSON object out of whatever the model actually said.

    Frontier models with a schema attached return bare JSON. Smaller local
    models wrap it in prose, fence it in markdown, or add a trailing sentence.
    Rather than fail on that, take the first balanced ``{...}`` block.
    """
    text = text.strip()
    if not text:
        raise LLMError("model returned an empty response")

    m = _FENCE.search(text)
    if m:
        text = m.group(1).strip()

    if text.startswith("{") and text.endswith("}"):
        return text

    start = text.find("{")
    if start == -1:
        raise LLMError(f"no JSON object in response: {text[:200]}")

    depth, in_str, esc = 0, False, False
    for i, ch in enumerate(text[start:], start):
        if in_str:
            if esc:
                esc = False
            elif ch == "\\":
                esc = True
            elif ch == '"':
                in_str = False
            continue
        if ch == '"':
            in_str = True
        elif ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                return text[start:i + 1]
    raise LLMError("unbalanced JSON in model response")


def parse_strategy(raw: str) -> FlatStrategy:
    payload = extract_json(raw)
    try:
        data = json.loads(payload)
    except json.JSONDecodeError as e:
        raise LLMError(f"model returned invalid JSON: {e}") from e
    try:
        return FlatStrategy.model_validate(data)
    except ValidationError as e:
        raise LLMError(_readable(e)) from e


def _readable(e: ValidationError) -> str:
    bits = []
    for err in e.errors()[:6]:
        loc = ".".join(str(p) for p in err["loc"])
        bits.append(f"{loc}: {err['msg']}")
    return "the model's strategy did not validate — " + "; ".join(bits)


def generate_with_repair(provider: Provider, system: str, messages: list[dict],
                         schema: dict, attempts: int = 2) -> LLMResult:
    """Ask once; if validation fails, show the model its own error and retry.

    One retry is worth it and two is not — past that, a model that cannot fill
    a flat schema is the wrong model for the job and should be swapped rather
    than nagged.
    """
    convo = list(messages)
    last_error = ""
    for attempt in range(attempts):
        raw, usage = provider.generate(system, convo, schema)
        try:
            strategy = parse_strategy(raw)
            return LLMResult(strategy=strategy, provider=provider.name,
                             model=provider.model, raw=raw,
                             repaired=attempt > 0, usage=usage)
        except LLMError as e:
            last_error = str(e)
            if attempt == attempts - 1:
                break
            convo = convo + [
                {"role": "assistant", "content": raw[:4000]},
                {"role": "user", "content":
                    f"That response was rejected: {last_error}\n\n"
                    f"Return ONLY a corrected JSON object matching the schema. "
                    f"No prose, no markdown fences."},
            ]
    raise LLMError(f"{provider.name}/{provider.model}: {last_error}")
