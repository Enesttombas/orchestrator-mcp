"""python score_ctx.py <sealed_dir> <run/X_ctx/answers.json>
Correctness: regex key on the answer. Web evidence: the cited URL is fetched and must contain the quoted text."""
import json
import re
import sys
import urllib.request
from pathlib import Path

sys.path.insert(0, sys.argv[1])
import ctx_questions as q

data = json.loads(Path(sys.argv[2]).read_text(encoding='utf-8'))


def text_of(url):
    req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
    html = urllib.request.urlopen(req, timeout=30).read().decode('utf-8', 'replace')
    html = re.sub(r'(?s)<(script|style).*?</\1>', ' ', html)
    return re.sub(r'\s+', ' ', re.sub(r'<[^>]+>', ' ', html)).lower()


def sq(s):
    return re.sub(r'[^a-z0-9]+', ' ', s.lower()).strip()


rows = []
for qid in list(q.FILE_Q) + list(q.WEB_Q):
    item = data.get(qid) or {}
    ans, ev = str(item.get('answer', '')), str(item.get('evidence', ''))
    row = {'q': qid, 'correct': q.correct(qid, ans), 'answer': ans[:80]}
    if qid.startswith('W'):
        m = re.search(r'https?://[^\s|)\]"]+', ev)
        quote = ev.split('|', 1)[1].strip().strip('"“” ') if '|' in ev else ''
        ok = False
        if m and quote:
            try:
                ok = sq(quote) in sq(text_of(m.group(0)))
            except Exception as e:
                row['fetch_error'] = str(e)[:60]
        row['evidence_verified'] = ok
    else:
        row['evidence_has_location'] = bool(re.search(r'\w+\.py', ev))
    rows.append(row)
print(json.dumps(rows, indent=0, ensure_ascii=False))
fc = sum(r['correct'] for r in rows if r['q'].startswith('F'))
wc = sum(r['correct'] for r in rows if r['q'].startswith('W'))
wv = sum(r.get('evidence_verified', False) for r in rows if r['q'].startswith('W'))
print(f'file correct {fc}/14; web correct {wc}/5; web quote verified on cited URL {wv}/5')
