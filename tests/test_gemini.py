"""The Gemini wrapper against a fake client: no network, no API key."""

import base64
from types import SimpleNamespace as NS

import pytest

from flowarc import config, gemini


def text_reply(text, status="completed", id="it1"):
    out = NS(type="model_output", content=[NS(type="text", text=text)])
    return NS(id=id, status=status, steps=[NS(type="thought", content=[]), out])


class FakeInteractions:
    def __init__(self, *replies):
        self.replies = list(replies)
        self.calls = []

    def create(self, **kw):
        self.calls.append(kw)
        return self.replies.pop(0)

    def get(self, id):
        self.calls.append({"get": id})
        return self.replies.pop(0)


@pytest.fixture
def fake(monkeypatch):
    def install(*replies, embeddings=None):
        inter = FakeInteractions(*replies)
        models = NS(
            embed_content=lambda model, contents: NS(
                embeddings=[NS(values=v) for v in embeddings[: len(contents)]]
            )
        )
        monkeypatch.setattr(gemini, "client", lambda: NS(interactions=inter, models=models))
        monkeypatch.setattr(gemini.time, "sleep", lambda s: None)
        return inter

    return install


def test_ask_defaults_to_flash_and_returns_text(fake):
    inter = fake(text_reply("hello"))
    assert gemini.ask("hi") == "hello"
    assert inter.calls == [{"model": config.FAST_MODEL, "input": "hi"}]


def test_argon_sends_thinking_level_never_sampling_params(fake):
    inter = fake(text_reply('{"a": 1}'))
    schema = {"type": "object", "properties": {"a": {"type": "integer"}}}
    assert gemini.argon("plan", schema=schema) == {"a": 1}
    kw = inter.calls[0]
    assert kw["model"] == config.LEAD_MODEL
    assert kw["generation_config"] == {"thinking_level": "medium"}
    assert kw["response_format"]["schema"] == schema
    for banned in ("temperature", "top_p", "top_k", "cached_content", "thinking_budget"):
        assert banned not in kw and banned not in kw["generation_config"]


def test_background_polls_until_done(fake):
    inter = fake(
        text_reply("", status="queued"),
        text_reply("", status="in_progress"),
        text_reply("done"),
    )
    assert gemini.ask("long", background=True, max_tokens=100_000) == "done"
    assert inter.calls[0]["background"] is True
    assert inter.calls[0]["generation_config"] == {"max_output_tokens": 100_000}
    assert inter.calls[1:] == [{"get": "it1"}, {"get": "it1"}]


def test_failed_interaction_raises(fake):
    fake(text_reply("", status="failed", id="bad"))
    with pytest.raises(RuntimeError, match="bad ended failed"):
        gemini.ask("x")


def test_generate_image_decodes_and_sends_refs(fake):
    jpg = b"\xff\xd8fake"
    inter = fake(NS(id="i", output_image=NS(data=base64.b64encode(jpg).decode())))
    assert gemini.generate_image("a cow", refs=[b"ref"]) == jpg
    kw = inter.calls[0]
    assert kw["model"] == config.IMAGE_MODEL
    assert kw["input"][1]["data"] == base64.b64encode(b"ref").decode()


def test_generate_image_without_output_raises(fake):
    fake(NS(id="i", output_image=None))
    with pytest.raises(RuntimeError, match="no image"):
        gemini.generate_image("a cow")


def test_embed_returns_vectors(fake):
    fake(embeddings=[[1.0, 0.0], [0.0, 1.0]])
    assert gemini.embed(["a", "b"]) == [[1.0, 0.0], [0.0, 1.0]]
