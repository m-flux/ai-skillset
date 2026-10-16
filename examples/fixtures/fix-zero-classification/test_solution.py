from solution import classify_number


def test_positive_number():
    assert classify_number(7) == "positive"


def test_negative_number():
    assert classify_number(-3) == "negative"


def test_zero_is_its_own_category():
    assert classify_number(0) == "zero"
