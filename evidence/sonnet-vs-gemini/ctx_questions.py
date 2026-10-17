"""Context-gathering benchmark: 14 questions answerable only from the code in tools/orchestrator_mcp, 5 from the web.
QUESTIONS are shown to the arms; KEYS (regex over the normalized answer) are used only by score_ctx.py."""
import re

FILE_Q = {
 'F01': 'In orchestrator_mcp, what is the maximum lease_seconds that Store.claim accepts?',
 'F02': 'What is the maximum size in bytes of one saved artifact (execution.save_artifact)?',
 'F03': 'What is the per-file size limit in bytes for a context file in execution.prepare?',
 'F04': 'What is the cap for the token budget after the runner doubles it following a "token limit" error?',
 'F05': 'What is the limit on TOTAL characters of context sent to the model in execution.prepare?',
 'F06': 'What is the limit in bytes on the combined model output files in execution.parse_response?',
 'F07': 'For how many seconds does the Pool cache a credential identity (auth_index, project_id) per account?',
 'F08': 'Which environment variable selects the retry context mode, which values matter, and what is the default?',
 'F09': 'Which account_id values does validate_spec accept?',
 'F10': 'What are the allowed ranges of timeout and max_attempts in validate_spec?',
 'F11': 'Which kinds of secrets does execution.secret_kind detect?',
 'F12': 'What is the maximum number of context files and output files per task in validate_spec?',
 'F13': 'What is the default max_iterations when a session is created with Store.create?',
 'F14': 'Which exception class carries the retryable flag and cooldown for provider failures, and in which module is it defined?',
}
WEB_Q = {
 'W1': 'In the Python standard library docs for functools.lru_cache, what is the default value of maxsize?',
 'W2': 'In the SQLite documentation on limits, what is the default value of SQLITE_MAX_LENGTH (maximum string/BLOB length)?',
 'W3': 'In the PostgreSQL documentation on SQL identifiers, what is the maximum identifier length in bytes?',
 'W4': 'Which HTTP status code number is "Misdirected Request" (per RFC 9110 / MDN)?',
 'W5': 'In which Python version was asyncio.timeout() added, per the official asyncio docs?',
}
KEYS = {
 'F01': r'3600',
 'F02': r'2[ ,_]?000[ ,_]?000|2 ?mb',
 'F03': r'200[ ,_]?000|200 ?kb',
 'F04': r'16[ ,_]?384',
 'F05': r'400[ ,_]?000|400 ?kb',
 'F06': r'500[ ,_]?000|500 ?kb',
 'F07': r'\b600\b',
 'F08': r'orchestrator_retry_context.*clean.*full|orchestrator_retry_context.*full.*clean',
 'F09': r'h01.*h15',
 'F10': r'(?=.*120)(?=.*[^0-9]3(?![0-9]))',
 'F11': r'(?=.*private key)(?=.*api key)(?=.*bearer)',
 'F12': r'(?=.*\b100\b)(?=.*\b30\b)',
 'F13': r'\b60\b',
 'F14': r'(?=.*providererror)(?=.*pool)',
 'W1': r'\b128\b',
 'W2': r'1[ ,_]?000[ ,_]?000[ ,_]?000|1 ?billion|10\^9|1e9',
 'W3': r'\b63\b',
 'W4': r'\b421\b',
 'W5': r'3\.11',
}


def norm(s):
    return re.sub(r'\s+', ' ', str(s).lower().replace('`', ''))


def correct(qid, answer):
    return bool(re.search(KEYS[qid], norm(answer), re.S))
