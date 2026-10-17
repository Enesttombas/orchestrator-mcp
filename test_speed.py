"""Per-call overhead: credential lookup is cached per account, and dropped on auth failure or expiry."""
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from pool import Pool, ProviderError
from store import Store

OK = {'status_code': 200, 'body': json.dumps({'response': {'candidates': [{'finishReason': 'STOP',
      'content': {'parts': [{'text': '{"files":{}}'}]}}], 'modelVersion': 'm',
      'usageMetadata': {'totalTokenCount': 4, 'promptTokenCount': 1, 'candidatesTokenCount': 2, 'thoughtsTokenCount': 1}}})}
LISTING = {'files': [{'provider': 'antigravity', 'auth_index': 'idx'}]}
URL = 'http://127.0.0.1:8401'
MSG = [{'role': 'user', 'content': 'x'}]


class Speed(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        root = Path(self.temp.name)
        self.pool = Pool(Store(root / 's.db'), root / 'pool')
        for n in (1, 2):
            auth = self.pool.root / f'h{n:02}' / 'auth'
            auth.mkdir(parents=True)
            (auth / 'a.json').write_text(json.dumps({'project_id': f'p{n}'}))

    def tearDown(self):
        self.temp.cleanup()

    @staticmethod
    def script(calls, answers):
        def fake(self_, number, path, payload=None, timeout=20):
            calls.append((number, path))
            return answers(number, path, payload)
        return fake

    def test_second_generation_skips_credential_listing(self):
        calls = []
        fake = self.script(calls, lambda n, p, d: LISTING if p == 'auth-files' else OK)
        with patch.object(Pool, '_management', fake):
            self.pool.complete(URL, MSG)
            self.pool.complete(URL, MSG)
            self.pool.complete(URL, MSG)
        self.assertEqual([p for _, p in calls].count('auth-files'), 1)
        self.assertEqual([p for _, p in calls].count('api-call'), 3)  # 4 requests for 3 generations; 6 before

    def test_cache_is_per_account(self):
        calls, projects = [], []

        def answers(n, p, d):
            if p == 'api-call':
                projects.append(json.loads(d['data'])['project'])
                return OK
            return LISTING
        with patch.object(Pool, '_management', self.script(calls, answers)):
            self.pool.complete(URL, MSG)
            self.pool.complete('http://127.0.0.1:8402', MSG)
        self.assertEqual(projects, ['p1', 'p2'])
        self.assertEqual([p for _, p in calls].count('auth-files'), 2)

    def test_auth_failure_drops_cache_so_stale_identity_is_not_reused(self):
        calls, state = [], {'fail': False}

        def answers(n, p, d):
            if p == 'auth-files':
                return LISTING
            return {'status_code': 401, 'body': ''} if state['fail'] else OK
        with patch.object(Pool, '_management', self.script(calls, answers)):
            self.pool.complete(URL, MSG)
            state['fail'] = True
            with self.assertRaises(ProviderError):
                self.pool.complete(URL, MSG)
            state['fail'] = False
            self.pool.complete(URL, MSG)
        self.assertEqual([p for _, p in calls].count('auth-files'), 2)

    def test_cache_expires(self):
        calls = []
        fake = self.script(calls, lambda n, p, d: LISTING if p == 'auth-files' else OK)
        clock = {'t': 1000.0}
        with patch.object(Pool, '_management', fake), patch('pool.time.monotonic', lambda: clock['t']):
            self.pool.complete(URL, MSG)
            clock['t'] += 10_000
            self.pool.complete(URL, MSG)
        self.assertEqual([p for _, p in calls].count('auth-files'), 2)

    def test_credential_listing_error_is_not_cached(self):
        calls, state = [], {'n': 0}

        def answers(n, p, d):
            if p == 'auth-files':
                state['n'] += 1
                return {'files': []} if state['n'] == 1 else LISTING
            return OK
        with patch.object(Pool, '_management', self.script(calls, answers)):
            with self.assertRaises(ProviderError):
                self.pool.complete(URL, MSG)
            self.pool.complete(URL, MSG)
        self.assertEqual([p for _, p in calls].count('auth-files'), 2)


    def test_listing_that_raced_with_an_auth_failure_is_not_cached(self):
        calls = []
        def answers(n, p, d):
            if p == 'auth-files':
                self.pool._drop_identity(n)  # another thread hit a 401 while we were listing
                return LISTING
            return OK
        with patch.object(Pool, '_management', self.script(calls, answers)):
            self.pool.complete(URL, MSG)
            self.pool.complete(URL, MSG)
        self.assertEqual([p for _, p in calls].count('auth-files'), 2)

if __name__ == '__main__':
    unittest.main()
