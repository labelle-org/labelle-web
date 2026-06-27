import os
from io import BytesIO

from PIL import Image

from labelle.lib.constants import (
    DEFAULT_BARCODE_TYPE,
    DEFAULT_MARGIN_PX,
    PIXELS_PER_MM,
    BarcodeType,
    Direction,
)
from labelle.lib.devices.dymo_labeler import DymoLabeler
from labelle.lib.font_config import get_font_path
from labelle.lib.render_engines.barcode import BarcodeRenderEngine
from labelle.lib.render_engines.barcode_with_text import BarcodeWithTextRenderEngine
from labelle.lib.render_engines.horizontally_combined import (
    HorizontallyCombinedRenderEngine,
)
from labelle.lib.render_engines.print_payload import PrintPayloadRenderEngine
from labelle.lib.render_engines.print_preview import PrintPreviewRenderEngine
from labelle.lib.render_engines.picture import PictureRenderEngine
from labelle.lib.render_engines.qr import QrRenderEngine
from labelle.lib.render_engines.render_context import RenderContext
from labelle.lib.render_engines.render_engine import RenderEngine
from labelle.lib.render_engines.text import TextRenderEngine


def mm_to_payload_px(mm: float, margin: float) -> float:
    """Convert a length in mm to pixels of payload, subtracting margin from each side."""
    return max(0, (mm * PIXELS_PER_MM) - margin * 2)


# Text scale as a percentage; matches the client default (DEFAULT_FONT_SCALE in
# client/src/lib/constants.ts). Used as the fallback when a widget carries an
# unusable fontScale.
DEFAULT_FONT_SCALE = 90


def _font_size_ratio(widget: dict) -> float:
    """A text widget's fontScale (%) as a positive ratio for TextRenderEngine.

    labelle sizes the font as round(line_height * ratio) and PIL rejects a
    size of 0, so a non-positive or non-numeric fontScale would 500 the whole
    render. The UI produces exactly that the instant the Scale field is cleared
    (Number("") === 0), and a malformed label file or direct API call can carry
    it too — so fall back to the default rather than crash. See #49.
    """
    raw = widget.get("fontScale", DEFAULT_FONT_SCALE)
    try:
        scale = float(raw)
    except (TypeError, ValueError):
        scale = DEFAULT_FONT_SCALE
    if scale <= 0:
        scale = DEFAULT_FONT_SCALE
    return scale / 100.0


# Cut-mark pattern. CUT_MARK_ON pixels on, CUT_MARK_OFF off, repeated for the
# tape's full height. A column of dotted pixels painted into the trailing
# margin of each batch label (except the last) so the user can tear/cut
# between them. See paint_cut_mark_in_trailing_margin below for placement.
CUT_MARK_ON = 1
CUT_MARK_OFF = 2
CUT_MARK_WIDTH_PX = 1


def paint_cut_mark_in_trailing_margin(bitmap: Image.Image, margin_px: int) -> None:
    """Paint a dotted column INTO an already-rendered label bitmap, in the
    middle of its trailing-margin zone. Mutates the bitmap in place.

    Why this design: each labelle label bitmap is built as
    `[content][~14 mm trailing margin]` (visible margin + labeler-margin
    compensation). The next label in a batch has no leading blank
    (paste offset clips its first column). So adding a separate
    cut-mark print between labels lands the dots flush against the
    next label's content edge — visually flush, not centered.

    Painting INTO the trailing zone puts the dotted column inside the
    14 mm that's already there, no extra tape consumed, and the
    dot sits in the middle of the visible inter-label gap.

    Position: width - margin_px, which is roughly the centre of the
    right trailing-margin zone for a typical centre-justified label.

    Labelle payload convention: mode "1" with 1 = ink, 0 = no ink.
    """
    width, height = bitmap.size
    # margin_px == 0 is valid in the UI (SettingsBar allows it). Treat it
    # as "paint at the rightmost column" so the cut mark still appears
    # rather than silently doing nothing.
    if margin_px <= 0:
        x = width - CUT_MARK_WIDTH_PX
    else:
        x = width - margin_px
    # If the bitmap is narrower than the margin (degenerate input), there is
    # no trailing-margin zone to paint into — skip rather than landing the
    # dots in the content area.
    if x < 0 or x >= width:
        return
    pixels = bitmap.load()
    step = CUT_MARK_ON + CUT_MARK_OFF
    for y in range(0, height, step):
        for dy in range(CUT_MARK_ON):
            if y + dy < height:
                for ox in range(CUT_MARK_WIDTH_PX):
                    if x + ox < width:
                        pixels[x + ox, y + dy] = 1


def _build_render_engines(
    widgets: list[dict], upload_dir: str = "",
) -> list[RenderEngine]:
    """Convert a list of widget dicts into labelle RenderEngine instances."""
    engines: list[RenderEngine] = []
    for widget in widgets:
        widget_type = widget.get("type")

        if widget_type == "text":
            text = widget.get("text", "")
            if not text:
                continue
            font_path = get_font_path(style=widget.get("fontStyle", "regular"))
            engines.append(
                TextRenderEngine(
                    text_lines=text.split("\n"),
                    font_file_name=font_path,
                    frame_width_px=widget.get("frameWidthPx", 0),
                    font_size_ratio=_font_size_ratio(widget),
                    align=Direction(widget.get("align", "left")),
                )
            )

        elif widget_type == "qr":
            content = widget.get("content", "").strip()
            if content:
                engines.append(QrRenderEngine(content))

        elif widget_type == "barcode":
            content = widget.get("content", "").strip()
            if not content:
                continue
            barcode_type_str = widget.get("barcodeType", "code128")
            try:
                barcode_type = BarcodeType(barcode_type_str.lower())
            except ValueError:
                barcode_type = DEFAULT_BARCODE_TYPE

            if widget.get("showText", False):
                font_path = get_font_path(style="regular")
                engines.append(
                    BarcodeWithTextRenderEngine(
                        content=content,
                        font_file_name=font_path,
                        barcode_type=barcode_type,
                    )
                )
            else:
                engines.append(
                    BarcodeRenderEngine(content=content, barcode_type=barcode_type)
                )

        elif widget_type == "image":
            filename = widget.get("filename", "")
            if filename and upload_dir:
                picture_path = os.path.join(upload_dir, filename)
                if os.path.isfile(picture_path):
                    engines.append(PictureRenderEngine(picture_path=picture_path))

    return engines


def _render_label(
    dymo_labeler: DymoLabeler,
    render_engine: RenderEngine,
    settings: dict,
    justify: Direction,
    margin_px: float,
    min_payload_px: float,
    *,
    for_print: bool = False,
    show_margins: bool = False,
) -> Image.Image:
    """Render a label bitmap.

    Args:
        for_print: If True, renders the raw B&W payload for the printer.
                   If False, renders a color preview image.
        show_margins: If True, show margin indicators in the preview.
    """
    render_context = RenderContext(
        height_px=dymo_labeler.height_px,
        foreground_color=settings.get("foregroundColor", "black"),
        background_color=settings.get("backgroundColor", "white"),
        preview_show_margins=show_margins,
    )
    engine_cls = PrintPayloadRenderEngine if for_print else PrintPreviewRenderEngine
    output_engine = engine_cls(
        render_engine=render_engine,
        justify=justify,
        visible_horizontal_margin_px=margin_px,
        labeler_margin_px=dymo_labeler.labeler_margin_px,
        min_width_px=min_payload_px,
    )
    if for_print:
        bitmap, _ = output_engine.render_with_meta(render_context)
        return bitmap
    return output_engine.render(render_context)


def _prepare_render(
    widgets: list[dict], settings: dict, upload_dir: str = "",
) -> tuple[DymoLabeler, RenderEngine, Direction, float, float]:
    """Shared setup for rendering: build engines, parse settings, create labeler."""
    engines = _build_render_engines(widgets, upload_dir)
    if not engines:
        raise ValueError("No renderable widgets provided")

    render_engine = HorizontallyCombinedRenderEngine(engines)

    margin_px = settings.get("marginPx", DEFAULT_MARGIN_PX)
    min_length_mm = settings.get("minLengthMm", 0)
    min_payload_px = mm_to_payload_px(min_length_mm, margin_px)
    justify = Direction(settings.get("justify", "center"))

    dymo_labeler = DymoLabeler(tape_size_mm=settings.get("tapeSizeMm", 12))

    return dymo_labeler, render_engine, justify, margin_px, min_payload_px


def render_preview(
    widgets: list[dict], settings: dict, upload_dir: str = "", show_margins: bool = False,
) -> Image.Image:
    """Render a color preview image from widgets."""
    dymo_labeler, render_engine, justify, margin_px, min_payload_px = _prepare_render(
        widgets, settings, upload_dir
    )
    return _render_label(
        dymo_labeler, render_engine, settings, justify, margin_px, min_payload_px,
        show_margins=show_margins,
    )


def render_payload(
    widgets: list[dict], settings: dict, upload_dir: str = "",
) -> Image.Image:
    """Render a B&W payload image ready for printing."""
    dymo_labeler, render_engine, justify, margin_px, min_payload_px = _prepare_render(
        widgets, settings, upload_dir
    )
    return _render_label(
        dymo_labeler, render_engine, settings, justify, margin_px, min_payload_px,
        for_print=True,
    )


def preview_label(widgets: list[dict], settings: dict, upload_dir: str = "") -> bytes:
    """Build render engines from widgets and return a PNG preview as bytes."""
    bitmap = render_preview(
        widgets, settings, upload_dir,
        show_margins=settings.get("showMargins", True),
    )
    buf = BytesIO()
    bitmap.save(buf, format="PNG")
    return buf.getvalue()
