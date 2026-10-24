import json

from flowarc import concepts, config, pipeline


def test_new_samples_store_embedding(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "DATA", tmp_path)
    monkeypatch.setattr(config, "MONGODB_URI", "")
    monkeypatch.setattr(
        concepts,
        "select",
        lambda n, seed=None: [{"name": "cube", "reynolds": 1e4, "embedding": [1.0]}],
    )
    (s,) = pipeline.new_samples(1)
    assert s.embedding == [1.0] and "embedding" not in s.concept and s.stage == "images"


def test_new_samples_log_argons_batch_call(tmp_path, monkeypatch):
    from flowarc import gemini

    monkeypatch.setattr(config, "DATA", tmp_path)
    monkeypatch.setattr(config, "MONGODB_URI", "")

    def select(n, seed=None):
        gemini._record("gemini-4-argon", "propose shapes", "{}", 0.0)
        return [{"name": f"c{i}", "reynolds": 1e4, "embedding": [1.0]} for i in range(n)]

    monkeypatch.setattr(concepts, "select", select)
    samples = pipeline.new_samples(2)
    logs = [
        [json.loads(x) for x in (s.dir / "log.jsonl").read_text().splitlines()] for s in samples
    ]
    calls = [[e for e in log if e.get("actor") == "gemini"] for log in logs]
    assert [len(c) for c in calls] == [1, 1]
    assert calls[0][0]["stage"] == "concept" and calls[0][0]["model"] == "gemini-4-argon"
    assert [c[0]["copy"] for c in calls] == [False, True]
    assert gemini.CALLS.get() is None
