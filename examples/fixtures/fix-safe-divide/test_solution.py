from solution import safe_divide


def test_normal_division():
    assert safe_divide(9, 3) == 3


def test_negative_division():
    assert safe_divide(-8, 2) == -4


def test_zero_denominator_returns_none():
    assert safe_divide(5, 0) is None
