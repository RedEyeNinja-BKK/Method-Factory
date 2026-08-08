"""Engine package — deterministic, storage-independent transition logic.

The engine owns WHAT a legal action does to a manifest (legality, gates,
mutation, revision/lineage). Storage owns WHERE the resulting manifest and
event are durably committed. The engine never touches SQLite, the filesystem,
or the artifact store; it returns the next manifest plus the content blobs
the storage layer must persist and verify.
"""
