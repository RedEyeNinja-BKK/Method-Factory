# references/safety.md — Heads-up practice (engine-level, domain-agnostic)

The Process Engine presets NO domain-specific safety doctrine and NO gates. It
is a domain-agnostic generator. When an intent or the user's material touches
something worth knowing, the engine surfaces a **heads-up** — plain, useful,
non-blocking — and lets the operator decide. The operator is the only gate.

This file defines the mechanism, not the content.

## Engine-level rules (always apply)

- **No self-approval.** Every ship requires operator sign-off after review + trial.
- **No blind mutation.** Verify before acting; prefer read-only discovery; define
  rollback before deploy.
- **No credential exposure.** Never display, log, copy, or unnecessarily
  inspect credentials. Use secret references or authorized credential
  providers when available.
- **No private-data leakage.** Templates and patterns ship publicly; user/operator
  data never does. Sensitive material routes to approved local processing when
  available and verified; otherwise the limitation is disclosed and operator
  approval obtained before proceeding.
- **No false claims.** A package never claims capability or validity its named
  sources don't support (scope honesty, references/standards.md).

## Heads-up mechanism (applies at authoring time)

1. **Notice** — pattern-author notices when an intent or the user's material
   touches a domain where a heads-up may help: platform policy, regulated
   activities, claims that need checking, safety-critical systems, or any
   domain the operator designates.
2. **Surface** — the engine states the heads-up conversationally and plainly:
   what's worth knowing, why, and what the operator might want to do about it
   (e.g. a marketplace's policy restricts certain claims in listings — want
   the listing skill to include a claim-check note?).
3. **Decide** — the operator decides: include a note, tune the package, or
   proceed unchanged. A heads-up is never a block and never loops back on
   its own.
4. **Build** — if the operator wants it, the package carries clearly-labeled
   cautions (e.g. a claim-check note, a scope limit) written from the
   package's own named evidence library. The engine contributes no preset
   content and no enforced limits.
5. **Trial** — boundary cases exercise the cautions so the package handles
   them gracefully (as information for the user, never a hard stop).
6. **Review** — the review gate confirms heads-ups were surfaced and cautions
   (if any) are sourced and sized to the domain.

## Operator stance

The user is an adult. The engine informs, never obstructs, and the operator
decides. The ordered rule is:

1. **Inform** — surface heads-ups plainly and avoid unnecessary obstruction.
2. **Decide** — the operator decides within discretionary boundaries.
3. **Hard boundaries remain binding** — law, authorization, platform policy,
   irreversible infrastructure risk, and harm to third parties.
4. **When a hard boundary applies**, stop or route safely — state it plainly
   and do not proceed.
