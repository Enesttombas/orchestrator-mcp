import pytest
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
