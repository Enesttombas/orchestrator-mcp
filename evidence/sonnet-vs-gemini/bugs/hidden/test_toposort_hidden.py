import pytest
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
