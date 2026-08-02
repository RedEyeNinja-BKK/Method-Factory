# Manifest Contract v0.1

**Status:** Accepted (2026-08-03, operator approval)
**Authority:** Code (the engine) creates, validates, mutates, hashes, and
persists the manifest. The model proposes data via the action envelope; it
never writes manifest state.

The logical schema is shown in YAML for readability. **The on-disk byte form
is JSON.** Canonical serialization for hashing:

```python
json.dumps(manifest, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
```

The digest of a manifest is `sha256` of its canonical serialization.

## Logical schema

```yaml
schema_version: "0.1"          # fixed
package_id: "pkg_<opaque-id>"  # ^pkg_[A-Za-z0-9_-]{1,63}$
revision: 7                    # non-negative int; +1 on every successful mutation
state: "SUMMARY_PENDING"       # from the transition table only (ADR-0003)
created_at: "<ISO-8601 UTC>"
updated_at: "<ISO-8601 UTC>"
previous_manifest_sha256: "<digest-or-null>"   # write lineage; null at revision 0

intent:
  raw: "<operator-provided text>"
  clarified: null              # structured re-statement, future phases

inputs:                        # every operator material item
  - input_id: "in_001"
    kind: "text|url|file-reference|constraint"
    source: "operator|adapter"
    disposition: "incorporated|excluded"
    exclusion_reason: null     # required when disposition == excluded
    content_sha256: "<code-computed digest of content bytes>"
    content_size: 123          # byte count
    content_path: "inputs/in_001.txt"   # artifact-store path

objective:
  statement: "<what good looks like>"
  desired_outcomes: ["<outcome>", ...]

summary:                       # null until prepared
  content: "<exact text the operator reviewed>"
  canonical_sha256: "<sha256 of content bytes>"
  presented_at: "<ISO-8601 UTC>"
  confirmation:
    status: "pending|confirmed"
    confirmed_at: null
    operator_id: null
    confirmed_summary_sha256: null

artifacts:                     # produced drafts; digests code-computed
  - artifact_id: "art_001"
    kind: "skill"
    logical_path: "skills/example/SKILL.md"
    status: "draft"
    sha256: "<code-computed digest>"
    byte_count: 1234

transition:
  last_event_id: "evt_<opaque-id>"
  last_action_id: "act_<opaque-id>"
```

## Ownership and integrity rules

1. The model proposes; **code writes**. No model output can alter a manifest
   except through a validated action envelope handled by the engine.
2. All hashes are **code-computed from canonical bytes**. Supplied hashes are
   rejected as unknown envelope fields; mismatches fail the gate.
3. Every successful mutation: `revision += 1`,
   `previous_manifest_sha256 = digest(current manifest)`, `updated_at` set,
   `state` set to the transition target.
4. Operator confirmation binds `summary.canonical_sha256` exactly
   (ADR-0006).
5. Persistence is atomic (temp file → fsync → `os.replace` → fsync dir)
   under a package lock; an append-only event log records each transition
   with `resulting_manifest_sha256` (ADR-0008).
6. On load, the engine verifies schema, event-chain continuity, snapshot
   digest, and referenced artifact digests. Failure → read-only recovery
   mode.

## Field classification (from the migrated v1.9.1 schema)

| Migrated group | v0.1 treatment |
|---|---|
| `package_id`, `package_version`, schema versioning | Kept as identity + monotonic revision |
| intent, objective, desired outcomes, input disposition | Kept (durable domain state) |
| artifact type / path / status | Kept, with code-computed digest + size |
| review verdict/findings | Kept for later phases (structured gate record) |
| trial run id / verdict / evidence path | Excluded from v0.1; added with trial phase |
| deployment target / objects / rollback | Excluded; runtime-adapter data (ADR-0007) |
| `target_runtime` | Optional adapter request; never gates authoring |
| `engine_version`, `engine_lineage` | Optional metadata; not lifecycle authority |
| evaluator_version, assertion contracts, semantic judge | **Legacy qualification — excluded** |
| transcript hashes, baseline, evaluator env | **Legacy trial evidence — excluded** |
| `assurance_tier` + policy logic | **Legacy policy — excluded from core** |
| Turnstone deployment object IDs, prompt-policy/judge records | **Runtime-specific — excluded from portable core** |
