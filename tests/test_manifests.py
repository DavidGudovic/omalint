import os
import unittest

from helpers import Helpers, context, find, good_manifest, run_check, temp_context, write_plugin

from omalint import inventory

BROKEN = {
    ("manifest.invalid-json", "acme.badjson"): "error",
    ("manifest.folder-mismatch", "acme.dup-one"): "warn",
    ("manifest.folder-mismatch", "acme.dup-two"): "warn",
    ("manifest.unknown-kind", "acme.ghostentry"): "warn",
    ("manifest.entry-point-missing", "acme.ghostentry"): "error",
    ("manifest.kind-without-entry-point", "acme.ghostentry"): "warn",
    ("manifest.schema-version", "acme.noschema"): "error",
    ("manifest.missing-field", "acme.noschema"): "error",
    ("manifest.reserved-id", "acme.reserved"): "error",
    ("manifest.missing", "nomanifest"): "warn",
    ("manifest.id-collision", "acme.dup"): "error",
}


class BrokenFixtureTests(Helpers, unittest.TestCase):
    def setUp(self):
        self.ctx = context("broken")
        self.result = run_check("manifests", self.ctx)

    def test_reports_exactly_the_expected_findings(self):
        self.assertFindings(self.result, BROKEN)

    def test_missing_field_message_names_the_field(self):
        self.assertIn("version", find(self.result, "manifest.missing-field", "acme.noschema").message)

    def test_id_collision_message_names_both_folders(self):
        message = find(self.result, "manifest.id-collision", "acme.dup").message
        self.assertIn("acme.dup-one", message)
        self.assertIn("acme.dup-two", message)

    def test_nine_of_thirteen_folders_are_loadable(self):
        plugins = inventory.build(self.ctx).third_party
        self.assertEqual(len(plugins), 13)
        self.assertEqual(sum(p.loadable for p in plugins), 9)

    def test_the_unloadable_folders_are_the_rejected_ones(self):
        plugins = inventory.build(self.ctx).third_party
        rejected = {p.dir.name for p in plugins if not p.loadable}
        self.assertEqual(rejected, {"acme.badjson", "acme.noschema", "acme.reserved", "nomanifest"})


class HealthyFixtureTests(Helpers, unittest.TestCase):
    def test_no_findings(self):
        self.assertFindings(run_check("manifests", context("healthy")), {})


class ManifestRuleTests(Helpers, unittest.TestCase):
    def setUp(self):
        self.ctx = temp_context(self.tempdir())

    def check(self, manifest, folder="acme.x"):
        write_plugin(self.ctx.config_dir, folder, manifest)
        return run_check("manifests", self.ctx)

    def loadable(self, folder="acme.x"):
        return {p.dir.name: p.loadable for p in inventory.build(self.ctx).third_party}[folder]

    def test_symlink_inside_a_plugin_is_a_warning(self):
        directory = write_plugin(self.ctx.config_dir, "acme.x")
        os.symlink("Widget.qml", directory / "alias.qml")
        self.assertFindings(run_check("manifests", self.ctx), {("manifest.symlink", "acme.x"): "warn"})

    def test_boolean_schema_version_is_rejected(self):
        result = self.check(good_manifest(schemaVersion=True))
        self.assertFindings(result, {("manifest.schema-version", "acme.x"): "error"})
        self.assertFalse(self.loadable())

    def test_string_schema_version_is_rejected(self):
        result = self.check(good_manifest(schemaVersion="1"))
        self.assertFindings(result, {("manifest.schema-version", "acme.x"): "error"})
        self.assertFalse(self.loadable())

    def test_numeric_schema_version_one_is_accepted(self):
        self.assertFindings(self.check(good_manifest(schemaVersion=1)), {})
        self.assertTrue(self.loadable())

    def test_id_with_a_slash_is_rejected(self):
        result = self.check(good_manifest("a/b"))
        self.assertFindings(result, {("manifest.invalid-id", "acme.x"): "error"})
        self.assertFalse(self.loadable())

    def test_id_with_dot_dot_is_rejected(self):
        result = self.check(good_manifest("a..b"))
        self.assertFindings(result, {("manifest.invalid-id", "acme.x"): "error"})
        self.assertFalse(self.loadable())

    def test_id_with_a_space_only_warns_and_still_loads(self):
        result = self.check(good_manifest("acme bad"), folder="acme bad")
        self.assertFindings(result, {("manifest.invalid-id", "acme bad"): "warn"})
        self.assertTrue(self.loadable("acme bad"))

    def test_empty_kinds_list_is_rejected(self):
        result = self.check(good_manifest(kinds=[]))
        self.assertFindings(result, {("manifest.invalid-kinds", "acme.x"): "error"})
        self.assertFalse(self.loadable())

    def test_absolute_entry_point_is_unsafe(self):
        result = self.check(good_manifest(entryPoints={"barWidget": "/abs.qml"}))
        self.assertFindings(result, {("manifest.unsafe-entry-point", "acme.x"): "error"})
        self.assertFalse(self.loadable())

    def test_parent_directory_entry_point_is_unsafe(self):
        result = self.check(good_manifest(entryPoints={"barWidget": "../x.qml"}))
        self.assertFindings(result, {("manifest.unsafe-entry-point", "acme.x"): "error"})
        self.assertFalse(self.loadable())

    def test_default_section_must_be_left_center_or_right(self):
        result = self.check(good_manifest(barWidget={"defaultSection": "middle"}))
        self.assertFindings(result, {("manifest.invalid-default-section", "acme.x"): "error"})
        self.assertFalse(self.loadable())

    def test_manifest_that_is_a_json_array_is_not_an_object(self):
        result = self.check("[1, 2, 3]")
        self.assertFindings(result, {("manifest.not-object", "acme.x"): "error"})
        self.assertFalse(self.loadable())

    def test_stray_byte_inside_a_string_loads_as_it_does_in_the_shell(self):
        directory = write_plugin(self.ctx.config_dir, "acme.x")
        raw = (directory / "manifest.json").read_bytes().replace(b'"Test plugin"', b'"Caf\xe9"')
        (directory / "manifest.json").write_bytes(raw)
        self.assertFindings(run_check("manifests", self.ctx), {})
        self.assertTrue(self.loadable())

    def test_byte_order_mark_is_tolerated_as_it_is_by_the_shell(self):
        directory = write_plugin(self.ctx.config_dir, "acme.x")
        path = directory / "manifest.json"
        path.write_bytes(b"\xef\xbb\xbf" + path.read_bytes())
        self.assertFindings(run_check("manifests", self.ctx), {})
        self.assertTrue(self.loadable())

    def test_numeric_id_loads_under_its_string_form_with_a_warning(self):
        result = self.check(good_manifest(5), folder="5")
        self.assertFindings(result, {("manifest.invalid-id", "5"): "warn"})
        self.assertTrue(self.loadable("5"))
        self.assertEqual([p.id for p in inventory.build(self.ctx).third_party], ["5"])

    def test_file_that_is_not_text_at_all_is_invalid_json(self):
        directory = write_plugin(self.ctx.config_dir, "acme.x")
        (directory / "manifest.json").write_bytes(b"\xff\xfe\x00{")
        self.assertFindings(run_check("manifests", self.ctx), {("manifest.invalid-json", "acme.x"): "error"})

    def test_hidden_folders_and_plain_files_are_ignored(self):
        write_plugin(self.ctx.config_dir, "acme.x")
        plugins = self.ctx.plugins_dir
        (plugins / ".staging").mkdir()
        (plugins / ".staging" / "junk.txt").write_text("leftover", encoding="utf-8")
        (plugins / "notes.txt").write_text("not a plugin", encoding="utf-8")
        self.assertFindings(run_check("manifests", self.ctx), {})
        self.assertEqual([p.dir.name for p in inventory.build(self.ctx).third_party], ["acme.x"])

    def test_missing_plugins_directory_gives_no_findings(self):
        self.assertFalse(self.ctx.plugins_dir.exists())
        self.assertFindings(run_check("manifests", self.ctx), {})


if __name__ == "__main__":
    unittest.main()
