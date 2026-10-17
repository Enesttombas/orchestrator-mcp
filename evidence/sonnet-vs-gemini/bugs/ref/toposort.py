import heapq


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
