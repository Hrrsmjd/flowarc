import importlib.util
from pathlib import Path

spec = importlib.util.spec_from_file_location(
    "run_pool", Path(__file__).parents[1] / "scripts/run_pool.py"
)
run_pool = importlib.util.module_from_spec(spec)
spec.loader.exec_module(run_pool)


def test_skip_ranges():
    assert run_pool.ids("s00102-s00104,s00110") == ["s00102", "s00103", "s00104", "s00110"]
