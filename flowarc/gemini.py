"""Thin wrapper over the Gemini Interactions API.

Argon rules: use thinking_level, never temperature/top_p/top_k; background=True for
outputs over 65,536 tokens.
"""

import base64
import json
import time
from functools import cache

from flowarc import config


@cache
def client():
    from google import genai

    return genai.Client()


MAX_TOOL_ROUNDS = 6


def tool(fn, description: str, parameters: dict) -> dict:
    """A Python function the model may call: {"spec": declaration, "fn": fn}."""
    spec = {"type": "function", "name": fn.__name__, "description": description}
    return {"spec": spec | {"parameters": parameters}, "fn": fn}


def _run(kwargs):
    it = client().interactions.create(**kwargs)
    while it.status in ("in_progress", "queued"):
        time.sleep(5)
        it = client().interactions.get(id=it.id)
    if it.status not in ("completed", "requires_action"):
        raise RuntimeError(f"Gemini interaction {it.id} ended {it.status}")
    return it


def ask(
    prompt,
    model=None,
    schema=None,
    thinking=None,
    max_tokens=None,
    background=False,
    tools=(),
):
    """Send text or a list of content parts. Returns text, or parsed JSON when schema is set.

    `tools` (from `tool()`) are offered to the model; its calls are run here and the results
    sent back in a follow-up interaction, until it answers or MAX_TOOL_ROUNDS is reached.
    """
    kwargs = {"model": model or config.FAST_MODEL, "input": prompt}
    gen = {}
    if thinking:
        gen["thinking_level"] = thinking
    if max_tokens:
        gen["max_output_tokens"] = max_tokens
    if gen:
        kwargs["generation_config"] = gen
    if schema:
        kwargs["response_format"] = {
            "type": "text",
            "mime_type": "application/json",
            "schema": schema,
        }
    if background:
        kwargs["background"] = True
    fns = {t["spec"]["name"]: t["fn"] for t in tools}
    if tools:
        kwargs["tools"] = [t["spec"] for t in tools]
    it = _run(kwargs)
    for rounds in range(MAX_TOOL_ROUNDS + 1):
        calls = [s for s in it.steps if s.type == "function_call"]
        if not calls:
            break
        if rounds == MAX_TOOL_ROUNDS:
            raise RuntimeError(
                f"Gemini interaction {it.id} still calling tools after {MAX_TOOL_ROUNDS}"
            )
        results = [_call(fns, c) for c in calls]
        it = _run({**kwargs, "input": results, "previous_interaction_id": it.id})
    text = "".join(
        c.text for s in it.steps if s.type == "model_output" for c in s.content if c.type == "text"
    )
    return json.loads(text) if schema else text


def _call(fns, call) -> dict:
    out = {"type": "function_result", "call_id": call.id, "name": call.name}
    try:
        return out | {"result": json.dumps(fns[call.name](**call.arguments), default=str)}
    except Exception as e:  # noqa: BLE001 -- the model sees the error and can retry
        return out | {"result": f"{type(e).__name__}: {e}", "is_error": True}


def argon(prompt, schema=None, thinking="medium", **kw):
    return ask(prompt, model=config.LEAD_MODEL, schema=schema, thinking=thinking, **kw)


def image_part(img: bytes, mime="image/jpeg") -> dict:
    return {"type": "image", "data": base64.b64encode(img).decode(), "mime_type": mime}


def generate_image(prompt, refs: list[bytes] = (), aspect="1:1") -> bytes:
    """Returns JPEG bytes; refs are JPEGs the image should match."""
    parts = [{"type": "text", "text": prompt}] + [image_part(r) for r in refs]
    it = client().interactions.create(
        model=config.IMAGE_MODEL,
        input=parts,
        response_format={"type": "image", "mime_type": "image/jpeg", "aspect_ratio": aspect},
    )
    if it.output_image is None:
        raise RuntimeError(f"no image returned ({it.id})")
    return base64.b64decode(it.output_image.data)


def embed(texts: list[str]) -> list[list[float]]:
    res = client().models.embed_content(model=config.EMBED_MODEL, contents=texts)
    return [e.values for e in res.embeddings]
