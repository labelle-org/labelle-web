import json
import os

from config import get_virtual_printers


class TestGetVirtualPrinters:
    def _set_env(self, value):
        os.environ["VIRTUAL_PRINTERS"] = value

    def _clear_env(self):
        os.environ.pop("VIRTUAL_PRINTERS", None)

    def teardown_method(self):
        self._clear_env()

    def test_valid_config(self):
        config = [{"name": "Office", "path": "/tmp/office"}]
        self._set_env(json.dumps(config))
        result = get_virtual_printers()
        assert len(result) == 1
        assert result[0]["name"] == "Office"
        assert result[0]["path"] == "/tmp/office"

    def test_multiple_printers(self):
        config = [
            {"name": "Printer A", "path": "/tmp/a"},
            {"name": "Printer B", "path": "/tmp/b"},
        ]
        self._set_env(json.dumps(config))
        result = get_virtual_printers()
        assert len(result) == 2

    def test_explicit_id_is_kept(self):
        config = [{"id": "office", "name": "Office (2nd Floor)", "path": "/tmp/o"}]
        self._set_env(json.dumps(config))
        result = get_virtual_printers()
        assert len(result) == 1
        assert result[0]["id"] == "office"

    def test_invalid_explicit_id_is_skipped(self):
        config = [{"id": "bad/id", "name": "Office", "path": "/tmp/o"}]
        self._set_env(json.dumps(config))
        assert get_virtual_printers() == []

    def test_colliding_derived_ids_skip_the_later(self):
        # Both names slug to virtual:Office_Floor_2 — keep the first only.
        config = [
            {"name": "Office Floor 2", "path": "/tmp/a"},
            {"name": "Office (Floor 2)", "path": "/tmp/b"},
        ]
        self._set_env(json.dumps(config))
        result = get_virtual_printers()
        assert len(result) == 1
        assert result[0]["path"] == "/tmp/a"

    def test_colliding_explicit_id_skips_the_later(self):
        config = [
            {"id": "shared", "name": "A", "path": "/tmp/a"},
            {"id": "shared", "name": "B", "path": "/tmp/b"},
        ]
        self._set_env(json.dumps(config))
        result = get_virtual_printers()
        assert len(result) == 1
        assert result[0]["name"] == "A"

    def test_empty_env_var(self):
        self._set_env("")
        result = get_virtual_printers()
        assert result == []

    def test_unset_env_var(self):
        self._clear_env()
        result = get_virtual_printers()
        assert result == []

    def test_whitespace_only_env_var(self):
        self._set_env("   ")
        result = get_virtual_printers()
        assert result == []

    def test_invalid_json(self):
        self._set_env("not json at all")
        result = get_virtual_printers()
        assert result == []

    def test_non_array_json_object(self):
        self._set_env('{"name": "test"}')
        result = get_virtual_printers()
        assert result == []

    def test_non_array_json_string(self):
        self._set_env('"just a string"')
        result = get_virtual_printers()
        assert result == []

    def test_missing_name_key(self):
        self._set_env(json.dumps([{"path": "/tmp/test"}]))
        result = get_virtual_printers()
        assert result == []

    def test_missing_path_key(self):
        self._set_env(json.dumps([{"name": "Test"}]))
        result = get_virtual_printers()
        assert result == []

    def test_non_dict_entries_skipped(self):
        self._set_env(json.dumps(["string_entry", 42, None]))
        result = get_virtual_printers()
        assert result == []

    def test_mixed_valid_and_invalid(self):
        config = [
            {"name": "Good", "path": "/tmp/good"},
            {"bad": "entry"},
            {"name": "Also Good", "path": "/tmp/also"},
        ]
        self._set_env(json.dumps(config))
        result = get_virtual_printers()
        assert len(result) == 2
        assert result[0]["name"] == "Good"
        assert result[1]["name"] == "Also Good"

    def test_output_field_defaults_to_image(self):
        config = [{"name": "Test", "path": "/tmp/test"}]
        self._set_env(json.dumps(config))
        result = get_virtual_printers()
        assert result[0]["output"] == "image"

    def test_output_field_image_accepted(self):
        config = [{"name": "Test", "path": "/tmp/test", "output": "image"}]
        self._set_env(json.dumps(config))
        result = get_virtual_printers()
        assert result[0]["output"] == "image"

    def test_output_field_json_accepted(self):
        config = [{"name": "Test", "path": "/tmp/test", "output": "json"}]
        self._set_env(json.dumps(config))
        result = get_virtual_printers()
        assert result[0]["output"] == "json"

    def test_output_field_both_accepted(self):
        config = [{"name": "Test", "path": "/tmp/test", "output": "both"}]
        self._set_env(json.dumps(config))
        result = get_virtual_printers()
        assert result[0]["output"] == "both"

    def test_invalid_output_field_skipped(self):
        config = [{"name": "Test", "path": "/tmp/test", "output": "pdf"}]
        self._set_env(json.dumps(config))
        result = get_virtual_printers()
        assert result == []
