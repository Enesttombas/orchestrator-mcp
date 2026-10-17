class EmitError(Exception):
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
