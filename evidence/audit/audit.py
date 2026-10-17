"""Isolated, offline audit. Never opens the live orchestrator database.

Run with the Python executable configured for the orchestrator MCP server.
The boundary tests intentionally assert the required behavior and may fail.
"""
import hashlib
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

OUT = Path(__file__).resolve().parent
SOURCE = Path.home() / '.gemini/antigravity/mcp_servers/orchestrator'
SANDBOX = tempfile.TemporaryDirectory(prefix='mcp-orchestrator-audit-')
ROOT = Path(SANDBOX.name)
os.environ['ORCHESTRATOR_DB_PATH'] = str(ROOT / 'boot.db')
os.environ['ORCHESTRATOR_ARTIFACTS_DIR'] = str(ROOT / 'artifacts')
sys.path.insert(0, str(SOURCE))
import server
from db import DatabaseManager
from dag import DAGEngine


class Wire:
    """Use actual stdio JSON-RPC, not direct decorated-function calls."""
    def __init__(self, db_name='wire.db'):
        env = os.environ.copy()
        env.update(ORCHESTRATOR_DB_PATH=str(ROOT / db_name),
                   ORCHESTRATOR_ARTIFACTS_DIR=str(ROOT / 'wire-artifacts'),
                   PYTHONIOENCODING='utf-8')
        self.proc = subprocess.Popen(
            [sys.executable, '-X', 'utf8', str(SOURCE / 'server.py')],
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            text=True, encoding='utf-8', env=env, cwd=str(ROOT))
        self.q = queue.Queue()
        self.errors = []
        self.seq = 0
        def read_stdout():
            for line in self.proc.stdout:
                self.q.put(line)
        def read_stderr():
            self.errors.extend(self.proc.stderr)
        threading.Thread(target=read_stdout, daemon=True).start()
        threading.Thread(target=read_stderr, daemon=True).start()
        init = self.request('initialize', {
            'protocolVersion': '2025-06-18', 'capabilities': {},
            'clientInfo': {'name': 'local-audit', 'version': '1.0'}})
        self.initialize = init
        self.send({'jsonrpc': '2.0', 'method': 'notifications/initialized'})

    def send(self, message):
        self.proc.stdin.write(json.dumps(message, ensure_ascii=False) + '\n')
        self.proc.stdin.flush()

    def request(self, method, params):
        self.seq += 1
        request_id = self.seq
        self.send({'jsonrpc': '2.0', 'id': request_id, 'method': method, 'params': params})
        until = time.monotonic() + 15
        while time.monotonic() < until:
            line = self.q.get(timeout=max(0.01, until-time.monotonic()))
            response = json.loads(line)
            if response.get('id') == request_id:
                return response
        raise TimeoutError(method)

    def raw_call(self, name, **arguments):
        return self.request('tools/call', {'name': name, 'arguments': arguments})

    def call(self, name, **arguments):
        response = self.raw_call(name, **arguments)
        if 'error' in response:
            raise AssertionError(response)
        result = response['result']
        if result.get('isError'):
            raise AssertionError(result)
        return json.loads(result['content'][0]['text'])

    def close(self):
        if self.proc.poll() is None:
            self.proc.stdin.close()
            try:
                self.proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                self.proc.terminate()
                self.proc.wait(timeout=5)
        self.proc.stdout.close()
        self.proc.stderr.close()


class WireSmoke(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.wire = Wire()

    @classmethod
    def tearDownClass(cls):
        cls.wire.close()

    def test_handshake_and_eight_tools(self):
        info = self.wire.initialize['result']
        self.assertEqual(info['serverInfo']['name'], 'antigravity-orchestrator')
        names = {t['name'] for t in self.wire.request('tools/list', {})['result']['tools']}
        self.assertEqual(len(names), 8)
        self.assertIn('orchestrator_record_result', names)

    def test_real_local_command_and_roundtrip(self):
        sid = self.wire.call('orchestrator_init', goal='Offline smoke', mode='custom_dag')['session_id']
        self.wire.call('orchestrator_add_task', session_id=sid, task_id='A', role='reviewer', title='A', description='Local assert')
        action = self.wire.call('orchestrator_get_next_action', session_id=sid)
        self.assertEqual(action['task']['task_id'], 'A')
        rc = subprocess.run([sys.executable, '-c', 'assert 2 + 2 == 4'], cwd=ROOT).returncode
        self.assertEqual(rc, 0)
        recorded = self.wire.call('orchestrator_record_result', session_id=sid, task_id='A', status='SUCCESS', exit_code=rc)
        self.assertTrue(recorded['is_gate_passed'])
        self.assertEqual(self.wire.call('orchestrator_get_next_action', session_id=sid)['session_status'], 'COMPLETED')

    def test_wire_missing_required_argument_rejected(self):
        response = self.wire.raw_call('orchestrator_init')
        self.assertTrue('error' in response or response.get('result', {}).get('isError'))

    def test_wire_nonzero_exit_blocks_dependents(self):
        sid = self.wire.call('orchestrator_init', goal='Offline failure')['session_id']
        self.wire.call('orchestrator_get_next_action', session_id=sid)
        rc = subprocess.run([sys.executable, '-c', 'raise SystemExit(7)'], cwd=ROOT).returncode
        result = self.wire.call('orchestrator_record_result', session_id=sid, task_id='T1_SCOUT', status='SUCCESS', exit_code=rc)
        self.assertFalse(result['is_gate_passed'])
        self.assertEqual(len(result['skipped_dependents']), 3)

    def test_wire_process_restart_resumes_task(self):
        first = Wire('restart.db')
        try:
            sid = first.call('orchestrator_init', goal='Restart')['session_id']
            task = first.call('orchestrator_get_next_action', session_id=sid)['task']['task_id']
        finally:
            first.close()
        second = Wire('restart.db')
        try:
            resumed = second.call('orchestrator_get_next_action', session_id=sid)
            self.assertTrue(resumed['is_resumed'])
            self.assertEqual(resumed['task']['task_id'], task)
        finally:
            second.close()

    def test_wire_boundary_characterization(self):
        # Characterization: confirm the important unit-test findings on the wire too.
        sid = self.wire.call('orchestrator_init', goal='Wire boundary probes', max_iterations=1)['session_id']
        bypass = self.wire.call('orchestrator_record_result', session_id=sid, task_id='T3_REVIEW', status='SUCCESS')
        unknown = self.wire.call('orchestrator_record_result', session_id=sid, task_id='MISSING', status='SUCCESS')
        dispatch = self.wire.call('orchestrator_get_next_action', session_id=sid)
        escaped = self.wire.call('orchestrator_save_artifact', session_id='../wire-escaped', task_id='T', filename='probe.txt', content='audit only')
        observations = {
            'protocol': self.wire.initialize['result'].get('protocolVersion'),
            'pending_reviewer_accepted_without_dependencies': bypass['is_gate_passed'],
            'unknown_task_accepted': unknown['is_gate_passed'],
            'iteration_after_two_unverified_reports': unknown['iteration'],
            'dispatch_after_limit': dispatch['action'],
            'artifact_escaped_root': not Path(escaped['artifact_path']).resolve().is_relative_to((ROOT / 'wire-artifacts').resolve())}
        (OUT / 'wire-observations.json').write_text(json.dumps(observations, indent=2), encoding='utf-8')
        self.assertTrue(observations['pending_reviewer_accepted_without_dependencies'])
        self.assertTrue(observations['unknown_task_accepted'])
        self.assertTrue(observations['artifact_escaped_root'])
        self.assertEqual(observations['dispatch_after_limit'], 'EXECUTE_TASK')


class Boundaries(unittest.TestCase):
    def setUp(self):
        self.case = ROOT / self._testMethodName
        self.case.mkdir()
        os.environ['ORCHESTRATOR_ARTIFACTS_DIR'] = str(self.case / 'artifacts')
        self.db = DatabaseManager(self.case / 'state.db')
        server.db_manager = self.db
        server.dag_engine = DAGEngine(self.db)
        self.sid = json.loads(server.orchestrator_init('Boundary check'))['session_id']

    def test_success_requires_independent_acceptance_evidence(self):
        # No command is executed, and the supplied evidence path does not exist.
        server.orchestrator_get_next_action(self.sid)
        result = json.loads(server.orchestrator_record_result(
            self.sid, 'T1_SCOUT', 'SUCCESS', artifact_path=str(self.case / 'missing.log')))
        self.assertFalse(result['is_gate_passed'], 'Caller-supplied SUCCESS and default rc=0 were trusted without evidence')

    def test_cannot_complete_pending_reviewer_before_dependencies(self):
        server.orchestrator_record_result(self.sid, 'T3_REVIEW', 'SUCCESS')
        self.assertNotEqual(self.db.get_task(self.sid, 'T3_REVIEW')['status'], 'COMPLETED')

    def test_unknown_task_does_not_count_as_success(self):
        result = json.loads(server.orchestrator_record_result(self.sid, 'DOES_NOT_EXIST', 'SUCCESS'))
        self.assertFalse(result.get('is_gate_passed', False), 'Unknown task was reported as accepted')
        self.assertEqual(self.db.get_session(self.sid)['iteration'], 0)

    def test_duplicate_result_is_idempotent(self):
        server.orchestrator_get_next_action(self.sid)
        server.orchestrator_record_result(self.sid, 'T1_SCOUT', 'SUCCESS')
        server.orchestrator_record_result(self.sid, 'T1_SCOUT', 'SUCCESS')
        self.assertEqual(self.db.get_session(self.sid)['iteration'], 1)

    def test_iteration_limit_stops_dispatch(self):
        sid = json.loads(server.orchestrator_init('Limited', max_iterations=1))['session_id']
        server.orchestrator_get_next_action(sid)
        server.orchestrator_record_result(sid, 'T1_SCOUT', 'SUCCESS')
        next_action = json.loads(server.orchestrator_get_next_action(sid))
        self.assertNotEqual(next_action['action'], 'EXECUTE_TASK', 'Dispatched next stage after configured limit')

    def test_artifact_cannot_escape_artifact_root(self):
        result = json.loads(server.orchestrator_save_artifact('../escaped', 'T1', 'probe.txt', 'audit only'))
        target = Path(result['artifact_path']).resolve()
        self.assertTrue(target.is_relative_to((self.case / 'artifacts').resolve()), str(target))

    def test_reset_clears_previous_failure_metadata(self):
        server.orchestrator_get_next_action(self.sid)
        server.orchestrator_record_result(self.sid, 'T1_SCOUT', 'FAILED', exit_code=7, error='old failure')
        server.orchestrator_reset_session(self.sid)
        task = self.db.get_task(self.sid, 'T1_SCOUT')
        self.assertIsNone(task['exit_code'])
        self.assertIsNone(task['error'])

    def test_missing_dependency_is_rejected(self):
        result = json.loads(server.orchestrator_add_task(
            self.sid, 'ORPHAN', 'worker', 'Orphan', 'Missing dependency', ['MISSING']))
        self.assertEqual(result.get('status'), 'error', 'Unresolvable dependency was stored')

    def test_independent_tasks_can_be_claimed_separately(self):
        sid = json.loads(server.orchestrator_init('Two independent tasks', mode='custom_dag'))['session_id']
        for task in ['A', 'B']:
            server.orchestrator_add_task(sid, task, 'worker', task, task)
        first = json.loads(server.orchestrator_get_next_action(sid))
        second = json.loads(server.orchestrator_get_next_action(sid))
        self.assertNotEqual(first['task']['task_id'], second['task']['task_id'],
                            'A second client receives the same in-progress task; no worker ownership')

    def test_record_completion_updates_session_status(self):
        for task in ['T1_SCOUT', 'T2_BUILD', 'T3_REVIEW', 'T4_COMPACT']:
            server.orchestrator_get_next_action(self.sid)
            server.orchestrator_record_result(self.sid, task, 'SUCCESS')
        state = json.loads(server.orchestrator_get_status(self.sid, format='json'))
        self.assertEqual(state['session']['status'], 'COMPLETED')


class EvidenceResult(unittest.TextTestResult):
    records = []

    def addSuccess(self, test):
        super().addSuccess(test)
        self.records.append({'test': test.id(), 'status': 'PASS'})

    def addFailure(self, test, err):
        super().addFailure(test, err)
        self.records.append({'test': test.id(), 'status': 'FAIL', 'detail': str(err[1])})

    def addError(self, test, err):
        super().addError(test, err)
        self.records.append({'test': test.id(), 'status': 'ERROR', 'detail': str(err[1])})


if __name__ == '__main__':
    import test_orchestrator
    suite = unittest.TestSuite([
        unittest.defaultTestLoader.loadTestsFromModule(test_orchestrator),
        unittest.defaultTestLoader.loadTestsFromTestCase(WireSmoke),
        unittest.defaultTestLoader.loadTestsFromTestCase(Boundaries)])
    with (OUT / 'test-output.txt').open('w', encoding='utf-8') as stream:
        result = unittest.TextTestRunner(stream=stream, verbosity=2, resultclass=EvidenceResult).run(suite)
    hashes = {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in SOURCE.glob('*.py')}
    evidence = {'source': str(SOURCE), 'python': sys.executable,
                'source_sha256': hashes, 'tests_run': result.testsRun,
                'failures': len(result.failures), 'errors': len(result.errors),
                'exit_code': 0 if result.wasSuccessful() else 1, 'tests': result.records,
                'network_or_model_calls': 0, 'database_scope': 'temporary isolated database'}
    (OUT / 'test-results.json').write_text(json.dumps(evidence, indent=2, ensure_ascii=False), encoding='utf-8')
    print(json.dumps({k:v for k,v in evidence.items() if k not in ['source_sha256','tests']}, indent=2))
    print((OUT / 'test-output.txt').read_text(encoding='utf-8')[-14000:])
    # Leave only audit evidence; all test databases and traversal probes were temporary.
    SANDBOX.cleanup()
    raise SystemExit(evidence['exit_code'])
