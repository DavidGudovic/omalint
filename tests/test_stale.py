import os
import shutil
import subprocess
import unittest

from helpers import FakeRun, Helpers, context, find, run_check, temp_context, write_plugin

from omalint.checks import stale
from omalint.model import Run

HAVE_GIT = shutil.which("git") is not None


class StripCommentsTests(unittest.TestCase):
    def test_line_comment_is_blanked(self):
        out = stale.strip_comments("a // note\nb")
        self.assertNotIn("note", out)
        self.assertTrue(out.startswith("a "))

    def test_block_comment_is_blanked(self):
        out = stale.strip_comments("a /* one\ntwo */ b")
        self.assertNotIn("one", out)
        self.assertNotIn("two", out)
        self.assertTrue(out.endswith(" b"))

    def test_string_containing_slashes_is_kept(self):
        text = 'const url = "http://x"\n'
        self.assertEqual(stale.strip_comments(text), text)

    def test_line_count_and_length_are_preserved(self):
        text = "a // one\n/* two\nthree */\nb\n"
        out = stale.strip_comments(text)
        self.assertEqual(out.count("\n"), text.count("\n"))
        self.assertEqual(len(out), len(text))


class ReferencesTests(unittest.TestCase):
    def found(self, text):
        return {(kind, target) for kind, _, target in stale.references(text)}

    def test_import_statement(self):
        self.assertEqual(self.found('import "lib/A.js" as A\n'), {("import", "lib/A.js")})

    def test_javascript_dot_import(self):
        self.assertEqual(self.found('.import "b.js" as B\n'), {("import", "b.js")})

    def test_resolved_url(self):
        self.assertEqual(self.found('x: Qt.resolvedUrl("icons/a.svg")'), {("resolvedUrl", "icons/a.svg")})

    def test_source_property(self):
        self.assertEqual(self.found('Image { source: "img/a.png" }'), {("source", "img/a.png")})

    def test_reference_carries_its_line_number(self):
        self.assertEqual(stale.references('\n\nimport "a.js" as A\n'), [("import", 3, "a.js")])

    def test_commented_out_references_are_ignored(self):
        text = '// import "a.js" as A\n/* source: "b.png" */\n'
        self.assertEqual(stale.references(text), [])

    def test_urls_with_a_scheme_are_ignored(self):
        text = 'source: "https://example.com/a.png"\nsource: "qrc:/a.png"\nsource: "image://theme/a"\n'
        self.assertEqual(stale.references(text), [])

    def test_absolute_paths_are_ignored(self):
        self.assertEqual(stale.references('source: "/usr/share/a.png"\n'), [])

    def test_source_without_an_asset_extension_is_ignored(self):
        self.assertEqual(stale.references('source: "inbox"\n'), [])


class MissingFileFixtureTests(Helpers, unittest.TestCase):
    def test_broken_fixture_reports_only_the_dangling_plugin(self):
        result = run_check("stale", context("broken"))
        self.assertFindings(result, {("stale.missing-file", "acme.brokenref"): "error"})

    def test_message_lists_the_missing_files_only(self):
        message = find(run_check("stale", context("broken")), "stale.missing-file", "acme.brokenref").message
        self.assertIn("lib/Missing.js", message)
        self.assertIn("icons/gone.svg", message)
        for text in ("Commented", "example.com", "in-a-string"):
            with self.subTest(text=text):
                self.assertNotIn(text, message)

    def test_healthy_fixture_has_no_findings(self):
        self.assertFindings(run_check("stale", context("healthy")), {})


def git(directory, *args):
    env = {k: v for k, v in os.environ.items() if not k.startswith("GIT_")}
    env.update(GIT_CONFIG_NOSYSTEM="1", GIT_CONFIG_GLOBAL=os.devnull)
    command = ["git", "-c", "user.name=Test", "-c", "user.email=test@example.com", "-c", "commit.gpgsign=false",
               "-C", str(directory), *args]
    return subprocess.run(command, check=True, capture_output=True, text=True, env=env).stdout


@unittest.skipUnless(HAVE_GIT, "git is not installed")
class GitCheckoutTests(Helpers, unittest.TestCase):
    def setUp(self):
        self.ctx = temp_context(self.tempdir())
        self.plugin = write_plugin(self.ctx.config_dir, "acme.x")
        git(self.plugin, "init", "-q")
        git(self.plugin, "add", ".")
        git(self.plugin, "commit", "-q", "-m", "initial")

    def edit_and_add_a_file(self):
        with open(self.plugin / "Widget.qml", "a", encoding="utf-8") as stream:
            stream.write("// local edit\n")
        (self.plugin / "notes.txt").write_text("mine\n", encoding="utf-8")

    def test_clean_checkout_has_no_local_changes(self):
        self.assertFindings(run_check("stale", self.ctx), {})

    def test_the_note_counts_the_checkouts_compared(self):
        self.assertEqual(
            run_check("stale", self.ctx).notes, ["1 git checkout compared with their last commit (no network)."]
        )

    def test_changed_and_untracked_files_are_reported(self):
        self.edit_and_add_a_file()
        result = run_check("stale", self.ctx)
        self.assertFindings(result, {("stale.local-changes", "acme.x"): "warn"})
        message = find(result, "stale.local-changes", "acme.x").message
        self.assertIn("Widget.qml", message)
        self.assertIn("notes.txt", message)

    def test_advice_for_edited_files_keeps_updates_possible(self):
        self.edit_and_add_a_file()
        finding = find(run_check("stale", self.ctx), "stale.local-changes", "acme.x")
        # A fast-forward only fails when the update touches the edited file, and a
        # local commit would block every later update, so neither may be claimed or advised.
        self.assertNotIn("cannot fast-forward", finding.message)
        self.assertNotIn("commit", finding.fix)
        self.assertIn("stash", finding.fix)
        self.assertIn("restore", finding.fix)

    def test_untracked_files_alone_get_their_own_advice(self):
        (self.plugin / "notes.txt").write_text("mine\n", encoding="utf-8")
        finding = find(run_check("stale", self.ctx), "stale.local-changes", "acme.x")
        self.assertIn("1 untracked (notes.txt)", finding.message)
        self.assertNotIn("restore", finding.fix)
        self.assertNotIn("stash", finding.fix)

    def test_running_the_check_does_not_touch_the_repository(self):
        self.edit_and_add_a_file()
        os.utime(self.plugin / "manifest.json", (1_000_000_000, 1_000_000_000))
        index = self.plugin / ".git" / "index"

        def state():
            status = git(self.plugin, "--no-optional-locks", "status", "--porcelain")
            return status, index.stat().st_mtime_ns, index.read_bytes()

        before = state()
        run_check("stale", self.ctx)
        self.assertEqual(state(), before)


class NoCheckoutTests(Helpers, unittest.TestCase):
    def test_without_plugins_the_note_says_none_were_installed_with_git(self):
        result = run_check("stale", temp_context(self.tempdir()))
        self.assertEqual(result.notes, ["No plugins were installed with git."])

    def test_plugins_without_a_git_folder_get_the_same_note(self):
        ctx = temp_context(self.tempdir())
        write_plugin(ctx.config_dir, "acme.x")
        self.assertEqual(run_check("stale", ctx).notes, ["No plugins were installed with git."])

    def test_the_fixtures_without_checkouts_get_the_same_note(self):
        for name in ("healthy", "broken"):
            with self.subTest(name=name):
                self.assertEqual(run_check("stale", context(name)).notes, ["No plugins were installed with git."])


class GitUnavailableTests(Helpers, unittest.TestCase):
    def test_checkout_that_git_cannot_report_on_gives_a_note_not_a_finding(self):
        root = self.tempdir()
        ctx = temp_context(root, run=FakeRun((("git",), Run("missing"))))
        (write_plugin(ctx.config_dir, "acme.x") / ".git").mkdir()
        result = run_check("stale", ctx)
        self.assertFindings(result, {})
        self.assertTrue(any("not checked for 1 checkout" in note and "git" in note for note in result.notes))

    def test_notes_do_not_claim_a_comparison_that_did_not_happen(self):
        root = self.tempdir()
        ctx = temp_context(root, run=FakeRun((("git",), Run("missing"))))
        (write_plugin(ctx.config_dir, "acme.x") / ".git").mkdir()
        result = run_check("stale", ctx)
        self.assertTrue(any(note.startswith("0 git checkouts compared") for note in result.notes))

    def test_a_checkout_that_git_could_not_report_on_still_counts_as_a_checkout(self):
        root = self.tempdir()
        ctx = temp_context(root, run=FakeRun((("git",), Run("missing"))))
        (write_plugin(ctx.config_dir, "acme.x") / ".git").mkdir()
        result = run_check("stale", ctx)
        self.assertEqual(len(result.notes), 2)
        self.assertNotIn("No plugins were installed with git.", result.notes)


if __name__ == "__main__":
    unittest.main()
