import pytest

from flowarc import config, pipeline
from flowarc.sample import Sample
from flowarc.sim.solver import SimConfig


def test_retry_resume_and_budget(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "DATA", tmp_path)
    calls = []

    def stage(name, fails=0):
        def fn(s, gpu):
            calls.append(name)
            if name == "sim":
                s.meta["gpu_seconds"] = 3600
            return s.attempts[name] > fails

        return fn

    monkeypatch.setattr(
        pipeline,
        "STAGE_FNS",
        {
            n: stage(n, fails=1 if n == "mesh" else 0)
            for n in ["images", "mesh", "sim", "render", "package"]
        },
    )
    s = Sample(id="s00001", stage="images")
    s.save()
    over = Sample(id="s00002", stage="sim", meta={"gpu_seconds": 7200})
    over.save()
    with pytest.raises(pipeline.BudgetExceeded):
        pipeline.run_sample(over, 0, budget_hours=1)
    done = pipeline.run_sample(Sample.load("s00001"), 0, budget_hours=3)
    assert done.status == "done" and done.stage == "done"
    assert calls == ["images", "mesh", "mesh", "sim", "render", "package"]
    assert Sample.load("s00001").attempts["mesh"] == 2


def test_out_of_attempts_fails(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "DATA", tmp_path)
    monkeypatch.setattr(pipeline, "STAGE_FNS", {"images": lambda s, g: False})
    s = pipeline.run_sample(Sample(id="s00003", stage="images"), 0)
    assert s.status == "failed" and s.attempts["images"] == config.MAX_ATTEMPTS["images"] + 1


def test_try_cut_short_by_restart_is_not_counted(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "DATA", tmp_path)
    ok = lambda s, g: True
    monkeypatch.setattr(pipeline, "STAGE_FNS", {n: ok for n in ["sim", "render", "package"]})
    s = Sample(id="s00008", stage="sim", attempts={"sim": 3}, meta={"in_try": "sim"})
    s = pipeline.run_sample(s, 0)
    assert s.status == "done" and s.attempts["sim"] == 3 and "in_try" not in s.meta


def test_too_fast_sim_retries_slower():
    s = Sample(id="s00009", stage="sim")
    assert pipeline.lattice_velocity(s) == SimConfig.lattice_velocity
    s.checks["sim"] = [{"name": "stable", "passed": False, "mach_max": 0.8}]
    assert pipeline.lattice_velocity(s) == pytest.approx(SimConfig.lattice_velocity / 2)
    s.checks["sim"].append({"name": "stable", "passed": False, "mach_max": 0.5, "u": 0.0375})
    assert pipeline.lattice_velocity(s) == pytest.approx(0.0375 * 0.8)


def test_failed_tries_are_uploaded(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "DATA", tmp_path)
    seen = []
    monkeypatch.setattr(pipeline, "upload", lambda s, st, a=None: seen.append((st, a)))
    monkeypatch.setattr(pipeline, "STAGE_FNS", {"images": lambda s, g: False})
    pipeline.run_sample(Sample(id="s00004", stage="images"), 0)
    assert seen == [("images", n) for n in range(1, config.MAX_ATTEMPTS["images"] + 1)]


def test_failed_dns_retries_with_les_not_slower():
    s = Sample(id="s1", concept={"reynolds": 500})
    assert not pipeline.sim_config(s).les
    s.checks["sim"] = [
        {"name": "stable", "passed": False, "mach_max": 0.9, "u": 0.075, "les": False}
    ]
    cfg = pipeline.sim_config(s)
    assert cfg.les and cfg.lattice_velocity == 0.075
    s.checks["sim"].append(
        {"name": "stable", "passed": False, "mach_max": 0.8, "u": 0.075, "les": True}
    )
    assert pipeline.sim_config(s).lattice_velocity == 0.075 * 0.5


def test_laminar_samples_stay_at_128_cells(monkeypatch):
    monkeypatch.setattr(pipeline.config, "PHASE", pipeline.config.PHASES["real"])
    assert pipeline.sim_config(Sample(id="s1", concept={"reynolds": 3e4})).cells_per_length == 256
    assert pipeline.sim_config(Sample(id="s2", concept={"reynolds": 500})).cells_per_length == 128


def test_view_mismatch_does_not_flag(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "DATA", tmp_path)

    def images(s, g):
        s.record_check("views_consistent", False, hard=False)
        return True

    fns = {n: (lambda s, g: True) for n in ["mesh", "sim", "render", "package"]}
    monkeypatch.setattr(pipeline, "STAGE_FNS", fns | {"images": images})
    assert pipeline.run_sample(Sample(id="s00005", stage="images"), 0).status == "done"


def test_package_deletes_sim_scratch(tmp_path, monkeypatch):
    from flowarc import package

    monkeypatch.setattr(config, "DATA", tmp_path)
    monkeypatch.setattr(pipeline, "sim_config", lambda s: None)
    monkeypatch.setattr(package, "pack", lambda *a, **k: tmp_path / "z")
    monkeypatch.setattr(package, "size_bytes", lambda z: 1e9)
    s = Sample(
        id="s00010",
        stage="package",
        meta={"sim": {"ok": True, "forces": "f", "frames": None, "stats": {}, "cost": 1}},
    )
    sim = s.dir / "sim"
    for sub in ("probes", "render", "frames"):
        (sim / sub).mkdir(parents=True)
        (sim / sub / "x").write_bytes(b"1")
    (sim / "video.mp4").write_bytes(b"1")
    assert pipeline.run_package(s, 0)
    assert not (sim / "probes").exists() and not (sim / "render").exists()
    assert (sim / "frames" / "x").exists() and (sim / "video.mp4").exists()
