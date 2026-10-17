"""Bounded durable DAG executor. One detached process per explicitly started run."""
from concurrent.futures import ThreadPoolExecutor, wait, FIRST_COMPLETED
import json
import os
from pathlib import Path
import sys
import time
import uuid

from execution import (acceptance, ancestor_tasks, artifact_root, digest, parse_response, prepare,
                       safe_path, save_artifact)
from pool import Pool, ProviderError, NoCapacity
from store import Store

SYSTEM=('Complete the assigned task. Return ONLY a JSON object with summary (string) and files '
        '(object of relative path to COMPLETE UTF-8 file text). No markdown. '
        'Modify only allowed output files. Do not claim tests ran. Do not use placeholders. '
        'To change an existing output file that is longer than ~60 lines, omit it from files and instead return '
        'edits: {path: [{"search": exact existing text appearing exactly once, "replace": new text}]}; '
        'otherwise return complete text in files. Never use both for one path. '
        'Close SQLite connections explicitly: a connection transaction context does not close it. '
        'For SQLite read-modify-write, BEGIN IMMEDIATE before the first SELECT; setting '
        'isolation_level alone does not start a transaction before reads. '
        'For analysis-only work return files: {} and the actual answer in summary.')


def execute(store,pool,sid,task):
    tid,owner = task['task_id'],task['owner']
    spec = json.loads(task['spec'])
    aid = None
    try:
        work,base,context,inherited = prepare(store,sid,task,spec)
        previous = json.loads(task.get('previous_evidence') or '{}')
        feedback = {'error':task.get('previous_error'),'exit_code':previous.get('exit_code')}
        if previous.get('log'):
            log = Path(previous['log'])
            if log.is_relative_to(artifact_root()) and log.is_file():
                feedback['acceptance_log_tail'] = log.read_text(encoding='utf-8',errors='replace')[-4000:]
        # Only the declared context and accepted ancestors' findings cross the provider boundary.
        upstream = {}
        for parent in ancestor_tasks(store,sid,tid):
            found = json.loads(parent['evidence'] or '{}').get('summary_full') or parent['summary']
            if found:
                upstream[parent['task_id']] = found[:8000]
        messages = [
            {'role':'system','content':SYSTEM},
            {'role':'user','content':json.dumps({'task':task['description'],'role':task['role'],
               'allowed_output_files':spec['output_files'],'context_files':context,
               'upstream':upstream or None,
               'previous_attempt_feedback':feedback if task['attempts']>1 else None},ensure_ascii=False)}]
        with pool.acquire(spec.get('account_id')) as (aid,url):
            store.account(sid,tid,aid)
            started = time.time()
            usage = None
            call_error = None
            effort='low' if task['attempts']==1 else 'high'
            budget = spec['max_tokens']
            if 'token limit' in (task.get('previous_error') or ''):
                budget = min(16384,budget*2**(task['attempts']-1))
            try:
                content,usage = pool.complete(url,messages,max_tokens=budget,reasoning_effort=effort)
            except Exception as e:
                call_error = e.kind if isinstance(e,ProviderError) else type(e).__name__
                if isinstance(e,ProviderError):usage=e.usage
                raise
            finally:
                model_seconds = time.time()-started
                save_artifact(sid,tid,'model-call.json',json.dumps({'account_id':aid,'task_id':tid,
                    'attempt':task['attempts'],'model':pool.model,'usage':usage,'error':call_error,
                    'max_output_tokens_requested':budget,'reasoning_effort':effort,
                    'seconds':round(model_seconds,3)},ensure_ascii=False))
        if store.session(sid)['status']=='CANCELLED':
            return
        summary,files = parse_response(content,spec['output_files'],
                                       {n:context[n] for n in spec['output_files'] if n in context})
        for name,text in files.items():
            path = safe_path(work,name)
            path.parent.mkdir(parents=True,exist_ok=True)
            path.write_text(text,encoding='utf-8',newline='')
        outputs = {name:{'path':str(safe_path(work,name)),
                         'sha256':digest(safe_path(work,name).read_bytes())} for name in files}
        ev = acceptance(spec['command'],work,spec['timeout'])
        # A test command may modify files: acceptance only attests the exact proposed bytes.
        if any(digest(Path(item['path']).read_bytes())!=item['sha256'] for item in outputs.values()):
            raise ValueError('Acceptance modified proposed outputs')
        ev.update(account_id=aid,model=pool.model,usage=usage,outputs=outputs,
                  base_hashes=base,inherited_hashes=inherited,work_dir=str(work),model_seconds=round(model_seconds,3),
                  summary_full=summary)
        saved = save_artifact(sid,tid,'evidence.json',json.dumps(ev,ensure_ascii=False,indent=2))
        passed = ev['exit_code'] in (None,0)
        retry = not passed and task['attempts']<spec['max_attempts']
        store.finish(sid,tid,owner,passed,ev['exit_code'],saved['artifact_path'],summary,
                     '' if passed else 'Acceptance command failed',ev,retry=retry)
    except NoCapacity:
        store.defer(sid,task)
        return False
    except ProviderError as e:
        if aid and e.cooldown:
            store.cooldown(aid,e.cooldown,e.kind)
        _fail(store,sid,task,e.kind,retry=e.retryable and task['attempts']<spec['max_attempts'])
    except Exception as e:
        # No provider body, credentials, or full prompts in durable error messages.
        kind = type(e).__name__
        safe_detail = str(e) if isinstance(e,ValueError) and len(str(e))<180 else kind
        _fail(store,sid,task,safe_detail,retry=task['attempts']<spec['max_attempts'])


def _fail(store,sid,task,error,retry=False):
    try:
        store.finish(sid,task['task_id'],task['owner'],False,error=error,retry=retry)
    except ValueError:
        if store.session(sid)['status']!='CANCELLED':
            raise


def run(store,pool,sid,parallel=15,capacity_wait=None):
    """Drain the DAG. Transient NoCapacity backs off and retries; only a stall of capacity_wait seconds
    with nothing in flight parks the session as WAITING_CAPACITY."""
    if not pool.enabled():
        raise ValueError('Gemini MCP execution is disabled')
    if not 1<=parallel<=15:
        raise ValueError('parallel must be 1..15')
    if capacity_wait is None:
        capacity_wait = float(os.environ.get('ORCHESTRATOR_CAPACITY_WAIT','180'))
    backoff = min(3.0,max(capacity_wait/4,0.05))
    active = {}
    blocked_until = 0.0
    stalled_since = None
    gave_up = False
    pool.refresh_quotas()
    refreshed = time.monotonic()
    with ThreadPoolExecutor(max_workers=parallel) as executor:
        while True:
            if store.session(sid)['status']=='CANCELLED':
                break
            now = time.monotonic()
            if now-refreshed>(30 if blocked_until and not active else 90):
                pool.refresh_quotas()
                refreshed = now
            no_work = False
            while now>=blocked_until and len(active)<parallel:
                owner = f'run_{os.getpid()}_{uuid.uuid4().hex[:16]}'
                task = store.claim(sid,owner,lease_seconds=600,automated=True)
                if not task:
                    no_work = True
                    break
                future = executor.submit(execute,store,pool,sid,task)
                active[future] = task['task_id']
            if not active:
                if no_work:
                    break
                stalled_since = stalled_since or now
                if now-stalled_since>=capacity_wait:
                    gave_up = True
                    break
                time.sleep(min(.25,backoff))
                continue
            done,_ = wait(active,timeout=1,return_when=FIRST_COMPLETED)
            for future in done:
                try:
                    outcome = future.result()
                except Exception as e:
                    # One broken task must not abandon its siblings; its lease expiry makes it recoverable.
                    print(f'task {active[future]} crashed: {type(e).__name__}',file=sys.stderr,flush=True)
                    outcome = None
                if outcome is False:
                    blocked_until = time.monotonic()+backoff
                else:
                    stalled_since = None
                del active[future]
    if gave_up:
        store.waiting_capacity(sid)
    return store.session(sid)


if __name__=='__main__':
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument('--db',required=True)
    parser.add_argument('--session',required=True)
    parser.add_argument('--parallel',type=int,default=15)
    args = parser.parse_args()
    store = Store(args.db)
    # The start tool transfers its lock to this process; only this PID may release it.
    lock = artifact_root()/('run-'+args.session+'.json')
    deadline = time.monotonic()+5
    while time.monotonic()<deadline:
        try:
            info = json.loads(lock.read_text(encoding='utf-8'))
            if info.get('pid')==os.getpid():
                break
        except (OSError,ValueError):
            pass
        time.sleep(.05)
    else:
        sys.exit('Runner lock not assigned')
    try:
        run(store,Pool(store),args.session,args.parallel)
    finally:
        try:
            if json.loads(lock.read_text(encoding='utf-8')).get('pid')==os.getpid():
                lock.unlink()
        except (OSError,ValueError):
            pass
