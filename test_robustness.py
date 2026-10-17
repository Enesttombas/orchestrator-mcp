"""Adversarial/usability regressions found by analysis of runner, store and server. Offline only."""
from contextlib import contextmanager
import json
import os
from pathlib import Path
import sqlite3
import sys
import tempfile
import threading
import time
import unittest
from unittest.mock import patch

from execution import artifact_root
from pool import NoCapacity
from runner import run
from store import Store
from test_orchestrator import FakePool
import plan


class Base(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='orch-robust-')
        self.root = Path(self.temp.name)
        self.env = patch.dict(os.environ, {'ORCHESTRATOR_ARTIFACTS_DIR': str(self.root / 'artifacts')})
        self.env.start()
        self.db = Store(self.root / 'state.db')
        (self.root / 'check.py').write_text('from calc import add\nassert add(2,3)==5\n')

    def tearDown(self):
        self.env.stop()
        self.temp.cleanup()

    def code_task(self, tid, deps=(), out='calc.py'):
        return {'task_id': tid, 'description': 'implement add', 'dependencies': list(deps),
                'context_files': ['check.py'], 'output_files': [out],
                'acceptance_command': [sys.executable, '-c', 'pass']}


class Limited(FakePool):
    """Only `slots` accounts exist; extra concurrent requests see NoCapacity, like a shared fleet."""
    def __init__(self, slots):
        super().__init__()
        self.slots = slots

    @contextmanager
    def acquire(self, preferred=None):
        with self.lock:
            if len(self.in_use) >= self.slots:
                raise NoCapacity('busy')
        with super().acquire(preferred) as pair:
            yield pair


class CapacityTests(Base):
    def test_partial_capacity_still_drains_every_task(self):
        sid = plan.submit(self.db, 'drain', str(self.root), [self.code_task(f'T{n}', out=f'c{n}.py') for n in range(6)])['session_id']
        result = run(self.db, Limited(2), sid, 6, capacity_wait=20)
        statuses = {t['task_id']: t['status'] for t in self.db.tasks(sid)}
        self.assertEqual(result['status'], 'COMPLETED')
        self.assertNotIn('PENDING', statuses.values(), statuses)

    def test_gives_up_only_after_capacity_wait(self):
        sid = plan.submit(self.db, 'busy', str(self.root), [self.code_task('A')])['session_id']

        class Never(FakePool):
            @contextmanager
            def acquire(self, preferred=None):
                raise NoCapacity('busy')
                yield
        started = time.monotonic()
        result = run(self.db, Never(), sid, 1, capacity_wait=1)
        self.assertEqual(result['status'], 'WAITING_CAPACITY')
        self.assertGreaterEqual(time.monotonic() - started, 1)
        self.assertEqual(self.db.task(sid, 'A')['attempts'], 0)


class ResilienceTests(Base):
    def test_store_failure_in_one_task_does_not_kill_run(self):
        sid = plan.submit(self.db, 'resilient', str(self.root),
                          [self.code_task('A', out='a.py'), self.code_task('B')])['session_id']
        real = Store.finish

        def flaky(store, session, tid, *args, **kwargs):
            if tid == 'A':
                raise sqlite3.OperationalError('database is locked')
            return real(store, session, tid, *args, **kwargs)
        with patch.object(Store, 'finish', flaky):
            run(self.db, FakePool(), sid, 2, capacity_wait=1)
        self.assertEqual(self.db.task(sid, 'B')['status'], 'COMPLETED')


class AnalysisFlowTests(Base):
    def test_full_analysis_answer_kept_and_given_to_dependent(self):
        long_answer = 'finding-' * 600  # 4800 chars, far over the old 1000 cap
        seen = {}

        class Scripted(FakePool):
            def complete(self, url, messages, max_tokens=4096, **options):
                data = json.loads(messages[-1]['content'])
                if data['allowed_output_files']:
                    seen['upstream'] = data.get('upstream')
                    return super().complete(url, messages, max_tokens)
                return json.dumps({'summary': long_answer, 'files': {}}), {'total_tokens': 5}
        tasks = [{'task_id': 'SCOUT', 'description': 'analyse', 'context_files': [], 'output_files': [],
                  'acceptance_command': []}, self.code_task('BUILD', deps=['SCOUT'])]
        sid = plan.submit(self.db, 'flow', str(self.root), tasks)['session_id']
        self.assertEqual(run(self.db, Scripted(), sid, 2, capacity_wait=1)['status'], 'COMPLETED')
        self.assertEqual(plan.result(self.db, sid, 'SCOUT')['summary'], long_answer)
        self.assertEqual(seen['upstream']['SCOUT'], long_answer)
        report = plan.apply_session(self.db, sid)
        self.assertEqual((report['applied'], report['rejected']), (['calc.py'], {}))


class PlanTests(Base):
    def test_rejects_bad_plans_without_leaving_a_session(self):
        before = len(self.db.list_sessions(100))
        for bad in ([self.code_task('A', deps=['Z'])],
                    [self.code_task('A', deps=['B']), self.code_task('B', deps=['A'])],
                    [self.code_task('A'), self.code_task('A')],
                    [{**self.code_task('A'), 'output_files': ['../x.py']}],
                    []):
            with self.assertRaises(ValueError):
                plan.submit(self.db, 'bad', str(self.root), bad)
        self.assertEqual(len(self.db.list_sessions(100)), before)

    def test_out_of_order_plan_is_sorted_by_dependency(self):
        sid = plan.submit(self.db, 'order', str(self.root),
                          [self.code_task('B', deps=['A']), self.code_task('A')])['session_id']
        self.assertEqual(self.db.task(sid, 'B')['dependencies'], ['A'])

    def test_apply_session_applies_whole_chain_and_reports_failures(self):
        sid = plan.submit(self.db, 'apply', str(self.root),
                          [self.code_task('A'), self.code_task('B', deps=['A'], out='extra.py')])['session_id']
        run(self.db, FakePool(), sid, 2, capacity_wait=1)
        report = plan.apply_session(self.db, sid)
        self.assertEqual(sorted(report['applied']), ['calc.py', 'extra.py'])
        self.assertEqual(report['rejected'], {})
        self.assertTrue((self.root / 'extra.py').is_file())

    def test_apply_session_skips_dirty_files_but_applies_others(self):
        sid = plan.submit(self.db, 'dirty', str(self.root),
                          [self.code_task('A'), self.code_task('B', out='other.py')])['session_id']
        run(self.db, FakePool(), sid, 2, capacity_wait=1)
        (self.root / 'calc.py').write_text('user edit')
        report = plan.apply_session(self.db, sid)
        self.assertIn('A', report['rejected'])
        self.assertEqual(report['applied'], ['other.py'])
        self.assertEqual((self.root / 'calc.py').read_text(), 'user edit')

    def test_wait_returns_when_session_settles_and_times_out_otherwise(self):
        sid = plan.submit(self.db, 'wait', str(self.root), [self.code_task('A')])['session_id']
        self.assertEqual(plan.wait(self.db, sid, timeout=0.3, poll=0.05)['timed_out'], True)
        run(self.db, FakePool(), sid, 1, capacity_wait=1)
        out = plan.wait(self.db, sid, timeout=5, poll=0.05)
        self.assertFalse(out['timed_out'])
        self.assertEqual(out['session_status'], 'COMPLETED')


class WireToolTests(unittest.TestCase):
    def test_new_tools_over_stdio(self):
        from test_orchestrator import Wire
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            wire = Wire(root)
            try:
                names = {t['name'] for t in wire.request('tools/list', {})['result']['tools']}
                self.assertEqual(len(names), 18)
                task = {'task_id': 'A', 'description': 'x', 'context_files': [], 'output_files': ['a.py'],
                        'acceptance_command': [sys.executable, '-c', 'pass']}
                with self.assertRaises(ValueError):
                    wire.call('orchestrator_submit_plan', goal='bad', work_dir=temp,
                              tasks=[{**task, 'dependencies': ['missing']}])
                sid = wire.call('orchestrator_submit_plan', goal='ok', work_dir=temp, tasks=[task])['session_id']
                waited = wire.call('orchestrator_wait', session_id=sid, timeout_seconds=0)
                self.assertTrue(waited['timed_out'])
                self.assertEqual(wire.call('orchestrator_get_result', session_id=sid, task_id='A')['status'], 'PENDING')
                with self.assertRaises(ValueError):  # Gemini flag off in this wire: start must refuse, not hang
                    wire.call('orchestrator_submit_plan', goal='go', work_dir=temp, tasks=[task], start=True)
            finally:
                wire.close()


if __name__ == '__main__':
    unittest.main()
