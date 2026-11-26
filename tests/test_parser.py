from crokbot.jev.parser import (
    answers_to_dict,
    as_bool,
    as_float,
    as_int,
    extract_line,
    extract_lines,
)


RAW = "1. normal\n2. yes\n3. 2\n4. 0.85\n5. buy\n"


def test_extract_lines_strips_numbers_keeps_numerals():
    lines = extract_lines(RAW)
    assert lines == ["normal", "yes", "2", "0.85", "buy"]


def test_extract_line_index():
    assert extract_line(RAW, 0) == "normal"
    assert extract_line(RAW, 2) == "2"
    assert extract_line(RAW, 99) is None


def test_as_bool():
    assert as_bool("yes") is True
    assert as_bool("TRUE") is True
    assert as_bool("no") is False
    assert as_bool("maybe") is False  # default


def test_as_float():
    assert as_float("0.9") == 0.9
    assert as_float("0.85, some note") == 0.85
    assert as_float("garbage", default=0.3) == 0.3


def test_as_int():
    assert as_int("2", (1, 2, 3), 0) == 2
    assert as_int("3", (1, 2), 0) == 0  # not in allowed


def test_answers_to_dict():
    d = answers_to_dict(RAW, ["a", "b", "c", "d", "e", "f"])
    assert d["a"] == "normal"
    assert d["e"] == "buy"
    assert d["f"] is None


def test_dict_answer_shape_flattened():
    from crokbot.jev.parser import _flatten

    assert _flatten({"choice": "buy"}) == "buy"
    assert _flatten(["a", "b"]) == "a\nb"
    assert _flatten(0.9) == "0.9"