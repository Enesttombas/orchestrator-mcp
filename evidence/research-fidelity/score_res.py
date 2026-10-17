"""python score_res.py <run/X_res> -> quote verified count, topic coverage input for the blind judge"""
import json
import sys
from pathlib import Path

from quote_check import verify

arm = Path(sys.argv[1])
rows = verify(arm / 'report.json', Path(__file__).parent / 'sources')
data = json.loads((arm / 'report.json').read_text(encoding='utf-8'))
print(json.dumps({'claims': len(data['claims']), 'quotes_verified': sum(ok for _, ok in rows),
                  'missing_ids': [i for i, ok in rows if not ok]}))
