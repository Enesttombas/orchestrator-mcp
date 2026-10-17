"""Restricted file proposals, isolated acceptance, and conflict-checked application."""
import hashlib
import json
import os
import re
from pathlib import Path, PureWindowsPath
import subprocess
import sys
import time
import uuid
from locking import file_lock


def digest(data):
    return hashlib.sha256(data).hexdigest()


WINDOWS_DEVICES = {'con','prn','aux','nul','conin$','conout$',*(f'com{n}' for n in range(10)),*(f'lpt{n}' for n in range(10))}


def safe_path(root, name):
    if not isinstance(name,str) or not name or '\\' in name or ':' in name or '\0' in name:
        raise ValueError('Use a relative POSIX file path')
    parts = Path(name).parts
    # Windows strips trailing dots/spaces and treats CON/NUL/AUX... (with any extension) as devices.
    if any(p!=p.strip() or p.endswith('.') and p not in ('.','..') or p.split('.')[0].strip().lower() in WINDOWS_DEVICES for p in parts):
        raise ValueError('Reserved or ambiguous file name')
    if Path(name).is_absolute() or PureWindowsPath(name).is_absolute() or '..' in parts or any(
        p.lower() in ('.git','.env','node_modules','.venv') or p.lower().startswith('.env.') for p in parts):
        raise ValueError('Unsafe or secret path')
    root = Path(root).resolve()
    candidate = (root/name).resolve()
    if not candidate.is_relative_to(root) or candidate == root:
        raise ValueError('Path escapes root')
    return candidate


def artifact_root():
    root = Path(os.environ.get('ORCHESTRATOR_ARTIFACTS_DIR',str(Path.home()/'.orchestrator/artifacts'))).resolve()
    root.mkdir(parents=True,exist_ok=True)
    return root


def save_artifact(sid, tid, filename, content):
    from store import identifier
    identifier(sid); identifier(tid)
    if Path(filename).name != filename or '/' in filename or '\\' in filename:
        raise ValueError('Artifact filename must be a basename')
    root = safe_path(artifact_root(),sid)
    root.mkdir(parents=True,exist_ok=True)
    target = safe_path(root,tid+'_'+uuid.uuid4().hex[:10]+'_'+filename)
    encoded = content.encode('utf-8')
    if len(encoded)>2_000_000:
        raise ValueError('Artifact exceeds 2 MB')
    with target.open('xb') as f:
        f.write(encoded)
    return {'artifact_path':str(target),'bytes_written':len(encoded),'sha256':digest(encoded)}


def validate_spec(root, context_files, output_files, command, timeout=60, max_attempts=2, account_id=None, max_tokens=4096):
    if len(context_files)>100 or len(output_files)>30 or not 1<=timeout<=120 or not 1<=max_attempts<=3 or not 128<=max_tokens<=16384:
        raise ValueError('Task limits exceeded')
    for name in context_files+output_files:
        safe_path(root,name)
    if len(set(output_files))!=len(output_files):
        raise ValueError('Duplicate output files')
    if output_files and not command:
        raise ValueError('Code proposals require an independent acceptance command')
    graded_by = {Path(a).as_posix() for a in (command or []) if isinstance(a,str)}
    if graded_by & {Path(o).as_posix() for o in output_files}:
        raise ValueError('An output file may not be the acceptance script or argument it is graded by')
    if command and (not all(isinstance(s,str) and s for s in command) or len(command)>50):
        raise ValueError('Command must be an argv list')
    if account_id and account_id not in {f'h{n:02}' for n in range(1,16)}:
        raise ValueError('Unknown account_id')
    return {'context_files':list(dict.fromkeys(context_files)), 'output_files':output_files,
            'command':command,'timeout':timeout,'max_attempts':max_attempts,'account_id':account_id,'max_tokens':max_tokens}


def ancestor_tasks(store,sid,tid):
    tasks = {t['task_id']:t for t in store.tasks(sid)}
    order,visited = [],set()
    def visit(node):
        if node in visited:
            return
        visited.add(node)
        for parent in tasks[node]['dependencies']:
            visit(parent)
        if node!=tid:
            order.append(tasks[node])
    visit(tid)
    return order


def prepare(store,sid,task,spec):
    from store import identifier
    identifier(sid); identifier(task['task_id'])
    source = Path(store.session(sid)['work_dir'])
    work = safe_path(artifact_root(),f'{sid}/{task["task_id"]}/attempt-{task["attempts"]}-{uuid.uuid4().hex[:8]}')
    work.mkdir(parents=True)
    base,context = {},{}
    for name in dict.fromkeys(spec['context_files']+spec['output_files']):
        path = safe_path(source,name)
        data = path.read_bytes() if path.is_file() else None
        base[name] = digest(data) if data is not None else None
        if data is not None:
            if len(data)>200_000:
                raise ValueError('Context file exceeds 200 KB')
            target = safe_path(work,name)
            target.parent.mkdir(parents=True,exist_ok=True)
            target.write_bytes(data)
    # Descendants see accepted ancestor outputs, including paths absent from initial context.
    for parent in ancestor_tasks(store,sid,task['task_id']):
        if parent['status']!='COMPLETED':
            raise ValueError('Dependency is not completed')
        ev = json.loads(parent['evidence'] or '{}')
        for name,item in ev.get('outputs',{}).items():
            data = Path(item['path']).read_bytes()
            if digest(data)!=item['sha256']:
                raise ValueError('Dependency artifact changed')
            dest = safe_path(work,name)
            dest.parent.mkdir(parents=True,exist_ok=True)
            dest.write_bytes(data)
            if name not in base:
                original = safe_path(source,name)
                base[name] = digest(original.read_bytes()) if original.is_file() else None
    inherited = {name:digest(safe_path(work,name).read_bytes()) for name in spec['output_files']
                 if safe_path(work,name).is_file()}
    # Retry against the exact rejected proposal, not an empty workspace and a traceback alone.
    previous = json.loads(task.get('previous_evidence') or '{}')
    # 'clean' restarts from the original files and keeps only the log feedback (context-contamination A/B).
    keep_previous = os.environ.get('ORCHESTRATOR_RETRY_CONTEXT','full')!='clean'
    for name,item in (previous.get('outputs',{}) if keep_previous else {}).items():
        if name not in spec['output_files']:
            continue
        path = Path(item['path']).resolve()
        if not path.is_relative_to(artifact_root()):
            raise ValueError('Previous proposal is outside artifact storage')
        data = path.read_bytes()
        if digest(data)!=item['sha256']:
            raise ValueError('Previous proposal changed')
        target=safe_path(work,name);target.parent.mkdir(parents=True,exist_ok=True);target.write_bytes(data)
    for name in dict.fromkeys(spec['context_files']+spec['output_files']):
        path = safe_path(work,name)
        if path.is_file():
            context[name] = path.read_text(encoding='utf-8')
    if sum(len(s) for s in context.values())>400_000:
        raise ValueError('Total context exceeds 400 KB')
    return work,base,context,inherited


def extract_json(content):
    """First JSON object in the reply; tolerates code fences (even unclosed) and prose around it."""
    raw = content.strip()
    try:
        data = json.loads(raw)
    except ValueError:
        data = None
        decoder = json.JSONDecoder()
        start = raw.find('{')
        while start!=-1 and data is None:
            try:
                data,_ = decoder.raw_decode(raw[start:])
            except ValueError:
                start = raw.find('{',start+1)
    if not isinstance(data,dict):
        raise ValueError('Model reply contains no JSON object')
    return data


def apply_edits(name,base,edits):
    """Exact-once SEARCH/REPLACE on `base`; each edit sees the result of the previous one."""
    if not isinstance(edits,list) or not edits or len(edits)>50:
        raise ValueError(f'{name}: edits must be a list of 1..50 search/replace objects')
    text = base
    for number,edit in enumerate(edits,1):
        if not (isinstance(edit,dict) and isinstance(edit.get('search'),str) and edit['search']
                and isinstance(edit.get('replace'),str)):
            raise ValueError(f'{name} edit {number}: need nonempty search and string replace')
        found = text.count(edit['search'])
        if found!=1:
            raise ValueError(f'{name} edit {number}: search text matches {found} places, need exactly 1')
        text = text.replace(edit['search'],edit['replace'],1)
    return text


def parse_response(content,allowed,existing=None):
    """`files` carries complete text; `edits` patches an existing output file (existing: path -> current text)."""
    data = extract_json(content)
    files = data.get('files',{})
    edits = data.get('edits',{})
    if not isinstance(files,dict) or set(files)-set(allowed) or not all(isinstance(v,str) for v in files.values()):
        bad = sorted(set(files)-set(allowed)) if isinstance(files,dict) else []
        raise ValueError(f'Model proposed files outside the allowed scope: {bad[:3]}; allowed: {list(allowed)[:5]}')
    if not isinstance(edits,dict) or set(edits)-set(allowed):
        bad = sorted(set(edits)-set(allowed)) if isinstance(edits,dict) else []
        raise ValueError(f'Model proposed edits outside the allowed scope: {bad[:3]}; allowed: {list(allowed)[:5]}')
    files = dict(files)
    for name,patch in edits.items():
        if name in files:
            raise ValueError(f'{name}: give either files or edits, not both')
        if name not in (existing or {}):
            raise ValueError(f'{name}: no existing content to edit; return the complete file')
        files[name] = apply_edits(name,existing[name],patch)
    if allowed and not files:
        raise ValueError('Model omitted code outputs')
    if any('\0' in s for s in files.values()):
        raise ValueError('Model output contains NUL bytes (binary); return UTF-8 text only')
    if sum(len(s.encode('utf-8')) for s in files.values())>500_000:
        raise ValueError('Model output exceeds 500 KB')
    return str(data.get('summary',''))[:20000],files


def acceptance(command,work,timeout):
    if not command:
        return {'kind':'model_output','exit_code':None}
    # Do not pass API keys, tokens, or client-specific environments to generated code.
    keys = ('SystemRoot','WINDIR','COMSPEC','PATH','PATHEXT','TEMP','TMP','HOME','USERPROFILE',
            'APPDATA','LOCALAPPDATA','PROGRAMFILES','PROGRAMFILES(X86)','SYSTEMDRIVE')
    env = {k:v for k,v in os.environ.items() if k.upper() in {s.upper() for s in keys}}
    env.update(PYTHONIOENCODING='utf-8',PYTHONUTF8='1',PYTHONDONTWRITEBYTECODE='1')
    log = artifact_root()/('acceptance-'+uuid.uuid4().hex+'.log')
    flags = subprocess.CREATE_NO_WINDOW | subprocess.CREATE_NEW_PROCESS_GROUP if os.name=='nt' else 0
    start = time.time()
    with log.open('wb') as stream:
        process = subprocess.Popen(command,cwd=work,env=env,stdin=subprocess.DEVNULL,
                                   stdout=stream,stderr=subprocess.STDOUT,shell=False,creationflags=flags)
        try:
            rc = process.wait(timeout=timeout)
        except subprocess.TimeoutExpired:
            import psutil
            try:
                children = psutil.Process(process.pid).children(recursive=True)
                for child in children:
                    try: child.kill()
                    except psutil.Error: pass
            except psutil.Error:
                pass
            process.kill(); process.wait()
            rc = 124
    return {'kind':'command','argv':command,'exit_code':rc,'log':str(log),
            'log_sha256':digest(log.read_bytes()),'seconds':round(time.time()-start,3)}


SECRET_PATTERNS = (
    ('private key', re.compile(rb'-----BEGIN (?:[A-Z]+ )?PRIVATE KEY-----')),
    ('API key', re.compile(rb'\b(?:AIza[0-9A-Za-z_\-]{35}|sk-[A-Za-z0-9_\-]{20,}|gh[pousr]_[A-Za-z0-9]{36,}|AKIA[0-9A-Z]{16}|xox[baprs]-[A-Za-z0-9\-]{10,})')),
    ('bearer token', re.compile(rb'(?i)bearer\s+[A-Za-z0-9._\-]{30,}')),
)


def secret_kind(data):
    """Name of the first credential-looking pattern in data, else None. Never returns the secret itself."""
    for kind,pattern in SECRET_PATTERNS:
        if pattern.search(data):
            return kind
    return None


def secret_hashes(data):
    """{(kind, sha256 of match)}: lets apply tell a newly introduced secret from one the file already held."""
    return {(kind,digest(m.group(0))) for kind,pattern in SECRET_PATTERNS for m in pattern.finditer(data)}


def apply_outputs(store,sid,tid):
    root = Path(store.session(sid)['work_dir']).resolve()
    lock = artifact_root()/('apply-'+digest(str(root).encode())+'.guard')
    with file_lock(lock):
        return _apply_outputs(store,sid,tid)


def _apply_outputs(store,sid,tid):
    task = store.task(sid,tid)
    if not task or task['status']!='COMPLETED':
        raise ValueError('Only accepted task outputs can be applied')
    evidence = json.loads(task['evidence'] or '{}')
    if evidence.get('kind')!='command' or evidence.get('exit_code')!=0:
        raise ValueError('Successful command evidence required')
    root = Path(store.session(sid)['work_dir']).resolve()
    old,changed = {},[]
    try:
        proposals = {}
        for name,item in evidence.get('outputs',{}).items():
            path = safe_path(root,name)
            existing = path.read_bytes() if path.is_file() else None
            current = digest(existing) if existing is not None else None
            data = Path(item['path']).read_bytes()
            if digest(data)!=item['sha256']:
                raise ValueError('Output artifact changed')
            if current==item['sha256']:
                continue
            expected = {evidence['base_hashes'][name]}
            if name in evidence.get('inherited_hashes',{}):
                expected.add(evidence['inherited_hashes'][name])
            if current not in expected:
                raise ValueError('Source changed since dispatch: '+name)
            fresh = secret_hashes(data)-secret_hashes(existing or b'')
            if fresh:
                raise ValueError(f'Output contains a new {sorted(fresh)[0][0]}: '+name)
            old[name] = existing
            proposals[name] = data
        backup = artifact_root()/sid/('apply-backup-'+uuid.uuid4().hex[:12])
        backup.mkdir(parents=True)
        for name,data in old.items():
            if data is not None:
                dest = safe_path(backup,name); dest.parent.mkdir(parents=True,exist_ok=True); dest.write_bytes(data)
        for name,data in proposals.items():
            path = safe_path(root,name); path.parent.mkdir(parents=True,exist_ok=True)
            temp = path.with_name(path.name+'.orchestrator-'+uuid.uuid4().hex[:8])
            temp.write_bytes(data); os.replace(temp,path); changed.append(name)
        return {'status':'applied','files':changed,'backup':str(backup)}
    except BaseException:
        for name in changed:
            path = safe_path(root,name)
            if old[name] is None:
                path.unlink(missing_ok=True)
            else:
                path.write_bytes(old[name])
        raise
