"""SQLite state; every ownership transition uses one IMMEDIATE transaction."""
from contextlib import contextmanager
import json
import os
from pathlib import Path
import re
import sqlite3
import time
import uuid


def identifier(value):
    if not isinstance(value, str) or not re.fullmatch(r"[A-Za-z0-9_-]{1,80}", value):
        raise ValueError("Invalid identifier")
    return value


class Store:
    def __init__(self, path):
        self.path = Path(path).resolve()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.tx() as c:
            c.executescript('''
                CREATE TABLE IF NOT EXISTS sessions (
                  session_id TEXT PRIMARY KEY, goal TEXT NOT NULL, mode TEXT NOT NULL,
                  status TEXT NOT NULL DEFAULT 'RUNNING', iteration INTEGER NOT NULL DEFAULT 0,
                  max_iterations INTEGER NOT NULL, work_dir TEXT, created_at REAL, updated_at REAL);
                CREATE TABLE IF NOT EXISTS tasks (
                  session_id TEXT NOT NULL, task_id TEXT NOT NULL, role TEXT NOT NULL,
                  title TEXT NOT NULL, description TEXT NOT NULL, status TEXT NOT NULL DEFAULT 'PENDING',
                  exit_code INTEGER, artifact_path TEXT, summary TEXT, error TEXT,
                  created_at REAL, updated_at REAL, PRIMARY KEY(session_id,task_id),
                  FOREIGN KEY(session_id) REFERENCES sessions(session_id));
                CREATE TABLE IF NOT EXISTS dependencies (
                  session_id TEXT, task_id TEXT, depends_on_task_id TEXT,
                  PRIMARY KEY(session_id,task_id,depends_on_task_id),
                  FOREIGN KEY(session_id,task_id) REFERENCES tasks(session_id,task_id));
                CREATE TABLE IF NOT EXISTS account_health (
                  account_id TEXT PRIMARY KEY, cooldown_until REAL NOT NULL DEFAULT 0,
                  failures INTEGER NOT NULL DEFAULT 0, last_error TEXT);
                CREATE TABLE IF NOT EXISTS account_quota (
                  account_id TEXT PRIMARY KEY, fraction REAL, reset_at REAL,
                  checked_at REAL NOT NULL, error TEXT, buckets TEXT);
                CREATE TABLE IF NOT EXISTS account_dispatch (
                  account_id TEXT PRIMARY KEY, leases INTEGER NOT NULL, last_selected REAL NOT NULL);
                CREATE TABLE IF NOT EXISTS account_generation (
                  account_id TEXT PRIMARY KEY, requests INTEGER NOT NULL DEFAULT 0,
                  completed INTEGER NOT NULL DEFAULT 0, failed INTEGER NOT NULL DEFAULT 0,
                  known_tokens INTEGER NOT NULL DEFAULT 0, unknown_usage INTEGER NOT NULL DEFAULT 0);
            ''')
            # Additive migration: preserve the existing database and all historical rows.
            columns = {r[1] for r in c.execute('PRAGMA table_info(tasks)')}
            for name, typ in {'owner':'TEXT', 'lease_until':'REAL', 'attempts':'INTEGER DEFAULT 0',
                              'spec':'TEXT', 'evidence':'TEXT', 'account_id':'TEXT'}.items():
                if name not in columns:
                    c.execute(f'ALTER TABLE tasks ADD COLUMN {name} {typ}')

    @contextmanager
    def tx(self):
        c = sqlite3.connect(self.path, timeout=30, isolation_level=None)
        c.row_factory = sqlite3.Row
        c.execute('PRAGMA journal_mode=WAL')
        c.execute('PRAGMA foreign_keys=ON')
        try:
            c.execute('BEGIN IMMEDIATE')
            yield c
            if c.in_transaction:
                c.commit()
        except BaseException:
            if c.in_transaction:
                c.rollback()
            raise
        finally:
            c.close()

    def create(self, goal, mode='staged_pipeline', max_iterations=60, work_dir=None):
        if not goal.strip() or mode not in ('staged_pipeline', 'custom_dag'):
            raise ValueError('Nonempty goal and supported mode required')
        if not 1 <= max_iterations <= 10000:
            raise ValueError('max_iterations must be 1..10000')
        root = Path(work_dir or os.getcwd()).resolve(strict=True)
        if not root.is_dir():
            raise ValueError('work_dir must be a directory')
        sid = 'ses_' + uuid.uuid4().hex[:16]
        now = time.time()
        with self.tx() as c:
            c.execute('INSERT INTO sessions VALUES (?,?,?,?,?,?,?,?,?)',
                      (sid, goal, mode, 'RUNNING', 0, max_iterations, str(root), now, now))
        return sid

    def session(self, sid):
        with self.tx() as c:
            row = c.execute('SELECT * FROM sessions WHERE session_id=?', (sid,)).fetchone()
            if not row:
                raise ValueError('Unknown session')
            return dict(row)

    def tasks(self, sid):
        with self.tx() as c:
            tasks = [dict(r) for r in c.execute(
                'SELECT * FROM tasks WHERE session_id=? ORDER BY created_at,task_id', (sid,))]
            for t in tasks:
                t['dependencies'] = [r[0] for r in c.execute(
                    'SELECT depends_on_task_id FROM dependencies WHERE session_id=? AND task_id=?',
                    (sid, t['task_id']))]
            return tasks

    def task(self, sid, tid):
        return next((t for t in self.tasks(sid) if t['task_id'] == tid), None)

    def add(self, sid, tid, role, title, description, deps=()):
        identifier(tid)
        deps = list(dict.fromkeys(deps))
        with self.tx() as c:
            session = c.execute('SELECT * FROM sessions WHERE session_id=?', (sid,)).fetchone()
            if not session or session['status'] != 'RUNNING':
                raise ValueError('Session must exist and be RUNNING')
            existing = {r[0] for r in c.execute('SELECT task_id FROM tasks WHERE session_id=?', (sid,))}
            # Only existing parents are accepted; forward references and updates cannot create cycles.
            if tid in existing or tid in deps or not set(deps) <= existing:
                raise ValueError('Duplicate task, cycle, or missing dependency')
            now = time.time()
            c.execute('''INSERT INTO tasks
                (session_id,task_id,role,title,description,created_at,updated_at)
                VALUES(?,?,?,?,?,?,?)''', (sid, tid, role, title, description, now, now))
            c.executemany('INSERT INTO dependencies VALUES(?,?,?)', [(sid, tid, p) for p in deps])

    def configure(self, sid, tid, spec):
        with self.tx() as c:
            row = c.execute('SELECT * FROM tasks WHERE session_id=? AND task_id=?', (sid, tid)).fetchone()
            if not row or row['status'] != 'PENDING' or row['attempts']:
                raise ValueError('Only unstarted tasks can be configured')
            c.execute('UPDATE tasks SET spec=?,updated_at=? WHERE session_id=? AND task_id=?',
                      (json.dumps(spec), time.time(), sid, tid))

    @staticmethod
    def _refresh(c, sid):
        s = c.execute('SELECT * FROM sessions WHERE session_id=?', (sid,)).fetchone()
        if not s:
            raise ValueError('Unknown session')
        if s['status'] in ('CANCELLED', 'PAUSED'):
            return s['status']
        statuses = [r[0] for r in c.execute('SELECT status FROM tasks WHERE session_id=?', (sid,))]
        if statuses and all(v == 'COMPLETED' for v in statuses):
            status = 'COMPLETED'
        elif 'IN_PROGRESS' in statuses:
            status = 'RUNNING'
        elif s['iteration'] >= s['max_iterations'] and 'PENDING' in statuses:
            status = 'LIMIT_REACHED'
        elif any(v in ('FAILED', 'SKIPPED') for v in statuses):
            status = 'BLOCKED'
        else:
            status = 'RUNNING'
        c.execute('UPDATE sessions SET status=?,updated_at=? WHERE session_id=?', (status, time.time(), sid))
        return status

    def claim(self, sid, owner, lease_seconds=300, automated=False):
        identifier(owner)
        if not 1 <= lease_seconds <= 3600:
            raise ValueError('lease_seconds must be 1..3600')
        now = time.time()
        with self.tx() as c:
            s = c.execute('SELECT * FROM sessions WHERE session_id=?', (sid,)).fetchone()
            if not s:
                raise ValueError('Unknown session')
            if s['status'] in ('CANCELLED', 'PAUSED', 'COMPLETED'):
                return None
            # A dead detached runner has no in-flight work; recover without waiting ten minutes.
            import psutil
            for t in c.execute("SELECT * FROM tasks WHERE session_id=? AND status='IN_PROGRESS' AND owner LIKE 'run_%'", (sid,)).fetchall():
                try:
                    pid = int(t['owner'].split('_')[1])
                    p = psutil.Process(pid)
                    alive = p.is_running() and p.create_time() <= t['updated_at']
                except (ValueError,IndexError,psutil.Error):
                    alive = False
                if not alive:
                    c.execute("UPDATE tasks SET status='PENDING',owner=NULL,lease_until=NULL,error='Previous runner exited' WHERE session_id=? AND task_id=?", (sid,t['task_id']))
            c.execute('''UPDATE tasks SET status='PENDING',owner=NULL,lease_until=NULL,
                         error='Lease expired; previous result rejected' WHERE session_id=?
                         AND status='IN_PROGRESS' AND (lease_until IS NULL OR lease_until<?)''', (sid, now))
            old = c.execute("SELECT * FROM tasks WHERE session_id=? AND owner=? AND status='IN_PROGRESS'", (sid, owner)).fetchone()
            if old:
                return {**dict(old),'previous_evidence':old['evidence'],'previous_error':old['error']}
            if s['iteration'] >= s['max_iterations']:
                self._refresh(c, sid)
                return None
            query = '''SELECT t.* FROM tasks t WHERE t.session_id=? AND t.status='PENDING'
                AND NOT EXISTS(SELECT 1 FROM dependencies d LEFT JOIN tasks p
                  ON p.session_id=d.session_id AND p.task_id=d.depends_on_task_id
                  WHERE d.session_id=t.session_id AND d.task_id=t.task_id
                  AND (p.status IS NULL OR p.status!='COMPLETED'))'''
            if automated:
                query += ' AND t.spec IS NOT NULL'
            row = c.execute(query + ' ORDER BY t.created_at,t.task_id LIMIT 1', (sid,)).fetchone()
            if not row:
                self._refresh(c, sid)
                return None
            c.execute('''UPDATE tasks SET status='IN_PROGRESS',owner=?,lease_until=?,attempts=attempts+1,
                         exit_code=NULL,error=NULL,evidence=NULL,updated_at=? WHERE session_id=? AND task_id=?''',
                      (owner, now + lease_seconds, now, sid, row['task_id']))
            c.execute('UPDATE sessions SET iteration=iteration+1,status=\'RUNNING\',updated_at=? WHERE session_id=?', (now, sid))
            result = dict(c.execute('SELECT * FROM tasks WHERE session_id=? AND task_id=?', (sid, row['task_id'])).fetchone())
            result['previous_evidence'] = row['evidence']
            result['previous_error'] = row['error']
            return result

    def defer(self, sid, task):
        with self.tx() as c:
            changed = c.execute("""UPDATE tasks SET status='PENDING',owner=NULL,lease_until=NULL,
                attempts=attempts-1,evidence=?,error=?,updated_at=? WHERE session_id=? AND task_id=?
                AND status='IN_PROGRESS' AND owner=?""",
                (task.get('previous_evidence'),task.get('previous_error'),time.time(),sid,task['task_id'],task['owner'])).rowcount
            if changed:
                c.execute('UPDATE sessions SET iteration=iteration-1 WHERE session_id=?',(sid,))

    def waiting_capacity(self, sid):
        with self.tx() as c:
            c.execute("UPDATE sessions SET status='WAITING_CAPACITY',updated_at=? WHERE session_id=? AND status='RUNNING'",(time.time(),sid))

    def finish(self, sid, tid, owner, success, exit_code=None, artifact='', summary='', error='', evidence=None, retry=False):
        now = time.time()
        with self.tx() as c:
            row = c.execute('SELECT * FROM tasks WHERE session_id=? AND task_id=?', (sid, tid)).fetchone()
            if not row:
                raise ValueError('Unknown task')
            if row['status'] in ('COMPLETED', 'FAILED') and row['owner'] == owner:
                return {'status': 'already_recorded', 'final_status': row['status']}
            s = c.execute('SELECT * FROM sessions WHERE session_id=?', (sid,)).fetchone()
            if s['status'] == 'CANCELLED' or row['status'] != 'IN_PROGRESS' or row['owner'] != owner or (row['lease_until'] or 0) < now:
                raise ValueError('Task not owned, cancelled, or lease expired')
            if success and not evidence:
                raise ValueError('Server-produced evidence required')
            status = 'COMPLETED' if success else ('PENDING' if retry else 'FAILED')
            c.execute('''UPDATE tasks SET status=?,exit_code=?,artifact_path=?,summary=?,error=?,evidence=?,
                         lease_until=NULL,owner=?,updated_at=? WHERE session_id=? AND task_id=?''',
                      (status, exit_code, artifact, summary[:1000], error[:1000], json.dumps(evidence) if evidence else None,
                       None if retry else owner, now, sid, tid))
            if status == 'FAILED':
                frontier = [tid]
                while frontier:
                    parent = frontier.pop()
                    for r in c.execute('''SELECT t.task_id FROM tasks t JOIN dependencies d
                        ON t.session_id=d.session_id AND t.task_id=d.task_id WHERE d.session_id=?
                        AND d.depends_on_task_id=? AND t.status='PENDING' ''', (sid, parent)).fetchall():
                        c.execute("UPDATE tasks SET status='SKIPPED',error=? WHERE session_id=? AND task_id=?",
                                  ('Dependency failed: ' + parent, sid, r[0]))
                        frontier.append(r[0])
            return {'status':'recorded', 'final_status':status, 'session_status':self._refresh(c, sid),
                    'is_gate_passed':success}

    def reset(self, sid):
        with self.tx() as c:
            if c.execute("SELECT 1 FROM tasks WHERE session_id=? AND status='IN_PROGRESS' AND lease_until>?", (sid, time.time())).fetchone():
                raise ValueError('Cancel/wait for active workers before resetting')
            count = c.execute('''UPDATE tasks SET status='PENDING',exit_code=NULL,artifact_path=NULL,summary=NULL,
                error=NULL,owner=NULL,lease_until=NULL,evidence=NULL,attempts=0,account_id=NULL
                WHERE session_id=? AND status IN ('FAILED','SKIPPED','IN_PROGRESS','CANCELLED')''', (sid,)).rowcount
            if not c.execute('SELECT 1 FROM sessions WHERE session_id=?', (sid,)).fetchone():
                raise ValueError('Unknown session')
            c.execute("UPDATE sessions SET status='RUNNING',iteration=0,updated_at=? WHERE session_id=?", (time.time(), sid))
            return count

    def cancel(self, sid):
        with self.tx() as c:
            if not c.execute('SELECT 1 FROM sessions WHERE session_id=?', (sid,)).fetchone():
                raise ValueError('Unknown session')
            c.execute("UPDATE sessions SET status='CANCELLED',updated_at=? WHERE session_id=?", (time.time(), sid))
            c.execute("UPDATE tasks SET status='CANCELLED',owner=NULL,lease_until=NULL WHERE session_id=? AND status IN ('PENDING','IN_PROGRESS')", (sid,))

    def account(self, sid, tid, account_id):
        with self.tx() as c:
            c.execute('UPDATE tasks SET account_id=? WHERE session_id=? AND task_id=?', (account_id, sid, tid))

    def cooldown(self, account_id, seconds, error):
        with self.tx() as c:
            c.execute('''INSERT INTO account_health VALUES(?,?,1,?) ON CONFLICT(account_id) DO UPDATE SET
                cooldown_until=excluded.cooldown_until,failures=failures+1,last_error=excluded.last_error''',
                      (account_id, time.time()+seconds, error))

    def accounts(self):
        with self.tx() as c:
            return {r['account_id']:dict(r) for r in c.execute('SELECT * FROM account_health')}

    def dispatch(self, aid):
        with self.tx() as c:
            c.execute('''INSERT INTO account_dispatch VALUES(?,1,?) ON CONFLICT(account_id) DO UPDATE SET
                         leases=leases+1,last_selected=excluded.last_selected''',(aid,time.time()))

    def dispatches(self):
        with self.tx() as c:
            return {r['account_id']:dict(r) for r in c.execute('SELECT * FROM account_dispatch')}

    def generation_start(self, aid):
        with self.tx() as c:
            c.execute('''INSERT INTO account_generation(account_id,requests) VALUES(?,1)
                ON CONFLICT(account_id) DO UPDATE SET requests=requests+1''',(aid,))

    def generation_finish(self, aid, success, usage):
        total=usage.get('total_tokens') if isinstance(usage,dict) else None
        known=isinstance(total,int) and not isinstance(total,bool) and total>=0
        with self.tx() as c:
            changed=c.execute('''UPDATE account_generation SET completed=completed+?,failed=failed+?,
                known_tokens=known_tokens+?,unknown_usage=unknown_usage+? WHERE account_id=?''',
                (int(success),int(not success),total if known else 0,int(not known),aid)).rowcount
            if not changed:raise ValueError('Generation was not started')

    def generations(self):
        with self.tx() as c:
            return {r['account_id']:dict(r) for r in c.execute('SELECT * FROM account_generation')}

    def quota(self, account_id, fraction, reset_at, error=None, buckets=()):
        with self.tx() as c:
            c.execute('''INSERT INTO account_quota VALUES(?,?,?,?,?,?) ON CONFLICT(account_id) DO UPDATE SET
                fraction=excluded.fraction,reset_at=excluded.reset_at,checked_at=excluded.checked_at,
                error=excluded.error,buckets=excluded.buckets''',
                (account_id,fraction,reset_at,time.time(),error,json.dumps(buckets)))

    def quotas(self):
        with self.tx() as c:
            rows={r['account_id']:dict(r) for r in c.execute('SELECT * FROM account_quota')}
        for row in rows.values():
            row['buckets']=json.loads(row.get('buckets') or '[]')
            row['windows']={}
            for window in ('5h','weekly'):
                matches=[b for b in row['buckets'] if b.get('window')==window]
                if matches:
                    bucket=min(matches,key=lambda b:b['fraction'])
                    row['windows'][window]={'fraction':bucket['fraction'],
                        'percent':round(bucket['fraction']*100,6),'reset_at':bucket['reset_at']}
        return rows

    def list_sessions(self, limit=10):
        with self.tx() as c:
            return [dict(r) for r in c.execute('SELECT * FROM sessions ORDER BY created_at DESC LIMIT ?', (max(1,min(limit,100)),))]
