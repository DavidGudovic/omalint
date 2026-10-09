import sys
import unittest

from helpers import FakeRun, Helpers, context, find, run_check

from omalint.checks import deps
from omalint.model import Run


def requirements(body, heading="Requirements"):
    return deps.readme_requirements(f"# Plugin\n\n## {heading}\n\n{body}\n")


class ReadmeRequirementsTests(unittest.TestCase):
    def test_list_items_under_requirements_are_read(self):
        self.assertEqual(requirements("- `jq`\n- `curl`"), {"jq": False, "curl": False})

    def test_tokens_outside_the_section_are_ignored(self):
        text = "# Plugin\n\nUses `fzf` internally.\n\n## Requirements\n\n- `jq`\n\n## Usage\n\n- `curl`\n"
        self.assertEqual(deps.readme_requirements(text), {"jq": False})

    def test_fenced_code_blocks_are_ignored(self):
        body = "- `jq`\n\n```sh\n`wget` --help\n```\n"
        self.assertEqual(requirements(body), {"jq": False})

    def test_later_paragraphs_are_ignored_when_the_section_has_list_items(self):
        self.assertEqual(requirements("- `jq`\n\nRun `fzf` to see more."), {"jq": False})

    def test_prose_only_section_uses_its_first_paragraph(self):
        body = "You need `jq` and `curl` installed.\n\nAlso try `fzf`."
        self.assertEqual(requirements(body), {"jq": False, "curl": False})

    def test_optional_wording_marks_an_item_optional(self):
        self.assertEqual(requirements("- `jq`, optional"), {"jq": True})

    def test_only_for_wording_marks_an_item_optional(self):
        self.assertEqual(requirements("- `jq` is only for previews"), {"jq": True})

    def test_item_without_optional_wording_is_required(self):
        self.assertEqual(requirements("- `jq` for parsing"), {"jq": False})

    def test_optional_subheading_marks_its_items_optional(self):
        body = "- `jq`\n\n### Optional\n\n- `fzf`"
        self.assertEqual(requirements(body), {"jq": False, "fzf": True})

    def test_table_rows_are_read(self):
        body = "| Tool | Purpose |\n|------|---------|\n| `jq` | JSON |\n| `curl` | HTTP |"
        self.assertEqual(requirements(body), {"jq": False, "curl": False})

    def test_tokens_with_dots_are_ignored(self):
        self.assertEqual(requirements("- `shell.json`"), {})

    def test_uppercase_tokens_are_ignored(self):
        self.assertEqual(requirements("- `PATH`"), {})

    def test_home_relative_paths_are_ignored(self):
        self.assertEqual(requirements("- `~/.config/x`"), {})

    def test_bare_binary_directory_is_ignored(self):
        self.assertEqual(requirements("- `/usr/bin`"), {})

    def test_absolute_binary_path_is_kept(self):
        self.assertEqual(requirements("- `/usr/bin/mpv`"), {"/usr/bin/mpv": False})

    def test_multi_word_token_uses_its_first_word(self):
        self.assertEqual(requirements("- `gh auth login`"), {"gh": False})

    def test_dependencies_heading_counts(self):
        self.assertEqual(requirements("- `jq`", heading="Dependencies"), {"jq": False})

    def test_prerequisites_heading_counts(self):
        self.assertEqual(requirements("- `jq`", heading="Prerequisites"), {"jq": False})


class BrokenFixtureTests(Helpers, unittest.TestCase):
    def setUp(self):
        self.result = run_check("deps", context("broken"))

    def test_reports_exactly_the_expected_findings(self):
        self.assertFindings(self.result, {
            ("deps.missing", "acme.needs-tools"): "warn",
            ("deps.optional-missing", "acme.needs-tools"): "info",
        })

    def test_missing_names_the_manifest_and_readme_tools(self):
        message = find(self.result, "deps.missing", "acme.needs-tools").message
        self.assertIn("omalint-fixture-manifest-tool", message)
        self.assertIn("omalint-fixture-missing-tool", message)

    def test_missing_ignores_installed_unrelated_and_out_of_section_tools(self):
        message = find(self.result, "deps.missing", "acme.needs-tools").message
        for text in ("`sh`", "unrelated", "codeblock", "usage"):
            with self.subTest(text=text):
                self.assertNotIn(text, message)

    def test_optional_tool_is_only_a_note(self):
        message = find(self.result, "deps.optional-missing", "acme.needs-tools").message
        self.assertIn("omalint-fixture-optional-tool", message)


class HealthyFixtureTests(Helpers, unittest.TestCase):
    def test_only_an_optional_note(self):
        result = run_check("deps", context("healthy"))
        self.assertFindings(result, {("deps.optional-missing", "acme.clock-plus"): "info"})


class MissingTests(unittest.TestCase):
    def test_command_reported_missing_but_installed_as_a_package_is_present(self):
        fake = FakeRun((("sh",), Run("ok", 0, "foo\n")), (("pacman",), Run("ok", 0, "foo\n")))
        self.assertEqual(deps.missing(context("healthy", run=fake), ["foo"]), set())

    def test_command_stays_missing_when_pacman_is_unavailable(self):
        fake = FakeRun((("sh",), Run("ok", 0, "foo\n")), (("pacman",), Run("missing")))
        self.assertEqual(deps.missing(context("healthy", run=fake), ["foo"]), {"foo"})

    def test_absolute_path_that_does_not_exist_is_missing(self):
        fake = FakeRun()
        ctx = context("healthy", run=fake)
        self.assertEqual(deps.missing(ctx, ["/nonexistent/omalint-fixture-tool"]), {"/nonexistent/omalint-fixture-tool"})
        self.assertEqual(fake.calls, [])

    def test_absolute_path_that_exists_is_present(self):
        self.assertEqual(deps.missing(context("healthy", run=FakeRun()), [sys.executable]), set())


if __name__ == "__main__":
    unittest.main()
