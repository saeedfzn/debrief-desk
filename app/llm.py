"""Model provider. One function, call_json, so the rest of the app never touches the SDK.

Uses the Anthropic SDK with ANTHROPIC_API_KEY from the environment. Swap this file to change provider.
"""
from __future__ import annotations

import json
import os
import re
import threading
import time

from app import config


class LLMUnavailable(RuntimeError):
    """No API key set, so live model calls are not possible."""


class LLMError(RuntimeError):
    """The model call failed or returned something unusable."""


# Running totals, read by scripts/make_saved.py.
_lock = threading.Lock()
USAGE = {"calls": 0, "input_tokens": 0, "output_tokens": 0}

_client = None


def has_key() -> bool:
    return bool(os.environ.get("ANTHROPIC_API_KEY", "").strip())


def model_name() -> str:
    return os.environ.get("DEBRIEF_MODEL") or getattr(config, "MODEL", "claude-sonnet-5-5")


def _get_client():
    global _client
    if _client is None:
        import anthropic
        _client = anthropic.Anthropic(max_retries=2, timeout=180)
    return _client


def _extract_json(text: str):
    """Pull the first JSON object out of the model's text (tolerates code fences and stray prose)."""
    text = text.strip()
    fence = re.search(r"```(?:json)?\s*(.*?)```", text, re.S)
    if fence:
        text = fence.group(1).strip()
    try:
        return json.loads(text)
    except ValueError:
        pass
    start = text.find("{")
    end = text.rfind("}")
    if start != -1 and end > start:
        return json.loads(text[start:end + 1])
    raise ValueError("no JSON object found")


def _one_call(system: str, messages: list, max_tokens: int, effort: str):
    client = _get_client()
    resp = client.messages.create(
        model=model_name(),
        max_tokens=max_tokens,
        system=system,
        messages=messages,
        output_config={"effort": effort},
    )
    with _lock:
        USAGE["calls"] += 1
        USAGE["input_tokens"] += resp.usage.input_tokens
        USAGE["output_tokens"] += resp.usage.output_tokens
    return resp


def call_json(system: str, user: str, max_tokens: int = 4000, effort: str = "low") -> tuple[dict, dict]:
    """Ask the model for a JSON object. Returns (parsed_json, meta).

    meta = {"model", "ms", "input_tokens", "output_tokens"} summed over any retry.
    One retry if the reply is not valid JSON. Raises LLMUnavailable without a key, LLMError otherwise.
    """
    if not has_key():
        raise LLMUnavailable("No ANTHROPIC_API_KEY is set, so the model cannot be called.")
    import anthropic

    t0 = time.perf_counter()
    meta = {"model": model_name(), "ms": 0, "input_tokens": 0, "output_tokens": 0}
    messages = [{"role": "user", "content": user}]
    last_err = None
    for attempt in range(2):
        try:
            resp = _one_call(system, messages, max_tokens, effort)
        except anthropic.APIStatusError as e:
            raise LLMError(f"Model call failed ({e.status_code}): {getattr(e, 'message', e)}") from e
        except anthropic.APIConnectionError as e:
            raise LLMError(f"Could not reach the model: {e}") from e
        meta["input_tokens"] += resp.usage.input_tokens
        meta["output_tokens"] += resp.usage.output_tokens
        meta["model"] = getattr(resp, "model", meta["model"]) or meta["model"]
        if resp.stop_reason == "refusal":
            raise LLMError("The model declined this request.")
        if resp.stop_reason == "max_tokens":
            raise LLMError("The model ran out of room before finishing its answer.")
        text = "".join(b.text for b in resp.content if getattr(b, "type", "") == "text")
        try:
            data = _extract_json(text)
            if not isinstance(data, dict):
                raise ValueError("top level is not an object")
            meta["ms"] = int((time.perf_counter() - t0) * 1000)
            return data, meta
        except ValueError as e:
            last_err = e
            messages = messages + [
                {"role": "assistant", "content": text or "(empty)"},
                {"role": "user", "content": "That was not a valid JSON object. Reply again with only the JSON object, nothing else."},
            ]
    raise LLMError(f"The model did not return valid JSON: {last_err}")
