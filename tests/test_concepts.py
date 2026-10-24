import random

from flowarc.concepts import RE_RANGE, flow_conditions, is_novel, similarity


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
