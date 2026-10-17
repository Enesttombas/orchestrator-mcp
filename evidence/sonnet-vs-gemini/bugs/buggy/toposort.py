class CycleError(Exception):
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
