# Architecture Reset — Project State (2026-08-08, RC1 candidate preparation)

**Status:** SQLite architecture approved in principle; senior review `4878235332` on PR #1 completed the architecture review and directed the Phase 2 implementation order (commits 1–4) with a design-convergence stop gate. The Phase 2 stop gate was accepted; the migration/export implementation gate (ADR-0012 amendment, frozen at `42ff7d9` + `b9e46c1`) closed at `775630e`; the documentation/reporting head is `c70a6f3`. **The current branch head is the RC1 candidate — pending independent senior acceptance and operator integration gate.** This document tracks the clean `feat/sqlite-persistence-reset` branch.

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
    ├── SQLite schema creation + identity + append-only guards ← commit 4 (Phase 2 stop gate — accepted)
    ├── transactional apply + deterministic replay + chain validator   ← Phase 3 foundation
    └── migration + deterministic exports + CLI (this gate)   ← committed for senior review
```

## Identities (verified 2026-08-08)

| Item | Value |
|---|---|
| Remote main | `fb5641cc1a3f1f54b96bba3af88ec5a1b010f4e5` (untouched) |
| Forensic branch | `review/jsonl-overhaul-8a7e916` = `8a7e9167d6ff77b3ccd32722683c9b42e4390687` |
| Clean branch | `feat/sqlite-persistence-reset` (merge-base with origin/main = `fb5641c`; does **not** descend from 8a7e916) |
| PR #1 | https://github.com/RedEyeNinja-BKK/Method-Factory/pull/1 — **actual GitHub Draft**, DO NOT MERGE |
| Git bundle | `method-factory-8a7e916.bundle` (SHA-256 `92c0bb1026190f9fd5e1f61bb4cd5fc16a08605aecf77f81eb5bc93b3b504f63`; `git bundle verify` OK) |
| Local archival | `persistence-reset` branch preserved locally (pre-revision ADR draft, not published) |

## Head lineage (implementation vs documentation vs RC1 candidate)

| Head | Role |
|---|---|
| `775630eebdfb7c4b8357a4d1976505109b4b085b` | **Migration/export implementation head** — product implementation closed here (10 commits from `b9e46c1`); 7-pass code-reviewed (0 critical / 0 major); 420 tests green; literal-head CI green; PR evidence comment id `5224200252`. |
| `c70a6f314b2329dc3e134546ad20b41519be98ab` | **Documentation/reporting head** — architecture-reset status marked the migration/export gate complete/stopped for senior review (docs-only commit). |
| *(this branch head)* | **RC1 candidate** — prepared by the RC1 Candidate Preparation Gate: version identity `2.0.0rc1`, release metadata cleanup, clean package build + isolated install proof, release-gate CI strengthening, RC1 evidence. RC1 candidate — **pending independent senior acceptance and operator integration gate.** Not released. |

Do not call the RC1 candidate "released". The eventual Git release/tag identity
is `v2.0.0-rc.1`; the tag is NOT created in this gate.

## Migration/export implementation gate (2026-08-08)

Bounded implementation authorized by Vincent at canonical head `b9e46c1` on
`feat/sqlite-persistence-reset`. Scope: public v0.1.2 → SQLite migration,
deterministic supported export, deterministic legacy-v0.1.2 evidence export,
and the minimal CLI/error/test/documentation surface for those capabilities.

**Gate status: COMPLETE — implementation closed at `775630e`, STOPPED for
independent senior review (historical record; superseded by the RC1
candidate preparation).**

- Implementation head: `775630eebdfb7c4b8357a4d1976505109b4b085b` (10 commits,
  fast-forward from `b9e46c1`; no force-push).
- Local suite: **420 tests green** (356 baseline + 64 migration/export).
- Code review: 7 passes of the mandatory family (bug/security/performance/
  quality → verify → dedupe → sanity); final verdict 0 critical / 0 major.
- Literal-head CI: run `31236027530` on `775630e` **SUCCESS** — 3.11 job
  `93048557007` and 3.12 job `93048556968`, both `Ran 420 tests … OK`,
  clean-worktree + artifact-scan steps success.
- PR #1 evidence comment: id `5224200252` (32-point gate checklist).
- CI fix: `release-gate.yml` now uses `fetch-depth: 0` so migration fixture
  generation can reach the frozen public commit `fb5641c` (prior run
  `31235850649` failed on a shallow checkout).

Implemented:

- `methodfactory/migrations/v012_jsonl.py` — frozen read-only v0.1.2 reader
  (exact `fb5641c` semantics; no CAS/lock/repair/append mechanics).
- `methodfactory/migrations/migrate.py` — atomic migration: legacy validation,
  semantic-action reconstruction by legacy hash, current-engine transformation
  (`next_manifest` only), equivalence verification, source-stability proof,
  temp-DB build + validation, durable receipt + DB publication (no-clobber
  `os.link`), final read-only verification, fault seams.
- `methodfactory/migrations/export.py` — `method-factory-events-v1` and
  `legacy-v012-jsonl` deterministic exports (read-only, consistent read).
- `methodfactory/cli.py` — bounded surface restored: `mf migrate-store` and
  `mf export`; lifecycle commands remain unavailable; `mf --version` unchanged.
- Six new frozen migration error codes (see `docs/public-surface.md`).
- `methodfactory/tests/_fixtures.py` + `test_migrations.py` — fb5641c-origin
  fixtures and 64 focused tests.

Not authorized / NOT implemented in this gate: merge, PR-ready, tag, release,
`main`/forensic mutation, force-push, deployment, lifecycle expansion,
backup/restore, generic import, garbage collection, JSONL as canonical store,
or 8a7e916 repair/CAS/locking mechanics.

## RC1 candidate preparation gate (2026-08-08)

Bounded release-preparation gate authorized by Vincent. Scope limited to:
release-version identity (`2.0.0rc1`), stale release-status/metadata cleanup,
clean-install/package proof, release-gate CI strengthening, RC1 evidence.
No product-semantic changes were authorized; the product implementation
remains frozen pending final senior review.

- **RC1 candidate head:** *(recorded after the RC preparation commit exists —
  see Head lineage table above.)*
- Version identity: `2.0.0rc1` across `pyproject.toml`, `methodfactory/
  __init__.py`, packaging tests, and CLI version tests. Eventual Git tag
  identity `v2.0.0-rc.1` — NOT created in this gate.
- Release metadata: `Development Status :: 3 - Alpha` → `4 - Beta`; stale
  "Phase 2 foundation" wording removed from the project description.
- Clean package build: wheel (+ sdist if supported) built from the exact
  candidate source in a disposable directory; filenames + SHA-256 recorded;
  no artifacts committed or left in the worktree.
- Fresh-environment install: wheel installed into a disposable venv with no
  editable checkout; import provenance, `__version__`, `mf --version`,
  `python -m methodfactory --version`, and CLI surface verified.
- Packaged functional smoke: canonical `fb5641c` fixture → installed
  `mf migrate-store` → authoritative validation → installed `mf export`
  (both formats) → legacy evidence export revalidated by the frozen
  legacy reader; source unchanged.
- Release-gate CI: builds the distributable wheel, installs into an isolated
  environment, proves `mf --version` = `2.0.0rc1`, runs installed
  migration/export smoke on 3.11 and 3.12; tracked-worktree and artifact-scan
  steps retained.
- RC1 candidate — **pending independent senior acceptance and operator
  integration gate.** Not released. No tag, no GitHub Release, no PyPI
  publication, no deployment.

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
