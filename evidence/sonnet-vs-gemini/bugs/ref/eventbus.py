class EmitError(Exception):
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
