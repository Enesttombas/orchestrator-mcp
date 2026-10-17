import unicodedata


def _w(c):
    if unicodedata.combining(c):
        return 0
    return 2 if unicodedata.east_asian_width(c) in ('W', 'F') else 1


def _sw(s):
    return sum(_w(c) for c in s)


def wrap(text, width):
    """Word-wrap text into lines of at most `width` display columns (wide East Asian chars = 2, combining marks = 0).
    '\n' separates paragraphs and an empty paragraph yields an empty line ('a\n' -> ['a', '']); inside a paragraph runs
    of whitespace collapse to one space and lines carry no leading/trailing spaces. A word longer than the width is
    hard-broken at the width, never inside a wide character and never separating a combining mark from its base.
    ValueError if width < 2."""
    if width < 2:
        raise ValueError('width must be >= 2')
    lines = []
    for para in text.split('\n'):
        words = para.split()
        if not words:
            lines.append('')
            continue
        cur = ''
        for w in words:
            while _sw(w) > width:
                if cur:
                    lines.append(cur)
                    cur = ''
                k, used = 0, 0
                while k < len(w) and used + _w(w[k]) <= width:
                    used += _w(w[k])
                    k += 1
                lines.append(w[:k])
                w = w[k:]
            if not w:
                continue
            if cur and _sw(cur) + 1 + _sw(w) <= width:
                cur += ' ' + w
            else:
                if cur:
                    lines.append(cur)
                cur = w
        if cur:
            lines.append(cur)
    return lines
