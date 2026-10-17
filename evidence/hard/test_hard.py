"""Offline proof the hard checks are sound: fail on the untouched stubs, pass on the reference solutions."""
import subprocess
import tempfile
import unittest
from pathlib import Path

import hard


def run_check(task, cwd):
    return subprocess.run(task['acceptance_command'], cwd=cwd, capture_output=True, text=True, timeout=120)


class HardChecks(unittest.TestCase):
    def test_every_check_fails_on_stub_and_passes_on_reference(self):
        dom = hard.hard_domain()
        self.assertGreaterEqual(len(dom['tasks']), 6)
        for task in dom['tasks']:
            with tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp)
                for name, text in dom['files'].items():
                    (root / name).write_text(text, encoding='utf-8')
                self.assertNotEqual(run_check(task, root).returncode, 0, task['task_id'] + ' passes on the stub')
                for name, text in dom['refs'][task['task_id']].items():
                    (root / name).write_text(text, encoding='utf-8')
                r = run_check(task, root)
                self.assertEqual(r.returncode, 0, task['task_id'] + ' reference fails: ' + (r.stderr or r.stdout)[-500:])

    def test_naive_solutions_fail_the_checks(self):
        """A plausible first attempt that ignores the edge rules must be rejected (otherwise the task is not hard)."""
        naive = {
            'H-INTERVALS': 'def merge_intervals(iv):\n    out = []\n    for lo, hi, lc, hc in sorted(iv):\n        if out and lo <= out[-1][1]:\n            out[-1] = (out[-1][0], max(hi, out[-1][1]), out[-1][2], hc)\n        else:\n            out.append((lo, hi, lc, hc))\n    return out\n',
            'H-MONEY': 'def split_money(total_cents, weights):\n    s = sum(weights)\n    return [round(total_cents * w / s) for w in weights]\n',
            'H-SEMVER': 'def satisfies(version, spec):\n    return tuple(map(int, version.split("-")[0].split("."))) >= (1, 0, 0)\n',
        }
        dom = hard.hard_domain()
        by = {t['task_id']: t for t in dom['tasks']}
        for tid, code in naive.items():
            with tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp)
                for name, text in dom['files'].items():
                    (root / name).write_text(text, encoding='utf-8')
                (root / list(dom['refs'][tid])[0]).write_text(code, encoding='utf-8')
                self.assertNotEqual(run_check(by[tid], root).returncode, 0, tid + ' naive solution slips through')


if __name__ == '__main__':
    unittest.main()
