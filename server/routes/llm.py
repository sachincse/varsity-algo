"""Natural language -> validated strategy.

The model fills in a flat schema; the server compiles it into a StrategySpec
and re-validates every field. Nothing the model returns is ever executed.
"""
from __future__ import annotations

import logging

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from core.nl import (UnsupportedStrategy, build_messages, compile_flat,
                     flat_schema)
from core.explain import explain, lint
from core.spec import VARSITY_DEFAULT, StrategySpec
from server.llm.base import LLMError, generate_with_repair
from server.llm.registry import CATALOG, build_provider, survey

router = APIRouter()
log = logging.getLogger("varsity.llm")


class DescribeBody(BaseModel):
    text: str = Field(min_length=3, max_length=1000)
    provider: str | None = None
    model: str | None = None


@router.get("/providers")
def providers() -> dict:
    return {"providers": survey()}


@router.post("/strategy")
def strategy_from_text(body: DescribeBody) -> dict:
    """Turn an English description into an executable strategy spec."""
    try:
        provider = build_provider(body.provider, body.model)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e

    if not provider.is_configured():
        info = CATALOG.get(provider.name)
        hint = ""
        if info and info.key_env:
            hint = (f" Set {info.key_env} in your .env — get a key at "
                    f"{info.signup}.")
        elif info:
            hint = f" {info.note}"
        raise HTTPException(
            status_code=400,
            detail=f"The '{provider.name}' provider is not configured.{hint}")

    system, messages = build_messages(body.text)
    try:
        result = generate_with_repair(provider, system, messages, flat_schema())
    except LLMError as e:
        raise HTTPException(status_code=502, detail=str(e)) from e

    warning = result.strategy.unsupported_request or ""
    try:
        spec = compile_flat(result.strategy)
    except UnsupportedStrategy as e:
        # The model recognised the request is out of scope. Fall back to the
        # closest supported thing rather than returning nothing.
        flat = result.strategy.model_copy(update={"unsupported_request": ""})
        try:
            spec = compile_flat(flat)
        except Exception as e2:
            raise HTTPException(status_code=422, detail=str(e)) from e2
        warning = str(e)
    except Exception as e:
        raise HTTPException(
            status_code=422,
            detail=f"The model produced a strategy that failed validation: {e}"
        ) from e

    log.info("strategy from %s/%s: %s%s", result.provider, result.model,
             spec.name, " (repaired)" if result.repaired else "")

    return {
        "spec": spec.model_dump(mode="json"),
        "summary": spec.describe(),
        # The round trip back to English. The notation summary above asks the
        # user to check what they typed; this asks them to check what was
        # UNDERSTOOD, which is the thing a model can get wrong while still
        # producing a spec that validates.
        "explanation": explain(spec),
        "lint": [{"level": n.level, "message": n.message} for n in lint(spec)],
        "warning": warning,
        "meta": {"provider": result.provider, "model": result.model,
                 "repaired": result.repaired, "usage": result.usage},
    }


@router.get("/default")
def default_strategy() -> dict:
    """The video's own strategy, with no LLM call — so the app is usable with
    no API key at all."""
    return {"spec": VARSITY_DEFAULT.model_dump(mode="json"),
            "summary": VARSITY_DEFAULT.describe(),
            "explanation": explain(VARSITY_DEFAULT),
            "lint": [{"level": n.level, "message": n.message}
                     for n in lint(VARSITY_DEFAULT)],
            "warning": "",
            "meta": {"provider": "builtin", "model": "none"}}


@router.get("/schema")
def schema() -> dict:
    """The contract the model is held to, and the spec it compiles into."""
    return {"flat_schema": flat_schema(),
            "spec_schema": StrategySpec.model_json_schema()}
