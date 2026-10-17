import pytest
from wrap import wrap


def test_basic_wrap():
    assert wrap('the quick brown fox', 9) == ['the quick', 'brown fox']


def test_paragraphs_preserved():
    assert wrap('a b\n\nc d', 10) == ['a b', '', 'c d']


def test_long_word_is_hard_broken():
    assert wrap('abcdefghij', 4) == ['abcd', 'efgh', 'ij']


def test_wide_characters_count_double():
    assert wrap('日本語のテキスト', 6) == ['日本語', 'のテキ', 'スト']


def test_width_too_small():
    with pytest.raises(ValueError):
        wrap('x', 1)
