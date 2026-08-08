# Governance Usage — Process Engine × Turnstone's Governance Surface

> **Historical / superseded.** This document describes the Process Engine era. Current Method Factory architecture and release state: see [architecture-reset-status.md](architecture-reset-status.md) and [ADR-0012](adr/ADR-0012-persistence-architecture.md).

> **Status:** PARTIALLY DEPLOYED (2026-08-01). Live: prompt policy
> `process-engine-context` (content-only, priority 1) + heuristic rule
> `process-engine-authoring` (advisory, review, low risk) + judge surface
> verified (14 settings, 36 rules, 19 patterns). Not deployed: nothing else
> — the design is documented, advisory by design, operator is the only
> gate.
>
> **Context:** Process Engine is built on Turnstone. This note answers two
> questions: (1) why Turnstone — what its Governance surface uniquely offers
> — and (2) how Process Engine can use Turnstone's Governance surfaces
> (Prompts, Judge) as *capability* to serve the engine's intent, without
> turning them into guardrails, and while keeping generated results portable.

---

## 1. Why Turnstone (the README case)

Turnstone's Governance surface is its differentiator among agent harnesses:
a first-class, self-hosted layer over how agents operate — identity (personas),
capability (roles, tool policies), behavioral anchoring (prompt policies),
judgment (Judge), and audit (Observe: usage, audit, memories).

| Harness | Governance surface | Self-hosted | Cost |
|---|---|---|---|
| **Turnstone** | Full — projects, personas, roles, policies, prompts, judge, audit | ✅ | free / open |
| Hermes | Agent runtime (skills, toolsets, tasks) — no governance objects | ✅ | free |
| OpenClaw | Agent + channels (Discord/LINE) — emission-focused | ✅ | free |
| Claude | Commercial harness, no governance layer | ❌ hosted | paid |

The deeper point: **the packages Process Engine generates ARE governance
objects** (project, persona, skills). The engine's "operator is the gate"
maps to Turnstone's approval surfaces; review/trial evidence maps to audit
and Judge. The engine's philosophy is literally what Governance enables.

**Proposed README addition** (in "Why Turnstone" form):

> **Why Turnstone?** Because the platform's Governance surface is the
> engine's output format. Process Engine generates governance objects —
> projects, personas, skills — and Turnstone is the self-hosted harness
> with a first-class governance layer over how agents operate (identity,
> capability, anchoring, judgment, audit). Hermes and OpenClaw are strong
> runtimes, but they don't expose this surface; commercial harnesses
> aren't self-hosted. We chose the platform whose governance objects are
> what the engine produces.

---

## 2. The reframe: Governance as capability, not guardrail

The v4 deployment plan deliberately chose "no native policies — guardrails
= content only." That decision predated a holistic view of the surface.

**Current stance (operator, 2026-08-01):** tool policies remain off the
table (not applicable). **Prompts and Judge are not for guardrails** — they
are platform capabilities to be used, where they serve the engine's
intent. The engine's own posture (heads-up, not police; operator is the
only gate) is preserved: every use below is advisory, never blocking.

---

## 3. Prompts — used as capability (not guardrails)

**What Prompts is:** content-only prompt policies (global scope, optional
`tool_gate`; our safe pattern = content-only, priority 1, no tool gate).

**Proposed use — "engine context" policy:**

A content-only, priority-1 prompt policy stating the engine's durable
operating stance, so every session on this Turnstone starts aligned even
before the core skill loads:

```text
Process Engine context (applies to sessions on the Process Engine project):
- Collect before creating: invite the user's material (links, text, files,
  docs); nothing is rejected by type.
- Ask what "good" looks like; form the objective and desired outcomes from
  the vision.
- Operator is the only gate: nothing ships without operator sign-off.
- Nothing ships untried: trials with evidence precede every ship.
- Adapt, never copy: extract techniques, author original instructions,
  attribute sources.
- Heads-up, not police: surface useful considerations, never obstruct.
```

**Why this is capability, not guardrail:** it anchors the engine's stance
in the platform (persistent across sessions) — it does not block anything.
Global scope is a caveat: the text is phrased so non-engine sessions are
not confused (it scopes itself to "sessions on the Process Engine project").

**Portable results preserved:** the policy shapes the engine's own
operation; it never enters generated-package content.

---

## 4. Judge — used as intent-fidelity evidence (not restriction)

**What Judge actually is** (verified from the installed source):
`core/judge.py` opens with "**Intent validation judge**" — it evaluates
non-auto-approved tool calls and produces structured **`IntentVerdict`s**:
intent summary, risk level, confidence, recommendation (approve/review/
deny), reasoning, evidence — *advisory verdicts that inform (but never
replace) the human approval decision.*

Two configurable surfaces:

| Surface | What it is | Restrictive? |
|---|---|---|
| **Heuristic Rules** | `heuristic_rules`: tool pattern + arg patterns → risk/confidence/recommendation/intent template | Advisory — informs, never blocks |
| **Output Guard** | 3-facet guard: regex + LLM judge (catches camouflaged payloads) + heuristic fallback | Advisory verdicts, not blocks |

Already live here: `judge.enabled = True`, `judge.model =
deepseek-deepseek-v4-flash`, `judge.smart_approvals = True`,
`judge.confidence_threshold = 0.95`, `judge.output_guard = True`; plus a
`/v1/api/admin/judge/…` admin API (settings, heuristic rules, output-guard
patterns).

**Proposed uses — three, all advisory:**

1. **Trial grading** — a heuristic rule targeting the engine's authoring /
   deploy tools (skills create/update, workstream creation) produces a
   per-call `IntentVerdict` → machine-consistent evidence that each
   gate-action matched the operator's intent (recommendation + reasoning).
2. **Review-gate evidence** — judge verdicts (intent summary, risk,
   reasoning) join the review checklist as auditable, non-blocking
   evidence — consistent with "operator is the only gate."
3. **Objective-fidelity check** — the LLM tier's reasoning can score "does
   this action serve what 'good' looked like" (the operator's vision) —
   the intent-alignment test, stored as output assessments.

**Portable results preserved:** Judge runs inside the Turnstone trial /
review harness. Case sets, expected outputs, and generated packages stay
portable; the judge only makes the evidence consistent. Nothing
Turnstone-only leaks into what ships.

---

## 5. Wiring plan (all operator-gated, all reversible)

**Status (2026-08-01): steps 1–3 executed and verified.**

| Step | Action | Verification | Rollback |
|---|---|---|---|
| 1 ✅ | Verify the judge admin API live (list settings, list heuristic rules, list output-guard patterns) | 14 settings, 36 rules, 19 patterns returned | — |
| 2 ✅ | Add one heuristic rule: `process-engine-authoring` (tool=skills, arg=process-engine, risk=low, rec=review, advisory) | Rule listed; id 64b985f99743463a9ddf1a78ded01466 | Delete rule |
| 3 ✅ | Create the "engine context" prompt policy `process-engine-context` (content-only, priority 1) | Policy listed; id f0991b6598ad4623a410b45cc7aabf28 | Disable/delete policy |
| 4 ✅ | Run a trial pass; confirm judge verdicts appear as evidence in the trial record | 31/31 PASS with policy live (evals/governance-trial-evidence.md); **judge rule dormant** — zero verdicts under blanket approval; recommendation documented | Re-run without the rule |
| 5 | Fold into the package canon: policy text + rule definition documented (this note) | Docs updated; portable outputs unchanged | Docs revert |

**Guardrails that stay:** nothing here blocks. Tool policies remain off the
table. The operator remains the only gate. Judge verdicts are advisory
input to that gate, never a replacement for it.

---

## 6. Open decisions (operator)

1. Approve the "Why Turnstone" README section (item 1 text).
2. Approve creating the "engine context" prompt policy (step 3).
3. Approve adding the heuristic rule (steps 2 + 4) after the API is
   verified live.
4. Confirm the wording of the policy so global scope doesn't confuse
   non-engine sessions.
