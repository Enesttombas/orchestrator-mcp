# Task: source-faithful report on free-threaded Python

Sources (local plain-text copies, do NOT use the web; cite only these): in `sources/`:
S1 PEP 703, S2 PEP 779, S3 free-threading HOWTO, S4 What's New 3.14, S5 PEP 684, S6 What's New 3.13.

Produce `report.json`: {"claims":[{"id":1..12,"claim":"one sentence","quote":"verbatim text copied from the source, at most 30 words","source":"S1..S6"}]}.
Exactly 12 claims. The first 8 must cover, in order:
1. What PEP 703 proposes and its acceptance/status.
2. PEP 779: the phases / criteria for free-threading to become officially supported.
3. Free-threaded status in Python 3.13.
4. Free-threaded status in Python 3.14.
5. How to detect a free-threaded build or control the GIL at runtime (e.g. PYTHON_GIL, sys flags).
6. A stated performance overhead or speedup figure for free-threaded builds.
7. What PEP 684 (per-interpreter GIL) does.
8. One limitation or caveat of free-threaded Python named in the docs.
Claims 9-12: any four other significant facts from the sources.
Hard rules: every quote must appear word for word in the cited file. A claim not backed by its quote is an error. If a source does not say something, do not claim it; write a claim stating the source is silent instead, quoting nothing is not allowed, so pick another fact.
Also write `report.md`: a half-page summary for a human, using only the 12 claims.
