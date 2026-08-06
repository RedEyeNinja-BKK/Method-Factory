"""CLI behavior tests — remediation of code-review F7 (apply package_id
mismatch) and F16 (stable error surface per ADR-0008).
"""

from __future__ import annotations

import contextlib
import io
import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from methodfactory.cli import main

PKG = "pkg_cli_001"


def _valid_apply_envelope(pkg: str = PKG) -> dict:
    return {
        "protocol_version": "0.1",
        "action_id": "act_cli_001",
        "package_id": pkg,
        "expected_revision": 0,
        "action": "record_input",
        "basis": {},
        "payload": {
            "input_id": "in_001",
            "kind": "text",
            "content": "material",
            "source": "operator",
            "disposition": "incorporated",
        },
    }


class CliTests(unittest.TestCase):
    def _run(self, argv: list[str], stdin: str | None = None) -> tuple[int, str, str]:
        out, err = io.StringIO(), io.StringIO()
        try:
            if stdin is not None:
                with (
                    contextlib.redirect_stdout(out),
                    contextlib.redirect_stderr(err),
                    mock.patch("sys.stdin", io.StringIO(stdin)),
                ):
                    code = main(argv)
            else:
                with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
                    code = main(argv)
        except SystemExit as exc:  # argparse --version / -h
            code = exc.code if isinstance(exc.code, int) else 0
        return code, out.getvalue(), err.getvalue()

    def test_create_and_status_exit_zero(self):
        with tempfile.TemporaryDirectory() as td:
            code, out, err = self._run(["--store", td, "create", PKG, "Build a skill."])
            self.assertEqual(code, 0, err)
            self.assertIn('"state": "INTAKE"', out)
            code, out, _ = self._run(["--store", td, "status", PKG])
            self.assertEqual(code, 0)
            self.assertIn('"revision": 0', out)

    def test_apply_package_id_mismatch_fails(self):
        """F7: envelope package_id must match the CLI argument."""
        with tempfile.TemporaryDirectory() as td:
            self._run(["--store", td, "create", PKG, "Build a skill."])
            env = _valid_apply_envelope(pkg="pkg_other_001")
            with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False) as fh:
                json.dump(env, fh)
                env_path = fh.name
            try:
                code, out, err = self._run(["--store", td, "apply", PKG, env_path])
            finally:
                Path(env_path).unlink()
            self.assertEqual(code, 1)
            self.assertIn("INVALID_ENVELOPE", err)
            self.assertNotIn("Traceback", err)

    def test_apply_missing_envelope_file_returns_stable_code(self):
        """F16: unreadable envelope file must produce {code, message} JSON, not a traceback."""
        with tempfile.TemporaryDirectory() as td:
            self._run(["--store", td, "create", PKG, "Build a skill."])
            code, out, err = self._run(["--store", td, "apply", PKG, "/nonexistent/envelope.json"])
            self.assertEqual(code, 1)
            self.assertIn("FILE_IO", err)
            self.assertNotIn("Traceback", err)
            payload = json.loads(err)
            self.assertEqual(payload["code"], "FILE_IO")

    def test_summary_without_summary_returns_stable_code(self):
        """F16: summary on a package with no summary must emit a machine-readable code."""
        with tempfile.TemporaryDirectory() as td:
            self._run(["--store", td, "create", PKG, "Build a skill."])
            code, out, err = self._run(["--store", td, "summary", PKG])
            self.assertEqual(code, 1)
            self.assertIn("NO_SUMMARY", err)

    def test_apply_stdin_happy_path(self):
        with tempfile.TemporaryDirectory() as td:
            self._run(["--store", td, "create", PKG, "Build a skill."])
            code, out, err = self._run(["--store", td, "apply", PKG, "-"], stdin=json.dumps(_valid_apply_envelope()))
            self.assertEqual(code, 0, err)
            self.assertIn('"revision": 1', out)

    def test_version(self):
        code, out, err = self._run(["--version"])
        self.assertEqual(code, 0)
        self.assertIn("2.0.0", out)


if __name__ == "__main__":
    unittest.main()
