import unicodedata
import pytest
from wrap import wrap


def _cols(s):
    return sum(0 if unicodedata.combining(c) else 2 if unicodedata.east_asian_width(c) in ('W', 'F') else 1 for c in s)


def test_mixed_wide_and_narrow_words():
    assert wrap('ab 日本 cd', 5) == ['ab', '日本', 'cd']


def test_combining_mark_has_zero_width():
    word = 'é' * 4
    assert wrap(word, 4) == [word]
    assert _cols(word) == 4


def test_break_never_separates_combining_mark():
    out = wrap('é' * 6, 4)
    assert out == ['é' * 4, 'é' * 2]


def test_whitespace_collapsed_and_trimmed():
    assert wrap('  hello   world  ', 20) == ['hello world']


def test_trailing_newline_gives_empty_line():
    assert wrap('a\n', 5) == ['a', '']
    assert wrap('', 5) == ['']


def test_no_line_exceeds_width():
    text = 'Supercalifragilistic 日本語のテキスト expialidocious and more words here'
    for width in (2, 3, 5, 8, 13):
        for line in wrap(text, width):
            assert _cols(line) <= width


def test_wide_char_not_split_when_width_odd():
    assert wrap('日本語', 3) == ['日', '本', '語']


def test_long_word_after_short_words():
    assert wrap('ab abcdefghij cd', 4) == ['ab', 'abcd', 'efgh', 'ij', 'cd']


def test_paragraph_whitespace_only_line():
    assert wrap('a\n   \nb', 5) == ['a', '', 'b']
