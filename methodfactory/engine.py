"""PipelineEngine — fail-fast application of validated action envelopes.

Order of checks (ADR-0008): parse+validate envelope → load+verify manifest →
action-id idempotency/reuse → revision check → legality → gates → build next
manifest → validate → event-journal-first CAS. No partial writes.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from typing import Callable, Optional

from .adapters.artifact_store import ArtifactStore, validate_logical_path
from .domain.errors import (
    ActionIdReuseError,
    IllegalTransitionError,
    ManifestInvalidError,
    StaleActionError,
)
from .domain.gates import check_action_gate
from .domain.states import State
from .domain.transitions import Action, transition_target
from .manifest.hashing import digest_json, digest_text, utcnow
from .manifest.render import render_summary
from .manifest.schema import validate_manifest
from .manifest.store import ManifestStore
from .protocol.envelope import ActionEnvelope, parse_envelope

NowFn = Callable[[], str]


@dataclass(frozen=True)
class ApplyResult:
    manifest: dict
    event: dict
    replayed: bool


class PipelineEngine:
    def __init__(
        self,
        store: ManifestStore,
        artifact_store: ArtifactStore,
        now: Optional[NowFn] = None,
    ) -> None:
        if getattr(store, "artifact_store", None) is None:
            raise ValueError(
                "PipelineEngine requires a ManifestStore constructed with artifact_store "
                "(artifact digest verification is mandatory on the mutation path)"
            )
        self.store = store
        self.artifacts = artifact_store
        self._now = now or utcnow

    # ── public API ─────────────────────────────────────────────────────
    def create_package(self, package_id: str, intent_raw: str) -> dict:
        return self.store.create(package_id, intent_raw, created_at=self._now())

    def apply_json(self, raw: str) -> ApplyResult:
        return self.apply(parse_envelope(raw))

    def apply(self, env: ActionEnvelope) -> ApplyResult:
        # 1. Envelope is already parsed + schema-validated. Read the journal
        #    once and reuse the parsed events for load + idempotency lookup
        #    (avoids parsing the whole journal three times per apply).
        events = self.store.read_events(env.package_id)
        manifest = self.store.load(env.package_id, events=events)  # MANIFEST_INVALID if missing/corrupt

        # 2. Idempotency / reuse BEFORE revision comparison: a retry of an
        #    already-committed action is not a stale action. The action's
        #    semantic content excludes expected_revision so a caller can
        #    retry with an updated revision and the same action_id; a changed
        #    action under the same action_id is ACTION_ID_REUSE.
        action_content = env.as_dict()
        action_content.pop("expected_revision", None)
        action_sha256 = digest_json(action_content)
        prior = self.store.find_event(env.package_id, env.action_id, events=events)
        if prior is not None:
            if prior.get("action_sha256") == action_sha256:
                return ApplyResult(manifest=manifest, event=prior, replayed=True)
            raise ActionIdReuseError(
                f"action_id {env.action_id!r} reused with different content",
                package_id=env.package_id,
                state=manifest["state"],
            )

        # 3. Revision check (stale action fails fast).
        if env.expected_revision != manifest["revision"]:
            raise StaleActionError(
                "expected_revision does not match current manifest revision",
                package_id=env.package_id,
                state=manifest["state"],
                expected_revision=env.expected_revision,
                actual_revision=manifest["revision"],
            )

        action = Action(env.action)

        # 4. Legality for the current state.
        target = transition_target(State(manifest["state"]), action)
        if target is None:
            raise IllegalTransitionError(
                f"{env.action!r} is not legal in state {manifest['state']!r}",
                package_id=env.package_id,
                state=manifest["state"],
                expected_revision=env.expected_revision,
                actual_revision=manifest["revision"],
            )

        # 5. Gate predicates (evidence + binding checks).
        check_action_gate(action, manifest, env)

        # 6. Build next manifest.
        event_id = "evt_" + uuid.uuid4().hex
        next_manifest = self._mutate(manifest, env, action, event_id)
        next_manifest["revision"] = manifest["revision"] + 1
        next_manifest["previous_manifest_sha256"] = digest_json(manifest)
        next_manifest["updated_at"] = self._now()
        next_manifest["state"] = target.value

        # 7. Validate the result before persisting anything.
        errors = validate_manifest(next_manifest)
        if errors:
            raise ManifestInvalidError(
                "engine produced an invalid manifest: " + "; ".join(errors),
                package_id=env.package_id,
            )

        event = {
            "event_id": event_id,
            "action": env.action,
            "action_id": env.action_id,
            "revision": next_manifest["revision"],
            "state_before": manifest["state"],
            "state_after": next_manifest["state"],
            "resulting_manifest_sha256": digest_json(next_manifest),
            "action_sha256": action_sha256,
            "at": self._now(),
        }

        # 8. Atomic commit: CAS + event (all-or-nothing). The already-verified
        #    manifest is passed in so the store only tail-checks under the lock
        #    instead of re-running a full chain replay.
        self.store.compare_and_swap(
            env.package_id,
            manifest["revision"],
            next_manifest,
            event,
            current_manifest=manifest,
        )
        return ApplyResult(manifest=next_manifest, event=event, replayed=False)

    def status(self, package_id: str) -> dict:
        manifest = self.store.load(package_id)
        summary = manifest.get("summary")
        return {
            "package_id": package_id,
            "state": manifest["state"],
            "revision": manifest["revision"],
            "intent": manifest["intent"]["raw"],
            "inputs": len(manifest["inputs"]),
            "artifacts": len(manifest["artifacts"]),
            "summary_confirmation": (
                None
                if summary is None
                else (summary.get("confirmation") or {}).get("status")
            ),
            "summary_sha256": None if summary is None else summary.get("canonical_sha256"),
        }

    # ── mutation ───────────────────────────────────────────────────────
    def _mutate(
        self, manifest: dict, env: ActionEnvelope, action: Action, event_id: str
    ) -> dict:
        from copy import deepcopy

        next_m = deepcopy(manifest)

        if action == Action.RECORD_INPUT:
            p = env.payload
            content = p["content"]
            digest, size = self.artifacts.put(
                env.package_id, f"inputs/{p['input_id']}.txt", content
            )
            next_m["inputs"].append(
                {
                    "input_id": p["input_id"],
                    "kind": p["kind"],
                    "source": p["source"],
                    "disposition": p["disposition"],
                    "exclusion_reason": p.get("exclusion_reason"),
                    "content_sha256": digest,
                    "content_size": size,
                    "content_path": f"inputs/{p['input_id']}.txt",
                }
            )

        elif action == Action.SET_OBJECTIVE:
            next_m["objective"] = {
                "statement": env.payload["statement"],
                "desired_outcomes": env.payload.get("desired_outcomes", []),
            }

        elif action == Action.PREPARE_SUMMARY:
            content = render_summary(manifest)
            next_m["summary"] = {
                "content": content,
                "canonical_sha256": digest_text(content),
                "presented_at": self._now(),
                "confirmation": {
                    "status": "pending",
                    "confirmed_at": None,
                    "operator_id": None,
                    "confirmed_summary_sha256": None,
                },
            }

        elif action == Action.CONFIRM_SUMMARY:
            summary = next_m["summary"]
            summary["confirmation"] = {
                "status": "confirmed",
                "confirmed_at": self._now(),
                "operator_id": env.payload.get("operator_id") or "operator",
                "confirmed_summary_sha256": summary["canonical_sha256"],
            }

        elif action == Action.REVISE_INTAKE:
            # Return to intake; any approval is invalidated until a new
            # summary is prepared and confirmed (ADR-0006).
            next_m["summary"] = None

        elif action == Action.RECORD_DRAFT_ARTIFACT:
            p = env.payload
            logical_path = validate_logical_path(p["logical_path"])
            digest, size = self.artifacts.put(env.package_id, logical_path, p["content"])
            next_m["artifacts"].append(
                {
                    "artifact_id": p["artifact_id"],
                    "kind": p["kind"],
                    "logical_path": logical_path,
                    "status": "draft",
                    "sha256": digest,
                    "byte_count": size,
                }
            )

        # CANCEL: state change only (handled by transition table target).

        next_m["transition"]["last_action_id"] = env.action_id
        next_m["transition"]["last_event_id"] = event_id
        return next_m
