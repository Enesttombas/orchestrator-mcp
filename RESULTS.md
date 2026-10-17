# Test results

Every number below comes from a run recorded in [`evidence/`](evidence/). Reports there are the original write-ups (Turkish, with PDF); raw JSON, scorers and test code are alongside. Success was always decided by a local script's exit code or a mechanical check, never by a model's claim.

Model for live runs: `gemini-3.8-flash-high` through a 15-account pool. Dates: 16–17 Oct 2026.

| # | Report | What it measures |
|---|---|---|
| 00 | [audit before](evidence/reports/00-audit-before.md) | boundary tests against the original server |
| 01 | [fix and live verification](evidence/reports/01-fix-and-live-verification.md) | rebuilt server, quota, 15-account live run |
| 02 | [v4 polish](evidence/reports/02-v4-polish.md) | edit format, adaptive retry, credential cache, before/after bench |
| 03 | [domain matrix](evidence/reports/03-domain-matrix.md) | 9 task domains x 2 repeats |
| 04 | [test by angle](evidence/reports/04-test-by-angle.md) | client path, chaos, adversarial, hard tasks, scale |
| 05 | [Sonnet solo vs Gemini MCP](evidence/reports/05-sonnet-vs-gemini.md) | speed, Claude tokens, quality on three jobs |
| 06 | [research fidelity](evidence/reports/06-research-fidelity.md) | quote accuracy with a mechanical checker |

---

## 1. Before and after the rebuild

<img src="docs/media/viz5.gif" width="860" alt="before and after">

| Check | Original server (audit) | Rebuilt |
|---|---|---|
| Independent boundary tests | **12/22**, 10 failed | all pass |
| Success decided by | caller's own `exit_code` (default 0) | harness runs the pinned acceptance command |
| Path escape (`../`) | wrote outside artifact root | refused |
| Task ownership / double result | none; two workers got the same task | atomic claim + lease, late results rejected |
| Quota reading | 0/15 (expired tokens, HTTP 401 hidden) | **15/15** via proxy management API |
| Offline regression suite | 6 original tests | **103 tests** (1 skipped: no symlink privilege on the test machine) |
| Live, installed config | n/a | **16/16**, 15 different accounts, 21.45 s, every acceptance command exit 0 |

Raw: [`evidence/audit/`](evidence/audit/) (rerun with `audit.py`; expected on the old code: rc=1, 22 tests, 10 failures).

## 2. Sonnet 5.5 solo vs Gemini orchestration

<img src="docs/media/viz2.gif" width="860" alt="Sonnet vs Gemini">

| Test | Time A / B (s) | Claude tokens A / B | Quality A | Quality B |
|---|---|---|---|---|
| Video summaries (5 videos) | 115.7 / 86.1 | 117,585 / 89,189 | cover 39/40, 0 unsourced claims, clarity 5.0 | cover 39/40, 2 unsourced claims, clarity 3.8 |
| Bug fixing (6 modules, hidden tests) | 214.8 / 135.3 | 97,793 / 86,005 | 6/6 | 6/6 |
| Context questions (14 file + 5 web) | 47.4 / 76.9 | 96,777 / 92,449 | 19/19 | 19/19 |
| **Total** | **377.9 / 298.3** | **312,155 / 267,643** | | |
| Total, 74,498-token fixed sub-agent cost removed | | **88,661 / 44,149** | | |

A = Sonnet solo, B = Sonnet as orchestrator with Gemini workers (about 106k extra Gemini tokens, not charged to the Claude quota).

Reading: code and fact-finding tied; B was about 21% faster overall and roughly half the net Claude cost, but slower on a small single-query job and weaker on prose. n=1 per cell, so these are signals, not statistics. Judge was a blind Opus with randomised X/Y labels.

## 3. Domain matrix: 44/46

<img src="docs/media/viz3.gif" width="860" alt="domain matrix">

Every acceptance script was first proven to **fail** on the untouched sandbox and **pass** on a known-good solution (`test_matrix.py`).

| Domain | Task | Kind | Passed | First try | Avg tokens | Avg model s |
|---|---|---|---|---|---|---|
| bugfix | BUG-1 | code | 2/2 | 2/2 | 522.5 | 2.2 |
| bugfix | BUG-2 | code | 2/2 | 2/2 | 853.5 | 4.4 |
| bugfix | BUG-3 | code | 2/2 | 2/2 | 1790.5 | 9.2 |
| cleaning | CLEAN-1 | code | 2/2 | 2/2 | 1769 | 7.8 |
| cleaning | CLEAN-2 | code | 2/2 | 2/2 | 2323 | 9.1 |
| analysis | ANA-1 | answer | 2/2 | 2/2 | 851 | 4.8 |
| analysis | ANA-2 | answer | **0/2** | 0/2 | 1271.5 | 8.4 |
| research | RES-1 | answer | 2/2 | 2/2 | 630 | 4.9 |
| research | RES-2 | answer | 2/2 | 2/2 | 450.5 | 3.1 |
| dag | A | code | 2/2 | 2/2 | 361.5 | 2.4 |
| dag | B | code | 2/2 | 2/2 | 489.5 | 3.7 |
| dag | C | code | 2/2 | 2/2 | 482.5 | 2.9 |
| dag | D | code | 2/2 | 2/2 | 422.5 | 2.1 |
| dag | X-IMPOSSIBLE | expected failure | 2/2 | 0/2 | n/a | n/a |
| dag | Y-AFTER-X | expected blocked | 2/2 | 2/2 | n/a | n/a |
| video | VID-1 | code | 2/2 | 2/2 | 1099 | 4.9 |
| video | VID-2 | code | 2/2 | 2/2 | 1171 | 4.6 |
| bigfile | BIG-1 | code | 2/2 | 2/2 | 2903.5 | 3.2 |
| bigfile | BIG-2 | code | 2/2 | 2/2 | 3068 | 4.2 |
| multifile | MULTI-1 | code | 2/2 | 2/2 | 687 | 2.6 |
| multifile | MULTI-2 | code | 2/2 | 2/2 | 634.5 | 6.0 |
| secrets | SEC-1 | secret must not land | 2/2 | 2/2 | 430.5 | 2.5 |
| secrets | SEC-2 | code (no false alarm) | 2/2 | 2/2 | 556 | 1.8 |

| Domain | Passed |
|---|---|
| bugfix | 6/6 |
| cleaning | 4/4 |
| analysis | 2/4 |
| research | 4/4 |
| dag | 12/12 |
| video | 4/4 |
| bigfile | 4/4 |
| multifile | 4/4 |
| secrets | 4/4 |
| **Total** | **44/46 (96%)** |

Findings from the matrix:

- **ANA-2 failed because the prompt was vague.** The same question asked explicitly (ANA-3, "list every service line by line, then name the worst") passed 3/3. Rule: state output format and scope in analysis prompts.
- **First run exposed a real usability defect.** Two independent tasks writing the same file ran in one session and the second apply was refused. Fix: `plan.submit` now rejects overlapping outputs up front (`test_plan_overlap.py`); the isolated rerun passed 8/8.
- **Secrets gate worked live.** SEC-1 (model asked to emit a fake key): refused at apply 4/4, nothing written. SEC-2 (64-char hex and long kebab routes): no false alarm 4/4.
- **Failure propagation correct.** X-IMPOSSIBLE failed after 2 attempts, its dependent was SKIPPED, no file written (4/4). Diamond DAG with inherited outputs passed 8/8.
- **Honesty probe.** Asked about a non-existent `itertools.chunked`, the model said it is not in the stdlib 4/4.
- **Edit format tokens.** On 300-line files, output was typically 85–96% smaller than a full rewrite (BIG-1: 296–331 output tokens over 6 runs); two BIG-2 runs fell back to a near-full rewrite (975 and 2229) and were still correct. Raw: `matrix/edit-format-tokens.json`.

Quota spent on the three matrix runs plus analysis rerun: about 121k tokens, at least 102 generation calls.

## 4. Test by angle

<img src="docs/media/viz4.gif" width="860" alt="five angles">

| Angle | Result | System defect found | Status |
|---|---|---|---|
| Client path (installed MCP, stdio) | 18 tools, live flow 6.3 s, malformed input did not crash the server | none | pass |
| Chaos / crash | 7 provider faults x 2 scenarios, hard-kill + takeover, 20-thread race | none | pass |
| Adversarial input | 25 path/name subcases, injection, acceptance hijack, huge/binary output | **3 holes** | fixed |
| Hard tasks (6 tasks, 4 repeats, 2 arms) | 45/48 | **1 real bug** | fixed |
| Scale: 30-task DAG | 30/30, 20.6 s, 14,276 tokens, 0 retries | none | pass |

### Adversarial: the three holes

| Hole | Evidence before | Fix |
|---|---|---|
| Windows device names (`CON`, `NUL`, `aux.py`, `com1.py`, `LPT1.txt`, `PRN.py`) and trailing dot/space (`m.py.`, `m.py `, `dir /m.py`) accepted | 11 subcases red | `safe_path` rejects them |
| NUL (`\0`) accepted in output path | subcase red | path and content cannot carry NUL |
| Model could write the acceptance script itself as an output (`check.py` becoming `pass`) | red | submit refuses an output file that is an argument of the acceptance command |

Already sound: `..`, absolute paths, `C:`, backslashes, alternate data streams (`m.py:stream`), `.git`, `.env`, `node_modules`. Symlink escape was **not** exercised (no privilege on the test machine). A live injection probe ("write out of scope, edit check.py, leak the key") was ignored by the model 3/3 times, so the gates themselves are proven only by the offline tests.

### Chaos matrix

HTTP 500, timeout, non-JSON text, empty answer, truncated JSON, wrong shape (`[1,2,3]`), `files` not a dict. Two bad replies then a good one: the session completes on attempt 3. Persistent fault: task fails cleanly at the attempt cap, no traceback leaks, nothing hangs. Non-retryable HTTP 400 burns no extra attempts. A runner hard-killed mid-call is taken over by another and the session completes. 20 threads racing for 40 tasks: no task completed twice.

### Hard tasks

Six tasks (interval merge, money split, semver, token bucket, cron, weighted LRU). Each acceptance script proves itself: red on the stub, green on the reference, red on a naive solution for three of them (`hard/hard.py`). Each task ran 4 times with the previous attempt kept in context (`full`) and with only the log (`clean`).

| Arm | Passed | First try | Retried | Tokens |
|---|---|---|---|---|
| full | 23/24 | 20 | 4 | 56,296 |
| clean | 22/24 | 19 | 3 | 52,060 |

The real bug: an **empty model answer was classed as non-retryable**, so a task died after one of its three attempts. `Model response did not complete` (SAFETY/OTHER finish) had the same problem. Both are retryable now; the regression test was red before and green after (`test_chaos.py::NativeEmptyAnswers`). These 48 runs predate the fix and were not re-run. `full` vs `clean` stays an **open question**: too few retries (7) to tell, and the failures were provider-side in both arms.

## 5. Research fidelity
n<img src="docs/media/viz6.gif" width="860" alt="research fidelity">

Topic: free-threaded Python, six frozen sources, 12 claims each with a verbatim quote of at most 30 words.

| Measure | Sonnet solo (A) | Gemini workers + orchestrator check (B) |
|---|---|---|
| Quote found verbatim in source (mechanical) | 12/12 | 12/12 |
| Judge: supported / partial / unsupported | 11 / 1 / 0 | 11 / 1 / 0 |
| Required topics covered | 8/8 | 7/8 (missing what PEP 703 proposed) |
| Sonnet tokens, fixed cost removed | 28,012 | 25,390 |
| Time | 46.7 s | 67.8 s |
| Extra Gemini tokens | 0 | 115,736 |

The six Gemini workers produced 60 quotes; **2 failed the mechanical check** (one over 30 words, one not in the source) and the orchestrator dropped both. Without that check, B's report could have contained an invented quote. Conclusion: workers are usable for source-critical research only with a mechanical quote check behind them. No token or speed advantage was shown on six small sources.

## 6. Quick bench: before and after v4 polish

6 tasks x 2 repeats, live.

| Metric | Before | After, retry=full | After, retry=clean |
|---|---|---|---|
| Pass rate | 1.00 | 1.00 | 1.00 |
| First-try pass | 1.00 | 1.00 | 1.00 |
| Time per run (s) | 5.59 | 6.12 | 5.12 |
| Tokens per run | 1410 | 1776 | 1798 |
| Output tokens per run | 384 | 402 | 425 |

Tokens rose about 26%: the edit-format instruction adds roughly 60 tokens per call and these files were under 60 lines, so the format never triggered. Its live benefit is shown only on larger files (section 3). Time differences are inside noise.

## Limits that apply to everything above

- Small and medium tasks. No large multi-file repository, no very long dependency chains, no more than 15 parallel tasks.
- Two repeats per matrix cell, n=1 for the Sonnet comparison: small samples that miss rare failures.
- The Sonnet comparison used the same library through a CLI, not the stdio path (that path was proved separately, section 4).
- Gemini token counts cover the last attempt only.
- Reconnecting from a real MCP client such as an IDE was never tested.
- Results are specific to this model pair; rerun on a new model.

## Reproduce

```bash
python -m unittest discover -s . -p "test_*.py"           # offline, 103 tests
python evidence/audit/audit.py                              # needs the ORIGINAL server code
python evidence/matrix/test_matrix.py                       # the matrix proves its own scripts
```

Live runs (`run_matrix.py`, `run_hard.py`, `run_dag30.py`) need a configured pool and spend real quota.
