"""Benchmark harness regression: offline run produces the metrics JSON; live mode is refused without the flag."""
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE / 'evals'))
import bench


class BenchTests(unittest.TestCase):
    def test_offline_benchmark_reports_all_metrics(self):
        with tempfile.TemporaryDirectory() as temp, patch.dict(os.environ, {}, clear=False):
            os.environ['ORCHESTRATOR_ARTIFACTS_DIR'] = str(Path(temp) / 'artifacts')
            result = bench.benchmark('offline', tasks=4, repeats=2, workdir=temp)
        self.assertEqual(result['summary']['pass_rate'], 1)
        self.assertEqual(result['summary']['first_pass_rate'], 1)
        for run in result['runs']:
            self.assertEqual((run['passed'], run['total'], run['status']), (4, 4, 'COMPLETED'))
            self.assertEqual(run['calls'], 4)
            self.assertEqual(run['calls_without_usage'], 0)
            self.assertGreater(run['total_tokens'], 0)
            self.assertGreater(run['seconds'], 0)

    def test_cli_writes_json_and_exits_zero(self):
        with tempfile.TemporaryDirectory() as temp:
            out = Path(temp) / 'r.json'
            env = {**os.environ, 'ORCHESTRATOR_ARTIFACTS_DIR': str(Path(temp) / 'a')}
            env.pop('ORCHESTRATOR_GEMINI_ENABLED', None)
            code = subprocess.run([sys.executable, '-X', 'utf8', str(HERE / 'evals' / 'bench.py'), '--mode', 'offline',
                                   '--tasks', '2', '--out', str(out)], env=env, capture_output=True).returncode
            self.assertEqual(code, 0)
            self.assertEqual(json.loads(out.read_text(encoding='utf-8'))['summary']['pass_rate'], 1)

    def test_live_mode_refused_without_flag(self):
        env = {k: v for k, v in os.environ.items() if k != 'ORCHESTRATOR_GEMINI_ENABLED'}
        proc = subprocess.run([sys.executable, '-X', 'utf8', str(HERE / 'evals' / 'bench.py'), '--mode', 'live'],
                              env=env, capture_output=True, text=True)
        self.assertNotEqual(proc.returncode, 0)
        self.assertIn('ORCHESTRATOR_GEMINI_ENABLED=1', proc.stderr)


if __name__ == '__main__':
    unittest.main()
