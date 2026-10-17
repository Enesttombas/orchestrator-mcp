"""One-command, repeatable MCP benchmark: wall time, tokens, first-pass rate, acceptance results as JSON.

  python evals/bench.py --mode offline --tasks 6 --repeats 2 --out result.json
  ORCHESTRATOR_GEMINI_ENABLED=1 python evals/bench.py --mode live --tasks 6 --repeats 2 --out result.json

Offline uses a scripted pool (no network, no quota). Live uses the real 15-account pool and spends quota.
"""
import argparse
import json
import os
from pathlib import Path
import sys
import tempfile
import time

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import plan
from execution import artifact_root
from runner import run
from store import Store

CHECK = 'import os, sys\nsys.path.insert(0, os.getcwd())\nfrom m{n} import f{n}\nassert f{n}(10) == {want}, f{n}(10)\nassert f{n}(-3) == {neg}\n'


class ScriptedPool:
    """Offline stand-in for the fleet: answers the micro scenario deterministically, no network."""
    model = 'scripted-offline'

    def __init__(self):
        from contextlib import contextmanager
        import threading
        self.lock, self.busy = threading.Lock(), set()

        @contextmanager
        def acquire(preferred=None):
            with self.lock:
                aid = next(f'h{n:02}' for n in range(1, 16) if f'h{n:02}' not in self.busy)
                self.busy.add(aid)
            try:
                yield aid, 'scripted://local'
            finally:
                with self.lock:
                    self.busy.discard(aid)
        self.acquire = acquire

    def enabled(self):
        return True

    def refresh_quotas(self):
        return []

    def complete(self, url, messages, max_tokens=4096, **options):
        data = json.loads(messages[-1]['content'])
        files = {}
        for name in data['allowed_output_files']:
            k = int(name[1:-3])
            files[name] = f'def f{k}(x):\n    return x + {k}\n'
        text = json.dumps({'summary': 'scripted', 'files': files})
        return text, {'prompt_tokens': len(messages[-1]['content']) // 4, 'completion_tokens': len(text) // 4,
                      'total_tokens': (len(messages[-1]['content']) + len(text)) // 4}


def scenario(tasks, checks_dir):
    """N independent micro tasks: write mK.py with fK(x)=x+K; the acceptance script is hidden from the model."""
    out = []
    for n in range(tasks):
        script = Path(checks_dir) / f'check_{n}.py'
        script.parent.mkdir(parents=True, exist_ok=True)
        script.write_text(CHECK.format(n=n, want=10 + n, neg=-3 + n), encoding='utf-8')
        out.append({'task_id': f'T{n}', 'description': f'Write m{n}.py with a function f{n}(x) returning x + {n}.',
                    'context_files': [], 'output_files': [f'm{n}.py'],
                    'acceptance_command': [sys.executable, str(script)]})
    return out


def usage_totals(sid):
    keys = {'prompt_tokens': 0, 'completion_tokens': 0, 'total_tokens': 0}
    calls, unknown = 0, 0
    for path in (artifact_root() / sid).glob('*_model-call.json'):
        item = json.loads(path.read_text(encoding='utf-8'))
        calls += 1
        usage = item.get('usage')
        if not isinstance(usage, dict) or 'total_tokens' not in usage:
            unknown += 1
            continue
        for key in keys:
            keys[key] += usage.get(key, 0) or 0
    return {**keys, 'calls': calls, 'calls_without_usage': unknown}


def one_run(db, pool, tasks, parallel):
    root = Path(db.path).parent / 'project'
    root.mkdir(exist_ok=True)
    sid = plan.submit(db, 'bench', str(root), tasks)['session_id']
    started = time.monotonic()
    session = run(db, pool, sid, parallel, capacity_wait=60)
    seconds = time.monotonic() - started
    rows = db.tasks(sid)
    done = [t for t in rows if t['status'] == 'COMPLETED']
    return {'session_id': sid, 'status': session['status'], 'seconds': round(seconds, 3),
            'passed': len(done), 'total': len(rows),
            'first_pass': sum(1 for t in done if t['attempts'] == 1),
            'attempts': sum(t['attempts'] for t in rows),
            'accounts': len({t['account_id'] for t in rows if t['account_id']}), **usage_totals(sid)}


def summarize(runs):
    n = len(runs)
    total = sum(r['total'] for r in runs)
    return {'runs': n, 'pass_rate': round(sum(r['passed'] for r in runs) / total, 4),
            'first_pass_rate': round(sum(r['first_pass'] for r in runs) / total, 4),
            'seconds_mean': round(sum(r['seconds'] for r in runs) / n, 3),
            'total_tokens_mean': round(sum(r['total_tokens'] for r in runs) / n, 1),
            'completion_tokens_mean': round(sum(r['completion_tokens'] for r in runs) / n, 1)}


def benchmark(mode, tasks=6, repeats=1, parallel=15, workdir=None, pool=None):
    if mode == 'live' and os.environ.get('ORCHESTRATOR_GEMINI_ENABLED') != '1':
        raise SystemExit('live mode needs ORCHESTRATOR_GEMINI_ENABLED=1 (it spends real quota)')
    if mode not in ('offline', 'live'):
        raise SystemExit('mode must be offline or live')
    base = Path(workdir) if workdir else Path(tempfile.mkdtemp(prefix='orch-bench-'))
    os.environ.setdefault('ORCHESTRATOR_ARTIFACTS_DIR', str(base / 'artifacts'))
    runs = []
    for i in range(repeats):
        db = Store(base / f'run{i}' / 'state.db')
        if pool is None:
            if mode == 'offline':
                active = ScriptedPool()
            else:
                from pool import Pool
                active = Pool(db)
        else:
            active = pool(db)
        specs = scenario(tasks, base / f'run{i}' / 'hidden-checks')
        runs.append(one_run(db, active, specs, parallel))
    return {'mode': mode, 'tasks': tasks, 'repeats': repeats, 'runs': runs, 'summary': summarize(runs)}


def main():
    p = argparse.ArgumentParser()
    p.add_argument('--mode', choices=('offline', 'live'), required=True)
    p.add_argument('--tasks', type=int, default=6)
    p.add_argument('--repeats', type=int, default=1)
    p.add_argument('--out', type=Path)
    a = p.parse_args()
    result = benchmark(a.mode, a.tasks, a.repeats)
    text = json.dumps(result, ensure_ascii=False, indent=2)
    if a.out:
        a.out.write_text(text, encoding='utf-8')
    print(text)
    return 0 if result['summary']['pass_rate'] == 1 else 1


if __name__ == '__main__':
    sys.exit(main())
