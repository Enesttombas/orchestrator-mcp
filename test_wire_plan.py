"""Real stdio JSON-RPC client path: tool surface and bad-input resilience of the v4 tools."""
import sys
import tempfile
import unittest
from pathlib import Path

from test_orchestrator import Wire

TASK = {'task_id': 'A', 'description': 'd', 'context_files': [], 'output_files': ['m.py'], 'acceptance_command': [sys.executable, 'c.py']}


class WirePlan(unittest.TestCase):
    def test_tool_surface_and_server_survives_bad_plans(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            (root / 'proj').mkdir()
            wire = Wire(root)
            try:
                names = {t['name'] for t in wire.request('tools/list', {})['result']['tools']}
                self.assertEqual(len(names), 18, sorted(names))
                for must in ('orchestrator_submit_plan', 'orchestrator_wait', 'orchestrator_get_result', 'orchestrator_apply_session'):
                    self.assertIn(must, names)
                proj = str(root / 'proj')
                bad = {
                    'cycle': [{**TASK, 'task_id': 'A', 'dependencies': ['B']}, {**TASK, 'task_id': 'B', 'output_files': ['n.py'], 'dependencies': ['A']}],
                    'escape': [{**TASK, 'output_files': ['../evil.py']}],
                    'absolute': [{**TASK, 'output_files': ['C:/Windows/evil.py']}],
                    'empty-description': [{**TASK, 'description': '  '}],
                    'no-command': [{**TASK, 'acceptance_command': []}],
                    'not-a-list': 'oops',
                    'empty-plan': [],
                }
                for label, tasks in bad.items():
                    with self.assertRaises(ValueError, msg=label):
                        wire.call('orchestrator_submit_plan', goal='g', work_dir=proj, tasks=tasks)
                # nothing was created by the rejected plans, and the server still answers
                self.assertEqual(wire.call('orchestrator_list_sessions', limit=10), [])
                ok = wire.call('orchestrator_submit_plan', goal='g', work_dir=proj, tasks=[TASK])
                self.assertEqual(ok['tasks'], ['A'])
            finally:
                wire.close()


if __name__ == '__main__':
    unittest.main()
