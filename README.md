# orchestrator-mcp

An MCP server that runs a DAG of coding tasks across a pool of model workers, and believes only an exit code.

<img src="docs/media/summary.gif" alt="Nothing counts as done until a script the model cannot edit says so" width="100%">

## Why

Cheap workers are easy to hand work to and hard to trust. A worker will report "done" on code that does not run, rewrite the test that grades it, or echo a secret it saw in context. This server makes those failures structurally impossible instead of unlikely.

## How it works

**Plan as a graph.** `orchestrator_submit_plan` validates the whole DAG first, so a bad plan creates nothing. Independent tasks run in parallel and dependent tasks receive upstream answers.

**Blind acceptance.** Each task carries an argv acceptance command. The harness pins it, runs it, and treats exit code 0 as the only success. The model cannot edit the script that grades it.

**Safe by construction.** Task claims and account leases are atomic. A hard-killed runner is taken over and the session still completes. Apply is scope-checked and hash-checked, so a file you edited meanwhile is reported, never overwritten. Secret-shaped output, binary output, path escapes and Windows device names are refused.

## Results

103 offline tests pass. Live, 44 of 46 matrix tasks and 16 of 16 installed-config tasks pass on fifteen accounts. Against Sonnet 5.5 working alone, the orchestrated run used about half the net Claude tokens and 21% less time with equal code quality. Prose clarity was lower, and two of sixty worker quotes were invented and caught by the mechanical check.

<img src="docs/media/comparison.png" alt="Sonnet alone against the orchestrated run" width="100%">

Every table, the three security holes and the one real bug the tests found are in [RESULTS.md](RESULTS.md). Raw data and scorers are in [`evidence/`](evidence/).

## Quick start

```bash
python -m pip install -r requirements.txt
python -m unittest discover -s . -p "test_*.py"
```

The suite is fully offline. Register `server.py` in your MCP client config. Real model calls stay off until you opt in with `ORCHESTRATOR_GEMINI_ENABLED=1`.

## Tools

Plan level: `orchestrator_submit_plan`, `orchestrator_wait`, `orchestrator_get_result`, `orchestrator_apply_session`.
Step level: `orchestrator_init`, `orchestrator_add_task`, `orchestrator_configure_task`, `orchestrator_run_session`, `orchestrator_get_status`, `orchestrator_apply_task`, `orchestrator_cancel_session`, `orchestrator_reset_session`.
Pool: `orchestrator_refresh_quotas`, `orchestrator_pool_status`, `orchestrator_list_sessions`.

## Configuration

| Variable | Default |
|---|---|
| `ORCHESTRATOR_DB_PATH` | `~/.orchestrator/orchestrator.db` |
| `ORCHESTRATOR_ARTIFACTS_DIR` | `~/.orchestrator/artifacts` |
| `ORCHESTRATOR_POOL_ROOT` | `~/.orchestrator/cpa-pool` |
| `ORCHESTRATOR_CPA_BINARY` | `cli-proxy-api` on `PATH` |
| `ORCHESTRATOR_CAPACITY_WAIT` | `180` seconds |
| `ORCHESTRATOR_UPSTREAM_UA` | provider client string, see [SECURITY.md](SECURITY.md) |
| `ORCHESTRATOR_MCP_CONFIG` | `~/.gemini/config/mcp_config.json` |
| `ORCHESTRATOR_GEMINI_ENABLED` | unset, model calls off |

## Limits

Task workspaces are temporary copies, not an OS sandbox. Acceptance commands and generated code run with your user rights. Workers see only the files you list. Cancelling an in-flight HTTP call can take up to 120 seconds.

Licensed under the [Apache License 2.0](LICENSE). Read [SECURITY.md](SECURITY.md) before running it against any provider account.
