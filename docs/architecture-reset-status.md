# Architecture Reset — Project State (2026-08-07)

**Status:** SQLite architecture approved in principle; controlled publication in progress. This is the corrected project-state document for the `feat/sqlite-persistence-reset` branch.

## Branch topology

```text
fb5641c  remote main (published v0.1.2-integrity base)
├── review/jsonl-overhaul-8a7e916        # forensic — exact 8a7e916, review-held, non-releasable
│   └── ... twelve JSONL remediation commits ... → 8a7e916
│
└── feat/sqlite-persistence-reset       # clean product branch (this branch) — from origin/main
    ├── ADR-0012 and architecture contracts      ← first pushed state (this commit)
    ├── selected reusable v2 foundation          ← later (port list in ADR-0012 §8)
    ├── SQLite implementation                    ← after ADR review
    └── invariant-driven tests                   ← after ADR review
```

## Identities (verified 2026-08-07)

| Item | Value |
|---|---|
| Remote main | `fb5641cc1a3f1f54b96bba3af88ec5a1b010f4e5` (untouched) |
| Forensic branch | `review/jsonl-overhaul-8a7e916` = `8a7e9167d6ff77b3ccd32722683c9b42e4390687` |
| Clean branch | `feat/sqlite-persistence-reset` (merge-base with origin/main = `fb5641c`; does **not** descend from 8a7e916) |
| Git bundle | `method-factory-8a7e916.bundle` (SHA-256 `92c0bb1026190f9fd5e1f61bb4cd5fc16a08605aecf77f81eb5bc93b3b504f63`; `git bundle verify` OK) |
| Local archival | `persistence-reset` branch preserved locally (contains pre-revision ADR-0012 draft, not published) |

## Reviewer direction (2026-08-07) — accepted

- **NO-GO** on publishing the `8a7e916` JSONL implementation; permanently review-held.
- **GO** on SQLite canonical store (approved in principle), behind the `ManifestStore` interface.
- **Controlled publication authorized** (evidence/visibility only): forensic branch + clean branch + draft PR; no merge, no tag, no release, no `main` change.
- Phase 0/1 evidence from the earlier archive was **not accepted** (bundle lacked the git bundle, ADR-0012, checkpoint, branch proof). Corrected once in the updated evidence package; no further JSONL remediation loop.

## What this branch contains now (first pushed state)

- `docs/adr/ADR-0012-persistence-architecture.md` — the architecture decision with the binding contracts:
  - one canonical immutable `events` table + `store_metadata` (schema §1);
  - transaction + idempotency contract (`BEGIN IMMEDIATE`, `ACTION_ID_CONFLICT`, §2);
  - operating mode (DELETE/FULL/busy_timeout, no WAL, 0700/0600, `application_id`, `user_version=1`, read-only validation, backup API, §3);
  - canonical serialization (`ensure_ascii=False`) and separate size limits; `summary.content` frozen to content-addressed body (§4);
  - hash chain narrowed to internal-consistency evidence; `mf validate` vs `--full` (§5);
  - public v0.1.2 migration contract (`mf migrate-store`, receipt, `LEGACY_STORE_DETECTED`, §6);
  - export contract (`method-factory-events-v1` + `legacy-v012-jsonl`, §7);
  - salvage/discard list from `8a7e916` (§8);
  - CI/test contract (unittest canonical gate, Hypothesis, 14 test classes, §9);
  - versioning (`2.0.0a1 → rc1 → 2.0.0`, no tag now, §10);
  - cumulative review lanes and release requirements (§11);
  - controlled publication scope (§12); threat model.
- `docs/architecture-reset-status.md` — this document.

## Not yet on this branch (port order, per ADR-0012 §8)

The `core`→`methodfactory` rename, packaging, artifact store, path protections, CLI error codes, envelope bounds, schema hardening, quarantine, CI pins, ignores, packaging tests, and docs that remain true under SQLite are **selected reusable v2 foundation** — ported in a later step, **after ADR-0012 is reviewed from this pushed branch**. No SQLite implementation code is present yet by design (reviewer's step 12: do not begin full persistence implementation until ADR-0012 has been reviewed from the actual pushed branch).

## Gates

1. ADR-0012 reviewed from the pushed branch (this PR).
2. Operator GO to proceed with foundation port + SQLite implementation.
3. Cumulative release-candidate review (`fb5641c..rc`, 7 lanes, ADR-0012 §11).
4. Operator approval to merge / tag / release (not currently authorized).
