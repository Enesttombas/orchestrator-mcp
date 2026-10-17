"""Independent tasks must not target the same output file: the second apply would be rejected after the model work was spent."""
import tempfile
import unittest
from pathlib import Path

import plan
from store import Store


def task(tid, out, deps=None):
    t = {'task_id': tid, 'description': 'x', 'context_files': [], 'output_files': out, 'acceptance_command': ['python', 'check.py']}
    if deps:
        t['dependencies'] = deps
    return t


class Overlap(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.db = Store(self.root / 's.db')

    def tearDown(self):
        self.temp.cleanup()

    def submit(self, tasks):
        return plan.submit(self.db, 'g', str(self.root), tasks)

    def test_independent_tasks_sharing_an_output_are_refused_up_front(self):
        with self.assertRaises(ValueError) as ctx:
            self.submit([task('A', ['m.py']), task('B', ['m.py'])])
        self.assertIn('m.py', str(ctx.exception))
        self.assertIn('A', str(ctx.exception))
        self.assertIn('B', str(ctx.exception))

    def test_chained_tasks_may_share_an_output_directly_or_transitively(self):
        self.submit([task('A', ['m.py']), task('B', ['m.py'], ['A'])])
        self.submit([task('A', ['m.py']), task('B', ['n.py'], ['A']), task('C', ['m.py'], ['B'])])

    def test_distinct_outputs_in_parallel_are_fine(self):
        self.submit([task('A', ['a.py']), task('B', ['b.py'])])


if __name__ == '__main__':
    unittest.main()
