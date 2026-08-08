"""Packaging smoke tests — version, entry point, and import surface (ADR-0012 §9)."""

from __future__ import annotations

import importlib.metadata
import unittest

import methodfactory


class PackagingTests(unittest.TestCase):
    def test_version_is_2_0_0rc1(self):
        self.assertEqual(methodfactory.__version__, "2.0.0rc1")

    def test_distribution_metadata_version_matches(self):
        try:
            dist = importlib.metadata.version("methodfactory")
        except importlib.metadata.PackageNotFoundError:
            self.skipTest("methodfactory not installed (not an editable install)")
        self.assertEqual(dist, "2.0.0rc1")

    def test_mf_entry_point_registered(self):
        eps = importlib.metadata.entry_points(group="console_scripts")
        mf = [ep for ep in eps if ep.name == "mf"]
        if not mf:
            self.skipTest("console script not registered (not an editable install)")
        self.assertEqual(mf[0].value, "methodfactory.cli:main")

    def test_import_surface(self):
        from methodfactory.adapters.artifact_store import ArtifactStore
        from methodfactory.domain.states import State
        from methodfactory.manifest.schema import validate_manifest
        from methodfactory.protocol.envelope import parse_envelope

        self.assertTrue(callable(parse_envelope))
        self.assertTrue(callable(validate_manifest))
        self.assertIsInstance(ArtifactStore, type)
        self.assertEqual(State.INTAKE.value, "INTAKE")

    def test_old_jsonl_engine_is_absent(self):
        # The JSONL-era store/engine were removed in the persistence reset and
        # must not be importable (ADR-0012 §8 discard list). The package name
        # `methodfactory.engine` is now the NEW pure transition-logic package
        # (no persistence, no JSONL-era API), so the guard asserts the
        # JSONL-era module and legacy submodules are absent and the new engine
        # exposes no legacy surface.
        import importlib

        with self.assertRaises(ImportError):
            importlib.import_module("methodfactory.manifest.store")
        with self.assertRaises(ImportError):
            importlib.import_module("methodfactory.engine.jsonl")
        import methodfactory.engine as engine

        self.assertFalse(hasattr(engine, "Engine"))
        self.assertFalse(hasattr(engine, "JsonlStore"))
        self.assertTrue(callable(engine.apply.next_manifest))


if __name__ == "__main__":
    unittest.main()
