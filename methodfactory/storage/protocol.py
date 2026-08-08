"""Storage protocol — the ManifestStore interface, independent of SQLite.

The SQLite store (and any future adapter) implements this interface. The
contract invariants are frozen in ADR-0012 §2, §6, §8; the authoritative
chain validator is owned by the storage layer and exercised on every
transactional apply (implemented in a later Phase 2 commit).
"""

from __future__ import annotations

from typing import Any, Optional, Protocol, runtime_checkable


@runtime_checkable
class ManifestStore(Protocol):
    """Canonical package store interface.

    Contract summary (ADR-0012):
    - ``create`` commits revision 0 (the create_package event) with
      ``state_before IS NULL``.
    - ``apply`` runs the ``BEGIN IMMEDIATE`` transaction: idempotency by
      (package_id, action_id) + ``action_sha256``, revision CAS, exactly one
      event insert; ``ACTION_ID_CONFLICT`` on same id + different hash;
      ``STALE_ACTION`` on a stale expected revision.
    - ``load`` returns the latest manifest via the indexed latest-event read;
      the hot path never runs a full-chain replay.
    - ``read_events`` returns ordered events for export/audit
      (``method-factory-events-v1``).
    """

    def create(
        self, package_id: str, intent_raw: str, created_at: Optional[str] = None
    ) -> dict[str, Any]: ...

    def apply(self, envelope: dict[str, Any]) -> dict[str, Any]: ...

    def load(self, package_id: str) -> dict[str, Any]: ...

    def read_events(self, package_id: str) -> list[dict[str, Any]]: ...
