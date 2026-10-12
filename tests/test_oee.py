import pytest

from analytics import calculate_oee


def test_oee_formula_components():
    result = calculate_oee(480, 48, 1.0, 360, 342, 400)
    assert result["availability"] == pytest.approx(0.9)
    assert result["performance"] == pytest.approx(0.9)
    assert result["quality"] == pytest.approx(0.95)
    assert result["oee"] == pytest.approx(0.7695)


def test_oee_rejects_invalid_counts():
    with pytest.raises(ValueError):
        calculate_oee(480, 10, 1, 10, 11, 400)
