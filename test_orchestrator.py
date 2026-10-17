"""Offline regression suite. All files/databases/endpoints are isolated; no real model calls."""
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
import json
import os
from pathlib import Path
import queue
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from unittest.mock import patch

from execution import (acceptance, apply_outputs, artifact_root, parse_response, prepare,
                       safe_path, save_artifact, validate_spec)
from pool import Pool, ProviderError, NoCapacity, parse_quota
from locking import file_lock
from runner import run
from store import Store


class FakePool:
    model='fake-offline'
    def __init__(self, fail_once=False, code='def add(a,b):\n    return a+b\n'):
        self.fail_once,self.code = fail_once,code
        self.lock=threading.Lock(); self.in_use=set(); self.peak=0; self.calls=0
    def enabled(self): return True
    def refresh_quotas(self): return []
    @contextmanager
    def acquire(self,preferred=None):
        with self.lock:
            aid=next(f'h{n:02}' for n in range(1,16) if f'h{n:02}' not in self.in_use)
            self.in_use.add(aid);self.peak=max(self.peak,len(self.in_use))
        try: yield aid,'fake://local'
        finally:
            with self.lock:self.in_use.remove(aid)
    def complete(self,url,messages,max_tokens=4096,**options):
        with self.lock:self.calls+=1; number=self.calls
        time.sleep(.03)
        if self.fail_once and number==1: raise ProviderError('HTTP 429 quota',True,300)
        data=json.loads(messages[-1]['content'])
        return json.dumps({'summary':'offline output','files':{p:self.code for p in data['allowed_output_files']}}),{'total_tokens':10}


class CoreTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory(prefix='orchestrator-test-')
        self.root=Path(self.temp.name)
        self.env=patch.dict(os.environ,{'ORCHESTRATOR_ARTIFACTS_DIR':str(self.root/'artifacts')})
        self.env.start()
        self.db=Store(self.root/'state.db')
        self.sid=self.db.create('Offline regression','custom_dag',60,str(self.root))
    def tearDown(self): self.env.stop();self.temp.cleanup()
    def add(self,tid='A',deps=(),role='worker'):
        self.db.add(self.sid,tid,role,tid,'Implement addition',deps)
    def configured(self,tid='A',deps=()):
        self.add(tid,deps)
        (self.root/'check.py').write_text('from calc import add\nassert add(2,3)==5\nassert add(-2,1)==-1\n')
        spec=validate_spec(self.root,['check.py'],['calc.py'],[sys.executable,'check.py'])
        self.db.configure(self.sid,tid,spec)
    def test_atomic_fifteen_claims(self):
        for n in range(15):self.add(f'T{n}')
        with ThreadPoolExecutor(max_workers=15) as ex:
            tasks=list(ex.map(lambda n:self.db.claim(self.sid,f'w{n}'),range(15)))
        self.assertEqual(len({t['task_id'] for t in tasks}),15)
        self.assertEqual(self.db.session(self.sid)['iteration'],15)
    def test_same_owner_resume_no_double_count(self):
        self.add();a=self.db.claim(self.sid,'one');b=self.db.claim(self.sid,'one')
        self.assertEqual(a,b);self.assertEqual(self.db.session(self.sid)['iteration'],1)
    def test_rejects_missing_dependency_duplicate_and_cycle(self):
        self.add()
        for tid,deps in [('B',['missing']),('A',[]),('B',['B'])]:
            with self.assertRaises(ValueError):self.add(tid,deps)
        self.assertEqual(len(self.db.tasks(self.sid)),1)
    def test_cannot_finish_before_claim_or_wrong_owner(self):
        self.add()
        with self.assertRaises(ValueError):self.db.finish(self.sid,'A','one',True,evidence={'kind':'test'})
        self.db.claim(self.sid,'one')
        with self.assertRaises(ValueError):self.db.finish(self.sid,'A','two',True,evidence={'kind':'test'})
    def test_evidence_required(self):
        self.add();self.db.claim(self.sid,'one')
        with self.assertRaises(ValueError):self.db.finish(self.sid,'A','one',True)
    def test_duplicate_finish_idempotent_and_terminal_immediate(self):
        self.add();self.db.claim(self.sid,'one')
        self.db.finish(self.sid,'A','one',True,0,evidence={'kind':'test'})
        again=self.db.finish(self.sid,'A','one',True,0,evidence={'kind':'test'})
        self.assertEqual(again['status'],'already_recorded')
        self.assertEqual(self.db.session(self.sid)['iteration'],1)
        self.assertEqual(self.db.session(self.sid)['status'],'COMPLETED')
    def test_failure_cascades_and_reset_clears_all(self):
        self.add();self.add('B',['A']);self.add('C',['B'])
        self.db.claim(self.sid,'one');self.db.finish(self.sid,'A','one',False,7,error='failed')
        self.assertEqual([t['status'] for t in self.db.tasks(self.sid)],['FAILED','SKIPPED','SKIPPED'])
        self.db.reset(self.sid)
        for t in self.db.tasks(self.sid):
            self.assertEqual(t['status'],'PENDING');self.assertIsNone(t['exit_code']);self.assertIsNone(t['error'])
        self.assertEqual(self.db.session(self.sid)['iteration'],0)
    def test_max_iterations_enforced_at_claim(self):
        self.add();self.add('B')
        with self.db.tx() as c:c.execute('UPDATE sessions SET max_iterations=1 WHERE session_id=?',(self.sid,))
        self.db.claim(self.sid,'one');self.db.finish(self.sid,'A','one',True,0,evidence={'kind':'test'})
        self.assertIsNone(self.db.claim(self.sid,'two'));self.assertEqual(self.db.session(self.sid)['status'],'LIMIT_REACHED')
    def test_expired_lease_rejects_late_result(self):
        self.add();self.db.claim(self.sid,'old')
        with self.db.tx() as c:c.execute('UPDATE tasks SET lease_until=0')
        with self.assertRaises(ValueError):self.db.finish(self.sid,'A','old',True,evidence={'kind':'test'})
        task=self.db.claim(self.sid,'new');self.assertEqual(task['attempts'],2)
    def test_cancel_rejects_late_result(self):
        self.add();self.db.claim(self.sid,'one');self.db.cancel(self.sid)
        with self.assertRaises(ValueError):self.db.finish(self.sid,'A','one',True,evidence={'kind':'test'})
        self.assertIsNone(self.db.claim(self.sid,'two'))
    def test_active_reset_rejected(self):
        self.add();self.db.claim(self.sid,'one')
        with self.assertRaises(ValueError):self.db.reset(self.sid)
    def test_configuration_immutable_after_claim(self):
        self.configured();self.db.claim(self.sid,'one')
        with self.assertRaises(ValueError):self.db.configure(self.sid,'A',{})
    def test_path_traversal_and_windows_forms_rejected(self):
        for name in ['../x','a/../../x','C:/x','C:\\x','//server/a','.git/config','.env','a/.env.production']:
            with self.subTest(name=name),self.assertRaises(ValueError):safe_path(self.root,name)
        for name in ['../../x','a/x','C:\\x']:
            with self.assertRaises(ValueError):save_artifact(self.sid,'A',name,'x')
    def test_unicode_bytes_and_no_overwrite(self):
        a=save_artifact(self.sid,'A','out.txt','şğ');b=save_artifact(self.sid,'A','out.txt','new')
        self.assertEqual(a['bytes_written'],4);self.assertNotEqual(a['artifact_path'],b['artifact_path'])
    def test_output_scope_validation(self):
        with self.assertRaises(ValueError):parse_response('{"files":{"evil.py":"x"}}',['calc.py'])
        with self.assertRaises(ValueError):validate_spec(self.root,[],['calc.py'],[])
    def test_actual_acceptance_failure_and_timeout(self):
        work=self.root/'work';work.mkdir()
        self.assertEqual(acceptance([sys.executable,'-c','raise SystemExit(7)'],work,3)['exit_code'],7)
        self.assertEqual(acceptance([sys.executable,'-c','import time;time.sleep(10)'],work,.1)['exit_code'],124)
    def test_runner_acceptance_apply_and_dirty_preservation(self):
        self.configured();original=(self.root/'check.py').read_bytes()
        result=run(self.db,FakePool(),self.sid,1)
        self.assertEqual(result['status'],'COMPLETED')
        self.assertFalse((self.root/'calc.py').exists())
        applied=apply_outputs(self.db,self.sid,'A');self.assertEqual(applied['files'],['calc.py'])
        self.assertEqual((self.root/'check.py').read_bytes(),original)
        self.assertEqual(apply_outputs(self.db,self.sid,'A')['files'],[])
    def test_dirty_source_rejects_application(self):
        self.configured();run(self.db,FakePool(),self.sid,1)
        (self.root/'calc.py').write_text('user edit')
        with self.assertRaisesRegex(ValueError,'Source changed'):apply_outputs(self.db,self.sid,'A')
        self.assertEqual((self.root/'calc.py').read_text(),'user edit')
    def test_bad_code_fails_real_test_and_skips_dependent(self):
        self.configured();self.configured('B',['A'])
        run(self.db,FakePool(code='def add(a,b):\n return 0\n'),self.sid,2)
        self.assertEqual(self.db.task(self.sid,'A')['attempts'],2)
        self.assertEqual(self.db.task(self.sid,'A')['exit_code'],1)
        self.assertEqual(self.db.task(self.sid,'B')['status'],'SKIPPED')
    def test_retry_429_is_bounded_and_accounts_cooldown(self):
        self.configured();pool=FakePool(fail_once=True);run(self.db,pool,self.sid,1)
        self.assertEqual(self.db.task(self.sid,'A')['attempts'],2)
        self.assertEqual(self.db.task(self.sid,'A')['status'],'COMPLETED')
        self.assertTrue(self.db.accounts())
    def test_fifteen_parallel_workspaces(self):
        for n in range(15):self.configured(f'T{n}')
        pool=FakePool();run(self.db,pool,self.sid,15)
        self.assertEqual(self.db.session(self.sid)['status'],'COMPLETED')
        workdirs={json.loads(t['evidence'])['work_dir'] for t in self.db.tasks(self.sid)}
        self.assertEqual(len(workdirs),15);self.assertGreater(pool.peak,1)
    def test_additive_migration_retains_original_rows(self):
        import sqlite3
        legacy=self.root/'legacy.db';c=sqlite3.connect(legacy)
        c.execute('CREATE TABLE tasks(session_id TEXT,task_id TEXT,role TEXT,title TEXT,description TEXT,status TEXT,exit_code INTEGER,artifact_path TEXT,summary TEXT,error TEXT,created_at REAL,updated_at REAL,PRIMARY KEY(session_id,task_id))')
        c.execute("INSERT INTO tasks VALUES('old','A','worker','title','desc','COMPLETED',0,'path','summary',NULL,0,0)")
        c.commit();c.close();migrated=Store(legacy)
        self.assertEqual(migrated.task('old','A')['summary'],'summary')
    def test_quota_parser_weekly_short_and_bad_values(self):
        data={'groups':[{'displayName':'Gemini Models','buckets':[{'remainingFraction':.9},
            {'remainingFraction':.2,'resetTime':'2026-10-17T00:00:00Z'},
            {'remainingFraction':'nan'},{'remainingFraction':True}]}]}
        frac,reset,buckets=parse_quota(data)
        self.assertEqual(frac,.2);self.assertIsNotNone(reset);self.assertEqual(len(buckets),2)
        with self.assertRaises(ValueError):parse_quota({'groups':[]})
    def test_quota_errors_replace_stale_success(self):
        self.db.quota('h01',1,None);pool=Pool(self.db,self.root/'missing')
        result=pool.refresh_quota(1)
        self.assertIsNone(result['fraction']);self.assertIsNotNone(result['error'])
    def test_quota_windows_are_separate_and_not_rounded_to_full(self):
        data={'groups':[{'displayName':'Gemini Models','buckets':[
            {'bucketId':'gemini-weekly','window':'weekly','remainingFraction':.8},
            {'bucketId':'gemini-5h','window':'5h','remainingFraction':.9997051}]}]}
        frac,reset,buckets=parse_quota(data);self.db.quota('h01',frac,reset,buckets=buckets)
        row=self.db.quotas()['h01']
        self.assertEqual(row['windows']['weekly']['percent'],80)
        self.assertEqual(row['windows']['5h']['percent'],99.97051)
        self.assertEqual(row['fraction'],.8)
    def test_pool_disabled_and_unknown_quota_rejected(self):
        pool=Pool(self.db,self.root/'pool')
        with patch.dict(os.environ,{'ORCHESTRATOR_GEMINI_ENABLED':'0'}),self.assertRaises(ProviderError):
            with pool.acquire():pass
        with patch.dict(os.environ,{'ORCHESTRATOR_GEMINI_ENABLED':'1'}),self.assertRaises(ProviderError):
            with pool.acquire():pass

    def test_os_lock_releases_after_process_crash(self):
        lock=self.root/'guard'
        with file_lock(lock):
            with self.assertRaises(BlockingIOError):
                with file_lock(lock):pass
        script='from locking import file_lock;import os,sys\nwith file_lock(sys.argv[1]):\n os._exit(17)\n'
        p=subprocess.run([sys.executable,'-c',script,str(lock)],cwd=Path(__file__).parent)
        self.assertEqual(p.returncode,17)
        with file_lock(lock):pass

    def test_two_pool_instances_cannot_share_account(self):
        self.db.quota('h01',1,None)
        one=Pool(self.db,self.root/'pool');two=Pool(self.db,self.root/'pool')
        with patch.dict(os.environ,{'ORCHESTRATOR_GEMINI_ENABLED':'1'}),patch.object(Pool,'_config',return_value={}):
            with one.acquire('h01'):
                with self.assertRaises(NoCapacity):
                    with two.acquire('h01'):pass
            with two.acquire('h01') as (aid,url):self.assertEqual(aid,'h01')

    def test_no_capacity_keeps_work_and_retry_budget(self):
        self.configured()
        class Busy(FakePool):
            @contextmanager
            def acquire(self,preferred=None):
                raise NoCapacity('busy')
                yield
        result=run(self.db,Busy(),self.sid,1,capacity_wait=.3)
        self.assertEqual(result['status'],'WAITING_CAPACITY')
        self.assertEqual(result['iteration'],0)
        self.assertEqual(self.db.task(self.sid,'A')['attempts'],0)
        self.assertEqual(run(self.db,FakePool(),self.sid,1)['status'],'COMPLETED')
    def test_account_fairness_survives_pool_restart(self):
        for n in range(1,16):self.db.quota(f'h{n:02}',1,None)
        selected=[]
        with patch.dict(os.environ,{'ORCHESTRATOR_GEMINI_ENABLED':'1'}),patch.object(Pool,'_config',return_value={}):
            for n in range(15):
                with Pool(self.db,self.root/'pool').acquire() as (aid,url):selected.append(aid)
        self.assertEqual(len(set(selected)),15)

    def test_dispatch_database_failure_releases_account(self):
        self.db.quota('h01',1,None)
        pool=Pool(self.db,self.root/'pool')
        with patch.dict(os.environ,{'ORCHESTRATOR_GEMINI_ENABLED':'1'}),patch.object(Pool,'_config',return_value={}):
            with patch.object(self.db,'dispatch',side_effect=RuntimeError('offline')):
                with self.assertRaises(RuntimeError):
                    with pool.acquire('h01'):pass
            with pool.acquire('h01') as (aid,url):self.assertEqual(aid,'h01')

    def generation_fixture(self, finish='STOP', status=200):
        pool=Pool(self.db,self.root/'pool');auth=pool.root/'h01/auth';auth.mkdir(parents=True)
        (auth/'fixture.json').write_text(json.dumps({'project_id':'offline-project'}))
        response={'response':{'candidates':[{'finishReason':finish,
            'content':{'parts':[{'text':'{"files":{}}'}]}}],
            'modelVersion':'fixture-model','usageMetadata':{'totalTokenCount':10,
                'promptTokenCount':3,'candidatesTokenCount':5,'thoughtsTokenCount':2}}}
        return pool,[{'files':[{'provider':'antigravity','auth_index':'fixture-index'}]},
                     {'status_code':status,'body':json.dumps(response)}]

    def test_native_generation_retains_token_limits_and_identity(self):
        pool,responses=self.generation_fixture()
        with patch.object(pool,'_management',side_effect=responses) as called:
            content,usage=pool.complete('http://127.0.0.1:8401',[
                {'role':'system','content':'system'},{'role':'user','content':'task'}],max_tokens=4096)
        payload=called.call_args.args[2];body=json.loads(payload['data'])
        self.assertEqual(body['request']['generationConfig']['maxOutputTokens'],4096)
        self.assertEqual(body['request']['generationConfig']['thinkingConfig']['thinkingBudget'],512)
        self.assertEqual(body['request']['systemInstruction']['parts'],[{'text':'system'}])
        self.assertEqual(payload['auth_index'],'fixture-index')
        self.assertTrue(payload['url'].endswith('/v1internal:generateContent'))
        self.assertEqual(payload['header']['Authorization'],'Bearer $TOKEN$')
        self.assertEqual(usage['total_tokens'],10)
        self.assertEqual(body['model'],'gemini-3.8-flash-high')
        self.assertEqual(self.db.generations()['h01']['completed'],1)

    def test_truncated_generation_fails_and_preserves_actual_cost(self):
        pool,responses=self.generation_fixture('MAX_TOKENS')
        with patch.object(pool,'_management',side_effect=responses),self.assertRaises(ProviderError) as caught:
            pool.complete('http://127.0.0.1:8401',[],max_tokens=128)
        self.assertEqual(caught.exception.usage['total_tokens'],10)
        self.assertTrue(caught.exception.retryable)  # runner retries with a doubled token budget (test_adaptive)
        self.assertEqual(self.db.generations()['h01']['failed'],1)
        self.assertEqual(self.db.generations()['h01']['known_tokens'],10)

    def test_native_rate_limit_records_unknown_cost_and_cooldown(self):
        pool,responses=self.generation_fixture(status=429)
        with patch.object(pool,'_management',side_effect=responses),self.assertRaises(ProviderError) as caught:
            pool.complete('http://127.0.0.1:8401',[])
        self.assertTrue(caught.exception.retryable)
        self.assertEqual(caught.exception.cooldown,300)
        self.assertEqual(self.db.generations()['h01']['unknown_usage'],1)

    def test_dead_runner_recovered_without_lease_timeout(self):
        self.add();self.db.claim(self.sid,'run_999999999_dead')
        recovered=self.db.claim(self.sid,'new')
        self.assertEqual(recovered['task_id'],'A')
        with self.assertRaises(ValueError):self.db.finish(self.sid,'A','run_999999999_dead',True,evidence={'test':1})

    def test_failed_acceptance_feedback_reaches_retry(self):
        self.configured()
        class Repair(FakePool):
            feedback=None
            def complete(self,url,messages,max_tokens=4096,**options):
                data=json.loads(messages[-1]['content']);self.feedback=data['previous_attempt_feedback']
                if self.calls:self.assertion=data['context_files']['calc.py']
                self.code='def add(a,b):\n return a+b\n' if self.calls else 'def add(a,b):\n return 0\n'
                return super().complete(url,messages,max_tokens)
        pool=Repair();self.assertEqual(run(self.db,pool,self.sid,1)['status'],'COMPLETED')
        self.assertEqual(pool.feedback['exit_code'],1)
        self.assertIn('AssertionError',pool.feedback['acceptance_log_tail'])
        self.assertIn('return 0',pool.assertion)
        calls=[json.loads(p.read_text(encoding='utf-8')) for p in (artifact_root()/self.sid).glob('*_model-call.json')]
        self.assertEqual(len(calls),2)
        self.assertEqual(sum(c['usage']['total_tokens'] for c in calls),20)

    def test_deleted_existing_source_is_conflict(self):
        self.configured();(self.root/'calc.py').write_text('def add(a,b): return 0\n')
        run(self.db,FakePool(),self.sid,1);(self.root/'calc.py').unlink()
        with self.assertRaisesRegex(ValueError,'Source changed'):apply_outputs(self.db,self.sid,'A')
        self.assertFalse((self.root/'calc.py').exists())

    def test_child_applies_after_accepted_parent(self):
        self.configured();self.configured('B',['A'])
        class Versions(FakePool):
            def complete(self,url,messages,max_tokens=4096,**options):
                self.code='def add(a,b):\n return a+b\n' + ('# child\n' if self.calls else '# parent\n')
                return super().complete(url,messages,max_tokens)
        self.assertEqual(run(self.db,Versions(),self.sid,1)['status'],'COMPLETED')
        apply_outputs(self.db,self.sid,'A');apply_outputs(self.db,self.sid,'B')
        self.assertIn('# child',(self.root/'calc.py').read_text())


class Wire:
    def __init__(self,root,enabled=False,entry=None,env_overrides=None):
        self.seq=0;self.q=queue.Queue()
        env=os.environ.copy();env.update(ORCHESTRATOR_DB_PATH=str(root/'wire.db'),
            ORCHESTRATOR_ARTIFACTS_DIR=str(root/'artifacts'),ORCHESTRATOR_GEMINI_ENABLED='1' if enabled else '0')
        env.update(env_overrides or {})
        self.p=subprocess.Popen([sys.executable,'-X','utf8',str(entry or Path(__file__).with_name('server.py'))],
            stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=subprocess.DEVNULL,
            text=True,encoding='utf-8',env=env)
        def reader():
            for line in self.p.stdout:self.q.put(line)
        threading.Thread(target=reader,daemon=True).start()
        self.request('initialize',{'protocolVersion':'2025-06-18','capabilities':{},
            'clientInfo':{'name':'regression','version':'1'}})
        self.send({'jsonrpc':'2.0','method':'notifications/initialized'})
    def send(self,data):self.p.stdin.write(json.dumps(data)+'\n');self.p.stdin.flush()
    def request(self,method,params):
        self.seq+=1;seq=self.seq
        self.send({'jsonrpc':'2.0','id':seq,'method':method,'params':params})
        while True:
            msg=json.loads(self.q.get(timeout=15))
            if msg.get('id')==seq:return msg
    def call(self,name,**kwargs):
        result=self.request('tools/call',{'name':name,'arguments':kwargs})['result']
        if result.get('isError'):raise ValueError('MCP tool error')
        return json.loads(result['content'][0]['text'])
    def close(self):
        self.p.stdin.close()
        try:self.p.wait(timeout=5)
        except subprocess.TimeoutExpired:self.p.kill();self.p.wait()
        self.p.stdout.close()


class WireTests(unittest.TestCase):
    def test_stdio_restart_and_real_command_evidence(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);wire=Wire(root)
            try:
                names={t['name'] for t in wire.request('tools/list',{})['result']['tools']}
                self.assertIn('orchestrator_run_session',names)
                self.assertIn('orchestrator_refresh_quotas',names)
                sid=wire.call('orchestrator_init',goal='Wire test',mode='custom_dag',work_dir=temp)['session_id']
                wire.call('orchestrator_add_task',session_id=sid,task_id='A',role='reviewer',title='test',description='test')
                wire.call('orchestrator_get_next_action',session_id=sid,worker_id='wire')
                wire.close();wire=Wire(root)
                resumed=wire.call('orchestrator_get_next_action',session_id=sid,worker_id='wire')
                self.assertEqual(resumed['task']['task_id'],'A')
                with self.assertRaises(ValueError):wire.call('orchestrator_record_result',session_id=sid,task_id='A',status='SUCCESS',worker_id='wire')
                artifact=wire.call('orchestrator_save_artifact',session_id=sid,task_id='A',filename='proof.txt',content='wire')
                result=wire.call('orchestrator_record_result',session_id=sid,task_id='A',status='SUCCESS',worker_id='wire',
                    artifact_path=artifact['artifact_path'],acceptance_command=[sys.executable,'-c','assert 2+2==4'])
                self.assertTrue(result['is_gate_passed'])
                final=wire.call('orchestrator_get_status',session_id=sid,format='json')
                self.assertEqual(final['session']['status'],'COMPLETED')
                self.assertEqual(json.loads(final['tasks'][0]['evidence'])['exit_code'],0)
                with self.assertRaises(ValueError):wire.call('orchestrator_save_artifact',session_id=sid,task_id='A',filename='../escape',content='x')
                with self.assertRaises(ValueError):wire.call('orchestrator_run_session',session_id=sid)
            finally:wire.close()


if __name__=='__main__':unittest.main(verbosity=2)
