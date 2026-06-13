import logging
import traceback

from PIL import Image

from labelle.lib.devices.device_manager import DeviceManager, DeviceManagerNoDevices
from labelle.lib.devices.dymo_labeler import DymoLabeler

import usb_power
from config import get_virtual_printers
from label_builder import render_payload, render_preview
from virtual_printer import VirtualPrinter

logger = logging.getLogger(__name__)

# Libusb cache invalidation is normally driven by `usb_power.power_on()`, so
# scans rely on the cache being already-fresh from the last power transition.
# We refresh it from this read path in exactly one case — recovering a stale
# context after a re-enumeration (see `_list_real_printers`) — and only when
# uhubctl confirms the device is physically present. That gate is what keeps
# us from triggering the kernel hub auto-resume that would re-energize a
# deliberately powered-off port. See `usb_power.invalidate_libusb_cache`.


def _printer_id(dev) -> str:
    """Stable id for a real USB printer.

    Prefer the device serial number: it survives re-enumeration (replug,
    reboot, and this app's own USB power-cycling), whereas labelle's
    `usb_id` embeds the kernel-assigned Bus/Device address, which changes
    on every re-enumeration and would orphan that printer's saved settings.
    Fall back to `usb_id` only when the device reports no serial. See #40.

    Used both when listing printers and when resolving a print request's
    printer_id back to a device, so the two always agree.
    """
    serial = dev.serial_number
    if serial:
        return f"serial:{serial}"
    return dev.usb_id


def _find_virtual_printer(printer_id: str) -> VirtualPrinter:
    """Resolve a virtual printer by its ID (e.g. 'virtual:Office_Printer')."""
    for config in get_virtual_printers():
        vp = VirtualPrinter.from_config(config)
        if vp.id == printer_id:
            return vp
    raise ValueError(f"Virtual printer not found: {printer_id}")


def _fallback_to_virtual(widgets: list[dict], settings: dict, upload_dir: str) -> None:
    """Print to the first configured virtual printer as a fallback."""
    virtual_printers_config = get_virtual_printers()
    if not virtual_printers_config:
        raise ValueError("No printers available (no USB printers found and no virtual printers configured)")

    vp = VirtualPrinter.from_config(virtual_printers_config[0])
    preview_bitmap = render_preview(widgets, settings, upload_dir)
    vp.save(preview_bitmap, widgets, settings)


def _scan_real_printers() -> list[dict]:
    """Scan USB once and return real DYMO printers as dicts.

    Raises DeviceManagerNoDevices when the scan finds nothing.
    """
    device_manager = DeviceManager()
    device_manager.scan()

    printers: list[dict] = []
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
            "id": _printer_id(dev),
            "name": name,
            "vendorProductId": dev.vendor_product_id,
            "serialNumber": dev.serial_number,
        })
    return printers


def _list_real_printers() -> list[dict]:
    """Real USB DYMO printers, with stale-libusb-context recovery.

    In a long-lived process pyusb caches its libusb context. If the printer
    re-enumerates to a new bus address (replug, or our own USB power-cycle)
    after that context is built, the scan keeps coming back empty even though
    the device is physically attached. When that happens — empty scan but
    uhubctl still sees the DYMO — drop the cached context and rescan once so
    the device reappears without a process restart.

    Never raises; returns [] on any failure.
    """
    try:
        return _scan_real_printers()
    except DeviceManagerNoDevices:
        pass  # genuinely absent, or a stale context — disambiguate below
    except Exception:
        traceback.print_exc()
        return []

    # The scan found nothing. Only refresh the cache when uhubctl confirms the
    # DYMO is still physically attached: that both targets the stale-context
    # case and guarantees we never resume a deliberately powered-off port
    # (where uhubctl sees no device, so this gate is False).
    if usb_power.printer_attached():
        logger.info(
            "USB scan empty but uhubctl still sees the DYMO; refreshing the "
            "stale libusb context and rescanning."
        )
        usb_power.invalidate_libusb_cache()
        try:
            return _scan_real_printers()
        except Exception:
            pass  # recovery didn't help; fall through to the empty result

    # Expected state when no DYMO is plugged in (e.g. local dev or a host with
    # only virtual printers). Surface as INFO without a traceback so the
    # console stays clean across plug/unplug cycles.
    logger.info("No USB DYMO printers detected.")
    return []


def list_printers() -> list[dict]:
    """List all available printers: real DYMO printers via USB and configured virtual printers.

    Never raises; returns partial results on scan failure.
    """
    printers: list[dict] = _list_real_printers()

    # Add virtual printers from configuration
    try:
        for config in get_virtual_printers():
            virtual = VirtualPrinter.from_config(config)
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
        printer_id: Optional printer ID (see _printer_id). Can be:
                   - "serial:<sn>" for a real printer reporting a serial
                     (falls back to "Bus NNN Device NNN: ID vvvv:pppp" if not)
                   - "virtual:<name>" for a virtual printer
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

        if printer_id:
            matching_devices = [dev for dev in device_manager.devices if _printer_id(dev) == printer_id]
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


def _bitmap_to_viewable(bitmap: Image.Image) -> Image.Image:
    """Convert a labelle-convention mode-"1" payload (1 = ink) to a viewable
    black-on-white image suitable for a virtual printer's PNG save."""
    return bitmap.point(lambda v: 0 if v else 255, mode="L").convert("1")


def _fallback_to_virtual_bitmap(
    bitmap: Image.Image, widgets: list[dict], settings: dict
) -> None:
    """Print a pre-rendered bitmap to the first configured virtual printer."""
    virtual_printers_config = get_virtual_printers()
    if not virtual_printers_config:
        raise ValueError(
            "No printers available (no USB printers found and no virtual printers configured)"
        )
    vp = VirtualPrinter.from_config(virtual_printers_config[0])
    vp.save(_bitmap_to_viewable(bitmap), widgets, settings)


def print_bitmap(
    bitmap: Image.Image,
    settings: dict,
    printer_id: str | None = None,
    widgets: list[dict] | None = None,
) -> None:
    """Send a pre-rendered mode-"1" bitmap to the printer.

    Used by callers that need to post-process a rendered payload before
    sending it (the cut-mark path mutates the bitmap to inject a dotted
    column into the trailing margin), so going back through
    `render_payload()` inside `print_label()` would discard that change.

    Behaviour mirrors `print_label()` apart from skipping the render step:
    virtual printers respect their configured `output_mode` (image / json
    / both) and an auto-select USB failure falls back to the first
    virtual printer rather than silently dropping the print.
    """
    widgets = widgets or []

    # Virtual printer
    if printer_id and printer_id.startswith("virtual:"):
        virtual_printer = _find_virtual_printer(printer_id)
        virtual_printer.save(_bitmap_to_viewable(bitmap), widgets, settings)
        return

    # Try real USB printer
    device = None
    try:
        device_manager = DeviceManager()
        device_manager.scan()
        if printer_id:
            matching = [d for d in device_manager.devices if _printer_id(d) == printer_id]
            if not matching:
                raise ValueError(f"Printer not found: {printer_id}")
            device = matching[0]
        else:
            device = device_manager.find_and_select_device()
    except Exception:
        if printer_id:
            raise
        # Auto-select failed: fall back to the first virtual printer rather
        # than silently swallowing the print and emitting a misleading
        # `printed` SSE event upstream.
        _fallback_to_virtual_bitmap(bitmap, widgets, settings)
        return

    device.setup()
    dymo_labeler = DymoLabeler(
        tape_size_mm=settings.get("tapeSizeMm", 12),
        device=device,
    )
    dymo_labeler.print(bitmap)
