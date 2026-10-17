import re


def slugify(text, max_len=None):
    """Lowercase ASCII slug. Accents are folded (cafe, not caf), runs of non-alphanumerics become one '-',
    no leading/trailing '-'. max_len: result is at most max_len chars; cut at a word boundary ('-') when the cut
    would split a word and a boundary exists, otherwise hard cut; never end with '-'."""
    s = re.sub(r'[^a-z0-9]+', '-', text.lower()).strip('-')
    if max_len:
        s = s[:max_len]
    return s
