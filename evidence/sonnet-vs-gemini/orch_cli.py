"""Gemini orchestrator MCP as a CLI (same library the MCP server wraps: plan.submit -> runner.run -> plan.apply_session).
  python orch_cli.py <spec.json> <out_dir> [--apply]
spec: {"name": str, "work_dir": str, "tasks": [ {task_id, description, context_files, output_files,
        acceptance_command, dependencies?, max_attempts?, max_tokens?} ]}
Task rules: independent tasks must not share an output file; code tasks need acceptance_command (argv list, run in a
scratch copy containing context+output files); analysis tasks use output_files [] and the answer goes in `summary`.
Writes <out_dir>/<task_id>.summary.md for each task. Prints one compact line per task (status, attempts, tokens)."""
import json
import os
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'tools' / 'orchestrator_mcp'))
spec = json.loads(Path(sys.argv[1]).read_text(encoding='utf-8'))
out = Path(sys.argv[2])
out.mkdir(parents=True, exist_ok=True)
state = out / '_state'
os.environ['ORCHESTRATOR_GEMINI_ENABLED'] = '1'
os.environ['ORCHESTRATOR_ARTIFACTS_DIR'] = str(state / 'artifacts')
from store import Store
from pool import Pool
from runner import run
import plan

db = Store(state / 'state.db')
t0 = time.time()
sid = plan.submit(db, spec.get('name', 'cli'), spec['work_dir'], spec['tasks'])['session_id']
res = run(db, Pool(db), sid, 15, capacity_wait=120)
print(f"session {res['status']} in {round(time.time() - t0, 1)}s")
applied = plan.apply_session(db, sid) if '--apply' in sys.argv else None
for t in db.tasks(sid):
    ev = json.loads(t['evidence'] or '{}')
    r = plan.result(db, sid, t['task_id'])
    (out / f"{t['task_id']}.summary.md").write_text(r.get('summary') or '', encoding='utf-8')
    print(f"{t['task_id']}: {t['status']} attempts={t['attempts']} tokens={(ev.get('usage') or {}).get('total_tokens')} "
          f"summary_chars={len(r.get('summary') or '')} err={(t.get('error') or '')[:100]}")
if applied is not None:
    print('applied', applied.get('applied'), 'rejected', applied.get('rejected') or {})
