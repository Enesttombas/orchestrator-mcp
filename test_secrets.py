"""apply refuses model output that introduces credentials; benign code passes."""
import json
import unittest

from execution import apply_outputs, secret_kind
from runner import run
from test_adaptive import Base
from test_orchestrator import FakePool

FAKE_KEY = 'AIza' + 'A' * 35
PEM = '-----' + 'BEGIN RSA PRIV' + 'ATE KEY-----'
BENIGN = 'def f(x):\n    return x + 1  # token_count, sk-learn, key = "short"\n'


class Detector(unittest.TestCase):
    def test_detects_credential_shapes(self):
        for text in (FAKE_KEY, PEM, 'sk-' + 'a' * 30, 'ghp_' + 'b' * 36, 'Authorization: Bearer ' + 'c' * 40):
            self.assertIsNotNone(secret_kind(text.encode()), text[:12])

    def test_benign_code_is_not_flagged(self):
        for text in (BENIGN, 'password = input("pw")', 'import sk_learn', 'https://example.com/a-b-c'):
            self.assertIsNone(secret_kind(text.encode()), text)

    def test_result_never_contains_the_secret(self):
        self.assertNotIn(FAKE_KEY, secret_kind(FAKE_KEY.encode()))


class Apply(Base):
    def propose(self, code):
        sid = self.submit()

        class Pool(FakePool):
            def complete(self_, url, messages, max_tokens=4096, **options):
                return json.dumps({'summary': 's', 'files': {'m.py': code}}), {'total_tokens': 1}
        run(self.db, Pool(), sid, 1, capacity_wait=1)
        return sid

    def test_benign_output_is_applied(self):
        sid = self.propose('def f(x):\n    return x + 1\n')
        self.assertEqual(apply_outputs(self.db, sid, 'A')['files'], ['m.py'])
        self.assertTrue((self.root / 'm.py').exists())

    def test_secret_output_is_refused_and_not_written(self):
        sid = self.propose('def f(x):\n    return x + 1\n' + f'KEY = "{FAKE_KEY}"\n')
        with self.assertRaises(ValueError) as ctx:
            apply_outputs(self.db, sid, 'A')
        self.assertIn('API key', str(ctx.exception))
        self.assertNotIn(FAKE_KEY, str(ctx.exception))
        self.assertFalse((self.root / 'm.py').exists())


class Hashes(unittest.TestCase):
    def test_second_key_of_same_kind_counts_as_new(self):
        from execution import secret_hashes
        old = secret_hashes(FAKE_KEY.encode())
        new = secret_hashes((FAKE_KEY + ' AIza' + 'B' * 35).encode())
        self.assertEqual(len(new - old), 1)
        self.assertEqual(new & old, old)

if __name__ == '__main__':
    unittest.main()
