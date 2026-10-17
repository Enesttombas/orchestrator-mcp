import pytest
from csvparse import parse_line


def test_empty_line():
    assert parse_line('') == ['']


def test_empty_quoted_field():
    assert parse_line('"",x') == ['', 'x']


def test_whitespace_preserved():
    assert parse_line(' a , b ') == [' a ', ' b ']


def test_custom_delimiter():
    assert parse_line('a;b', ';') == ['a', 'b']
    assert parse_line('a,b;c', ';') == ['a,b', 'c']


def test_lone_delimiters():
    assert parse_line(',') == ['', '']
    assert parse_line(',,') == ['', '', '']


def test_embedded_quote_char_not_at_start():
    assert parse_line('ab"c,d') == ['ab"c', 'd']


def test_escaped_quote_mid_field():
    assert parse_line('x,"a""",y') == ['x', 'a"', 'y']


def test_unterminated_after_escape():
    with pytest.raises(ValueError):
        parse_line('"abc""')
