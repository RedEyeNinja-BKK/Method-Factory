# Portable install test — 20260801

> **Historical / superseded.** This document describes the Process Engine era. Current Method Factory architecture and release state: see [architecture-reset-status.md](architecture-reset-status.md) and [ADR-0012](adr/ADR-0012-persistence-architecture.md).

**Status:** provisioned, not executed (operator deferred external-client testing 2026-08-01).

## Target
```
skills dir: /tmp/pe-portable-target
agent runtime: (record client name + version here)
repo commit: cc549f6
```

## 1. Fresh environment
```bash
mkdir -p /tmp/pe-portable-target
```

## 2. Install all six skills
```bash
cp -r /home/vincent/shared-workspace/operations/process-engine/repo-staging/skills/process-engine-* /tmp/pe-portable-target/
```

## 3-9. Pipeline (record outputs here when executed)
- Invoke core -> first response asks for material (PASS/FAIL/notes)
- Generate small package (release-notes) -> DRAFT produced
- Review -> verdict recorded
- Trial -> case set run, PASS/FAIL
- Filesystem ship -> files copied, hashes match
- Verify installed package -> frontmatter valid, agent discovers skills
- Rollback -> copied package deleted

## Discovered skills
```bash
ls /tmp/pe-portable-target/ | grep process-engine
```

