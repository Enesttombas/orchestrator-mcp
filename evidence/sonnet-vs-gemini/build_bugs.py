"""Builds the bug-fix benchmark: 6 modules (3 medium, 3 hard), each with a buggy version, a reference version,
visible tests (given to the fixer) and hidden tests (only used for scoring). Validates the whole thing.
  python build_bugs.py            -> writes bugs/{buggy,ref,visible,hidden}/ and validates"""
import shutil
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
OUT = HERE / 'bugs'

MODS = {}

# ------------------------------------------------------------------ M1 slugify (medium)
MODS['slugify'] = dict(level='medium', ref=r'''import re
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
''', buggy=r'''import re


def slugify(text, max_len=None):
    """Lowercase ASCII slug. Accents are folded (cafe, not caf), runs of non-alphanumerics become one '-',
    no leading/trailing '-'. max_len: result is at most max_len chars; cut at a word boundary ('-') when the cut
    would split a word and a boundary exists, otherwise hard cut; never end with '-'."""
    s = re.sub(r'[^a-z0-9]+', '-', text.lower()).strip('-')
    if max_len:
        s = s[:max_len]
    return s
''', visible=r'''from slugify import slugify


def test_basic():
    assert slugify('Hello, World!') == 'hello-world'


def test_accents_are_folded():
    assert slugify('Café Münster') == 'cafe-munster'


def test_max_len_cuts_at_word_boundary():
    assert slugify('hello wonderful world', 10) == 'hello'


def test_no_trailing_dash():
    assert slugify('ab cd ef', 3) == 'ab'
''', hidden=r'''from slugify import slugify


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
''')

# ------------------------------------------------------------------ M2 csvparse (medium)
MODS['csvparse'] = dict(level='medium', ref=r'''def parse_line(line, delim=','):
    """RFC 4180-style single line. A quote opens a quoted field only at the start of a field; inside quotes a
    doubled quote is one literal quote and the delimiter is literal. Whitespace is preserved. A trailing delimiter
    yields a trailing empty field; '' parses to ['']. ValueError on an unterminated quote."""
    out, cur, inq, i, n = [], [], False, 0, len(line)
    while i < n:
        c = line[i]
        if inq:
            if c == '"':
                if i + 1 < n and line[i + 1] == '"':
                    cur.append('"')
                    i += 1
                else:
                    inq = False
            else:
                cur.append(c)
        elif c == '"' and not cur:
            inq = True
        elif c == delim:
            out.append(''.join(cur))
            cur = []
        else:
            cur.append(c)
        i += 1
    if inq:
        raise ValueError('unterminated quote')
    out.append(''.join(cur))
    return out
''', buggy=r'''def parse_line(line, delim=','):
    """RFC 4180-style single line. A quote opens a quoted field only at the start of a field; inside quotes a
    doubled quote is one literal quote and the delimiter is literal. Whitespace is preserved. A trailing delimiter
    yields a trailing empty field; '' parses to ['']. ValueError on an unterminated quote."""
    out, cur, inq = [], '', False
    for c in line:
        if c == '"':
            inq = not inq
        elif c == delim and not inq:
            out.append(cur)
            cur = ''
        else:
            cur += c
    if cur:
        out.append(cur)
    return out
''', visible=r'''import pytest
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
''', hidden=r'''import pytest
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
''')

# ------------------------------------------------------------------ M3 dates (medium)
MODS['bizdays'] = dict(level='medium', ref=r'''from datetime import timedelta


def business_days(start, end, holidays=()):
    """Number of business days (Mon-Fri, not in holidays) in the half-open range [start, end): start counts,
    end does not. A holiday counts once however often it is listed, and weekend holidays change nothing.
    If end < start the result is the negative of business_days(end, start)."""
    if end < start:
        return -business_days(end, start, holidays)
    hol = set(holidays)
    n, d = 0, start
    while d < end:
        if d.weekday() < 5 and d not in hol:
            n += 1
        d += timedelta(days=1)
    return n
''', buggy=r'''from datetime import timedelta


def business_days(start, end, holidays=()):
    """Number of business days (Mon-Fri, not in holidays) in the half-open range [start, end): start counts,
    end does not. A holiday counts once however often it is listed, and weekend holidays change nothing.
    If end < start the result is the negative of business_days(end, start)."""
    days = (end - start).days
    weeks, extra = divmod(days, 7)
    n = weeks * 5
    for i in range(extra + 1):
        if (start + timedelta(days=i)).weekday() < 5:
            n += 1
    n -= len([h for h in holidays if start <= h <= end])
    return n
''', visible=r'''from datetime import date
from bizdays import business_days

MON = date(2026, 1, 5)
NEXT_MON = date(2026, 1, 12)


def test_one_week():
    assert business_days(MON, NEXT_MON) == 5


def test_weekday_holiday():
    assert business_days(MON, NEXT_MON, [date(2026, 1, 7)]) == 4


def test_reversed_is_negative():
    assert business_days(NEXT_MON, MON) == -5


def test_end_is_exclusive():
    assert business_days(MON, MON) == 0
    assert business_days(MON, date(2026, 1, 6)) == 1
''', hidden=r'''from datetime import date
from bizdays import business_days


def test_weekend_holiday_ignored():
    assert business_days(date(2026, 1, 5), date(2026, 1, 12), [date(2026, 1, 10)]) == 5


def test_duplicate_holiday_counts_once():
    h = date(2026, 1, 7)
    assert business_days(date(2026, 1, 5), date(2026, 1, 12), [h, h]) == 4


def test_friday_to_monday():
    assert business_days(date(2026, 1, 9), date(2026, 1, 12)) == 1


def test_saturday_to_monday():
    assert business_days(date(2026, 1, 10), date(2026, 1, 12)) == 0


def test_three_weeks():
    assert business_days(date(2026, 1, 5), date(2026, 1, 26)) == 15
    assert business_days(date(2026, 1, 5), date(2026, 1, 26), [date(2026, 1, 6), date(2026, 1, 20)]) == 13


def test_holiday_on_end_not_counted():
    assert business_days(date(2026, 1, 5), date(2026, 1, 12), [date(2026, 1, 12)]) == 5


def test_holiday_outside_range():
    assert business_days(date(2026, 1, 5), date(2026, 1, 12), [date(2026, 2, 2)]) == 5


def test_reversed_with_holiday():
    assert business_days(date(2026, 1, 12), date(2026, 1, 5), [date(2026, 1, 7)]) == -4
''')

# ------------------------------------------------------------------ M4 eventbus (hard)
MODS['eventbus'] = dict(level='hard', ref=r'''class EmitError(Exception):
    def __init__(self, errors, results):
        super().__init__(f'{len(errors)} handler(s) failed')
        self.errors = errors
        self.results = results


class _H:
    __slots__ = ('fn', 'priority', 'seq', 'once', 'active')


class EventBus:
    """on/once register a handler and return an unsubscribe callable that removes ONLY that registration (idempotent).
    emit(event, *args) calls handlers by priority (higher first), ties in registration order, and returns their
    results in call order. Semantics during an emit: handlers removed before they are reached are skipped; handlers
    added during the emit are NOT called by it; a once-handler fires exactly once even if the same event is emitted
    again from inside a handler. A handler that raises does not stop the others; after all ran, EmitError
    (errors, results) is raised. off(event, fn) removes every registration of fn for that event."""

    def __init__(self):
        self._h = {}
        self._seq = 0

    def _add(self, event, fn, priority, once):
        self._seq += 1
        h = _H()
        h.fn, h.priority, h.seq, h.once, h.active = fn, priority, self._seq, once, True
        self._h.setdefault(event, []).append(h)

        def unsubscribe():
            self._drop(event, h)
        return unsubscribe

    def _drop(self, event, h):
        h.active = False
        lst = self._h.get(event, [])
        if h in lst:
            lst.remove(h)

    def on(self, event, fn, priority=0):
        return self._add(event, fn, priority, False)

    def once(self, event, fn, priority=0):
        return self._add(event, fn, priority, True)

    def off(self, event, fn):
        for h in list(self._h.get(event, [])):
            if h.fn == fn:
                self._drop(event, h)

    def emit(self, event, *args):
        snapshot = sorted(self._h.get(event, []), key=lambda h: (-h.priority, h.seq))
        results, errors = [], []
        for h in snapshot:
            if not h.active:
                continue
            if h.once:
                self._drop(event, h)
            try:
                results.append(h.fn(*args))
            except Exception as e:
                errors.append(e)
        if errors:
            raise EmitError(errors, results)
        return results
''', buggy=r'''class EmitError(Exception):
    def __init__(self, errors, results):
        super().__init__(f'{len(errors)} handler(s) failed')
        self.errors = errors
        self.results = results


class EventBus:
    """on/once register a handler and return an unsubscribe callable that removes ONLY that registration (idempotent).
    emit(event, *args) calls handlers by priority (higher first), ties in registration order, and returns their
    results in call order. Semantics during an emit: handlers removed before they are reached are skipped; handlers
    added during the emit are NOT called by it; a once-handler fires exactly once even if the same event is emitted
    again from inside a handler. A handler that raises does not stop the others; after all ran, EmitError
    (errors, results) is raised. off(event, fn) removes every registration of fn for that event."""

    def __init__(self):
        self._h = {}

    def on(self, event, fn, priority=0):
        self._h.setdefault(event, []).append((priority, fn, False))
        self._h[event].sort(key=lambda t: t[0], reverse=True)
        return lambda: self.off(event, fn)

    def once(self, event, fn, priority=0):
        self._h.setdefault(event, []).append((priority, fn, True))
        self._h[event].sort(key=lambda t: t[0], reverse=True)
        return lambda: self.off(event, fn)

    def off(self, event, fn):
        self._h[event] = [t for t in self._h.get(event, []) if t[1] != fn]

    def emit(self, event, *args):
        results = []
        for priority, fn, once in self._h.get(event, []):
            results.append(fn(*args))
            if once:
                self.off(event, fn)
        return results
''', visible=r'''import pytest
from eventbus import EventBus, EmitError


def test_priority_order_and_ties():
    bus, seen = EventBus(), []
    bus.on('e', lambda: seen.append('a'))
    bus.on('e', lambda: seen.append('b'))
    bus.on('e', lambda: seen.append('hi'), priority=5)
    bus.emit('e')
    assert seen == ['hi', 'a', 'b']


def test_once_fires_once():
    bus, seen = EventBus(), []
    bus.once('e', lambda: seen.append(1))
    bus.emit('e')
    bus.emit('e')
    assert seen == [1]


def test_failing_handler_does_not_stop_others():
    bus = EventBus()

    def boom():
        raise RuntimeError('x')
    bus.on('e', boom, priority=2)
    bus.on('e', lambda: 'ok')
    with pytest.raises(EmitError) as info:
        bus.emit('e')
    assert info.value.results == ['ok']
    assert len(info.value.errors) == 1


def test_unsubscribe():
    bus, seen = EventBus(), []
    off = bus.on('e', lambda: seen.append(1))
    off()
    bus.emit('e')
    assert seen == []
''', hidden=r'''import pytest
from eventbus import EventBus, EmitError


def test_removed_before_reached_is_skipped():
    bus, seen = EventBus(), []
    state = {}

    def first():
        seen.append('first')
        state['off']()
    bus.on('e', first, priority=2)
    state['off'] = bus.on('e', lambda: seen.append('second'), priority=1)
    bus.emit('e')
    assert seen == ['first']


def test_added_during_emit_not_called_by_it():
    bus, seen = EventBus(), []

    def adder():
        seen.append('adder')
        bus.on('e', lambda: seen.append('late'))
    bus.on('e', adder)
    bus.emit('e')
    assert seen == ['adder']
    bus.emit('e')
    assert seen == ['adder', 'adder', 'late']


def test_once_with_nested_emit_fires_exactly_once():
    bus, seen = EventBus(), []

    def h():
        seen.append(1)
        if len(seen) < 3:
            bus.emit('e')
    bus.once('e', h)
    bus.emit('e')
    assert seen == [1]


def test_unsubscribe_only_that_registration_and_idempotent():
    bus, seen = EventBus(), []

    def f():
        seen.append('f')
    off1 = bus.on('e', f)
    bus.on('e', f)
    off1()
    off1()
    bus.emit('e')
    assert seen == ['f']


def test_off_removes_all_registrations_of_fn():
    bus, seen = EventBus(), []

    def f():
        seen.append('f')
    bus.on('e', f)
    bus.once('e', f)
    bus.off('e', f)
    bus.emit('e')
    assert seen == []


def test_unknown_event_and_results_order():
    bus = EventBus()
    assert bus.emit('nothing') == []
    bus.on('e', lambda x: x + 1, priority=1)
    bus.on('e', lambda x: x * 10)
    assert bus.emit('e', 2) == [3, 20]


def test_once_handler_that_raises_is_still_consumed():
    bus = EventBus()

    def boom():
        raise ValueError('x')
    bus.once('e', boom)
    with pytest.raises(EmitError):
        bus.emit('e')
    assert bus.emit('e') == []


def test_multiple_errors_collected():
    bus = EventBus()
    for _ in range(3):
        bus.on('e', lambda: (_ for _ in ()).throw(RuntimeError('r')))
    with pytest.raises(EmitError) as info:
        bus.emit('e')
    assert len(info.value.errors) == 3
''')

# ------------------------------------------------------------------ M5 graph (hard)
MODS['toposort'] = dict(level='hard', ref=r'''import heapq


class CycleError(Exception):
    def __init__(self, cycle):
        super().__init__(' -> '.join(map(str, cycle)))
        self.cycle = cycle


def _find_cycle(deps, rest):
    cur = min(rest)
    path, seen = [cur], {cur: 0}
    while True:
        nxt = min(d for d in deps.get(cur, ()) if d in rest)
        if nxt in seen:
            return path[seen[nxt]:] + [nxt]
        seen[nxt] = len(path)
        path.append(nxt)
        cur = nxt


def toposort(deps):
    """deps maps node -> iterable of nodes it depends on (those come first). Nodes that appear only as dependencies
    are included. Deterministic: whenever several nodes are ready, the smallest goes first. Must handle very deep
    chains (no recursion limit problems). On a cycle raise CycleError whose .cycle is a SIMPLE cycle: first == last
    and every consecutive pair (a, b) means a depends on b; a self-dependency is a cycle [a, a]."""
    nodes = set(deps)
    for ds in deps.values():
        nodes.update(ds)
    indeg = {n: 0 for n in nodes}
    rev = {n: [] for n in nodes}
    for n, ds in deps.items():
        for d in set(ds):
            indeg[n] += 1
            rev[d].append(n)
    ready = [n for n in nodes if indeg[n] == 0]
    heapq.heapify(ready)
    out = []
    while ready:
        n = heapq.heappop(ready)
        out.append(n)
        for m in rev[n]:
            indeg[m] -= 1
            if indeg[m] == 0:
                heapq.heappush(ready, m)
    if len(out) < len(nodes):
        raise CycleError(_find_cycle(deps, nodes - set(out)))
    return out
''', buggy=r'''class CycleError(Exception):
    def __init__(self, cycle):
        super().__init__(' -> '.join(map(str, cycle)))
        self.cycle = cycle


def toposort(deps):
    """deps maps node -> iterable of nodes it depends on (those come first). Nodes that appear only as dependencies
    are included. Deterministic: whenever several nodes are ready, the smallest goes first. Must handle very deep
    chains (no recursion limit problems). On a cycle raise CycleError whose .cycle is a SIMPLE cycle: first == last
    and every consecutive pair (a, b) means a depends on b; a self-dependency is a cycle [a, a]."""
    seen, out = set(), []

    def visit(n, stack):
        if n in stack:
            raise CycleError(stack + [n])
        if n in seen:
            return
        seen.add(n)
        for d in deps.get(n, ()):
            visit(d, stack + [n])
        out.append(n)
    for n in deps:
        visit(n, [])
    return out
''', visible=r'''import pytest
from toposort import toposort, CycleError


def test_simple_chain():
    assert toposort({'c': ['b'], 'b': ['a']}) == ['a', 'b', 'c']


def test_smallest_ready_first():
    assert toposort({'z': [], 'a': [], 'm': ['z']}) == ['a', 'z', 'm']


def test_diamond_is_not_a_cycle():
    deps = {'d': ['b', 'c'], 'b': ['a'], 'c': ['a']}
    assert toposort(deps) == ['a', 'b', 'c', 'd']


def test_cycle_detected():
    with pytest.raises(CycleError):
        toposort({'a': ['b'], 'b': ['a']})
''', hidden=r'''import pytest
from toposort import toposort, CycleError


def _is_simple_cycle(deps, cyc):
    assert cyc[0] == cyc[-1] and len(cyc) >= 2
    assert len(set(cyc[:-1])) == len(cyc) - 1
    for a, b in zip(cyc, cyc[1:]):
        assert b in deps.get(a, ())


def test_cycle_path_excludes_tail_prefix():
    deps = {'x': ['a'], 'a': ['b'], 'b': ['c'], 'c': ['a']}
    with pytest.raises(CycleError) as info:
        toposort(deps)
    _is_simple_cycle(deps, info.value.cycle)
    assert 'x' not in info.value.cycle


def test_self_dependency():
    with pytest.raises(CycleError) as info:
        toposort({'a': ['a']})
    assert info.value.cycle == ['a', 'a']


def test_deep_chain_no_recursion_error():
    n = 6000
    deps = {i: [i - 1] for i in range(1, n)}
    assert toposort(deps) == list(range(n))


def test_lexicographic_independent_of_insertion_order():
    d1 = {'b': [], 'a': [], 'c': ['a']}
    d2 = {'c': ['a'], 'a': [], 'b': []}
    assert toposort(d1) == toposort(d2) == ['a', 'b', 'c']


def test_dependency_only_nodes_and_duplicates():
    assert toposort({'b': ['a', 'a']}) == ['a', 'b']
    assert toposort({}) == []


def test_two_cycles_still_reports_a_valid_one():
    deps = {'a': ['b'], 'b': ['a'], 'x': ['y'], 'y': ['x'], 'ok': []}
    with pytest.raises(CycleError) as info:
        toposort(deps)
    _is_simple_cycle(deps, info.value.cycle)


def test_wide_diamond_lattice():
    deps = {f'm{i}': ['top'] for i in range(50)}
    deps['bottom'] = [f'm{i}' for i in range(50)]
    out = toposort(deps)
    assert out[0] == 'top' and out[-1] == 'bottom' and len(out) == 52
''')

# ------------------------------------------------------------------ M6 wrap (hard)
MODS['wrap'] = dict(level='hard', ref=r'''import unicodedata


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
''', buggy=r'''def wrap(text, width):
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
''', visible=r'''import pytest
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
''', hidden=r'''import unicodedata
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
''')


def build():
    shutil.rmtree(OUT, ignore_errors=True)
    for sub in ('buggy', 'ref', 'visible', 'hidden'):
        (OUT / sub).mkdir(parents=True)
    for name, m in MODS.items():
        (OUT / 'buggy' / f'{name}.py').write_text(m['buggy'], encoding='utf-8')
        (OUT / 'ref' / f'{name}.py').write_text(m['ref'], encoding='utf-8')
        (OUT / 'visible' / f'test_{name}.py').write_text(m['visible'], encoding='utf-8')
        (OUT / 'hidden' / f'test_{name}_hidden.py').write_text(m['hidden'], encoding='utf-8')


def pytest_counts(workdir, files):
    r = subprocess.run([sys.executable, '-X', 'utf8', '-m', 'pytest', '-q', '-p', 'no:cacheprovider', *files],
                       cwd=workdir, capture_output=True, text=True, timeout=120)
    line = [l for l in r.stdout.splitlines() if ' passed' in l or ' failed' in l or 'error' in l]
    return r.returncode, (line[-1] if line else r.stdout[-200:])


def validate():
    import tempfile
    ok = True
    for name in MODS:
        for which, src in (('buggy', 'buggy'), ('ref', 'ref')):
            with tempfile.TemporaryDirectory() as tmp:
                tmp = Path(tmp)
                shutil.copy(OUT / src / f'{name}.py', tmp)
                shutil.copy(OUT / 'visible' / f'test_{name}.py', tmp)
                shutil.copy(OUT / 'hidden' / f'test_{name}_hidden.py', tmp)
                v = pytest_counts(tmp, [f'test_{name}.py'])
                h = pytest_counts(tmp, [f'test_{name}_hidden.py'])
                print(f'{name:9} {MODS[name]["level"]:6} {which:5} visible rc={v[0]} [{v[1]}]  hidden rc={h[0]} [{h[1]}]')
                good = (v[0] == 0 and h[0] == 0) if which == 'ref' else (v[0] != 0 and h[0] != 0)
                ok &= good
    print('VALID' if ok else 'INVALID')
    return ok


if __name__ == '__main__':
    build()
    sys.exit(0 if validate() else 1)
