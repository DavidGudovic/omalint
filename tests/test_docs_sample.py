"""docs/sample is what the screenshots are taken of; these tests keep it producing the problems they show."""

import unittest

from helpers import FIXTURES, ROOT, Helpers, find, run_check

from omalint.model import Context

SAMPLE = ROOT / "docs" / "sample"


class SampleTests(Helpers, unittest.TestCase):
    def setUp(self):
        self.ctx = Context(
            config_dir=SAMPLE / "omarchy",
            hypr_dir=SAMPLE / "hypr",
            omarchy_path=FIXTURES / "stock",
            live=False,
        )

    def test_manifests(self):
        self.assertFindings(run_check("manifests", self.ctx), {
            ("manifest.entry-point-missing", "acme.notes"): "error",
        })

    def test_bar(self):
        result = run_check("bar", self.ctx)
        self.assertFindings(result, {
            ("bar.unknown-widget", "acme.old-clock"): "warn",
            ("bar.duplicate-widget", "omarchy.tray"): "warn",
        })
        self.assertTrue(find(result, "bar.unknown-widget", "acme.old-clock").fixable)
        self.assertFalse(find(result, "bar.duplicate-widget", "omarchy.tray").fixable)

    def test_keys(self):
        self.assertFindings(run_check("keys", self.ctx), {("keys.conflict", "SUPER + F"): "warn"})

    def test_deps(self):
        self.assertFindings(run_check("deps", self.ctx), {("deps.missing", "acme.gpu-meter"): "warn"})

    def test_stale(self):
        self.assertFindings(run_check("stale", self.ctx), {})


if __name__ == "__main__":
    unittest.main()
