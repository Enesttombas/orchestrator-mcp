"""Live 30-task DAG (20 leaves ready at once > 15 parallel cap, 8 mid, 2 final): python run_dag30.py <sandbox> <out.json>"""
import json
import os
import subprocess
import sys
import time
from pathlib import Path

here = Path(__file__).resolve().parent
sys.path.insert(0, str(here.parents[2] / 'tools' / 'orchestrator_mcp'))
box, out = Path(sys.argv[1]), Path(sys.argv[2])
os.environ['ORCHESTRATOR_GEMINI_ENABLED'] = '1'
os.environ['ORCHESTRATOR_ARTIFACTS_DIR'] = str(box / 'artifacts')
from store import Store
from pool import Pool
from runner import run
import plan

PY = sys.executable
HEAD = 'import os, sys\nsys.path.insert(0, os.getcwd())\n'
files, tasks, truth = {}, [], {}


def f(i, x):
    return x * i + i % 7


for i in range(20):
    files[f'check_m{i:02}.py'] = HEAD + f'from m{i:02} import f{i:02}\nfor x in (0, 1, 5, -3):\n    assert f{i:02}(x) == x * {i} + {i % 7}, (x, f{i:02}(x))\nprint("ok")\n'
    tasks.append({'task_id': f'L{i:02}', 'description': f'In m{i:02}.py define f{i:02}(x) returning x * {i} + {i % 7}.',
                  'context_files': [f'check_m{i:02}.py'], 'output_files': [f'm{i:02}.py'],
                  'acceptance_command': [PY, f'check_m{i:02}.py'], 'max_attempts': 2})
legs = {}
for j in range(8):
    legs[j] = [j * 2, j * 2 + 1, (j * 2 + 2) % 20]
    imports = ''.join(f'from m{k:02} import f{k:02}\n' for k in legs[j])
    files[f'check_agg{j}.py'] = HEAD + f'from agg{j} import g{j}\nfor x in (0, 2, 7):\n    assert g{j}(x) == ' + ' + '.join(f'(x * {k} + {k % 7})' for k in legs[j]) + ', x\nprint("ok")\n'
    tasks.append({'task_id': f'M{j}', 'description': f'In agg{j}.py define g{j}(x) = ' + ' + '.join(f'f{k:02}(x)' for k in legs[j]) + f' using the existing modules ' + ', '.join(f'm{k:02}.py' for k in legs[j]) + '.',
                  'context_files': [f'check_agg{j}.py'], 'output_files': [f'agg{j}.py'], 'dependencies': [f'L{k:02}' for k in legs[j]],
                  'acceptance_command': [PY, f'check_agg{j}.py'], 'max_attempts': 2})
for n, group in enumerate((range(0, 4), range(4, 8)), 1):
    expr = ' + '.join(f'g{j}(x)' for j in group)
    files[f'check_final{n}.py'] = HEAD + 'from final%d import total\n' % n + 'import importlib\nfor x in (0, 3):\n    assert total(x) == ' + ' + '.join(' + '.join(f'(x * {k} + {k % 7})' for k in legs[j]) for j in group) + ', x\nprint("ok")\n'
    tasks.append({'task_id': f'F{n}', 'description': f'In final{n}.py define total(x) = {expr}, importing each g from its agg module.',
                  'context_files': [f'check_final{n}.py'], 'output_files': [f'final{n}.py'], 'dependencies': [f'M{j}' for j in group],
                  'acceptance_command': [PY, f'check_final{n}.py'], 'max_attempts': 2})
assert len(tasks) == 30

src = box / 'project'
src.mkdir(parents=True, exist_ok=True)
for name, text in files.items():
    (src / name).write_text(text, encoding='utf-8')
db = Store(box / 'state.db')
pool = Pool(db)
t0 = time.time()
sid = plan.submit(db, 'dag30', str(src), tasks)['session_id']
peaks = []
res = run(db, pool, sid, 15, capacity_wait=180)
wall = round(time.time() - t0, 1)
applied = plan.apply_session(db, sid)
by = {t['task_id']: t for t in db.tasks(sid)}
rows = []
for spec in tasks:
    t = by[spec['task_id']]
    ev = json.loads(t['evidence'] or '{}')
    ok = t['status'] == 'COMPLETED' and subprocess.run(spec['acceptance_command'], cwd=src, capture_output=True, timeout=120).returncode == 0
    rows.append({'task': spec['task_id'], 'ok': ok, 'status': t['status'], 'attempts': t['attempts'],
                 'tokens': (ev.get('usage') or {}).get('total_tokens'), 'model_seconds': ev.get('model_seconds'), 'error': (t.get('error') or '')[:150]})
summary = {'session': res['status'], 'wall_seconds': wall, 'passed': sum(r['ok'] for r in rows), 'total': len(rows),
           'retried': sum(1 for r in rows if (r['attempts'] or 0) > 1), 'tokens': sum(r['tokens'] or 0 for r in rows),
           'rejected_on_apply': applied.get('rejected') or None, 'rows': rows}
out.write_text(json.dumps(summary, indent=1), encoding='utf-8')
print(json.dumps({k: v for k, v in summary.items() if k != 'rows'}))
for r in rows:
    if not r['ok']:
        print('FAIL', r)
