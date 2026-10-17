# Context questions (answer each; give the evidence)

## File questions (code under C:~/Documents/repo/tools/orchestrator_mcp, ignore test_*.py when deciding facts)
F01 In orchestrator_mcp, what is the maximum lease_seconds that Store.claim accepts?
F02 What is the maximum size in bytes of one saved artifact (execution.save_artifact)?
F03 What is the per-file size limit in bytes for a context file in execution.prepare?
F04 What is the cap for the token budget after the runner doubles it following a "token limit" error?
F05 What is the limit on TOTAL characters of context sent to the model in execution.prepare?
F06 What is the limit in bytes on the combined model output files in execution.parse_response?
F07 For how many seconds does the Pool cache a credential identity (auth_index, project_id) per account?
F08 Which environment variable selects the retry context mode, which values matter, and what is the default?
F09 Which account_id values does validate_spec accept?
F10 What are the allowed ranges of timeout and max_attempts in validate_spec?
F11 Which kinds of secrets does execution.secret_kind detect?
F12 What is the maximum number of context files and output files per task in validate_spec?
F13 What is the default max_iterations when a session is created with Store.create?
F14 Which exception class carries the retryable flag and cooldown for provider failures, and in which module is it defined?

## Web questions (must come from the live official pages, not memory)
W1 In the Python standard library docs for functools.lru_cache, what is the default value of maxsize?
W2 In the SQLite documentation on limits, what is the default value of SQLITE_MAX_LENGTH (maximum string/BLOB length)?
W3 In the PostgreSQL documentation on SQL identifiers, what is the maximum identifier length in bytes?
W4 Which HTTP status code number is "Misdirected Request" (per RFC 9110 / MDN)?
W5 In which Python version was asyncio.timeout() added, per the official asyncio docs?

## Output
Write answers.json: {"F01": {"answer": "...", "evidence": "file:line"}, ..., "W1": {"answer": "...", "evidence": "https://... | verbatim quote from the page (<=25 words)"}}
