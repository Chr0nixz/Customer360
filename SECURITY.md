# Security policy

Customer360 Agent Benchmark ships a SQL execution gateway, authorization checks, and result filters. Safety is on by default.

## What to report privately

Use **GitHub Security Advisories** (or another private channel the maintainers publish) for:

- SQL Guard bypasses (writes, filesystem/network reads, extension load, system tables, side-effect functions)
- Authorization bypasses (role, table, column, or row-scope)
- Result leaks of sensitive fields, hidden-pack contents, Gold SQL, or private evaluator traces
- Ways to disable or skip the gateway while still receiving a successful evaluation

Do **not** open a public issue for these. Do **not** attach hidden packs, `hidden_oracles.yaml`, Gold SQL, private JSONL, or real personal data.

## What is not a vulnerability

- An Agent producing wrong SQL that the evaluator marks as failed
- `POLICY_INCOMPATIBLE` / `INPUT_LIMIT` / timeout on oversized queries
- Official Baseline scoring below a diagnostic target
- Missing PostgreSQL, FastAPI, or network model adapters (they are out of v1.0 scope)

## Public tree rules

- Wheel, sdist, and Docker images must not contain `data/trusted`, `data/hidden`, `outputs/`, or generated Gold.
- `data/trusted/human_oracles.yaml` in this source repository covers only the 20 public human cases (`C360_0001–0020`). It is not the hidden set.
- Generated hidden packs stay in gitignored `outputs/` on the maintainer machine.

## Supported versions

Only the current `main` line and any signed `v1.x` tag the maintainers publish. Unsigned local snapshots are not a supported distribution.

## After a report

Maintainers should reproduce on Tiny, keep hidden artifacts off the public tree, and treat scoring-rule or whitelist changes as protocol changes (update versions and docs). Do not “fix” a leak by rewriting Gold or turning off a gate.
