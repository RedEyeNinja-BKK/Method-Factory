# Case Study — First Live Run: a Shop Package, End to End

> **What this is:** the first real-world run of Process Engine — a shop owner
> used it to generate a package for their online store, and the whole pipeline
> (collect → clarify → objective → gate → pattern → review → trial → ship)
> ran with recorded evidence.
>
> **Privacy:** names, products, and numbers below are **anonymized**. The
> original run stays private (per the engine's principle: user data never
> ships). The pattern and the evidence are real.

---

## The scenario

An independent online shop owner (marketplace store) came to Process Engine
with an intent:

> "I want a package to help me review my store, review my spreadsheet, and
> create store listings — titles, tags, descriptions."

They were asked whether they had anything to work from, and gave two inputs:

1. **A spreadsheet skill** (link to a third-party skill) — fetched, its
   craft extracted (verification discipline, formula-choice rules), adapted,
   attributed — never copied.
2. **Their store URL** — treated as *domain context* (not a skill): fetched
   to learn what the shop sells and its tone, used to make the package
   specific, never published.

The engine also asked: **"What does 'good' look like to you?"** The owner's
answer — a monthly net-profit target and "don't waste my time" — became the
package's objective and its north-star number.

## What the session looked like

| Stage | What happened |
|---|---|
| **Collect** | Two inputs taken (link + text/store context), each routed through intake |
| **Clarify** | Questions referenced the material ("your spreadsheet skill covers creation — what does your sheet hold?") |
| **Objective** | "What does 'good' look like?" → a concrete target, threaded through the design |
| **Summary gate** | "Working from: 1 skill link + 1 store link. Intent: X. Good looks like: <target>. Generate?" — owner confirmed |
| **Eligibility** | Shape decided: a **persona + four skills** (not one skill, not a full new project) |
| **Pattern → Review** | Draft produced to standard; owner reviewed and approved |
| **Trial** | 6/6 cases + 14/14 trigger set + with/without baseline (below) |
| **Ship** | Owner approved; deployed via native mechanisms; verified by read-back; rollback defined first |

## What shipped

A **persona** (a store-operations manager with the owner's style and the
target as north star) and **four skills**:

- **Store audit** — reviews existing listings, scores them against platform
  anatomy (title/tags/description/materials/category), runs an advisory
  policy sweep, outputs a ranked, evidence-cited action list.
- **Listing writer** — drafts new listings in the owner's voice; **pauses and
  asks** rather than inventing product facts or style it doesn't have.
- **Policy reviewer** — an advisory checklist: flags wording that risks
  platform policy (e.g. claim-sensitive categories), suggests neutral
  alternatives, **never blocks — the operator decides**.
- **Targets tracker** — weekly business review: math shown, gap to the
  target computed, top moves with labeled estimates, aspirational framing.

## The evidence (why we trust it)

Trials ran each case **with** the package vs **without** it (a generic
session). The deltas are the point:

| Case | Generic session | With package |
|---|---|---|
| Store audit | Ad-hoc, no scoring, no citations, "not a full audit" | Structured scoring, ranked verdicts, every finding cited |
| Listing draft | **Invented product facts** and a generic voice | Paused for facts + style; complete anatomy; rationale per element |
| Policy check | **Offered a risky compromise**; no citations | Flagged the wording, cited the policy section, offered neutral text, operator decides |
| Target review | Stated the gap, **no math shown** | Full math, labeled assumptions, top-3 moves with estimates |

Trigger set: **14/14 correct** (8 should-activate, 6 shouldn't, including
near-misses). Cost noted: the package runs added ~1.2–1.8k input tokens and
produced the discipline that was absent without it.

Every gate was recorded with the operator's actual sign-off. Rollback was
defined before deploy. Ship evidence and trial evidence are part of the
package record.

## What this run demonstrated

1. **Intent engineering works end to end.** The answer to "what does good
   look like" became the package's objective — and that objective shows up
   in the persona and the tracking skill, not just the intake chat.
2. **Input-agnostic collection works.** A skill link and a store URL were
   both used, each handled per its type; the external skill's craft was
   adapted and attributed (provenance metadata in the generated
   frontmatter), never copied.
3. **Heads-up, not police.** The claim-sensitive category was flagged
   advisory-style, with neutral alternatives — and the trial proved the
   generic version would have shipped the risky wording. The engine
   informed; the owner decided.
4. **The gate held.** Nothing shipped without the owner's sign-off at
   review, trial, and ship — and the machine that produced the package was
   left untouched (no changes to Process Engine itself).

## Try it yourself

1. Open a workstream on the **Process Engine** project with the
   **process-engine** persona and load `process-engine-core`.
2. Say what you want to build; give it any material you have — links, pasted
   text, files, your own docs.
3. Answer "what does 'good' look like to you?" — even a vague vision helps.
4. Watch it flow through Pattern → Review → Trial → Ship, with your sign-off
   at each gate.

## Anonymization note

Store name, product details, exact figures, and margins were replaced with
representative equivalents; the structure, flow, and evidence are
unchanged. The original run remains private by design.
