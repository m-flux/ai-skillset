from solution import in_range


def test_inside_range():
    assert in_range(5, 1, 9) is True


def test_both_endpoints_are_included():
    assert in_range(1, 1, 9) is True
    assert in_range(9, 1, 9) is True


def test_outside_range():
    assert in_range(0, 1, 9) is False
    assert in_range(10, 1, 9) is False
