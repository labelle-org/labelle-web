import os
import tempfile

import pytest
from PIL import Image

from label_builder import (
    DEFAULT_FONT_SCALE,
    _build_render_engines,
    mm_to_payload_px,
    preview_label,
)
from labelle.lib.constants import PIXELS_PER_MM
from labelle.lib.render_engines.barcode import BarcodeRenderEngine
from labelle.lib.render_engines.barcode_with_text import BarcodeWithTextRenderEngine
from labelle.lib.render_engines.picture import PictureRenderEngine
from labelle.lib.render_engines.qr import QrRenderEngine
from labelle.lib.render_engines.text import TextRenderEngine


@pytest.fixture
def upload_dir():
    """Temporary directory for test image uploads."""
    with tempfile.TemporaryDirectory() as d:
        yield d


@pytest.fixture
def sample_image(upload_dir):
    """Create a small PNG in the upload dir and return its filename."""
    filename = "test.png"
    img = Image.new("RGB", (10, 10), color="red")
    img.save(os.path.join(upload_dir, filename))
    return filename


class TestBuildRenderEngines:
    def test_text_widget_produces_text_engine(self):
        widgets = [{"type": "text", "text": "Hello", "id": "1"}]
        engines = _build_render_engines(widgets)
        assert len(engines) == 1
        assert isinstance(engines[0], TextRenderEngine)

    def test_qr_widget_produces_qr_engine(self):
        widgets = [{"type": "qr", "content": "https://example.com", "id": "1"}]
        engines = _build_render_engines(widgets)
        assert len(engines) == 1
        assert isinstance(engines[0], QrRenderEngine)

    def test_barcode_widget_produces_barcode_engine(self):
        widgets = [{"type": "barcode", "content": "12345", "id": "1"}]
        engines = _build_render_engines(widgets)
        assert len(engines) == 1
        assert isinstance(engines[0], BarcodeRenderEngine)

    def test_barcode_with_show_text_produces_barcode_with_text_engine(self):
        widgets = [
            {"type": "barcode", "content": "12345", "showText": True, "id": "1"}
        ]
        engines = _build_render_engines(widgets)
        assert len(engines) == 1
        assert isinstance(engines[0], BarcodeWithTextRenderEngine)

    def test_image_widget_with_valid_file(self, upload_dir, sample_image):
        widgets = [{"type": "image", "filename": sample_image, "id": "1"}]
        engines = _build_render_engines(widgets, upload_dir)
        assert len(engines) == 1
        assert isinstance(engines[0], PictureRenderEngine)

    def test_image_widget_with_missing_file_is_skipped(self, upload_dir):
        widgets = [{"type": "image", "filename": "nonexistent.png", "id": "1"}]
        engines = _build_render_engines(widgets, upload_dir)
        assert len(engines) == 0

    def test_empty_text_widget_is_skipped(self):
        widgets = [{"type": "text", "text": "", "id": "1"}]
        engines = _build_render_engines(widgets)
        assert len(engines) == 0

    def test_empty_qr_content_is_skipped(self):
        widgets = [{"type": "qr", "content": "", "id": "1"}]
        engines = _build_render_engines(widgets)
        assert len(engines) == 0

    def test_empty_barcode_content_is_skipped(self):
        widgets = [{"type": "barcode", "content": "", "id": "1"}]
        engines = _build_render_engines(widgets)
        assert len(engines) == 0

    def test_unknown_widget_type_is_skipped(self):
        widgets = [{"type": "unknown", "id": "1"}]
        engines = _build_render_engines(widgets)
        assert len(engines) == 0

    def test_multiple_widgets_produce_engines_in_order(self):
        widgets = [
            {"type": "text", "text": "First", "id": "1"},
            {"type": "qr", "content": "Second", "id": "2"},
            {"type": "barcode", "content": "12345", "id": "3"},
        ]
        engines = _build_render_engines(widgets)
        assert len(engines) == 3
        assert isinstance(engines[0], TextRenderEngine)
        assert isinstance(engines[1], QrRenderEngine)
        assert isinstance(engines[2], BarcodeRenderEngine)

    def test_invalid_barcode_type_falls_back_to_default(self):
        widgets = [
            {
                "type": "barcode",
                "content": "12345",
                "barcodeType": "invalid_type",
                "id": "1",
            }
        ]
        engines = _build_render_engines(widgets)
        assert len(engines) == 1
        assert isinstance(engines[0], BarcodeRenderEngine)


class TestFontScaleGuard:
    """A non-positive or non-numeric fontScale must not crash rendering.

    labelle computes the pixel font size as round(line_height * fontScale/100)
    and PIL's ImageFont rejects a size of 0, so a fontScale of 0 — which the UI
    produces the moment the Scale field is cleared (Number("") === 0), and which
    a malformed label file or direct API call can also carry — would otherwise
    500 the whole preview/print. We fall back to the default instead. See #49."""

    def test_zero_font_scale_falls_back_to_default(self):
        widgets = [{"type": "text", "text": "Hello", "id": "1", "fontScale": 0}]
        engines = _build_render_engines(widgets)
        assert engines[0].font_size_ratio == DEFAULT_FONT_SCALE / 100.0

    def test_negative_font_scale_falls_back_to_default(self):
        widgets = [{"type": "text", "text": "Hello", "id": "1", "fontScale": -20}]
        engines = _build_render_engines(widgets)
        assert engines[0].font_size_ratio == DEFAULT_FONT_SCALE / 100.0

    def test_non_numeric_font_scale_falls_back_to_default(self):
        widgets = [{"type": "text", "text": "Hello", "id": "1", "fontScale": None}]
        engines = _build_render_engines(widgets)
        assert engines[0].font_size_ratio == DEFAULT_FONT_SCALE / 100.0

    def test_nan_and_infinity_fall_back_to_default(self):
        # Flask's JSON parser accepts the NaN/Infinity literals, and both slip
        # past a plain `<= 0` check before exploding in PIL's int conversion.
        for bad in (float("nan"), float("inf"), float("-inf")):
            widgets = [{"type": "text", "text": "Hi", "id": "1", "fontScale": bad}]
            engines = _build_render_engines(widgets)
            assert engines[0].font_size_ratio == DEFAULT_FONT_SCALE / 100.0

    def test_preview_with_nan_font_scale_does_not_raise(self):
        widgets = [{"type": "text", "text": "Hi", "id": "1", "fontScale": float("nan")}]
        result = preview_label(widgets, {"tapeSizeMm": 6})
        assert result[:8] == b"\x89PNG\r\n\x1a\n"

    def test_valid_font_scale_is_preserved(self):
        widgets = [{"type": "text", "text": "Hello", "id": "1", "fontScale": 50}]
        engines = _build_render_engines(widgets)
        assert engines[0].font_size_ratio == 0.5

    def test_missing_font_scale_uses_default(self):
        widgets = [{"type": "text", "text": "Hello", "id": "1"}]
        engines = _build_render_engines(widgets)
        assert engines[0].font_size_ratio == DEFAULT_FONT_SCALE / 100.0

    def test_preview_with_zero_font_scale_does_not_raise(self):
        widgets = [{"type": "text", "text": "Hello", "id": "1", "fontScale": 0}]
        result = preview_label(widgets, {"tapeSizeMm": 12})
        assert result[:8] == b"\x89PNG\r\n\x1a\n"


class TestPreviewLabel:
    def test_returns_valid_png_bytes(self):
        widgets = [{"type": "text", "text": "Test", "id": "1"}]
        settings = {"tapeSizeMm": 12}
        result = preview_label(widgets, settings)
        # PNG magic bytes
        assert result[:8] == b"\x89PNG\r\n\x1a\n"

    def test_raises_value_error_for_no_renderable_widgets(self):
        widgets = [{"type": "text", "text": "", "id": "1"}]
        settings = {"tapeSizeMm": 12}
        with pytest.raises(ValueError, match="No renderable widgets"):
            preview_label(widgets, settings)

    def test_respects_settings(self):
        widgets = [{"type": "text", "text": "Test", "id": "1"}]
        small = preview_label(widgets, {"tapeSizeMm": 6})
        large = preview_label(widgets, {"tapeSizeMm": 19})
        # Different tape sizes should produce different image heights
        small_img = Image.open(__import__("io").BytesIO(small))
        large_img = Image.open(__import__("io").BytesIO(large))
        assert large_img.height > small_img.height


class TestMmToPayloadPx:
    def test_basic_conversion(self):
        result = mm_to_payload_px(10, 0)
        assert result == 10 * PIXELS_PER_MM

    def test_zero_mm_returns_zero(self):
        assert mm_to_payload_px(0, 0) == 0

    def test_margin_larger_than_total_returns_zero(self):
        # margin * 2 > mm * PIXELS_PER_MM → clamped to 0
        result = mm_to_payload_px(1, 1000)
        assert result == 0

    def test_margin_subtracted(self):
        margin = 10
        result = mm_to_payload_px(10, margin)
        assert result == (10 * PIXELS_PER_MM) - margin * 2
