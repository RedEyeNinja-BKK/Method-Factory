# Architecture Reset — Project State (2026-08-07, Phase 2)

**Status:** SQLite architecture approved in principle; senior review `4878235332` on PR #1 completed the architecture review and directed the Phase 2 implementation order (commits 1–4) with a design-convergence stop gate. This document tracks the clean `feat/sqlite-persistence-reset` branch.

## Branch topology

```text
fb5641c  remote main (published v0.1.2-integrity base)
├── review/jsonl-overhaul-8a7e916        # forensic — exact 8a7e916, review-held, non-releasable
│   └── ... twelve JSONL remediation commits ... → 8a7e916
│
└── feat/sqlite-persistence-reset       # clean product branch (this branch) — from origin/main
    ├── ADR-0012 + architecture contracts   ← commits 1 (docs) — done
    ├── package foundation (rename, CI, ignores)   ← commit 2
    ├── storage protocol + canonical primitives    ← commit 3
    ├── SQLite schema creation + identity + append-only guards ← commit 4 (Phase 2 stop gate)
    └── (later, after gate) transactional apply, migration, exports, lifecycle
```

## Identities (verified 2026-08-07)

| Item | Value |
|---|---|
| Remote main | `fb5641cc1a3f1f54b96bba3af88ec5a1b010f4e5` (untouched) |
| Forensic branch | `review/jsonl-overhaul-8a7e916` = `8a7e9167d6ff77b3ccd32722683c9b42e4390687` |
| Clean branch | `feat/sqlite-persistence-reset` (merge-base with origin/main = `fb5641c`; does **not** descend from 8a7e916) |
| PR #1 | https://github.com/RedEyeNinja-BKK/Method-Factory/pull/1 — **actual GitHub Draft** (reviewer converted it), DO NOT MERGE |
| Git bundle | `method-factory-8a7e916.bundle` (SHA-256 `92c0bb1026190f9fd5e1f61bb4cd5fc16a08605aecf77f81eb5bc93b3b504f63`; `git bundle verify` OK) |
| Local archival | `persistence-reset` branch preserved locally (pre-revision ADR draft, not published) |

## Senior review 4878235332 (2026-08-07) — accepted

- SQLite reset remains **APPROVED IN PRINCIPLE**; corrected evidence package closes the prior evidence gap.
- PR #1 converted to an actual GitHub Draft.
- **One focused ADR amendment commit first** closing 12 review items, then the bounded implementation order:
  1. `docs: finalize ADR-0012 persistence contracts`
  2. `chore: establish methodfactory package, test extras, CI matrix, and ignores`
  3. `refactor: introduce storage protocol and canonical serialization primitives`
  4. `feat: add SQLite schema creation, identity checks, and append-only guards`
  5–8. (later) transactional apply; migration + exports; test evidence; docs alignment.
- **Phase 2 stop gate:** after commits 1–4, return head SHA, ADR diff summary, DDL + triggers, database-open state table, action-hash definition, successful CI run on the exact SHA, local unit results, `EXPLAIN QUERY PLAN`, clean `git status --short`, and confirmation of no merge/tag/release/`main` change. Do not proceed to the full lifecycle until the senior reviewer accepts this gate.

## ADR-0012 amendment (commit 1, done)

The amendment closes all 12 review items:

1. Publication fact — public v0.1.2 exists; no production user stores known (evidence limitation, not proof of absence); migration compatibility retained.
2. Open/validation modes — hot path: schema/app-id/user-version only, no `integrity_check`; `mf validate`: `quick_check` + current-package; `--full`: `integrity_check` + full chain/hash/artifact.
3. Durability qualified — subject to OS/filesystem/storage honesty; DELETE+FULL cannot override lying hardware/hostile host.
4. Physical DB contract — `methodfactory.sqlite3` under store root; `application_id` `0x4D465354`; `user_version` 1; full state table (missing/zero-byte/wrong-ID/future-version/corrupt/legacy-only/sqlite-only/neither/both); read-only URI; no accidental creation.
5. Append-only executable — UPDATE/DELETE rejection triggers in binding DDL.
6. Revision/chain invariants frozen — rev 0 create + `state_before IS NULL`; predecessor required; state/digest match; manifest columns agree; one authoritative validator.
7. `action_sha256` defined — hash of canonical `{action, package_id, action_id, basis, payload}`; excludes only `expected_revision`.
8. Artifact boundary — blobs before txn, content-addressed, verified before insert, orphan-safe; no auto-delete during mutation; GC proves global unreachability.
9. Migration — v0.1.2 layout; explicit source/dest; fail-closed existing dest; same-filesystem atomic rename; no overwrite; receipt durable and part of success.
10. Evidence checksum — archive-root-relative `SHA256SUMS`; `cd <root> && sha256sum -c SHA256SUMS` exits zero.
11. Clean worktree for next evidence capture.
12. Architecture CI honest — run `31127787460` was cancelled; CI unproven until a run succeeds on the exact SHA.

## CI state (honest)

- Run `31127787460` (workflow_dispatch on `7d9fa3c`): **cancelled without executing steps** — recorded, treated as unproven (ADR item 12).
- Phase 2 will run CI on the exact final head SHA (after commits 1–4 pushed) and report the run URL and conclusion. The canonical gate is `python -m unittest discover -s methodfactory/tests -t .` (ADR-0012 §9).

## Gates

1. ✅ ADR-0012 reviewed from the pushed branch (senior review 4878235332).
2. ✅ Operator GO to proceed with foundation + SQLite implementation (Phase 2 authorization).
3. ⏳ Phase 2 stop gate: commits 1–4 + CI evidence + PR comment; senior reviewer acceptance.
4. Cumulative release-candidate review (`fb5641c..rc`, 7 lanes, ADR-0012 §11).
5. Operator approval to merge / tag / release (not currently authorized).
