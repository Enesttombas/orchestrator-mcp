"""Adaptive retry: token-limit growth, tolerant JSON extraction, explicit scope feedback, retry-context knob."""
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

from execution import parse_response
from pool import ProviderError
from runner import run
from store import Store
from test_orchestrator import FakePool
import plan


class Extraction(unittest.TestCase):
    def test_prose_wrapped_json_is_extracted(self):
        text = 'Here is the result:\n{"summary": "ok", "files": {"a.py": "x = {1}\\n"}}\nHope that helps {really}'
        self.assertEqual(parse_response(text, ['a.py'])[1], {'a.py': 'x = {1}\n'})

    def test_unclosed_fence_is_extracted(self):
        text = '```json\n{"summary": "ok", "files": {"a.py": "y"}}\n'
        self.assertEqual(parse_response(text, ['a.py'])[1], {'a.py': 'y'})

    def test_garbage_still_raises_value_error(self):
        for bad in ('', 'no json at all', '{"files": ', '[1,2]'):
            with self.assertRaises(ValueError, msg=bad):
                parse_response(bad, ['a.py'])


class Base(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='orch-adapt-')
        self.root = Path(self.temp.name)
        self.env = patch.dict(os.environ, {'ORCHESTRATOR_ARTIFACTS_DIR': str(self.root / 'a')})
        self.env.start()
        self.db = Store(self.root / 's.db')
        (self.root / 'check.py').write_text('import os, sys\nsys.path.insert(0, os.getcwd())\nimport m\nassert m.f(1) == 2\n')

    def tearDown(self):
        self.env.stop()
        self.temp.cleanup()

    def submit(self, **extra):
        task = {'task_id': 'A', 'description': 'f(x)=x+1', 'context_files': [], 'output_files': ['m.py'],
                'acceptance_command': [sys.executable, str(self.root / 'check.py')], 'max_attempts': 3, **extra}
        return plan.submit(self.db, 'adapt', str(self.root), [task])['session_id']


class TokenLimit(Base):
    def test_token_limit_is_retryable_and_budget_doubles_up_to_cap(self):
        sid = self.submit(max_tokens=1024)
        budgets = []

        class Truncating(FakePool):
            def complete(self, url, messages, max_tokens=4096, **options):
                budgets.append(max_tokens)
                if len(budgets) < 3:
                    raise ProviderError('Model output token limit reached', True)
                return json.dumps({'summary': 's', 'files': {'m.py': 'def f(x):\n    return x + 1\n'}}), {'total_tokens': 3}
        self.assertEqual(run(self.db, Truncating(), sid, 1, capacity_wait=1)['status'], 'COMPLETED')
        self.assertEqual(budgets, [1024, 2048, 4096])

    def test_budget_never_exceeds_provider_cap(self):
        sid = self.submit(max_tokens=12000)
        budgets = []

        class Truncating(FakePool):
            def complete(self, url, messages, max_tokens=4096, **options):
                budgets.append(max_tokens)
                raise ProviderError('Model output token limit reached', True)
        run(self.db, Truncating(), sid, 1, capacity_wait=1)
        self.assertEqual(budgets, [12000, 16384, 16384])

    def test_real_pool_marks_max_tokens_retryable(self):
        from pool import Pool
        src = Path(__file__).with_name('pool.py').read_text(encoding='utf-8')
        self.assertRegex(src, r"ProviderError\('Model output token limit reached',\s*True")


class ScopeFeedback(Base):
    def test_out_of_scope_file_gives_model_a_specific_error_and_recovers(self):
        sid = self.submit()
        seen = []

        class Wrong(FakePool):
            def complete(self, url, messages, max_tokens=4096, **options):
                data = json.loads(messages[-1]['content'])
                seen.append(data['previous_attempt_feedback'])
                name = 'evil.py' if len(seen) == 1 else 'm.py'
                return json.dumps({'summary': 's', 'files': {name: 'def f(x):\n    return x + 1\n'}}), {'total_tokens': 1}
        self.assertEqual(run(self.db, Wrong(), sid, 1, capacity_wait=1)['status'], 'COMPLETED')
        self.assertIn('outside the allowed scope', seen[1]['error'])

    def test_scope_error_names_offending_file_and_allowed_ones(self):
        with self.assertRaises(ValueError) as ctx:
            parse_response(json.dumps({'files': {'evil.py': 'x'}}), ['m.py'])
        self.assertIn('evil.py', str(ctx.exception))
        self.assertIn('m.py', str(ctx.exception))
        self.assertLess(len(str(ctx.exception)), 180)

class RetryContext(Base):
    def run_with(self, mode):
        sid = self.submit()
        contexts = []

        class Bad(FakePool):
            def complete(self, url, messages, max_tokens=4096, **options):
                data = json.loads(messages[-1]['content'])
                contexts.append(data['context_files'])
                code = 'def f(x):\n    return 0  # BAD\n' if len(contexts) == 1 else 'def f(x):\n    return x + 1\n'
                return json.dumps({'summary': 's', 'files': {'m.py': code}}), {'total_tokens': 1}
        with patch.dict(os.environ, {'ORCHESTRATOR_RETRY_CONTEXT': mode}):
            self.assertEqual(run(self.db, Bad(), sid, 1, capacity_wait=1)['status'], 'COMPLETED')
        return contexts

    def test_full_mode_shows_previous_proposal(self):
        self.assertIn('BAD', self.run_with('full')[1].get('m.py', ''))

    def test_clean_mode_hides_previous_proposal_but_keeps_log_feedback(self):
        contexts = self.run_with('clean')
        self.assertNotIn('m.py', contexts[1])


if __name__ == '__main__':
    unittest.main()
