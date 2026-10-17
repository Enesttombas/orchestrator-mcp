"""Six hard single-file tasks (spec in the stub docstring, graded by a local script the model can read but not edit).
Built so a first attempt plausibly fails on an edge rule; used for the full-vs-clean retry-context A/B."""
import sys

PY = sys.executable
HEAD = 'import os, sys\nsys.path.insert(0, os.getcwd())\n'

STUBS = {
 'intervals.py': '''def merge_intervals(intervals):
    """intervals: list of (lo, hi, lo_closed, hi_closed). Return the merged list sorted by lo, same tuple shape.
    Two intervals merge when they overlap, or touch at a point that at least one of them includes.
    Empty intervals (lo > hi, or lo == hi unless both ends closed) are dropped.
    Merged closedness: an end is closed if any interval that ends/starts exactly there is closed."""
    raise NotImplementedError
''',
 'money.py': '''def split_money(total_cents, weights):
    """Split an integer amount of cents by integer weights so the parts sum EXACTLY to total_cents.
    Largest-remainder method; ties in remainder go to the lower index; weight 0 always gets 0.
    Negative totals split symmetrically (split abs, negate). ValueError if weights is empty, any weight < 0,
    or all weights are 0."""
    raise NotImplementedError
''',
 'semver.py': '''def satisfies(version, spec):
    """Does semver `version` ("1.2.3", "1.2.3-beta.1") satisfy `spec`?
    spec = sets joined by "||"; a set = comparators joined by spaces. Comparators: >=,>,<=,<,= or bare version,
    ^X.Y.Z (caret), ~X.Y.Z (tilde), "*" / "x" wildcards in X.Y.x / X.x forms.
    Caret keeps the left-most non-zero part: ^1.2.3 = >=1.2.3 <2.0.0, ^0.2.3 = >=0.2.3 <0.3.0, ^0.0.3 = >=0.0.3 <0.0.4.
    Tilde: ~1.2.3 = >=1.2.3 <1.3.0. Precedence: 1.0.0-alpha < 1.0.0-alpha.1 < 1.0.0-beta < 1.0.0
    (numeric identifiers compare as numbers and sort before alphanumeric ones).
    A version with a prerelease tag only satisfies a set if some comparator in that same set names the
    same major.minor.patch with a prerelease tag."""
    raise NotImplementedError
''',
 'bucket.py': '''class TokenBucket:
    """Token bucket. Starts full. `rate` tokens/second refill, never above `capacity`; tokens are fractional.
    clock() returns seconds. consume(n=1) -> bool: all-or-nothing, a failed call takes nothing.
    retry_after(n=1) -> seconds until n tokens are available (0 if available now, float('inf') if n > capacity).
    Time going backwards neither adds nor removes tokens and the bucket keeps measuring from the latest time it has seen."""

    def __init__(self, rate, capacity, clock):
        raise NotImplementedError
''',
 'cron.py': '''def next_run(expr, after):
    """expr: 5 fields "minute hour day-of-month month day-of-week". Field syntax: *, N, A-B, A,B,C, */S, A-B/S.
    Day-of-week 0 or 7 = Sunday. If BOTH day-of-month and day-of-week are restricted (not *), a day matches when
    EITHER matches (vixie cron); if one is *, only the other applies.
    Return the first datetime STRICTLY after `after` (a naive datetime) at second 0 whose fields all match.
    ValueError on a malformed expression or out-of-range value."""
    raise NotImplementedError
''',
 'wlru.py': '''class WeightedLRU:
    """LRU cache bounded by total weight. put(key, value, weight) -> bool.
    A weight above max_weight is rejected (returns False, nothing changes, nothing evicted).
    Otherwise least-recently-used entries are evicted until the new entry fits; on_evict(key, value) is called
    for each evicted entry, in eviction order. get(key, default=None) marks the key most-recently-used.
    Replacing an existing key swaps value+weight, refreshes recency, and does NOT call on_evict for the old value.
    delete(key) -> bool never calls on_evict. len() is the entry count; total_weight property."""

    def __init__(self, max_weight, on_evict=None):
        raise NotImplementedError
''',
}

CHECKS = {
 'check_intervals.py': HEAD + '''from intervals import merge_intervals as m
T, F = True, False
assert m([]) == []
assert m([(1, 3, T, F), (3, 5, F, T)]) == [(1, 3, T, F), (3, 5, F, T)], "open-open touch must not merge"
assert m([(1, 3, T, T), (3, 5, F, T)]) == [(1, 5, T, T)]
assert m([(1, 3, T, F), (3, 5, T, T)]) == [(1, 5, T, T)]
assert m([(5, 9, T, T), (1, 6, F, F)]) == [(1, 9, F, T)]
assert m([(1, 5, T, F), (1, 5, T, T)]) == [(1, 5, T, T)]
assert m([(1, 5, F, F), (1, 5, T, F)]) == [(1, 5, T, F)]
assert m([(2, 2, T, T)]) == [(2, 2, T, T)]
assert m([(2, 2, T, F), (7, 6, T, T)]) == []
assert m([(1, 2, T, T), (2, 2, T, T), (2, 4, F, F)]) == [(1, 4, T, F)]
assert m([(1, 10, T, F), (2, 3, T, T), (10, 12, F, F)]) == [(1, 10, T, F), (10, 12, F, F)]
assert m([(1, 10, T, F), (3, 10, T, T)]) == [(1, 10, T, T)]
print("ok")
''',
 'check_money.py': HEAD + '''from money import split_money as s
assert s(100, [1, 1, 1]) == [34, 33, 33]
assert s(100, [1, 1, 1, 1, 1, 1]) == [17, 17, 17, 17, 16, 16]
assert s(10, [0, 1, 1]) == [0, 5, 5]
assert s(1, [1, 1]) == [1, 0]
assert s(0, [3, 4]) == [0, 0]
assert s(-100, [1, 1, 1]) == [-34, -33, -33]
assert s(100, [3, 1]) == [75, 25]
assert s(7, [1, 2, 4]) == [1, 2, 4]
assert s(5, [0, 0, 1]) == [0, 0, 5]
assert sum(s(1000003, [7, 13, 29, 1, 0, 50])) == 1000003
for bad in ([], [0, 0], [1, -1], [-2]):
    try:
        s(10, bad)
    except ValueError:
        continue
    raise AssertionError(f"no ValueError for {bad}")
r = s(10, [1, 1, 1, 0])
assert r == [4, 3, 3, 0], r
print("ok")
''',
 'check_semver.py': HEAD + '''from semver import satisfies as ok
assert ok("1.2.3", "^1.2.3") and ok("1.9.9", "^1.2.3") and not ok("2.0.0", "^1.2.3") and not ok("1.2.2", "^1.2.3")
assert ok("0.2.9", "^0.2.3") and not ok("0.3.0", "^0.2.3")
assert ok("0.0.3", "^0.0.3") and not ok("0.0.4", "^0.0.3")
assert ok("1.2.9", "~1.2.3") and not ok("1.3.0", "~1.2.3")
assert ok("1.5.0", ">=1.2.0 <2.0.0") and not ok("2.0.0", ">=1.2.0 <2.0.0")
assert ok("3.0.0", "^1.0.0 || ^3.0.0") and not ok("2.0.0", "^1.0.0 || ^3.0.0")
assert ok("1.4.7", "1.x") and ok("1.4.7", "1.4.x") and not ok("1.5.0", "1.4.x") and ok("9.9.9", "*")
assert ok("1.2.3", "1.2.3") and ok("1.2.3", "=1.2.3") and not ok("1.2.4", "=1.2.3")
assert not ok("1.0.0-beta", ">=1.0.0"), "prerelease is below the release"
assert ok("1.0.0", ">1.0.0-beta")
assert ok("1.0.0-beta", ">1.0.0-alpha") and ok("1.0.0-alpha.1", ">1.0.0-alpha") and ok("1.0.0-beta", ">1.0.0-alpha.1")
assert ok("1.0.0-alpha.2", ">1.0.0-alpha.1") and ok("1.0.0-alpha.10", ">1.0.0-alpha.9"), "numeric ids compare as numbers"
assert ok("1.0.0-alpha.beta", ">1.0.0-alpha.1"), "alphanumeric sorts after numeric"
assert ok("1.2.3-beta.2", ">=1.2.3-beta.1 <1.2.4")
assert not ok("1.2.4-beta.1", ">=1.2.3-beta.1 <1.3.0"), "prerelease of another tuple is excluded"
assert not ok("1.5.0-rc.1", "^1.2.3")
assert ok("1.2.3-beta.2", "^1.2.3-beta.1")
assert ok("2.0.0", "<1.0.0 || >=2.0.0")
print("ok")
''',
 'check_bucket.py': HEAD + '''from bucket import TokenBucket
t = [0.0]
b = TokenBucket(2, 10, lambda: t[0])
assert b.consume(10) and not b.consume(1)
assert b.retry_after(1) == 0.5 and b.retry_after(4) == 2.0
t[0] = 1.0
assert b.consume(2) and not b.consume(1)
t[0] = 100.0
assert b.consume(10) and not b.consume(1), "refill never exceeds capacity"
t[0] = 100.25
assert not b.consume(1) and abs(b.retry_after(1) - 0.25) < 1e-9, b.retry_after(1)
assert b.retry_after(11) == float("inf")
b2 = TokenBucket(1, 5, lambda: t[0])
assert b2.consume(5)
t[0] = 102.25
assert not b2.consume(3), "only 2 tokens"
assert b2.consume(2), "failed consume must not have taken tokens"
t[0] = 50.0
b3 = TokenBucket(1, 5, lambda: t[0])
assert b3.consume(5)
t[0] = 40.0
assert not b3.consume(1), "backwards clock must not add or remove tokens"
t[0] = 52.0
assert b3.consume(2) and not b3.consume(1)
b4 = TokenBucket(0.5, 3, lambda: t[0])
assert b4.consume(3) and b4.retry_after(1) == 2.0
t[0] += 1.0
assert abs(b4.retry_after(1) - 1.0) < 1e-9
print("ok")
''',
 'check_cron.py': HEAD + '''from datetime import datetime as D
from cron import next_run as n
assert n("*/15 * * * *", D(2026, 1, 1, 10, 7)) == D(2026, 1, 1, 10, 15)
assert n("*/15 * * * *", D(2026, 1, 1, 10, 15)) == D(2026, 1, 1, 10, 30), "strictly after"
assert n("0 9 * * *", D(2026, 1, 1, 9, 0)) == D(2026, 1, 2, 9, 0)
assert n("30 23 31 * *", D(2026, 2, 1)) == D(2026, 3, 31, 23, 30), "February has no 31st"
assert n("0 0 29 2 *", D(2026, 3, 1)) == D(2028, 2, 29, 0, 0), "leap day"
assert n("0 12 * * 1", D(2026, 1, 1)) == D(2026, 1, 5, 12, 0), "Monday"
assert n("0 12 * * 7", D(2026, 1, 1)) == D(2026, 1, 4, 12, 0), "7 is Sunday"
assert n("0 12 * * 0", D(2026, 1, 1)) == D(2026, 1, 4, 12, 0)
assert n("0 8 15 * 1", D(2026, 1, 1)) == D(2026, 1, 5, 8, 0), "dom OR dow when both restricted"
assert n("0 8 15 * 1", D(2026, 1, 6)) == D(2026, 1, 12, 8, 0)
assert n("0 8 15 * 1", D(2026, 1, 13)) == D(2026, 1, 15, 8, 0)
assert n("5,10-12 1-2/1 * * *", D(2026, 1, 1, 1, 12)) == D(2026, 1, 1, 2, 5)
assert n("10-30/10 * * * *", D(2026, 1, 1, 0, 0)) == D(2026, 1, 1, 0, 10)
assert n("10-30/10 * * * *", D(2026, 1, 1, 0, 20)) == D(2026, 1, 1, 0, 30)
assert n("59 23 31 12 *", D(2026, 12, 31, 23, 59)) == D(2027, 12, 31, 23, 59)
assert n("0 0 1 1 *", D(2026, 6, 15, 8, 30, 45)) == D(2027, 1, 1, 0, 0)
for bad in ("* * * *", "60 * * * *", "* 24 * * *", "* * 0 * *", "* * * 13 *", "*/0 * * * *", "a * * * *", "* * * * 8"):
    try:
        n(bad, D(2026, 1, 1))
    except ValueError:
        continue
    raise AssertionError("no ValueError for " + bad)
print("ok")
''',
 'check_wlru.py': HEAD + '''from wlru import WeightedLRU
ev = []
c = WeightedLRU(10, lambda k, v: ev.append((k, v)))
assert c.put("a", 1, 4) and c.put("b", 2, 4)
assert c.get("a") == 1
assert c.put("c", 3, 4) and ev == [("b", 2)], ev
assert c.total_weight == 8 and len(c) == 2
assert not c.put("huge", 0, 11) and ev == [("b", 2)] and c.get("huge") is None and len(c) == 2
assert c.put("a", 10, 2), "replace shrinks"
assert ev == [("b", 2)], "replace must not call on_evict"
assert c.total_weight == 6
assert c.put("d", 4, 4) and ev == [("b", 2)]
assert c.put("e", 5, 10), "exact fit evicts everything else"
assert ev == [("b", 2), ("c", 3), ("a", 10), ("d", 4)], ev
assert len(c) == 1 and c.total_weight == 10
assert c.delete("e") is True and c.delete("e") is False and len(ev) == 4
assert c.get("zzz", "dflt") == "dflt"
c2 = WeightedLRU(5)
assert c2.put("x", 1, 3) and c2.put("y", 2, 3) and c2.get("x") is None and c2.get("y") == 2
c3 = WeightedLRU(6, lambda k, v: ev.append(("c3", k)))
c3.put("p", 1, 3); c3.put("q", 2, 3); c3.get("p"); c3.put("r", 3, 3)
assert ev[-1] == ("c3", "q") and c3.get("p") == 1
c3.put("p", 9, 3); c3.put("s", 4, 3)
assert ev[-1] == ("c3", "r"), "replacing p refreshed its recency"
print("ok")
''',
}

REFS = {
 'intervals.py': '''def merge_intervals(intervals):
    xs = [t for t in intervals if not (t[0] > t[1] or (t[0] == t[1] and not (t[2] and t[3])))]
    xs.sort(key=lambda t: (t[0], not t[2]))
    out = []
    for lo, hi, lc, hc in xs:
        if out:
            plo, phi, plc, phc = out[-1]
            if lo < phi or (lo == phi and (phc or lc)):
                if hi > phi:
                    out[-1] = (plo, hi, plc, hc)
                elif hi == phi:
                    out[-1] = (plo, phi, plc, phc or hc)
                continue
        out.append((lo, hi, lc, hc))
    return out
''',
 'money.py': '''def split_money(total_cents, weights):
    if not weights or any(w < 0 for w in weights) or sum(weights) == 0:
        raise ValueError("bad weights")
    sign = -1 if total_cents < 0 else 1
    total = abs(total_cents)
    whole = sum(weights)
    parts = [total * w // whole for w in weights]
    rem = [(total * w % whole, i) for i, w in enumerate(weights) if w]
    rem.sort(key=lambda r: (-r[0], r[1]))
    for _, i in rem[:total - sum(parts)]:
        parts[i] += 1
    return [sign * p for p in parts]
''',
 'semver.py': '''import re


def _parse(v):
    m = re.fullmatch(r"(\\d+)\\.(\\d+)\\.(\\d+)(?:-([0-9A-Za-z.-]+))?", v)
    return int(m[1]), int(m[2]), int(m[3]), tuple(m[4].split(".")) if m[4] else ()


def _pre_key(pre):
    return [(0, int(x), "") if x.isdigit() else (1, 0, x) for x in pre]


def _cmp(a, b):
    if a[:3] != b[:3]:
        return -1 if a[:3] < b[:3] else 1
    if a[3] == b[3]:
        return 0
    if not a[3]:
        return 1
    if not b[3]:
        return -1
    ka, kb = _pre_key(a[3]), _pre_key(b[3])
    return -1 if ka < kb else 1


def _expand(tok):
    if tok in ("*", "x", "X", ""):
        return [(">=", (0, 0, 0, ()))]
    if tok[0] in "^~":
        base = _parse(tok[1:])
        M, m, p, _ = base
        if tok[0] == "~":
            hi = (M, m + 1, 0, ())
        elif M:
            hi = (M + 1, 0, 0, ())
        elif m:
            hi = (0, m + 1, 0, ())
        else:
            hi = (0, 0, p + 1, ())
        return [(">=", base), ("<", hi)]
    m = re.fullmatch(r"(>=|<=|>|<|=)?\\s*(.+)", tok)
    op, rest = m[1] or "=", m[2]
    parts = rest.split(".")
    if any(x in ("x", "X", "*") for x in parts) or len(parts) < 3:
        nums = []
        for x in parts:
            if x in ("x", "X", "*"):
                break
            nums.append(int(x))
        if not nums:
            return [(">=", (0, 0, 0, ()))]
        lo = tuple(nums + [0] * (3 - len(nums))) + ((),)
        up = list(nums)
        up[-1] += 1
        hi = tuple(up + [0] * (3 - len(up))) + ((),)
        return [(">=", lo), ("<", hi)]
    return [(op, _parse(rest))]


def satisfies(version, spec):
    v = _parse(version)
    for group in spec.split("||"):
        comps = []
        for tok in group.split():
            comps += _expand(tok)
        if not comps:
            comps = _expand("*")
        good = True
        for op, c in comps:
            r = _cmp(v, c)
            good &= {">=": r >= 0, ">": r > 0, "<=": r <= 0, "<": r < 0, "=": r == 0}[op]
        if good and v[3]:
            good = any(c[3] and c[:3] == v[:3] for _, c in comps)
        if good:
            return True
    return False
''',
 'bucket.py': '''class TokenBucket:
    def __init__(self, rate, capacity, clock):
        self.rate, self.capacity, self.clock = rate, capacity, clock
        self.tokens = float(capacity)
        self.last = clock()

    def _refill(self):
        now = self.clock()
        if now > self.last:
            self.tokens = min(self.capacity, self.tokens + (now - self.last) * self.rate)
            self.last = now

    def consume(self, n=1):
        self._refill()
        if n > self.tokens + 1e-12:
            return False
        self.tokens = max(0.0, self.tokens - n)
        return True

    def retry_after(self, n=1):
        if n > self.capacity:
            return float("inf")
        self._refill()
        return max(0.0, (n - self.tokens) / self.rate)
''',
 'cron.py': '''from datetime import datetime, timedelta

_RANGES = [(0, 59), (0, 23), (1, 31), (1, 12), (0, 7)]


def _field(text, lo, hi):
    out = set()
    for part in text.split(","):
        step = 1
        if "/" in part:
            part, s = part.split("/")
            step = int(s)
            if step < 1:
                raise ValueError("step")
        if part == "*":
            a, b = lo, hi
        elif "-" in part:
            a, b = (int(x) for x in part.split("-"))
        else:
            a = b = int(part)
        if a < lo or b > hi or a > b:
            raise ValueError("range")
        out.update(range(a, b + 1, step))
    return out


def next_run(expr, after):
    f = expr.split()
    if len(f) != 5:
        raise ValueError("fields")
    try:
        sets = [_field(t, *r) for t, r in zip(f, _RANGES)]
    except ValueError:
        raise
    except Exception as e:
        raise ValueError(str(e))
    dows = {d % 7 for d in sets[4]}
    dom_any, dow_any = f[2].startswith("*"), f[4].startswith("*")
    t = after.replace(second=0, microsecond=0) + timedelta(minutes=1)
    for _ in range(366 * 5 * 24 * 60):
        if t.month in sets[3] and t.hour in sets[1] and t.minute in sets[0]:
            dom_ok, dow_ok = t.day in sets[2], (t.isoweekday() % 7) in dows
            if (dom_ok and dow_ok) if (dom_any or dow_any) else (dom_ok or dow_ok):
                return t
        t += timedelta(minutes=1)
    raise ValueError("no match")
''',
 'wlru.py': '''from collections import OrderedDict


class WeightedLRU:
    def __init__(self, max_weight, on_evict=None):
        self.max_weight, self.on_evict = max_weight, on_evict
        self._d = OrderedDict()
        self.total_weight = 0

    def __len__(self):
        return len(self._d)

    def get(self, key, default=None):
        if key not in self._d:
            return default
        self._d.move_to_end(key)
        return self._d[key][0]

    def delete(self, key):
        if key not in self._d:
            return False
        self.total_weight -= self._d.pop(key)[1]
        return True

    def put(self, key, value, weight):
        if weight > self.max_weight:
            return False
        if key in self._d:
            self.total_weight -= self._d.pop(key)[1]
        while self.total_weight + weight > self.max_weight:
            k, (v, w) = self._d.popitem(last=False)
            self.total_weight -= w
            if self.on_evict:
                self.on_evict(k, v)
        self._d[key] = (value, weight)
        self.total_weight += weight
        return True
''',
}

DESC = {
 'intervals.py': 'Implement merge_intervals in intervals.py exactly as its docstring says. check_intervals.py must pass.',
 'money.py': 'Implement split_money in money.py exactly as its docstring says. check_money.py must pass.',
 'semver.py': 'Implement satisfies in semver.py exactly as its docstring says. check_semver.py must pass.',
 'bucket.py': 'Implement TokenBucket in bucket.py exactly as its docstring says. check_bucket.py must pass.',
 'cron.py': 'Implement next_run in cron.py exactly as its docstring says. check_cron.py must pass.',
 'wlru.py': 'Implement WeightedLRU in wlru.py exactly as its docstring says. check_wlru.py must pass.',
}


def hard_domain():
    files = {**STUBS, **CHECKS}
    tasks = []
    for mod in STUBS:
        check = 'check_' + mod
        tasks.append({'task_id': 'H-' + mod[:-3].upper(), 'description': DESC[mod],
                      'context_files': [mod, check], 'output_files': [mod],
                      'acceptance_command': [PY, check], 'max_attempts': 3})
    return {'name': 'hard', 'files': files, 'tasks': tasks,
            'refs': {'H-' + m[:-3].upper(): {m: REFS[m]} for m in REFS}}
