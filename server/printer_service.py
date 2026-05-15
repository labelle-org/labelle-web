import traceback

from PIL import Image

from labelle.lib.devices.device_manager import DeviceManager
from labelle.lib.devices.dymo_labeler import DymoLabeler

from config import get_virtual_printers
from label_builder import render_payload, render_preview
from virtual_printer import VirtualPrinter

# Note: libusb cache invalidation lives in `usb_power.power_on()`, not
# here. Scans rely on the cache being already-fresh from the last power
# transition. See `usb_power._invalidate_libusb_cache` for the rationale
# (resetting libusb in the read path triggers kernel hub auto-resume
# which re-energizes off ports).


def _find_virtual_printer(printer_id: str) -> VirtualPrinter:
    """Resolve a virtual printer by its ID (e.g. 'virtual:Office_Printer')."""
    for config in get_virtual_printers():
        vp = VirtualPrinter(config["name"], config["path"], output_mode=config.get("output", "image"))
        if vp.id == printer_id:
            return vp
    raise ValueError(f"Virtual printer not found: {printer_id}")


def _fallback_to_virtual(widgets: list[dict], settings: dict, upload_dir: str) -> None:
    """Print to the first configured virtual printer as a fallback."""
    virtual_printers_config = get_virtual_printers()
    if not virtual_printers_config:
        raise ValueError("No printers available (no USB printers found and no virtual printers configured)")

    config = virtual_printers_config[0]
    vp = VirtualPrinter(config["name"], config["path"], output_mode=config.get("output", "image"))
    preview_bitmap = render_preview(widgets, settings, upload_dir)
    vp.save(preview_bitmap, widgets, settings)


def list_printers() -> list[dict]:
    """List all available printers: real DYMO printers via USB and configured virtual printers.

    Never raises; returns partial results on scan failure.
    """
    printers: list[dict] = []

    # Add real USB printers
    try:
        device_manager = DeviceManager()
        device_manager.scan()

        for dev in device_manager.devices:
            parts = []
            if dev.manufacturer:
                parts.append(dev.manufacturer)
            if dev.product:
                parts.append(dev.product)
            if dev.serial_number:
                parts.append(f"(S/N: {dev.serial_number})")

            name = " ".join(parts) if parts else dev.usb_id

            printers.append({
                "id": dev.usb_id,
                "name": name,
                "vendorProductId": dev.vendor_product_id,
                "serialNumber": dev.serial_number,
            })
    except Exception:
        traceback.print_exc()

    # Add virtual printers from configuration
    try:
        for config in get_virtual_printers():
            virtual = VirtualPrinter(config["name"], config["path"], output_mode=config.get("output", "image"))
            printers.append({
                "id": virtual.id,
                "name": virtual.display_name,
                "vendorProductId": "virtual",
                "serialNumber": None,
            })
    except Exception:
        traceback.print_exc()

    return printers


def print_label(
    widgets: list[dict], settings: dict, upload_dir: str = "", printer_id: str | None = None
) -> None:
    """Resolve printer and dispatch a label for printing.

    Args:
        widgets: List of widget dictionaries to render
        settings: Label settings (tape size, margins, etc.)
        upload_dir: Directory where uploaded images are stored
        printer_id: Optional printer ID. Can be:
                   - USB ID (e.g. "Bus 001 Device 005: ID 0922:1234") for real printer
                   - virtual:name (e.g. "virtual:Office_Printer") for virtual printer
                   - None to auto-select first available real printer
    """
    # Virtual printer request
    if printer_id and printer_id.startswith("virtual:"):
        virtual_printer = _find_virtual_printer(printer_id)
        preview_bitmap = render_preview(widgets, settings, upload_dir)
        virtual_printer.save(preview_bitmap, widgets, settings)
        return

    # Try real USB printer
    device = None
    try:
        device_manager = DeviceManager()
        device_manager.scan()

        # TODO: Future improvement - store per-printer settings (tape size, margins, color)
        if printer_id:
            matching_devices = [dev for dev in device_manager.devices if dev.usb_id == printer_id]
            if not matching_devices:
                raise ValueError(f"Printer not found: {printer_id}")
            device = matching_devices[0]
        else:
            device = device_manager.find_and_select_device()
    except Exception:
        # If a specific printer was requested but not found, don't fall back
        if printer_id:
            raise
        # Auto-select: fall back to first virtual printer
        _fallback_to_virtual(widgets, settings, upload_dir)
        return

    device.setup()

    dymo_labeler = DymoLabeler(
        tape_size_mm=settings.get("tapeSizeMm", 12),
        device=device,
    )
    bitmap = render_payload(widgets, settings, upload_dir)
    dymo_labeler.print(bitmap)


def print_bitmap(
    bitmap: Image.Image, settings: dict, printer_id: str | None = None
) -> None:
    """Send a pre-rendered mode-"1" bitmap directly to the printer.

    Used for the cut-mark strip where MarginsRenderEngine's labeler-margin
    offset compensation would clip a narrow payload off-canvas. For virtual
    printers, the bitmap is saved as-is via save_preview (inverted to the
    intuitive black-on-white form first).
    """
    # Virtual printer
    if printer_id and printer_id.startswith("virtual:"):
        virtual_printer = _find_virtual_printer(printer_id)
        # Bitmap is mode "1" with 1=ink. Convert to a viewable PNG where
        # ink shows as black on white tape.
        viewable = bitmap.point(lambda v: 0 if v else 255, mode="L").convert("1")
        virtual_printer.save_preview(viewable)
        return

    # Real USB printer
    try:
        device_manager = DeviceManager()
        device_manager.scan()
        if printer_id:
            matching = [d for d in device_manager.devices if d.usb_id == printer_id]
            if not matching:
                raise ValueError(f"Printer not found: {printer_id}")
            device = matching[0]
        else:
            device = device_manager.find_and_select_device()
    except Exception:
        if printer_id:
            raise
        # No USB printer available — silently skip the cut mark rather
        # than crashing the surrounding batch.
        return

    device.setup()
    dymo_labeler = DymoLabeler(
        tape_size_mm=settings.get("tapeSizeMm", 12),
        device=device,
    )
    dymo_labeler.print(bitmap)
