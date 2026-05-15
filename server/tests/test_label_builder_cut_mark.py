"""Tests for the cut-mark trailing-margin painter.

The dot lives inside each batch label's existing trailing margin so no
extra tape is consumed; placement is `bitmap.width - margin_px`. These
tests lock in that contract.
"""

from PIL import Image

from label_builder import (
    CUT_MARK_OFF,
    CUT_MARK_ON,
    CUT_MARK_WIDTH_PX,
    paint_cut_mark_in_trailing_margin,
)


def _make_blank_payload(width: int = 200, height: int = 64) -> Image.Image:
    """Mode-"1" bitmap with everything = 0 (no ink, labelle convention)."""
    return Image.new("1", (width, height), 0)


class TestPaintCutMarkInTrailingMargin:
    def test_paints_at_width_minus_margin(self):
        bm = _make_blank_payload(width=200, height=64)
        paint_cut_mark_in_trailing_margin(bm, margin_px=56)

        # All ink should be on the same column.
        ink_cols = {x for x in range(bm.width) for y in range(bm.height) if bm.getpixel((x, y))}
        assert ink_cols == set(range(200 - 56, 200 - 56 + CUT_MARK_WIDTH_PX))

    def test_pattern_is_one_on_two_off(self):
        bm = _make_blank_payload(width=200, height=64)
        paint_cut_mark_in_trailing_margin(bm, margin_px=56)

        x = 200 - 56
        ink_rows = [y for y in range(bm.height) if bm.getpixel((x, y))]
        # 1 on, 2 off → rows 0, 3, 6, ..., 63 (every 3rd row)
        expected = list(range(0, bm.height, CUT_MARK_ON + CUT_MARK_OFF))
        assert ink_rows == expected

    def test_does_nothing_outside_trailing_margin(self):
        """Content area (x < width - margin_px) should stay untouched."""
        bm = _make_blank_payload(width=200, height=64)
        paint_cut_mark_in_trailing_margin(bm, margin_px=56)

        for x in range(0, 200 - 56):
            for y in range(bm.height):
                assert bm.getpixel((x, y)) == 0, f"unexpected ink at ({x}, {y})"

    def test_preserves_existing_ink(self):
        """Painting the cut mark must not erase the label's content."""
        bm = _make_blank_payload(width=200, height=64)
        # Plant some "content" ink in the leading half
        for x in range(10, 30):
            for y in range(20, 40):
                bm.putpixel((x, y), 1)

        paint_cut_mark_in_trailing_margin(bm, margin_px=56)

        for x in range(10, 30):
            for y in range(20, 40):
                assert bm.getpixel((x, y)) == 1, f"content erased at ({x}, {y})"

    def test_no_op_when_margin_larger_than_bitmap(self):
        """A degenerate input shouldn't crash or write out of bounds."""
        bm = _make_blank_payload(width=10, height=64)
        paint_cut_mark_in_trailing_margin(bm, margin_px=999)

        # Bitmap should still be blank — no ink anywhere.
        for x in range(bm.width):
            for y in range(bm.height):
                assert bm.getpixel((x, y)) == 0
