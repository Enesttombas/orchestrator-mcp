import re
import unicodedata


def slugify(text, max_len=None):
    """Lowercase ASCII slug. Accents are folded (cafe, not caf), runs of non-alphanumerics become one '-',
    no leading/trailing '-'. max_len: result is at most max_len chars; cut at a word boundary ('-') when the cut
    would split a word and a boundary exists, otherwise hard cut; never end with '-'."""
    s = unicodedata.normalize('NFKD', text)
    s = ''.join(c for c in s if not unicodedata.combining(c)).lower()
    s = re.sub(r'[^a-z0-9]+', '-', s).strip('-')
    if max_len is not None and len(s) > max_len:
        if s[max_len] != '-':
            idx = s[:max_len].rfind('-')
            s = s[:idx] if idx > 0 else s[:max_len]
        else:
            s = s[:max_len]
        s = s.strip('-')
    return s
