# Method Factory

**A prompt+code system for producing tested, portable agent packages — with deterministic enforcement and lighter, conversation-first prompts.**

Method Factory is the successor to [Process Engine](https://github.com/RedEyeNinja-BKK/Process-Engine). Process Engine proved the pipeline works through prompt-only experimentation and a successful end-to-end case study. Method Factory takes that proven design and adds a code layer: the state machine, gate enforcement, and manifest integrity are deterministic. The prompts are lighter, focused on conversation and content generation — not on enforcing their own rules.

> **Process Engine** remains the Turnstone-native, prompts-only reference implementation — active, not abandoned. It is the philosophical anchor. This repo builds outward from it.

---

## What it does

Tell it what you want to build, share any material you have, and it produces a complete agent package — persona, skills, templates, and evaluation cases — through a gated pipeline:

```
Intent → Collect → Clarify → Objective → Summary Gate → Pattern Author → Review → Trial → Ship → Triage
```

The pipeline was discovered through prompt-only experimentation (Process Engine v1.0–v1.6.0) and validated in a real end-to-end case study. Method Factory hardens the gatekeeping logic into code while keeping the prompts conversation-first.

---

## How it differs from Process Engine

| | Process Engine | Method Factory |
|---|---|---|
| **Enforcement** | Prompts + Turnstone governance | Deterministic code |
| **Platform** | Turnstone-native | Platform-agnostic |
| **Prompts** | Include enforcement rules | Conversation + content only |
| **State machine** | Prompts describe it | Code enforces it |
| **Manifest** | LLM reads/writes TOML | Validated schema + code I/O |
| **Trials** | Prompt-described | Code-driven harness |
| **Status** | Active reference | Under development |

---

## Architecture

```
Code owns:  state machine, gate enforcement, manifest I/O, trial harness
Prompts own: conversation, clarifying questions, content generation, tone
```

Design principle: the model should not be responsible for enforcing its own constraints. Code enforces the rules; prompts guide the work.

---

## Origin

Method Factory is built from the domain knowledge captured in [Process Engine](https://github.com/RedEyeNinja-BKK/Process-Engine) — specifically the pipeline design (Intent → Collect → Clarify → Objective → Summary Gate → Pattern → Review → Trial → Ship → Triage) that emerged from hundreds of prompt-only experiments and was validated in a [real end-to-end run](https://github.com/RedEyeNinja-BKK/Process-Engine/blob/main/evals/case-study-first-run.md).

The prompt-only phase was not a shortcut — it was the discovery method. We didn't guess the architecture. We ran real interactions until the lifecycle proved itself. Now we're hardening the guarantees into code.

---

## Status

**Under active development.** This repo contains migrated content from Process Engine v1.9.1 and is being restructured around the prompt+code architecture. The initial code layer (state machine, manifest validation, gate enforcement) is under construction.

---

## License

MIT — see [LICENSE](LICENSE).

---

## Docs

- [Architecture](docs/architecture.md)
- [Migration from Process Engine](docs/migration-from-process-engine.md)
- [Spec compliance](docs/spec-compliance.md)
- [Case study: first live run](evals/case-study-first-run.md)
