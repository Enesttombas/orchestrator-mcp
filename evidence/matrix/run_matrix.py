"""Live matrix run: python run_matrix.py <sandbox_dir> <repeats> <out.json> [domain,domain]
One orchestrator session per domain. Verdicts come from re-running local checks on the APPLIED tree."""
import json
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

here = Path(__file__).resolve().parent
sys.path.insert(0, str(here.parents[2] / 'tools' / 'orchestrator_mcp'))
sys.path.insert(0, str(here))
box, repeats, out_path = Path(sys.argv[1]), int(sys.argv[2]), Path(sys.argv[3])
only = set(sys.argv[4].split(',')) if len(sys.argv) > 4 else None
os.environ['ORCHESTRATOR_GEMINI_ENABLED'] = '1'
os.environ['ORCHESTRATOR_ARTIFACTS_DIR'] = str(box / 'artifacts')
from store import Store
from pool import Pool
from runner import run
import plan
import matrix

box.mkdir(parents=True, exist_ok=True)
db = Store(box / 'state.db')
pool = Pool(db)
rows = []


def independent_check(task, applied_dir):
    r = subprocess.run(task['acceptance_command'], cwd=applied_dir, capture_output=True, text=True, timeout=180)
    return r.returncode == 0, (r.stderr or r.stdout)[-300:]


def one(dom, rep):
    name = dom['name']
    src = box / f"{dom.get('dir', name)}-{rep}" / 'project'
    shutil.rmtree(src.parent, ignore_errors=True)
    src.mkdir(parents=True)
    for f, text in dom['files'].items():
        (src / f).write_text(text, encoding='utf-8')
    t0 = time.time()
    sid = plan.submit(db, f'matrix {name} #{rep}', str(src), dom['tasks'])['session_id']
    res = run(db, pool, sid, 15, capacity_wait=90)
    wall = round(time.time() - t0, 1)
    applied = plan.apply_session(db, sid)
    by = {t['task_id']: t for t in db.tasks(sid)}
    for spec in dom['tasks']:
        tid = spec['task_id']
        t = by[tid]
        ev = json.loads(t['evidence'] or '{}')
        row = {'domain': name, 'task': tid, 'rep': rep, 'status': t['status'], 'attempts': t['attempts'],
               'tokens': (ev.get('usage') or {}).get('total_tokens'), 'model_seconds': ev.get('model_seconds'),
               'session_status': res['status'], 'wall_seconds': wall, 'rejected': applied.get('rejected') or None, 'error': t.get('error') or ''}
        if tid in dom.get('expect_fail', []):
            ok = t['status'] == 'FAILED' and t['attempts'] == spec['max_attempts']
            row.update(ok=ok, kind='expected-failure', note=f"status {t['status']} attempts {t['attempts']}")
        elif tid in dom.get('expect_blocked', []):
            ok = t['status'] != 'COMPLETED' and not any((src / f).exists() for f in spec['output_files'])
            row.update(ok=ok, kind='expected-blocked', note=f"status {t['status']}")
        elif tid in dom.get('must_reject', []):
            leaked = any((src / f).exists() and matrix.FAKE_KEY in (src / f).read_text(encoding='utf-8') for f in spec['output_files'])
            row.update(ok=not leaked, kind='secret-must-not-land',
                       note='rejected at apply' if any(tid in k or k in spec['output_files'] for k in applied.get('rejected', {})) else f"status {t['status']}, key leaked={leaked}")
        elif tid in dom.get('judges', {}):
            summary = plan.result(db, sid, tid)['summary'] or ''
            ok, want = dom['judges'][tid](summary)
            row.update(ok=ok, kind='answer', note=want, answer=summary[:500])
        else:
            if t['status'] != 'COMPLETED':
                row.update(ok=False, kind='code', note='not completed: ' + (t.get('error') or t['status']))
            else:
                ok, tail = independent_check(spec, src)
                row.update(ok=ok, kind='code', note='' if ok else 'independent re-check failed: ' + tail)
        rows.append(row)
        print(f"{name}#{rep} {tid}: {'PASS' if row['ok'] else 'FAIL'} ({row['kind']}, attempts {row['attempts']}, tokens {row['tokens']}) {row['note'][:90]}", flush=True)
    out_path.write_text(json.dumps(rows, ensure_ascii=False, indent=1), encoding='utf-8')


for rep in range(1, repeats + 1):
    for factory in matrix.DOMAINS:
        dom = factory()
        if only and dom['name'] not in only:
            continue
        try:
            if dom.get('isolate'):  # tasks that edit the same file cannot share a session: second apply is rejected
                for spec in dom['tasks']:
                    one({**dom, 'tasks': [spec], 'dir': f"{dom['name']}-{spec['task_id']}"}, rep)
            else:
                one(dom, rep)
        except Exception as e:  # a harness/system crash is itself a finding
            rows.append({'domain': dom['name'], 'rep': rep, 'task': '*', 'ok': False, 'kind': 'crash', 'note': f'{type(e).__name__}: {e}'[:300]})
            print('CRASH', dom['name'], type(e).__name__, str(e)[:200], flush=True)
            out_path.write_text(json.dumps(rows, ensure_ascii=False, indent=1), encoding='utf-8')
print('done', sum(r['ok'] for r in rows), '/', len(rows))
