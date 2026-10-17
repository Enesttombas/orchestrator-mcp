"""Fault injection: provider failures, hard-killed runner, concurrent claim races."""
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import textwrap
import threading
import time
import unittest
from unittest.mock import patch

import plan
from pool import ProviderError
from runner import run
from store import Store
from test_orchestrator import FakePool

GOOD = json.dumps({'summary': 's', 'files': {'m.py': 'def f(x):\n    return x + 1\n'}})
CHECK = 'import os, sys\nsys.path.insert(0, os.getcwd())\nimport m\nassert m.f(1) == 2\n'


class Base(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='orch-chaos-')
        self.root = Path(self.temp.name)
        self.env = patch.dict(os.environ, {'ORCHESTRATOR_ARTIFACTS_DIR': str(self.root / 'a')})
        self.env.start()
        self.db = Store(self.root / 's.db')
        (self.root / 'check.py').write_text(CHECK)

    def tearDown(self):
        self.env.stop()
        self.temp.cleanup()

    def submit(self, attempts=3):
        task = {'task_id': 'A', 'description': 'f(x)=x+1', 'context_files': [], 'output_files': ['m.py'],
                'acceptance_command': [sys.executable, str(self.root / 'check.py')], 'max_attempts': attempts}
        return plan.submit(self.db, 'chaos', str(self.root), [task])['session_id']


def faulty(fault, bad_calls):
    """Pool whose first `bad_calls` completions fail the given way, then answer correctly."""
    class P(FakePool):
        def complete(self, url, messages, max_tokens=4096, **options):
            with self.lock:
                self.calls += 1
                n = self.calls
            if n <= bad_calls:
                if isinstance(fault, BaseException):
                    raise fault
                return fault, {'total_tokens': 3}
            return GOOD, {'total_tokens': 3}
    return P()


FAULTS = {
    'http500': ProviderError('HTTP 500', True),
    'timeout': TimeoutError('read timed out'),
    'not-json': 'I am sorry, here is some prose without any object',
    'empty': '',
    'truncated': '{"summary": "x", "files": {"m.py": "def f(x',
    'wrong-shape': '[1, 2, 3]',
    'files-not-dict': '{"summary": "x", "files": ["m.py"]}',
}


class ProviderFaults(Base):
    def test_every_transient_fault_is_survived_within_the_attempt_budget(self):
        for label, fault in FAULTS.items():
            with self.subTest(fault=label):
                sid = self.submit(attempts=3)
                t0 = time.time()
                res = run(self.db, faulty(fault, 2), sid, 1, capacity_wait=1)
                task = self.db.task(sid, 'A')
                self.assertEqual(res['status'], 'COMPLETED', (label, task['status'], task['error']))
                self.assertEqual(task['attempts'], 3)
                self.assertLess(time.time() - t0, 20)

    def test_persistent_fault_fails_cleanly_at_the_attempt_cap(self):
        for label, fault in FAULTS.items():
            with self.subTest(fault=label):
                sid = self.submit(attempts=2)
                run(self.db, faulty(fault, 99), sid, 1, capacity_wait=1)
                task = self.db.task(sid, 'A')
                self.assertEqual(task['status'], 'FAILED', label)
                self.assertEqual(task['attempts'], 2)
                self.assertNotIn('Traceback', task['error'] or '')
                self.assertLess(len(task['error'] or ''), 400)
                self.assertFalse([t for t in self.db.tasks(sid) if t['status'] == 'IN_PROGRESS'])

    def test_non_retryable_provider_error_does_not_burn_attempts(self):
        sid = self.submit(attempts=3)
        run(self.db, faulty(ProviderError('HTTP 400 bad request', False), 99), sid, 1, capacity_wait=1)
        task = self.db.task(sid, 'A')
        self.assertEqual(task['status'], 'FAILED')
        self.assertEqual(task['attempts'], 1)


class NativeEmptyAnswers(Base):
    """Live hard-task run: 'Empty model response' killed H-CRON on attempt 1 of 3 (non-retryable). Flaky, so retry."""

    def pool_with(self, finish, text):
        from pool import Pool
        pool = Pool(self.db, self.root / 'pool')
        auth = pool.root / 'h01' / 'auth'
        auth.mkdir(parents=True, exist_ok=True)
        (auth / 'f.json').write_text(json.dumps({'project_id': 'p'}))
        body = {'response': {'candidates': [{'finishReason': finish, 'content': {'parts': [{'text': text}]}}],
                'modelVersion': 'm', 'usageMetadata': {'totalTokenCount': 4}}}
        return pool, [{'files': [{'provider': 'antigravity', 'auth_index': 'i'}]},
                      {'status_code': 200, 'body': json.dumps(body)}]

    def test_empty_and_incomplete_answers_are_retryable_provider_errors(self):
        for label, finish, text in (('empty', 'STOP', '  \n'), ('other', 'OTHER', 'x'), ('safety', 'SAFETY', '')):
            with self.subTest(case=label):
                pool, responses = self.pool_with(finish, text)
                with patch.object(pool, '_management', side_effect=responses), self.assertRaises(ProviderError) as caught:
                    pool.complete('http://127.0.0.1:8401', [])
                self.assertTrue(caught.exception.retryable, caught.exception.kind)


class HardKill(Base):
    def test_runner_killed_mid_task_is_taken_over_and_session_completes(self):
        sid = self.submit(attempts=2)
        started = self.root / 'started'
        child = textwrap.dedent(f'''
            import os, sys, time
            sys.path.insert(0, {str(Path(__file__).parent)!r})
            os.environ["ORCHESTRATOR_ARTIFACTS_DIR"] = {str(self.root / "a")!r}
            from store import Store
            from runner import run
            from test_orchestrator import FakePool
            class Slow(FakePool):
                def complete(self, url, messages, max_tokens=4096, **o):
                    open({str(started)!r}, "w").write("1")
                    time.sleep(60)
            run(Store({str(self.root / "s.db")!r}), Slow(), {sid!r}, 1, capacity_wait=5)
        ''')
        proc = subprocess.Popen([sys.executable, '-X', 'utf8', '-c', child],
                                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        try:
            deadline = time.time() + 20
            while not started.exists() and time.time() < deadline:
                time.sleep(.1)
            self.assertTrue(started.exists(), 'child never reached the model call')
            self.assertEqual(self.db.task(sid, 'A')['status'], 'IN_PROGRESS')
        finally:
            proc.kill()
            proc.wait()
        res = run(self.db, faulty('', 0), sid, 1, capacity_wait=5)
        self.assertEqual(res['status'], 'COMPLETED')
        self.assertEqual(self.db.task(sid, 'A')['status'], 'COMPLETED')


class ClaimRace(Base):
    def test_twenty_threads_never_complete_a_task_twice(self):
        tasks = [{'task_id': f'T{i:02}', 'description': 'x', 'context_files': [], 'output_files': [f'o{i}.py'],
                  'acceptance_command': [sys.executable, str(self.root / 'check.py')]} for i in range(40)]
        sid = plan.submit(self.db, 'race', str(self.root), tasks)['session_id']
        done, lock = {}, threading.Lock()

        def worker(n):
            owner = f'w{n}'
            while True:
                task = self.db.claim(sid, owner)
                if not task:
                    return
                self.db.finish(sid, task['task_id'], owner, True, 0, 'artifact', 'ok', '',
                               {'kind': 'command', 'exit_code': 0})
                with lock:
                    done[task['task_id']] = done.get(task['task_id'], 0) + 1
        threads = [threading.Thread(target=worker, args=(n,)) for n in range(20)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(60)
        self.assertEqual(len(done), 40)
        self.assertEqual(set(done.values()), {1})


if __name__ == '__main__':
    unittest.main()
