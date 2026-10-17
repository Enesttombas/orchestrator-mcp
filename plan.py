"""One-call planning, whole-session apply, result lookup and bounded waiting for the MCP tools."""
import json
from pathlib import Path
import time

from execution import apply_outputs, validate_spec
from store import identifier

SETTLED = ('COMPLETED', 'CANCELLED', 'BLOCKED', 'LIMIT_REACHED', 'WAITING_CAPACITY')


def _order(tasks):
    ids = []
    for t in tasks:
        if not isinstance(t, dict):
            raise ValueError('Each task must be an object')
        ids.append(identifier(t.get('task_id')))
        if not str(t.get('description', '')).strip():
            raise ValueError('Each task needs a description: ' + ids[-1])
    if len(set(ids)) != len(ids):
        raise ValueError('Duplicate task_id in plan')
    by_id = dict(zip(ids, tasks))
    ordered, done = [], set()
    pending = list(ids)
    while pending:
        ready = [i for i in pending if set(by_id[i].get('dependencies') or []) <= done]
        if not ready:
            raise ValueError('Plan has a cycle or a missing dependency')
        for i in ready:
            if i in (by_id[i].get('dependencies') or []):
                raise ValueError('Task depends on itself: ' + i)
        ordered += [by_id[i] for i in ready]
        done.update(ready)
        pending = [i for i in pending if i not in done]
    return ordered


def _refuse_shared_outputs(ordered):
    """Two tasks with no dependency path between them cannot both own a file: the second apply would be rejected."""
    ancestors = {}
    for t in ordered:  # _order guarantees parents come first
        mine = set()
        for d in t.get('dependencies') or []:
            mine |= {d} | ancestors[d]
        ancestors[t['task_id']] = mine
    owners = {}
    for t in ordered:
        for name in t.get('output_files') or []:
            for other in owners.get(name, []):
                if other not in ancestors[t['task_id']]:
                    raise ValueError(f"Tasks {other} and {t['task_id']} both write {name} without a dependency between them; "
                                     "chain them with dependencies or give each its own session")
            owners.setdefault(name, []).append(t['task_id'])


def submit(store, goal, work_dir, tasks, max_iterations=None):
    """Validate the whole DAG first, then create session, tasks and frozen specs together."""
    if not isinstance(tasks, list) or not tasks or len(tasks) > 200:
        raise ValueError('Plan needs 1..200 tasks')
    root = Path(work_dir).resolve(strict=True)
    ordered = _order(tasks)
    _refuse_shared_outputs(ordered)
    specs = []
    for t in ordered:
        specs.append(validate_spec(root, list(t.get('context_files') or []), list(t.get('output_files') or []),
                                   list(t.get('acceptance_command') or []), t.get('timeout', 60),
                                   t.get('max_attempts', 2), t.get('account_id'), t.get('max_tokens', 4096)))
    limit = max_iterations or min(10000, sum(s['max_attempts'] for s in specs) + 5)
    sid = store.create(goal, 'custom_dag', limit, str(root))
    try:
        for t, spec in zip(ordered, specs):
            store.add(sid, t['task_id'], t.get('role') or 'worker', t.get('title') or t['task_id'],
                      t['description'], t.get('dependencies') or [])
            store.configure(sid, t['task_id'], spec)
    except BaseException:
        store.cancel(sid)
        raise
    return {'session_id': sid, 'tasks': [t['task_id'] for t in ordered], 'max_iterations': limit}


def result(store, sid, tid):
    task = store.task(sid, tid)
    if not task:
        raise ValueError('Unknown task')
    ev = json.loads(task['evidence'] or '{}')
    return {'task_id': tid, 'status': task['status'], 'attempts': task['attempts'],
            'account_id': task['account_id'], 'exit_code': task['exit_code'], 'error': task['error'],
            'summary': ev.get('summary_full') or task['summary'] or '',
            'outputs': sorted(ev.get('outputs', {})), 'evidence_kind': ev.get('kind')}


def apply_session(store, sid):
    """Apply accepted tasks in dependency order; a rejected parent blocks its children, others still apply."""
    tasks = {t['task_id']: t for t in store.tasks(sid)}
    applied, rejected, handled = [], {}, set()

    def visit(tid):
        if tid in handled:
            return
        handled.add(tid)
        task = tasks[tid]
        for parent in task['dependencies']:
            visit(parent)
        if task['status'] != 'COMPLETED':
            return
        if not json.loads(task['evidence'] or '{}').get('outputs'):
            return  # analysis-only: nothing to apply, never blocks children
        if any(p in rejected for p in task['dependencies']):
            rejected[tid] = 'Dependency was not applied'
            return
        try:
            applied.extend(apply_outputs(store, sid, tid)['files'])
        except ValueError as e:
            rejected[tid] = str(e)[:200]
    for tid in tasks:
        visit(tid)
    return {'applied': applied, 'rejected': rejected,
            'not_completed': sorted(t for t, v in tasks.items() if v['status'] != 'COMPLETED')}


def wait(store, sid, timeout=60, poll=1.0):
    deadline = time.monotonic() + max(0, timeout)
    while True:
        status = store.session(sid)['status']
        if status in SETTLED or time.monotonic() >= deadline:
            return {'timed_out': status not in SETTLED, 'session_status': status,
                    'tasks': {t['task_id']: t['status'] for t in store.tasks(sid)}}
        time.sleep(poll)
