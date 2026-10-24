import json

from flowarc import config, gemini, pipeline, triage
from flowarc.sample import Sample, past_fixes


def mesh_fails_until(n, calls):
    def fn(s, gpu):
        calls.append(("mesh", dict(s.meta), s.concept["description"]))
        ok = len([c for c in calls if c[0] == "mesh"]) > n
        s.record_check("mesh", ok, summary="tail fins too thin, broken off")
        return ok

    return fn


def stages(calls, mesh):
    def ok(name):
        def fn(s, gpu):
            calls.append((name,))
            return True

        return fn

    return {n: ok(n) for n in ["images", "sim", "render", "package"]} | {"mesh": mesh}


def logs(s):
    return [json.loads(line) for line in (s.dir / "log.jsonl").read_text().splitlines()]


def test_argon_redraws_and_the_fix_is_remembered(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "DATA", tmp_path)
    calls, prompts = [], []
    monkeypatch.setattr(pipeline, "STAGE_FNS", stages(calls, mesh_fails_until(1, calls)))

    def argon(prompt, schema=None, **kw):
        prompts.append(prompt)
        assert schema["properties"]["action"]["enum"] == triage.STAGE_ACTIONS["mesh"]
        return {
            "diagnosis": "Fins are too thin for the mesh model to keep.",
            "action": "redraw_views",
            "fix": "thicker fins",
            "description": "A manta with thick fins.",
        }

    monkeypatch.setattr(gemini, "argon", argon)
    s = Sample(id="s00001", stage="mesh", concept={"name": "Manta", "description": "A manta."})
    s = pipeline.run_sample(s, 0)

    assert s.status == "done"
    assert [c[0] for c in calls] == ["mesh", "images", "mesh", "sim", "render", "package"]
    assert calls[2][2] == "A manta with thick fins."
    assert s.concept["original_description"] == "A manta."
    assert "tail fins too thin" in prompts[0] and "No similar failures" in prompts[0]
    assert "open_repair" not in s.meta

    rows = [e for e in logs(s) if e["msg"].startswith("repair:")]
    assert rows == [
        rows[0]
        | {
            "msg": "repair: redraw_views: thicker fins",
            "diagnosis": "Fins are too thin for the mesh model to keep.",
            "actor": "argon",
            "stage": "mesh",
        }
    ]
    assert any(e["msg"] == "Argon repair fixed mesh" for e in logs(s))
    # the next sample with fins trouble sees this fix
    assert past_fixes("thin fins broke off", "mesh")[0]["action"] == "redraw_views: thicker fins"
    t = Sample(id="s00002", stage="mesh", concept={"name": "Ray", "description": "A ray."})
    calls.clear()
    pipeline.run_sample(t, 0)
    assert "thicker fins" in prompts[1]


def test_repair_mesh_reuses_raw_and_failed_fix_is_recorded(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "DATA", tmp_path)
    calls = []
    monkeypatch.setattr(pipeline, "STAGE_FNS", stages(calls, mesh_fails_until(2, calls)))
    monkeypatch.setattr(
        gemini,
        "argon",
        lambda p, schema=None, **kw: {
            "diagnosis": "holes",
            "action": "repair_mesh",
            "fix": "remesh",
        },
    )
    s = pipeline.run_sample(Sample(id="s00003", stage="mesh", concept={"description": "x"}), 0)
    assert s.status == "done"
    meshes = [c for c in calls if c[0] == "mesh"]
    assert [m[1].get("remesh") for m in meshes] == [None, True, True]
    repairs = [json.loads(line) for line in (tmp_path / "repairs.jsonl").read_text().splitlines()]
    assert [r["fixed"] for r in repairs if "action" not in r] == [False, True]


def test_argon_gives_up(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "DATA", tmp_path)
    calls = []
    monkeypatch.setattr(pipeline, "STAGE_FNS", stages(calls, mesh_fails_until(9, calls)))
    monkeypatch.setattr(
        gemini,
        "argon",
        lambda p, schema=None, **kw: {
            "diagnosis": "a cloud has no surface",
            "action": "give_up",
            "fix": "",
        },
    )
    s = pipeline.run_sample(Sample(id="s00004", stage="mesh", concept={"description": "x"}), 0)
    assert s.status == "failed" and len(calls) == 1
    assert any(e["msg"] == "repair: give_up" for e in logs(s))
    assert "open_repair" not in s.meta


def test_crash_is_evidence_and_gemini_down_falls_back(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "DATA", tmp_path)
    seen = []

    def argon(prompt, schema=None, **kw):
        seen.append(prompt)
        raise RuntimeError("spend cap")

    monkeypatch.setattr(gemini, "argon", argon)
    tries = []

    def sim(s, gpu):
        tries.append(1)
        if len(tries) == 1:
            raise ValueError("CUDA out of memory")
        return True

    monkeypatch.setattr(pipeline, "STAGE_FNS", {"sim": sim, "render": lambda s, g: True})
    s = Sample(id="s00005", stage="sim", concept={"description": "x"})
    monkeypatch.setattr(pipeline, "STAGES", ["sim", "render"], raising=False)
    s = pipeline.run_sample(s, 0)
    assert "CUDA out of memory" in seen[0]
    assert len(tries) == 2
    assert any(e["msg"].startswith("Argon repair unavailable") for e in logs(s))


def test_fixed_policy_when_switched_off(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "DATA", tmp_path)
    monkeypatch.setattr(config, "ARGON_REPAIR", False)
    s = Sample(id="s00006", stage="mesh", attempts={"mesh": 2})
    assert triage.handle(s, "mesh", []) and s.stage == "images"
    s = Sample(id="s00007", stage="mesh", attempts={"mesh": 1})
    assert triage.handle(s, "mesh", []) and s.stage == "mesh"
