import pytest
from csvparse import parse_line


def test_plain():
    assert parse_line('a,b,c') == ['a', 'b', 'c']


def test_quoted_delimiter():
    assert parse_line('a,"b,c",d') == ['a', 'b,c', 'd']


def test_trailing_empty_field():
    assert parse_line('a,b,') == ['a', 'b', '']


def test_escaped_quote():
    assert parse_line('"say ""hi"""') == ['say "hi"']


def test_unterminated():
    with pytest.raises(ValueError):
        parse_line('a,"b')
