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


def ask(prompt, model=None, schema=None, thinking=None, max_tokens=None, background=False):
    """Send text or a list of content parts. Returns text, or parsed JSON when schema is set."""
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
    it = client().interactions.create(**kwargs)
    while it.status in ("in_progress", "queued"):
        time.sleep(5)
        it = client().interactions.get(id=it.id)
    if it.status != "completed":
        raise RuntimeError(f"Gemini interaction {it.id} ended {it.status}")
    text = "".join(
        c.text for s in it.steps if s.type == "model_output" for c in s.content if c.type == "text"
    )
    return json.loads(text) if schema else text


def argon(prompt, schema=None, thinking="medium", **kw):
    return ask(prompt, model=config.LEAD_MODEL, schema=schema, thinking=thinking, **kw)


def image_part(png: bytes, mime="image/png") -> dict:
    return {"type": "image", "data": base64.b64encode(png).decode(), "mime_type": mime}


def generate_image(prompt, refs: list[bytes] = (), aspect="1:1") -> bytes:
    parts = [{"type": "text", "text": prompt}] + [image_part(r) for r in refs]
    it = client().interactions.create(
        model=config.IMAGE_MODEL,
        input=parts,
        response_format={"type": "image", "mime_type": "image/png", "aspect_ratio": aspect},
    )
    if it.output_image is None:
        raise RuntimeError(f"no image returned ({it.id})")
    return base64.b64decode(it.output_image.data)


def embed(texts: list[str]) -> list[list[float]]:
    res = client().models.embed_content(model=config.EMBED_MODEL, contents=texts)
    return [e.values for e in res.embeddings]
