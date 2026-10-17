import pytest
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
