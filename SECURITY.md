# Security notes

## Design guarantees (covered by tests)

- Acceptance runs as an argv list (no shell), pinned before execution; the model cannot edit it.
- Outputs are written only inside the declared scope; path escapes, device names, NUL/binary and
  oversized content are rejected (`test_adversarial`).
- Secret-shaped model output is refused and never persisted or echoed (`test_secrets`).
- Context is passed to the model as a JSON data field; embedded instructions are not honoured.
- No automatic provider/model fallback; execution is disabled unless explicitly enabled.

## Known risks: read before running

1. **Upstream identity string.** `pool.py` calls the provider's internal quota/generate endpoints
   through a local proxy while sending a client-identifying `User-Agent` (`ORCHESTRATOR_UPSTREAM_UA`)
   and a `userAgent` body field. That imitates an official client and may violate the provider's
   terms of service. Use only with accounts and endpoints you are permitted to automate.
2. **Credentials live outside the repo.** The pool root (`~/.orchestrator/cpa-pool`) holds per-account
   OAuth files and a management key. They are read into memory and never written to tool output.
   Keep that folder out of version control and out of backups you share.
3. **Not a sandbox.** Workspaces are temp copies; generated code and acceptance commands run with
   the invoking user's rights. Review diffs before `apply`.
4. **Local proxies** listen on `127.0.0.1:8401..8415`; never bind them to other interfaces.

## Before reusing this code

The code is licensed under Apache-2.0. Resolve risk 1 before running this against any provider account.
