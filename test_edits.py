"""SEARCH/REPLACE edit format: exact-once matching, scope, retry feedback and output-size saving."""
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

from execution import parse_response, validate_spec
from runner import run
from store import Store
from test_orchestrator import FakePool
import plan

BIG = ''.join(f'def f{i}(x):\n    return x + {i}\n\n' for i in range(120))  # 360 lines


def reply(**data):
    return json.dumps({'summary': 's', **data})


class ParseEdits(unittest.TestCase):
    def test_single_match_applies(self):
        _, files = parse_response(reply(edits={'m.py': [{'search': 'return x + 7\n', 'replace': 'return x * 7\n'}]}),
                                  ['m.py'], {'m.py': BIG})
        self.assertIn('return x * 7', files['m.py'])
        self.assertEqual(files['m.py'].count('return x * 7'), 1)
        self.assertEqual(len(files['m.py'].splitlines()), len(BIG.splitlines()))

    def test_edits_apply_in_order_on_the_result_of_the_previous_edit(self):
        edits = [{'search': 'def f1(x):\n    return x + 1\n', 'replace': 'def f1(x):\n    return MARK\n'},
                 {'search': 'return MARK', 'replace': 'return x - 1'}]
        _, files = parse_response(reply(edits={'m.py': edits}), ['m.py'], {'m.py': BIG})
        self.assertIn('def f1(x):\n    return x - 1\n', files['m.py'])

    def test_zero_matches_rejected_with_specific_message(self):
        with self.assertRaisesRegex(ValueError, r'm\.py edit 1.*matches 0'):
            parse_response(reply(edits={'m.py': [{'search': 'not there', 'replace': 'x'}]}), ['m.py'], {'m.py': BIG})

    def test_ambiguous_match_rejected(self):
        with self.assertRaisesRegex(ValueError, r'matches 120'):
            parse_response(reply(edits={'m.py': [{'search': '    return x + ', 'replace': 'x'}]}), ['m.py'], {'m.py': BIG})

    def test_new_file_cannot_use_edits_and_must_be_full(self):
        with self.assertRaisesRegex(ValueError, 'no existing content'):
            parse_response(reply(edits={'new.py': [{'search': 'a', 'replace': 'b'}]}), ['new.py'], {})
        _, files = parse_response(reply(files={'new.py': 'x = 1\n'}), ['new.py'], {})
        self.assertEqual(files, {'new.py': 'x = 1\n'})

    def test_out_of_scope_and_double_specification_rejected(self):
        with self.assertRaises(ValueError):
            parse_response(reply(edits={'evil.py': [{'search': 'a', 'replace': 'b'}]}), ['m.py'], {'m.py': BIG})
        with self.assertRaisesRegex(ValueError, 'both'):
            parse_response(reply(files={'m.py': 'x'}, edits={'m.py': [{'search': 'def', 'replace': 'x'}]}),
                           ['m.py'], {'m.py': BIG})

    def test_malformed_edit_entries_rejected(self):
        for bad in ({'m.py': 'text'}, {'m.py': [{'search': '', 'replace': 'x'}]}, {'m.py': [{'search': 'def'}]},
                    {'m.py': [{'search': 'def', 'replace': 5}]}, {'m.py': []}):
            with self.assertRaises(ValueError, msg=str(bad)):
                parse_response(reply(edits=bad), ['m.py'], {'m.py': BIG})

    def test_full_file_mode_unchanged(self):
        _, files = parse_response(reply(files={'m.py': 'x = 1\n'}), ['m.py'])
        self.assertEqual(files, {'m.py': 'x = 1\n'})

    def test_edit_response_is_at_least_half_smaller_than_whole_file(self):
        whole = reply(files={'m.py': BIG.replace('return x + 7\n', 'return x * 7\n')})
        edit = reply(edits={'m.py': [{'search': 'return x + 7\n', 'replace': 'return x * 7\n'}]})
        self.assertLessEqual(len(edit), len(whole) * 0.5, (len(edit), len(whole)))
        self.assertLessEqual(len(edit), len(whole) * 0.05)  # in practice far below the 50% bar


class EndToEnd(unittest.TestCase):
    def test_runner_applies_edits_to_existing_file_and_retries_on_bad_search(self):
        with tempfile.TemporaryDirectory() as temp, patch.dict(os.environ, {'ORCHESTRATOR_ARTIFACTS_DIR': str(Path(temp) / 'a')}):
            root = Path(temp)
            (root / 'm.py').write_text(BIG, encoding='utf-8')
            (root / 'check.py').write_text('import os, sys\nsys.path.insert(0, os.getcwd())\nimport m\nassert m.f7(1) == 7\nassert m.f8(1) == 9\n', encoding='utf-8')
            db = Store(root / 's.db')
            sid = plan.submit(db, 'edit', str(root), [{
                'task_id': 'A', 'description': 'make f7 multiply', 'context_files': ['m.py'],
                'output_files': ['m.py'], 'acceptance_command': [sys.executable, str(root / 'check.py')]}])['session_id']
            seen = []

            class Scripted(FakePool):
                def complete(self, url, messages, max_tokens=4096, **options):
                    data = json.loads(messages[-1]['content'])
                    seen.append(data['previous_attempt_feedback'])
                    search = 'nonexistent' if len(seen) == 1 else 'return x + 7\n'
                    text = reply(edits={'m.py': [{'search': search, 'replace': 'return x * 7\n'}]})
                    return text, {'total_tokens': 1}
            self.assertEqual(run(db, Scripted(), sid, 1, capacity_wait=1)['status'], 'COMPLETED')
            self.assertIn('matches 0', seen[1]['error'])
            self.assertEqual(db.task(sid, 'A')['attempts'], 2)
            out = json.loads(db.task(sid, 'A')['evidence'])['outputs']['m.py']['path']
            self.assertIn('return x * 7', Path(out).read_text(encoding='utf-8'))


if __name__ == '__main__':
    unittest.main()
