from slugify import slugify


def test_exact_fit_boundary():
    assert slugify('Crème brûlée recipe', 12) == 'creme-brulee'


def test_hard_cut_when_no_boundary():
    assert slugify('supercalifragilistic', 5) == 'super'


def test_empty_and_symbols():
    assert slugify('') == ''
    assert slugify('---') == ''
    assert slugify('  !!  ') == ''


def test_mixed_accents():
    assert slugify('ÀÉÎ ñ') == 'aei-n'


def test_max_len_zero():
    assert slugify('abc def', 0) == ''


def test_unchanged_when_short():
    assert slugify('one two', 20) == 'one-two'
    assert slugify('one two', 7) == 'one-two'
