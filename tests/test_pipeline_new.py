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
