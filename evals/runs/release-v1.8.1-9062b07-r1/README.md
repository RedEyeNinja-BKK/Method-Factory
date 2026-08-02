# Process Engine v1.8.1 mirrored release bundle

This bundle `release-v1.8.1-9062b07-r1` records two independently sourced final-release sub-runs against commit `9062b07a766dad8aad3c769a5d39f438c0a412d3` under the mirrored-dual-source protocol. Run A: `turnstone-orchestrator` executed and `openclaw-main` verified using `gpt-5.6-terra`; result 34 PASS / 0 FAIL / 0 PENDING. Run B: `turnstone-orchestrator` executed and `hermes-gateway` verified using `gpt-5.6-terra`; result 34 PASS / 0 FAIL / 0 PENDING. The requested baseline status is `executed`.

Each sub-run contains immutable `actual/` transcript evidence, SHA-256 integrity data in `hashes.json`, append-only judgment and assertion records, the case inputs, a sealed manifest, environment metadata, and summary evidence links. Finalization writes conservative FAIL judgments for cases that lack recorded judgment evidence; it never creates an automatic PASS.
