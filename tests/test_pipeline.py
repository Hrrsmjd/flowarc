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


def test_too_fast_sim_retries_slower():
    s = Sample(id="s00009", stage="sim")
    assert pipeline.lattice_velocity(s) == SimConfig.lattice_velocity
    s.checks["sim"] = [{"name": "stable", "passed": False, "mach_max": 0.8}]
    assert pipeline.lattice_velocity(s) == pytest.approx(SimConfig.lattice_velocity / 2)
    s.checks["sim"].append({"name": "stable", "passed": False, "mach_max": 0.5, "u": 0.0375})
    assert pipeline.lattice_velocity(s) == pytest.approx(0.0375 * 0.8)
