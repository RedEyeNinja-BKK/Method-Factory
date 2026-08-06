# Architecture — Method Factory v2.0.0

Method Factory is the **prompt+code** successor to Process Engine. Code owns
the lifecycle state machine, gates, protocol validation, persistence,
manifest integrity, and artifact verification. Prompts own conversation,
clarification, content generation, and tone — the model proposes via a
validated JSON Action Envelope, and **code decides legality**. The model is
never responsible for enforcing its own constraints.

Process Engine (prompts-only, Turnstone-native) remains the philosophical
reference at `RedEyeNinja-BKK/Process-Engine`. The migrated Process Engine
snapshot that seeded this repo is quarantined under `evidence/process-engine/`
(nothing deleted; see ADR-0009).

## Repository layout (v2.0.0)

```
methodfactory/              # stdlib-only Python package (ADR-0001)
├── engine.py               # PipelineEngine: envelope -> legality -> gates -> CAS
├── cli.py                  # mf CLI (console_scripts entry point)
├── domain/                 # states, transitions (sole legality authority),
│                           #   gates, errors (stable codes), vocabulary
├── protocol/envelope.py    # strict Action Envelope parse + schema
├── manifest/               # hashing, render, schema, store (journal-first CAS)
├── adapters/artifact_store.py  # digest-addressed immutable blobs
└── tests/                  # unittest suite (CI hard gate)
prompts/                    # active conversation content (method-factory-*)
docs/                       # ADRs (0001..0011), manifest contract, envelope spec
evidence/process-engine/    # quarantined Process Engine snapshot (ADR-0009)
README.md · CHANGELOG.md · pyproject.toml · LICENSE · CONTRIBUTING.md
```

## The code/prompt boundary

| Concern | Owner |
|---|---|
| State machine, transition legality, gates | code (`methodfactory/domain`) |
| Manifest schema, revisioning, hashing, integrity | code (`methodfactory/manifest`) |
| Action Envelope parse + validation | code (`methodfactory/protocol`) |
| Persistence, atomic CAS, event journal, locks | code (`methodfactory/manifest/store.py`) |
| Conversation, clarification, content generation, tone | prompts (`prompts/`) |
| Operator interaction surface, transport, credentials | adapters (ADR-0007; CLI in v2.0.0) |

## State machine (v2.0.0 slice)

```
INTAKE ──prepare_summary──▶ SUMMARY_PENDING ──confirm_summary──▶ AUTHORING_AUTHORIZED ──record_draft_artifact──▶ DRAFT_READY
   ▲                            │                                   │
   └──────revise_intake─────────┴────────revise_intake──────────────┘
any non-terminal ──cancel──▶ CANCELLED (terminal)
```

`TRANSITION_TABLE` is the sole legality authority. **Review / Trial / Ship /
Triage are future phases** (states declared, transitions not yet implemented
— see ADR-0003). v2.0.0 ends at `DRAFT_READY` after the operator confirms the
canonical summary.

## Manifest and integrity

- Event journal is canonical (`events/<pkg>.events.jsonl`); the package JSON
  snapshot (`packages/<pkg>.json`) is a cache (ADR-0008).
- Every mutation is an atomic compare-and-swap: append event + fsync, then
  atomic snapshot write. Full chain verification on load: revision
  monotonicity, state continuity, `previous_manifest_sha256`, snapshot
  digests, and referenced artifact digests (each unique blob verified once —
  O(J) per load).
- Approvals bind exact digests: `confirm_summary` records
  `confirmed_summary_sha256` equal to `summary.canonical_sha256`; editing the
  intent/objective invalidates the approval (ADR-0006).
- Artifacts are stored once under their SHA-256 digest; reads and duplicate
  writes verify content (no poisoned digests).
- Crashes: a torn final journal line is an in-flight append (tolerated); a
  leftover lock is reclaimed when its owner is dead or the lock is ancient.

## Adapters

`ManifestStore`, `ArtifactStore`, `ConversationAdapter`, `RuntimeAdapter`
(ADR-0007). In v2.0.0 the CLI is the sanctioned operator channel; Turnstone /
Hermes / OpenClaw / git adapters attach through the interfaces without core
changes. Adapter success is never treated as domain truth.

## CI (release gate)

Hard gates (ADR-0010): full unittest suite, identity sweep (no stale Process
Engine identity in active paths; `evidence/` allowlisted), no stray generated
output, packaging sanity. No `|| true`. See `.github/workflows/release-gate.yml`.
