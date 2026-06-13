import json
import os

import pytest
from PIL import Image

from virtual_printer import VirtualPrinter


class TestVirtualPrinterId:
    def test_basic_name(self):
        vp = VirtualPrinter("Office", "/tmp/test")
        assert vp.id == "virtual:Office"

    def test_spaces_replaced_with_underscores(self):
        vp = VirtualPrinter("My Printer", "/tmp/test")
        assert vp.id == "virtual:My_Printer"

    def test_parentheses_removed(self):
        vp = VirtualPrinter("Office (2nd Floor)", "/tmp/test")
        assert vp.id == "virtual:Office_2nd_Floor"

    def test_virtual_prefix(self):
        vp = VirtualPrinter("Printer", "/tmp/test")
        assert vp.id.startswith("virtual:")

    def test_slashes_sanitized(self):
        # Slashes would split the settings route path — must not survive. (#42)
        vp = VirtualPrinter("Floor/2", "/tmp/test")
        assert vp.id == "virtual:Floor_2"

    def test_dots_sanitized(self):
        vp = VirtualPrinter("v2.0 Printer", "/tmp/test")
        assert vp.id == "virtual:v2_0_Printer"

    def test_unicode_letters_preserved(self):
        # Unicode letters are \w and %-encode fine in a URL path.
        vp = VirtualPrinter("Drucker Büro", "/tmp/test")
        assert vp.id == "virtual:Drucker_Büro"

    def test_emoji_stripped(self):
        vp = VirtualPrinter("Printer 🖨️", "/tmp/test")
        assert vp.id == "virtual:Printer"

    def test_empty_name_falls_back(self):
        vp = VirtualPrinter("", "/tmp/test")
        assert vp.id == "virtual:printer"


class TestVirtualPrinterExplicitId:
    def test_explicit_id_overrides_name(self):
        vp = VirtualPrinter("Office (2nd Floor)", "/tmp/test", printer_id="office")
        assert vp.id == "virtual:office"

    def test_explicit_id_is_decoupled_from_display_name(self):
        # Renaming the display name must not change the id.
        vp = VirtualPrinter("Renamed", "/tmp/test", printer_id="office")
        assert vp.id == "virtual:office"
        assert vp.display_name == "Renamed (Virtual)"

    def test_from_config_honors_id_and_output(self):
        vp = VirtualPrinter.from_config(
            {"name": "X", "path": "/tmp/test", "output": "both", "id": "x1"}
        )
        assert vp.id == "virtual:x1"
        assert vp.output_mode == "both"

    def test_from_config_without_id_slugs_name(self):
        vp = VirtualPrinter.from_config({"name": "Floor/2", "path": "/tmp/test"})
        assert vp.id == "virtual:Floor_2"


class TestVirtualPrinterDisplayName:
    def test_virtual_suffix(self):
        vp = VirtualPrinter("Office", "/tmp/test")
        assert vp.display_name == "Office (Virtual)"

    def test_preserves_original_name(self):
        vp = VirtualPrinter("My Fancy Printer", "/tmp/test")
        assert vp.display_name == "My Fancy Printer (Virtual)"


class TestVirtualPrinterInit:
    def test_creates_output_directory(self, tmp_output_dir):
        assert not os.path.exists(tmp_output_dir)
        VirtualPrinter("Test", tmp_output_dir)
        assert os.path.isdir(tmp_output_dir)

    def test_existing_directory_ok(self, tmp_path):
        output_dir = str(tmp_path / "existing")
        os.makedirs(output_dir)
        # Should not raise
        VirtualPrinter("Test", output_dir)
        assert os.path.isdir(output_dir)


class TestVirtualPrinterOutputMode:
    def test_default_output_mode(self, tmp_output_dir):
        vp = VirtualPrinter("Test", tmp_output_dir)
        assert vp.output_mode == "image"

    def test_custom_output_mode(self, tmp_output_dir):
        vp = VirtualPrinter("Test", tmp_output_dir, output_mode="json")
        assert vp.output_mode == "json"

    def test_both_output_mode(self, tmp_output_dir):
        vp = VirtualPrinter("Test", tmp_output_dir, output_mode="both")
        assert vp.output_mode == "both"

    def test_invalid_output_mode_raises(self, tmp_output_dir):
        with pytest.raises(ValueError, match="Invalid output_mode 'img'"):
            VirtualPrinter("Test", tmp_output_dir, output_mode="img")


class TestVirtualPrinterSavePreview:
    def test_saves_png_file(self, tmp_output_dir):
        vp = VirtualPrinter("Test", tmp_output_dir)
        bitmap = Image.new("RGB", (200, 50), color="white")
        filepath = vp.save_preview(bitmap)

        assert os.path.isfile(filepath)
        assert filepath.endswith(".png")

    def test_returns_filepath_in_output_dir(self, tmp_output_dir):
        vp = VirtualPrinter("Test", tmp_output_dir)
        bitmap = Image.new("RGB", (200, 50), color="white")
        filepath = vp.save_preview(bitmap)

        assert filepath.startswith(tmp_output_dir)

    def test_saved_image_is_valid_color_png(self, tmp_output_dir):
        vp = VirtualPrinter("Test", tmp_output_dir)
        bitmap = Image.new("RGB", (200, 50), color="red")
        filepath = vp.save_preview(bitmap)

        saved = Image.open(filepath)
        assert saved.size == (200, 50)
        assert saved.mode == "RGB"

    def test_multiple_saves_create_unique_files(self, tmp_output_dir):
        vp = VirtualPrinter("Test", tmp_output_dir)
        bitmap = Image.new("RGB", (200, 50), color="white")

        path1 = vp.save_preview(bitmap)
        path2 = vp.save_preview(bitmap)

        assert path1 != path2
        assert os.path.isfile(path1)
        assert os.path.isfile(path2)


class TestVirtualPrinterSaveJson:
    def test_saves_json_file(self, tmp_output_dir):
        vp = VirtualPrinter("Test", tmp_output_dir)
        widgets = [{"type": "text", "text": "Hello"}]
        settings = {"tapeSizeMm": 12}
        filepath = vp.save_json(widgets, settings)

        assert os.path.isfile(filepath)
        assert filepath.endswith(".json")

    def test_json_contains_widgets_and_settings(self, tmp_output_dir):
        vp = VirtualPrinter("Test", tmp_output_dir)
        widgets = [{"type": "text", "text": "Hello"}]
        settings = {"tapeSizeMm": 12, "marginPx": 56}
        filepath = vp.save_json(widgets, settings)

        with open(filepath) as f:
            data = json.load(f)
        assert data["widgets"] == widgets
        assert data["settings"] == settings

    def test_returns_filepath_in_output_dir(self, tmp_output_dir):
        vp = VirtualPrinter("Test", tmp_output_dir)
        filepath = vp.save_json([{"type": "text", "text": "Hi"}], {})

        assert filepath.startswith(tmp_output_dir)


class TestVirtualPrinterSave:
    def _make_bitmap(self):
        return Image.new("RGB", (200, 50), color="blue")

    def test_image_mode_saves_only_png(self, tmp_output_dir):
        vp = VirtualPrinter("Test", tmp_output_dir, output_mode="image")
        paths = vp.save(self._make_bitmap(), [{"type": "text", "text": "Hi"}], {})

        assert len(paths) == 1
        assert paths[0].endswith(".png")

    def test_json_mode_saves_only_json(self, tmp_output_dir):
        vp = VirtualPrinter("Test", tmp_output_dir, output_mode="json")
        paths = vp.save(self._make_bitmap(), [{"type": "text", "text": "Hi"}], {})

        assert len(paths) == 1
        assert paths[0].endswith(".json")

    def test_both_mode_saves_png_and_json(self, tmp_output_dir):
        vp = VirtualPrinter("Test", tmp_output_dir, output_mode="both")
        paths = vp.save(self._make_bitmap(), [{"type": "text", "text": "Hi"}], {})

        assert len(paths) == 2
        extensions = {os.path.splitext(p)[1] for p in paths}
        assert extensions == {".png", ".json"}

    def test_all_saved_files_exist(self, tmp_output_dir):
        vp = VirtualPrinter("Test", tmp_output_dir, output_mode="both")
        paths = vp.save(self._make_bitmap(), [{"type": "text", "text": "Hi"}], {})

        for path in paths:
            assert os.path.isfile(path)
