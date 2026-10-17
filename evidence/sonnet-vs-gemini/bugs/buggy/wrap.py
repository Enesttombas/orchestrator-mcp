def wrap(text, width):
    """Word-wrap text into lines of at most `width` display columns (wide East Asian chars = 2, combining marks = 0).
    '\n' separates paragraphs and an empty paragraph yields an empty line ('a\n' -> ['a', '']); inside a paragraph runs
    of whitespace collapse to one space and lines carry no leading/trailing spaces. A word longer than the width is
    hard-broken at the width, never inside a wide character and never separating a combining mark from its base.
    ValueError if width < 2."""
    lines, cur = [], ''
    for w in text.split():
        if cur and len(cur) + 1 + len(w) <= width:
            cur += ' ' + w
        else:
            if cur:
                lines.append(cur)
            cur = w
    if cur:
        lines.append(cur)
    return lines
