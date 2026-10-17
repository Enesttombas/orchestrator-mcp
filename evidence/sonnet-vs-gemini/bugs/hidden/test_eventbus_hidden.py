import pytest
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
