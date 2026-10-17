from slugify import slugify


def test_basic():
    assert slugify('Hello, World!') == 'hello-world'


def test_accents_are_folded():
    assert slugify('Café Münster') == 'cafe-munster'


def test_max_len_cuts_at_word_boundary():
    assert slugify('hello wonderful world', 10) == 'hello'


def test_no_trailing_dash():
    assert slugify('ab cd ef', 3) == 'ab'
