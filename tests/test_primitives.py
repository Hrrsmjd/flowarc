import pytest

from flowarc.mesh.primitives import ahmed


@pytest.mark.parametrize("slant", [25.0, 35.0])
def test_ahmed_is_one_closed_body(slant):
    m = ahmed(slant)
    assert m.is_watertight and len(m.split()) == 1
    lo, hi = m.bounds
    assert lo[0] == pytest.approx(0) and hi[0] == pytest.approx(1)
    assert lo[2] == pytest.approx(0) and hi[2] == pytest.approx((50 + 288) / 1044)
