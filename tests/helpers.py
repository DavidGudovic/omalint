"""Shared paths, builders and fakes for the omalint tests."""

import hashlib
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
FIXTURES = ROOT / "tests" / "fixtures"
CLI = ROOT / "bin" / "omalint"

sys.dont_write_bytecode = True
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from omalint import inventory  # noqa: E402
from omalint.checks import CHECKS  # noqa: E402
from omalint.model import Context, Run  # noqa: E402


def context(name, **overrides):
    settings = dict(
        config_dir=FIXTURES / name / "omarchy",
        hypr_dir=FIXTURES / name / "hypr",
        omarchy_path=FIXTURES / "stock",
        live=False,
    )
    settings.update(overrides)
    return Context(**settings)


def temp_context(root, **overrides):
    """A context over root/omarchy and root/hypr that uses the stock fixture as the Omarchy install."""
    settings = dict(
        config_dir=Path(root) / "omarchy",
        hypr_dir=Path(root) / "hypr",
        omarchy_path=FIXTURES / "stock",
        live=False,
    )
    settings.update(overrides)
    return Context(**settings)


def run_check(check_name, ctx):
    return CHECKS[check_name].check(ctx, inventory.build(ctx))


def pairs(result):
    return {(f.code, f.subject) for f in result.findings}


def find(result, code, subject=None):
    matches = [f for f in result.findings if f.code == code and (subject is None or f.subject == subject)]
    if len(matches) != 1:
        found = sorted((f.code, f.subject) for f in result.findings)
        raise AssertionError(f"expected exactly one {code}/{subject}, got {len(matches)} in {found}")
    return matches[0]


def directory_args(config_dir, hypr_dir, omarchy_path=None):
    return [
        "--config-dir", str(config_dir),
        "--hypr-dir", str(hypr_dir),
        "--omarchy-path", str(omarchy_path or FIXTURES / "stock"),
    ]


def fixture_args(name):
    return directory_args(FIXTURES / name / "omarchy", FIXTURES / name / "hypr")


def cli(*args):
    return subprocess.run(
        [sys.executable, "-B", str(CLI), *map(str, args)],
        capture_output=True, text=True, stdin=subprocess.DEVNULL, timeout=120,
    )


def good_manifest(plugin_id="acme.x", **changes):
    manifest = {
        "schemaVersion": 1,
        "id": plugin_id,
        "name": "Test plugin",
        "version": "1.0.0",
        "author": "Acme",
        "description": "Test plugin",
        "kinds": ["bar-widget"],
        "entryPoints": {"barWidget": "Widget.qml"},
    }
    manifest.update(changes)
    return manifest


def write_plugin(config_dir, folder, manifest=None, files=("Widget.qml",)):
    """Create plugins/<folder> with a manifest (a dict, or raw text) and stub QML files."""
    directory = Path(config_dir) / "plugins" / folder
    directory.mkdir(parents=True, exist_ok=True)
    if manifest is None:
        manifest = good_manifest(folder)
    text = manifest if isinstance(manifest, str) else json.dumps(manifest, indent=2)
    (directory / "manifest.json").write_text(text, encoding="utf-8")
    for name in files:
        (directory / name).write_text("import QtQuick\n\nItem {}\n", encoding="utf-8")
    return directory


def write_shell_json(config_dir, value):
    """Write shell.json from a dict, or from raw text when the test needs invalid JSON."""
    Path(config_dir).mkdir(parents=True, exist_ok=True)
    text = value if isinstance(value, str) else json.dumps(value, indent=2)
    path = Path(config_dir) / "shell.json"
    path.write_text(text, encoding="utf-8")
    return path


def snapshot(root):
    """{relative path: sha256 or "dir"} for everything under root."""
    state = {}
    for dirpath, dirnames, filenames in os.walk(root):
        for name in dirnames:
            state[os.path.relpath(os.path.join(dirpath, name), root)] = "dir"
        for name in filenames:
            full = os.path.join(dirpath, name)
            with open(full, "rb") as stream:
                state[os.path.relpath(full, root)] = hashlib.sha256(stream.read()).hexdigest()
    return state


class FakeRun:
    """Stands in for Context.run. Rules are (argv prefix, Run); the first match answers, else "missing".

    calls holds each argv; handed holds, call for call, the cwd and input that went in beside it.
    """

    def __init__(self, *rules):
        self.rules = [(tuple(prefix), result) for prefix, result in rules]
        self.calls = []
        self.handed = []

    def __call__(self, argv, timeout=5.0, env=None, cwd=None, input=None):
        argv = list(argv)
        self.calls.append(argv)
        self.handed.append({"cwd": cwd, "input": input})
        for prefix, result in self.rules:
            if tuple(argv[:len(prefix)]) == prefix:
                return result
        return Run("missing")

    def calls_to(self, command):
        return [argv for argv in self.calls if argv[0] == command]


class Helpers:
    """Mixin for TestCase subclasses."""

    def tempdir(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        return Path(directory.name)

    def assertFindings(self, result, expected):
        """The result holds exactly the expected {(code, subject): severity} findings."""
        actual = sorted((f.code, f.subject, f.severity) for f in result.findings)
        wanted = sorted((code, subject, severity) for (code, subject), severity in expected.items())
        self.assertEqual(actual, wanted)
