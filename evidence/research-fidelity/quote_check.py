"""python quote_check.py <claims.json> <sources_dir> -> per-claim OK/MISSING, exit 0 always.
claims.json: {"claims":[{"id":1,"claim":"...","quote":"verbatim <=30 words","source":"S4"}]}
A quote is OK only if it appears verbatim (whitespace and case ignored) in <sources_dir>/<source>.txt."""
import json
import re
import sys
from pathlib import Path


def norm(s):
    return re.sub(r'\s+', ' ', s).strip().lower()


def verify(claims_path, src_dir):
    data = json.loads(Path(claims_path).read_text(encoding='utf-8'))
    rows = []
    for c in data['claims']:
        f = Path(src_dir) / f"{c.get('source', '')}.txt"
        ok = f.exists() and bool(norm(c.get('quote', ''))) and norm(c['quote']) in norm(f.read_text(encoding='utf-8'))
        rows.append((c.get('id'), ok))
    return rows


if __name__ == '__main__':
    rows = verify(sys.argv[1], sys.argv[2])
    for i, ok in rows:
        print(i, 'OK' if ok else 'MISSING')
    print(f'verified {sum(ok for _, ok in rows)}/{len(rows)}')
