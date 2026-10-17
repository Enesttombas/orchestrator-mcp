"""Antigravity MCP orchestration with atomic leases and a bounded 15-account executor."""
import json
import os
from pathlib import Path
import subprocess
import sys
import time

from mcp.server import MCPServer
import psutil

from execution import (acceptance, apply_outputs, artifact_root, digest, safe_path,
                       save_artifact, validate_spec)
from pool import Pool
from store import Store, identifier
from locking import file_lock
import plan

db_manager = Store(os.environ.get('ORCHESTRATOR_DB_PATH',str(Path.home()/'.orchestrator/orchestrator.db')))
server = MCPServer(name='antigravity-orchestrator',version='3.0.0',
                   description='Atomic DAG leases, independently executed acceptance, bounded Gemini CPA fleet.')


def response(data):
    return json.dumps(data,ensure_ascii=False)


@server.tool()
def orchestrator_init(goal: str, mode: str='staged_pipeline', max_iterations: int=60, work_dir: str|None=None) -> str:
    """Create a durable session. custom_dag supports parallel Gemini tasks; staged_pipeline creates four manual stages."""
    sid = db_manager.create(goal,mode,max_iterations,work_dir)
    tasks = []
    if mode=='staged_pipeline':
        for tid,role,description in [('T1_SCOUT','scout','Inspect scope and produce source-backed findings'),
                                     ('T2_BUILD','builder','Implement the smallest correct change'),
                                     ('T3_REVIEW','reviewer','Run independent acceptance'),
                                     ('T4_COMPACT','compactor','Summarize verified results')]:
            db_manager.add(sid,tid,role,tid,description,tasks[-1:])
            tasks.append(tid)
    return response({'status':'success','session_id':sid,'tasks':tasks,
                     'next_step':'Add/configure tasks, then run_session; manual claims need unique worker_id.'})


@server.tool()
def orchestrator_add_task(session_id: str, task_id: str, role: str, title: str, description: str,
                          dependencies: list[str]|None=None) -> str:
    """Add a unique node. Parents must already exist; existing task definitions cannot be replaced."""
    db_manager.add(session_id,task_id,role,title,description,dependencies or [])
    return response({'status':'task_added','task_id':task_id})


@server.tool()
def orchestrator_configure_task(session_id: str, task_id: str, context_files: list[str], output_files: list[str],
                                acceptance_command: list[str], timeout: int=60, max_attempts: int=2,
                                account_id: str|None=None, max_tokens: int=4096) -> str:
    """Freeze an unstarted task's explicit file scope and server-run acceptance argv. Code outputs require acceptance.

    Workers see only context_files and existing output_files. Commands run in a disposable file workspace;
    this is filesystem staging, not an OS security sandbox. Model-proposed commands are never executed.
    account_id optionally pins h01..h15; otherwise a free account is selected fairly.
    """
    root = db_manager.session(session_id)['work_dir']
    spec = validate_spec(root,context_files,output_files,acceptance_command,timeout,max_attempts,account_id,max_tokens)
    db_manager.configure(session_id,task_id,spec)
    return response({'status':'configured','task_id':task_id,'spec':spec})


@server.tool()
def orchestrator_get_next_action(session_id: str, worker_id: str='manual', lease_seconds: int=300) -> str:
    """Atomically claim/resume one manual task per unique worker_id. Independent workers can claim in parallel.

    Keep the returned worker_id for record_result. An expired lease rejects late results.
    """
    task = db_manager.claim(session_id,worker_id,lease_seconds)
    s = db_manager.session(session_id)
    action = 'EXECUTE_TASK' if task else ('ALL_TASKS_COMPLETED' if s['status']=='COMPLETED' else 'NO_OP')
    return response({'action':action,'session_status':s['status'],'task':task,'worker_id':worker_id})


@server.tool()
def orchestrator_record_result(session_id: str, task_id: str, status: str, exit_code: int|None=None,
                                artifact_path: str='', summary: str='', error: str='', worker_id: str='manual',
                                acceptance_command: list[str]|None=None) -> str:
    """Finish an owned manual task. SUCCESS needs a real artifact; builder/reviewer also need a command run HERE.

    Caller-supplied exit_code is informational and never proves success. Configure task acceptance in advance
    when possible. A repeated accepted result is idempotent. Autonomous tasks must finish through their runner.
    """
    task = db_manager.task(session_id,task_id)
    if not task:
        raise ValueError('Unknown task')
    if task['status'] in ('COMPLETED','FAILED') and task['owner']==worker_id:
        return response({'status':'already_recorded','final_status':task['status']})
    if task['status']!='IN_PROGRESS' or task['owner']!=worker_id or (task['lease_until'] or 0)<time.time():
        raise ValueError('Claim a live task with the same worker_id before recording')
    if worker_id.startswith('run_'):
        raise ValueError('Autonomous task is owned by the runner')
    if status.upper() not in ('SUCCESS','FAILED'):
        raise ValueError('status must be SUCCESS or FAILED')
    ev = None
    rc = exit_code
    if status.upper()=='SUCCESS':
        path = Path(artifact_path).resolve(strict=True)
        allowed = safe_path(artifact_root(),session_id)
        if not path.is_relative_to(allowed) or not path.is_file():
            raise ValueError('Use save_artifact to create evidence inside this session')
        spec = json.loads(task['spec'] or '{}')
        command = spec.get('command') or acceptance_command
        if task['role'] in ('builder','reviewer','worker') and not command:
            raise ValueError('Code work requires an independent acceptance command')
        ev = acceptance(command,Path(db_manager.session(session_id)['work_dir']),spec.get('timeout',60))
        ev.update(artifact_sha256=digest(path.read_bytes()),verification='server-executed' if command else 'artifact-only')
        rc = ev['exit_code']
    success = status.upper()=='SUCCESS' and rc in (None,0)
    return response(db_manager.finish(session_id,task_id,worker_id,success,rc,artifact_path,summary,error,ev))


@server.tool()
def orchestrator_save_artifact(session_id: str, task_id: str, filename: str, content: str) -> str:
    """Write a unique UTF-8 artifact inside a known session/task; traversal and overwrite are rejected."""
    if not db_manager.task(session_id,task_id):
        raise ValueError('Unknown task')
    return response({'status':'success',**save_artifact(session_id,task_id,filename,content)})


def runner_info(session_id):
    identifier(session_id)
    lock = artifact_root()/('run-'+session_id+'.json')
    try:
        info = json.loads(lock.read_text(encoding='utf-8'))
        return {**info,'active':Pool.alive(info)}
    except (OSError,ValueError):
        return {'active':False}


@server.tool()
def orchestrator_get_status(session_id: str, format: str='compact') -> str:
    """Read durable tasks/evidence and detached runner liveness; no model request."""
    s = db_manager.session(session_id)
    tasks = db_manager.tasks(session_id)
    if format=='json':
        return response({'session':s,'tasks':tasks,'runner':runner_info(session_id)})
    return '\n'.join([f'{session_id}: {s["status"]} ({s["iteration"]}/{s["max_iterations"]} attempts)']+
                     [f'{t["task_id"]}: {t["status"]}; account={t["account_id"] or "-"}; {t["summary"] or t["error"] or ""}' for t in tasks])


@server.tool()
def orchestrator_list_sessions(limit: int=10) -> str:
    """List recent durable sessions without making model requests."""
    return response(db_manager.list_sessions(limit))


@server.tool()
def orchestrator_reset_session(session_id: str) -> str:
    """Explicitly retry failed/cancelled tasks, clearing stale evidence and counters. Active runs must stop first."""
    if runner_info(session_id)['active']:
        raise ValueError('Wait for runner exit before reset')
    return response({'status':'success','reset_tasks':db_manager.reset(session_id)})


@server.tool()
def orchestrator_pool_status() -> str:
    """Inspect 15 configured account slots, leases and cooldowns. Never returns credentials or consumes model quota."""
    return response(Pool(db_manager).status())


@server.tool()
def orchestrator_refresh_quotas() -> str:
    """Refresh all 15 quotas without model generation. CPA performs OAuth renewal; return real errors, never unknown-as-full.

    Starts loopback CPA processes if needed. Reads Gemini short/weekly buckets, taking the lowest remaining fraction.
    """
    return response({'accounts':Pool(db_manager).refresh_quotas()})


@server.tool()
def orchestrator_run_session(session_id: str, parallel: int=15) -> str:
    """Start one bounded detached executor. Explicit Gemini enable flag required; no timer, loop daemon, or fallback.

    Results stay in isolated artifact workspaces until apply_task. Poll get_status for completion. Client restart
    does not kill the runner; calling this tool again returns the existing PID rather than launching another.
    """
    if not 1<=parallel<=15:
        raise ValueError('parallel must be 1..15')
    s = db_manager.session(session_id)
    if s['status'] in ('COMPLETED','CANCELLED'):
        raise ValueError('Session is terminal; reset explicitly before retrying')
    if not Pool(db_manager).enabled():
        raise ValueError('Set ORCHESTRATOR_GEMINI_ENABLED=1 for this MCP only')
    tasks = db_manager.tasks(session_id)
    if not tasks or any(not t['spec'] for t in tasks if t['status']=='PENDING'):
        raise ValueError('Configure every pending task before starting an autonomous run')
    lock = artifact_root()/('run-'+identifier(session_id)+'.json')
    with file_lock(lock.with_suffix('.guard')):
        return _launch(session_id,parallel,lock)


def _launch(session_id,parallel,lock):
    old = runner_info(session_id)
    if old['active']:
        return response({'status':'already_running',**old})
    if lock.exists():
        # A new launcher may be writing the lock; do not mistake it for a stale runner.
        if time.time()-lock.stat().st_mtime<10:
            raise ValueError('Runner launch already in progress')
        lock.unlink()
    with lock.open('x',encoding='utf-8') as f:
        json.dump({'pid':os.getpid(),'pid_bas':psutil.Process().create_time(),'launching':True},f)
    log = artifact_root()/(session_id+'-runner.log')
    try:
        with log.open('ab') as stream:
            flags = subprocess.CREATE_NO_WINDOW | subprocess.CREATE_NEW_PROCESS_GROUP if os.name=='nt' else 0
            process = subprocess.Popen([sys.executable,'-X','utf8',str(Path(__file__).with_name('runner.py')),
                '--db',str(db_manager.path),'--session',session_id,'--parallel',str(parallel)],
                stdin=subprocess.DEVNULL,stdout=stream,stderr=stream,close_fds=True,creationflags=flags)
        info = {'pid':process.pid,'pid_bas':psutil.Process(process.pid).create_time(),'started_at':time.time(),'parallel':parallel}
        temporary = lock.with_suffix('.tmp')
        temporary.write_text(json.dumps(info),encoding='utf-8'); os.replace(temporary,lock)
        return response({'status':'started',**info,'log':str(log)})
    except BaseException:
        lock.unlink(missing_ok=True)
        raise


@server.tool()
def orchestrator_cancel_session(session_id: str) -> str:
    """Cancel pending/running tasks and reject late results. In-flight HTTP may take up to 120s to drain."""
    db_manager.cancel(session_id)
    return response({'status':'cancelled','runner':runner_info(session_id)})


@server.tool()
def orchestrator_apply_task(session_id: str, task_id: str) -> str:
    """Apply accepted files with source-hash conflict checks and backups. Existing user edits cause rejection."""
    return response(apply_outputs(db_manager,session_id,task_id))


@server.tool()
def orchestrator_submit_plan(goal: str, work_dir: str, tasks: list[dict], max_iterations: int|None=None,
                             start: bool=False, parallel: int=15) -> str:
    """One call: validate a whole DAG, create the session, add and freeze every task, optionally start the run.

    Each task: task_id, description, dependencies[], context_files[], output_files[], acceptance_command[] (argv),
    optional role, timeout, max_attempts, account_id, max_tokens. Bad plans create nothing. Analysis-only tasks
    use empty output_files/acceptance_command; their full answer reaches dependent tasks automatically.
    """
    out = plan.submit(db_manager,goal,work_dir,tasks,max_iterations)
    if start:
        out['run'] = json.loads(orchestrator_run_session(out['session_id'],parallel))
    return response(out)


@server.tool()
def orchestrator_wait(session_id: str, timeout_seconds: int=60) -> str:
    """Block up to timeout_seconds (max 600) until the session settles (COMPLETED/BLOCKED/WAITING_CAPACITY/...)."""
    out = plan.wait(db_manager,session_id,min(max(timeout_seconds,0),600))
    return response({**out,'runner':runner_info(session_id)})


@server.tool()
def orchestrator_get_result(session_id: str, task_id: str) -> str:
    """Full untruncated answer, status, attempts, account and output file names of one task."""
    return response(plan.result(db_manager,session_id,task_id))


@server.tool()
def orchestrator_apply_session(session_id: str) -> str:
    """Apply every accepted task in dependency order with hash conflict checks; dirty files are reported, not overwritten."""
    return response(plan.apply_session(db_manager,session_id))


if __name__=='__main__':
    server.run(transport='stdio')
