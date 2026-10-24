import random

from flowarc import concepts, config, gemini
from flowarc.concepts import RE_RANGE, TAXONOMY, flow_conditions, is_novel, similarity
from flowarc.sample import Sample


def test_novelty_rejects_near_copies():
    assert is_novel([1.0, 0.0], [])
    assert not is_novel([1.0, 0.01], [[1.0, 0.0]])
    assert is_novel([0.0, 1.0], [[1.0, 0.0]])
    assert similarity([2.0, 0.0], [[1.0, 0.0], [0.0, 1.0]]) == 1.0


def test_flow_conditions_stay_in_range():
    rng = random.Random(0)
    for _ in range(200):
        r = flow_conditions(rng)["reynolds"]
        assert RE_RANGE[0] * 0.9 <= r <= RE_RANGE[1] * 1.1


def _concept(name, bucket=TAXONOMY[0]):
    return {
        "name": name,
        "bucket": bucket,
        "description": f"a {name}",
        "ground": False,
        "facing": "nose first",
        "symmetric": True,
    }


def test_propose_prompts_with_coverage_and_existing_names(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "DATA", tmp_path)
    Sample(id="s1", concept=_concept("cow", TAXONOMY[0])).save()
    seen = {}

    def fake_argon(prompt, schema, thinking, tools):
        seen.update(prompt=prompt, schema=schema, thinking=thinking, tools=tools)
        return {"concepts": [_concept("heron")]}

    monkeypatch.setattr(gemini, "argon", fake_argon)
    assert concepts.propose(1)[0]["name"] == "heron"
    assert f"- {TAXONOMY[0]}: 1" in seen["prompt"]
    assert f"- {TAXONOMY[1]}: 0" in seen["prompt"]
    assert "cow" in seen["prompt"] and "Propose 1 new" in seen["prompt"]
    assert seen["schema"] is concepts.SCHEMA
    assert seen["tools"] == [concepts.SEARCH_TOOL]


def test_search_registry_tool_offline(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "DATA", tmp_path)
    Sample(id="s1", concept=_concept("heron")).save()
    Sample(id="s2", concept=_concept("teapot", TAXONOMY[3])).save()
    Sample(id="s3", concept=_concept("egret"), status="failed").save()
    hits = concepts.search_registry("heron with long legs")
    assert [h["name"] for h in hits] == ["heron"]
    assert concepts.search_registry("teapot", bucket=TAXONOMY[0]) == []


def test_select_drops_registry_and_batch_duplicates(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "DATA", tmp_path)
    Sample(id="s1", concept=_concept("cow"), embedding=[1.0, 0.0, 0.0]).save()
    cands = [_concept(n) for n in ("bull", "heron", "egret", "teapot")]
    vecs = {
        "bull": [0.99, 0.05, 0.0],  # near the cow already in the registry
        "heron": [0.0, 1.0, 0.0],
        "egret": [0.0, 0.99, 0.05],  # near the heron in the same batch
        "teapot": [0.0, 0.0, 1.0],
    }
    monkeypatch.setattr(gemini, "argon", lambda *a, **k: {"concepts": cands})
    monkeypatch.setattr(gemini, "embed", lambda texts: [vecs[t.split(":")[0]] for t in texts])

    picked = concepts.select(2, seed=0)
    assert sorted(c["name"] for c in picked) == ["heron", "teapot"]
    for c in picked:
        assert RE_RANGE[0] * 0.9 <= c["reynolds"] <= RE_RANGE[1] * 1.1
        assert c["similarity"] < concepts.NOVELTY and len(c["embedding"]) == 3


def test_select_returns_fewer_when_all_are_duplicates(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "DATA", tmp_path)
    Sample(id="s1", concept=_concept("cow"), embedding=[1.0, 0.0]).save()
    monkeypatch.setattr(gemini, "argon", lambda *a, **k: {"concepts": [_concept("bull")] * 2})
    monkeypatch.setattr(gemini, "embed", lambda texts: [[1.0, 0.01]] * len(texts))
    assert concepts.select(1) == []
