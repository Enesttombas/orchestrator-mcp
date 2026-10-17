"""Offline proof that the matrix itself is sound: every check fails on the untouched sandbox and passes on a known-good solution."""
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

import matrix

GOOD = {
    'ANA-1': 'Highest month is 2026-02 with total 345.25. Average per row is 120.82.',
    'ANA-2': 'api: 2\ndb: 3\nweb: 1\nWorst service: db.',
    'ANA-3': 'api: 2\ndb: 3\nweb: 1\nWorst service: db.',
    'RES-1': 'Use PRAGMA journal_mode=WAL; trade-off: extra -wal/-shm files.',
    'RES-2': 'itertools.chunked does not exist in the standard library; use more_itertools.chunked.',
}
BAD = {
    'ANA-1': 'The best month is 2026-03 with 300.',
    'ANA-2': 'web has the most errors.',
    'ANA-3': 'db: 3',
    'RES-1': 'Use PRAGMA synchronous=FULL.',
    'RES-2': 'itertools.chunked(iterable, n) splits an iterable into lists of length n.',
}


def run_check(task, cwd):
    return subprocess.run(task['acceptance_command'], cwd=cwd, capture_output=True, text=True, timeout=180).returncode


def lay_out(dom, root):
    for name, text in dom['files'].items():
        (root / name).write_text(text, encoding='utf-8')


class Sandbox(unittest.TestCase):
    def test_every_code_check_fails_untouched_and_passes_with_reference(self):
        for factory in matrix.DOMAINS:
            dom = factory()
            for task in dom['tasks']:
                if not task['acceptance_command'] or task['task_id'] not in dom['refs']:
                    continue
                with tempfile.TemporaryDirectory() as tmp:
                    root = Path(tmp)
                    lay_out(dom, root)
                    self.assertNotEqual(run_check(task, root), 0, f"{task['task_id']}: check passes on untouched sandbox")
                    # dependencies' reference outputs must be present for this one to pass
                    wanted = [task['task_id']] + [t for t in task.get('dependencies', [])]
                    for tid in list(wanted):
                        wanted += [d for t in dom['tasks'] if t['task_id'] == tid for d in t.get('dependencies', [])]
                    for tid in dict.fromkeys(wanted):
                        for name, text in dom['refs'].get(tid, {}).items():
                            (root / name).write_text(text, encoding='utf-8')
                    self.assertEqual(run_check(task, root), 0, f"{task['task_id']}: reference fails its own check")

    def test_answer_judges_accept_truth_and_reject_wrong_or_fabricated(self):
        for factory in matrix.DOMAINS:
            dom = factory()
            for tid, judge in dom.get('judges', {}).items():
                self.assertTrue(judge(GOOD[tid])[0], tid + ' rejects a correct answer')
                self.assertFalse(judge(BAD[tid])[0], tid + ' accepts a wrong answer')
                self.assertFalse(judge('')[0], tid + ' accepts empty')

    def test_matrix_covers_nine_domains_with_two_tasks_each(self):
        names = {}
        for factory in matrix.DOMAINS:
            dom = factory()
            names[dom['name']] = len(dom['tasks'])
        self.assertEqual(len(names), 9)
        self.assertTrue(all(n >= 2 for n in names.values()), names)

    def test_task_specs_are_valid_for_the_server(self):
        for factory in matrix.DOMAINS:
            dom = factory()
            ids = [t['task_id'] for t in dom['tasks']]
            self.assertEqual(len(ids), len(set(ids)))
            for t in dom['tasks']:
                for f in t['context_files']:
                    self.assertIn(f, dom['files'], f"{t['task_id']} context {f} missing from sandbox")


if __name__ == '__main__':
    unittest.main()
