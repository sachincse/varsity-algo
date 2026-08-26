"""Which LLM provider to use, and how to reach it.

MODEL IDS ROT FAST. Treat this table as a starting point, not a constant.
Verified on 2026-08-23; by way of illustration, Groq retired every Llama chat
model on 2026-08-16 — one week before this was written — so any guide still
telling you to use ``llama-3.3-70b-versatile`` on Groq is already broken.

Every default here can be overridden without touching code:

    LLM_PROVIDER=groq
    LLM_MODEL=openai/gpt-oss-120b

If a model id stops working you will get a clear "provider does not know this
model" error pointing you at the provider's model list. That is deliberate —
the failure mode should be a sentence, not a stack trace.
"""
from __future__ import annotations

import os
from dataclasses import dataclass

from .providers import AnthropicProvider, OpenAICompatProvider


@dataclass(frozen=True)
class ProviderInfo:
    key: str
    label: str
    base_url: str
    key_env: str | None
    default_model: str
    json_mode: str            # json_schema | json_object | none
    open_weights: bool
    signup: str
    note: str = ""
    key_optional: bool = False


# --------------------------------------------------------------------------
# Verified 2026-08-23. See docs/PROVIDERS.md for the full per-provider notes.
# --------------------------------------------------------------------------
CATALOG: dict[str, ProviderInfo] = {
    "anthropic": ProviderInfo(
        key="anthropic", label="Anthropic (Claude)",
        base_url="", key_env="ANTHROPIC_API_KEY",
        default_model="claude-opus-5", json_mode="json_schema",
        open_weights=False, signup="https://console.anthropic.com/settings/keys",
        note="Uses the official anthropic SDK, not an OpenAI-compatible shim. "
             "Most reliable at filling the schema first time."),

    "groq": ProviderInfo(
        key="groq", label="Groq",
        base_url="https://api.groq.com/openai/v1", key_env="GROQ_API_KEY",
        default_model="openai/gpt-oss-120b", json_mode="json_schema",
        open_weights=True, signup="https://console.groq.com/keys",
        note="Free tier, no card. Very fast. NOTE: all Llama chat models were "
             "retired on 2026-08-16 — use gpt-oss-120b / gpt-oss-20b. strict "
             "json_schema is honoured on the gpt-oss models only."),

    "openrouter": ProviderInfo(
        key="openrouter", label="OpenRouter",
        base_url="https://openrouter.ai/api/v1", key_env="OPENROUTER_API_KEY",
        default_model="z-ai/glm-5.2", json_mode="json_schema",
        open_weights=True, signup="https://openrouter.ai/keys",
        note="One key, 400+ models. Has genuinely free ':free' variants "
             "(z-ai/glm-5.2:free, google/gemma-4-31b-it:free) at 20 req/min "
             "and 50 req/day without credits."),

    "together": ProviderInfo(
        key="together", label="Together AI",
        base_url="https://api.together.ai/v1", key_env="TOGETHER_API_KEY",
        default_model="openai/gpt-oss-120b", json_mode="json_schema",
        open_weights=True, signup="https://api.together.ai/settings/api-keys",
        note="Good open-weight catalogue: DeepSeek-V4-Pro, Kimi-K3, GLM-5.2."),

    "fireworks": ProviderInfo(
        key="fireworks", label="Fireworks AI",
        base_url="https://api.fireworks.ai/inference/v1",
        key_env="FIREWORKS_API_KEY",
        default_model="accounts/fireworks/models/gpt-oss-120b",
        json_mode="json_schema", open_weights=True,
        signup="https://app.fireworks.ai/settings/users/api-keys",
        note="Model ids need the full accounts/fireworks/models/ prefix, and "
             "dots become 'p' (GLM 5.2 -> glm-5p2)."),

    "cerebras": ProviderInfo(
        key="cerebras", label="Cerebras",
        base_url="https://api.cerebras.ai/v1", key_env="CEREBRAS_API_KEY",
        default_model="gpt-oss-120b", json_mode="json_schema",
        open_weights=True, signup="https://cloud.cerebras.ai/",
        note="Extremely low latency but only two public models "
             "(gpt-oss-120b, gemma-4-31b) and a tight 5 req/min free trial."),

    "deepseek": ProviderInfo(
        key="deepseek", label="DeepSeek",
        base_url="https://api.deepseek.com", key_env="DEEPSEEK_API_KEY",
        default_model="deepseek-v4-flash", json_mode="json_object",
        open_weights=True, signup="https://platform.deepseek.com/api_keys",
        note="Cheap. json_object only — no schema enforcement — and the docs "
             "admit it can occasionally return empty content, so the repair "
             "retry matters here. deepseek-chat/deepseek-reasoner are gone."),

    "gemini": ProviderInfo(
        key="gemini", label="Google Gemini",
        base_url="https://generativelanguage.googleapis.com/v1beta/openai/",
        key_env="GEMINI_API_KEY", default_model="gemini-3.6-flash",
        json_mode="json_object", open_weights=False,
        signup="https://aistudio.google.com/apikey",
        note="Generous free tier on Flash models. The trailing slash on the "
             "base URL is required. Flash models reason before answering, so "
             "they need a generous max_tokens or they return nothing at all."),

    "mistral": ProviderInfo(
        key="mistral", label="Mistral",
        base_url="https://api.mistral.ai/v1", key_env="MISTRAL_API_KEY",
        default_model="mistral-medium-3.5", json_mode="json_object",
        open_weights=True, signup="https://console.mistral.ai",
        note="Free 'Experiment' tier, phone verification required. magistral "
             "and devstral are deprecated."),

    "xai": ProviderInfo(
        key="xai", label="xAI (Grok)",
        base_url="https://api.x.ai/v1", key_env="XAI_API_KEY",
        default_model="grok-4.6", json_mode="json_schema",
        open_weights=False, signup="https://console.x.ai",
        note="Sign-up credit, no standing free tier."),

    "ollama": ProviderInfo(
        key="ollama", label="Ollama (local, no API key)",
        base_url="http://localhost:11434/v1", key_env=None,
        default_model="qwen3:8b", json_mode="json_object",
        open_weights=True, signup="https://ollama.com/download",
        key_optional=True,
        note="Runs entirely on your machine. No key, no cost, no data leaves "
             "the laptop. Slower, and small models need the repair retry more "
             "often. Start with `ollama pull qwen3:8b`."),

    "lmstudio": ProviderInfo(
        key="lmstudio", label="LM Studio (local, no API key)",
        base_url="http://localhost:1234/v1", key_env=None,
        default_model="local-model", json_mode="json_object",
        open_weights=True, signup="https://lmstudio.ai/",
        key_optional=True,
        note="Enable the local server in LM Studio's Developer tab, then set "
             "LLM_MODEL to whatever the server reports."),

    "custom": ProviderInfo(
        key="custom", label="Custom OpenAI-compatible endpoint",
        base_url="", key_env="LLM_API_KEY", default_model="",
        json_mode="json_object", open_weights=True, signup="",
        key_optional=True,
        note="For vLLM, llama.cpp server, LiteLLM proxy, or a company gateway. "
             "Set LLM_BASE_URL and LLM_MODEL."),
}

DEFAULT_ORDER = ["anthropic", "groq", "openrouter", "gemini", "together",
                 "deepseek", "fireworks", "cerebras", "mistral", "xai",
                 "ollama", "lmstudio"]


def build_provider(key: str | None = None, model: str | None = None):
    """Construct the configured provider. Raises ValueError on a bad key."""
    key = (key or os.getenv("LLM_PROVIDER") or "anthropic").strip().lower()
    if key not in CATALOG:
        raise ValueError(
            f"unknown LLM_PROVIDER '{key}'. Valid: {', '.join(CATALOG)}")

    info = CATALOG[key]
    model = model or os.getenv("LLM_MODEL") or info.default_model

    if key == "anthropic":
        return AnthropicProvider(model=model)

    base_url = info.base_url
    if key == "custom":
        base_url = os.getenv("LLM_BASE_URL", "").strip()
        if not base_url:
            raise ValueError("LLM_PROVIDER=custom requires LLM_BASE_URL")
        if not model:
            raise ValueError("LLM_PROVIDER=custom requires LLM_MODEL")
    else:
        base_url = os.getenv("LLM_BASE_URL", "").strip() or base_url

    return OpenAICompatProvider(
        name=key, base_url=base_url, model=model,
        key_env=info.key_env, json_mode=info.json_mode,
        api_key_optional=info.key_optional,
    )


def survey() -> list[dict]:
    """Which providers look usable right now — for the UI's setup panel."""
    out = []
    for k in DEFAULT_ORDER:
        info = CATALOG[k]
        has_key = bool(info.key_env and os.getenv(info.key_env)) or info.key_optional
        try:
            configured = build_provider(k).is_configured()
        except Exception:
            configured = False
        out.append({
            "key": k, "label": info.label,
            "model": os.getenv("LLM_MODEL") or info.default_model,
            "env_var": info.key_env, "has_key": has_key,
            "configured": configured, "open_weights": info.open_weights,
            "local": info.key_optional and "localhost" in info.base_url,
            "signup": info.signup, "note": info.note,
        })
    return out


def active_key() -> str:
    return (os.getenv("LLM_PROVIDER") or "anthropic").strip().lower()
