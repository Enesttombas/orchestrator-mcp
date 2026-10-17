"""Live retry-context A/B on hard tasks: python run_hard.py <sandbox_dir> <repeats> <out.json> [full,clean]
Per rep and mode: fresh sandbox, six independent tasks in one session. Verdict = independent re-run of the check
on the applied tree. Attempts/tokens come from the store."""
import json
import os
import subprocess
import sys
import time
from pathlib import Path

here = Path(__file__).resolve().parent
sys.path.insert(0, str(here.parents[2] / 'tools' / 'orchestrator_mcp'))
sys.path.insert(0, str(here))
box, repeats, out = Path(sys.argv[1]), int(sys.argv[2]), Path(sys.argv[3])
modes = sys.argv[4].split(',') if len(sys.argv) > 4 else ['full', 'clean']
os.environ['ORCHESTRATOR_GEMINI_ENABLED'] = '1'
os.environ['ORCHESTRATOR_ARTIFACTS_DIR'] = str(box / 'artifacts')
from store import Store
from pool import Pool
from runner import run
import plan
import hard

box.mkdir(parents=True, exist_ok=True)
db = Store(box / 'state.db')
pool = Pool(db)
rows = []
for rep in range(1, repeats + 1):
    for mode in modes:
        os.environ['ORCHESTRATOR_RETRY_CONTEXT'] = mode
        dom = hard.hard_domain()
        src = box / f'{mode}-{rep}' / 'project'
        src.mkdir(parents=True, exist_ok=True)
        for name, text in dom['files'].items():
            (src / name).write_text(text, encoding='utf-8')
        t0 = time.time()
        sid = plan.submit(db, f'hard {mode} #{rep}', str(src), dom['tasks'])['session_id']
        res = run(db, pool, sid, 15, capacity_wait=120)
        wall = round(time.time() - t0, 1)
        applied = plan.apply_session(db, sid)
        by = {t['task_id']: t for t in db.tasks(sid)}
        for spec in dom['tasks']:
            t = by[spec['task_id']]
            ev = json.loads(t['evidence'] or '{}')
            ok = False
            if t['status'] == 'COMPLETED':
                ok = subprocess.run(spec['acceptance_command'], cwd=src, capture_output=True, timeout=120).returncode == 0
            row = {'mode': mode, 'rep': rep, 'task': spec['task_id'], 'ok': ok, 'status': t['status'], 'attempts': t['attempts'],
                   'tokens': (ev.get('usage') or {}).get('total_tokens'), 'wall': wall, 'session': res['status'],
                   'error': (t.get('error') or '')[:200]}
            rows.append(row)
            print(json.dumps(row), flush=True)
        out.write_text(json.dumps(rows, indent=1), encoding='utf-8')
print('done', sum(r['ok'] for r in rows), '/', len(rows))
