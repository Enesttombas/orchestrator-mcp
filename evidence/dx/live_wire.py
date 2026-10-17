"""Live client-path check: spawn the INSTALLED server exactly as mcp_config.json says and drive it over stdio JSON-RPC."""
import json, shutil, subprocess, sys, time
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[3] / 'tools' / 'orchestrator_mcp'))
from test_orchestrator import Wire

box = Path(sys.argv[1]); shutil.rmtree(box, ignore_errors=True); (box / 'proj').mkdir(parents=True)
cfg = json.loads((Path.home() / '.gemini/config/mcp_config.json').read_text(encoding='utf-8'))['mcpServers']['orchestrator']
env = {k: v for k, v in cfg['env'].items() if k not in ('ORCHESTRATOR_DB_PATH', 'ORCHESTRATOR_ARTIFACTS_DIR')}
proj = box / 'proj'
(proj / 'check.py').write_text('import os, sys\nsys.path.insert(0, os.getcwd())\nfrom calc import add, mul\nassert add(2, 3) == 5 and mul(4, 5) == 20\nprint("ok")\n')
wire = Wire(box, enabled=True, entry=Path(cfg['args'][-1]), env_overrides=env)
t0 = time.time()
try:
    names = sorted(t['name'] for t in wire.request('tools/list', {})['result']['tools'])
    print('tools', len(names))
    tasks = [{'task_id': 'T', 'description': 'Create calc.py with add(a,b) and mul(a,b). See check.py.', 'context_files': ['check.py'],
              'output_files': ['calc.py'], 'acceptance_command': [sys.executable, 'check.py']}]
    sub = wire.call('orchestrator_submit_plan', goal='wire live', work_dir=str(proj), tasks=tasks, start=True)
    sid = sub['session_id']; print('submitted', sid, 'run', json.dumps(sub.get('run'))[:120])
    for _ in range(20):
        w = wire.call('orchestrator_wait', session_id=sid, timeout_seconds=30)
        print('wait', w.get('session_status')); 
        if w.get('session_status') in ('COMPLETED', 'BLOCKED', 'WAITING_CAPACITY', 'CANCELLED', 'LIMIT_REACHED'): break
    r = wire.call('orchestrator_get_result', session_id=sid, task_id='T'); print('result', r['status'], r['attempts'], r['outputs'])
    a = wire.call('orchestrator_apply_session', session_id=sid); print('apply', json.dumps(a)[:200])
    rc = subprocess.run([sys.executable, 'check.py'], cwd=proj).returncode
    print('independent check rc', rc, 'seconds', round(time.time() - t0, 1))
    json.dump({'tools': len(names), 'status': r['status'], 'attempts': r['attempts'], 'apply': a, 'check_rc': rc, 'seconds': round(time.time() - t0, 1)},
              open(Path(__file__).with_name('live-wire.json'), 'w'), indent=1)
finally:
    wire.close()
