"""Tests for printer_service: list_printers() and print_label()."""

import os
from unittest.mock import MagicMock, patch

import pytest


@pytest.fixture
def sample_widgets():
    return [{"type": "text", "text": "Hello", "id": "1"}]


@pytest.fixture
def sample_settings():
    return {
        "tapeSizeMm": 12,
        "marginPx": 56,
        "minLengthMm": 0,
        "justify": "center",
        "foregroundColor": "black",
        "backgroundColor": "white",
        "showMargins": False,
    }


def _fake_device(serial="08383504012013", usb_id="Bus 001 Device 005: ID 0922:1002"):
    dev = MagicMock()
    dev.serial_number = serial
    dev.usb_id = usb_id
    dev.vendor_product_id = "0922:1002"
    dev.manufacturer = "DYMO"
    dev.product = "LabelManager PnP"
    return dev


class TestStablePrinterId:
    """Real-printer ids must be keyed by serial (stable across
    re-enumeration), falling back to usb_id only when no serial. See #40."""

    def test_uses_serial_when_present(self):
        from printer_service import _printer_id

        assert _printer_id(_fake_device(serial="ABC123")) == "serial:ABC123"

    def test_falls_back_to_usb_id_when_no_serial(self):
        from printer_service import _printer_id

        dev = _fake_device(serial=None, usb_id="Bus 001 Device 005: ID 0922:1002")
        assert _printer_id(dev) == "Bus 001 Device 005: ID 0922:1002"

    @patch("printer_service.DeviceManager")
    def test_list_printers_emits_serial_based_id(self, mock_dm_cls, no_virtual_printers_env):
        mock_dm = MagicMock()
        mock_dm.devices = [_fake_device(serial="ABC123")]
        mock_dm_cls.return_value = mock_dm

        from printer_service import list_printers

        real = [p for p in list_printers() if p["vendorProductId"] == "0922:1002"]
        assert real[0]["id"] == "serial:ABC123"

    @patch("printer_service.render_payload")
    @patch("printer_service.DymoLabeler")
    @patch("printer_service.DeviceManager")
    def test_print_resolves_device_by_serial_id(
        self, mock_dm_cls, mock_labeler_cls, mock_render, sample_widgets, sample_settings
    ):
        dev = _fake_device(serial="ABC123")
        mock_dm = MagicMock()
        mock_dm.devices = [dev]
        mock_dm_cls.return_value = mock_dm

        from printer_service import print_label

        # The same id list_printers emits must resolve back to the device.
        print_label(sample_widgets, sample_settings, printer_id="serial:ABC123")
        dev.setup.assert_called_once()
        mock_labeler_cls.return_value.print.assert_called_once()

    @patch("printer_service.DeviceManager")
    def test_print_raises_when_serial_id_does_not_match(
        self, mock_dm_cls, sample_widgets, sample_settings
    ):
        mock_dm = MagicMock()
        mock_dm.devices = [_fake_device(serial="ABC123")]
        mock_dm_cls.return_value = mock_dm

        from printer_service import print_label

        with pytest.raises(ValueError, match="Printer not found"):
            print_label(sample_widgets, sample_settings, printer_id="serial:NOPE")


class TestListPrinters:
    @patch("printer_service.DeviceManager")
    def test_returns_virtual_printers(self, mock_dm_cls, virtual_printer_env):
        mock_dm = MagicMock()
        mock_dm.devices = []
        mock_dm_cls.return_value = mock_dm

        from printer_service import list_printers

        printers = list_printers()

        virtual = [p for p in printers if p["vendorProductId"] == "virtual"]
        assert len(virtual) == 2
        assert virtual[0]["name"].endswith("(Virtual)")
        assert virtual[0]["id"].startswith("virtual:")

    @patch("printer_service.DeviceManager")
    def test_no_printers_configured(self, mock_dm_cls, no_virtual_printers_env):
        mock_dm = MagicMock()
        mock_dm.devices = []
        mock_dm_cls.return_value = mock_dm

        from printer_service import list_printers

        assert list_printers() == []

    @patch("printer_service.DeviceManager")
    def test_virtual_printer_ids_are_unique(self, mock_dm_cls, virtual_printer_env):
        mock_dm = MagicMock()
        mock_dm.devices = []
        mock_dm_cls.return_value = mock_dm

        from printer_service import list_printers

        printers = list_printers()
        ids = [p["id"] for p in printers]
        assert len(ids) == len(set(ids))


class TestListPrintersUsbScanFailure:
    @patch("printer_service.DeviceManager")
    def test_returns_virtual_printers_when_usb_scan_throws(self, mock_dm_cls, virtual_printer_env):
        """USB scan failure should not prevent virtual printers from being returned."""
        mock_dm_cls.side_effect = Exception("USB subsystem unavailable")

        from printer_service import list_printers

        printers = list_printers()
        virtual = [p for p in printers if p["vendorProductId"] == "virtual"]
        assert len(virtual) == 2

    @patch("printer_service.DeviceManager")
    def test_returns_empty_when_usb_scan_throws_and_no_virtual(self, mock_dm_cls, no_virtual_printers_env):
        mock_dm_cls.side_effect = Exception("USB subsystem unavailable")

        from printer_service import list_printers

        assert list_printers() == []

    @patch("printer_service.DeviceManager")
    def test_no_devices_logs_info_without_traceback(
        self, mock_dm_cls, no_virtual_printers_env, caplog
    ):
        # labelle.scan() raises DeviceManagerNoDevices when no DYMO is
        # plugged in. That is an expected state — make sure it surfaces
        # as a single INFO line, not a noisy traceback, and the result
        # is still a (possibly empty) list rather than a crash.
        from labelle.lib.devices.device_manager import DeviceManagerNoDevices

        mock_dm = MagicMock()
        mock_dm.scan.side_effect = DeviceManagerNoDevices("No supported devices found")
        mock_dm_cls.return_value = mock_dm

        from printer_service import list_printers

        with caplog.at_level("INFO", logger="printer_service"):
            result = list_printers()

        assert result == []
        info_msgs = [
            r.message for r in caplog.records
            if r.levelname == "INFO" and "DYMO" in r.message
        ]
        assert len(info_msgs) == 1


class TestStaleLibusbContextRecovery:
    """A long-lived process caches its libusb context. If the printer
    re-enumerates to a new bus address (replug, or our own USB power-cycle)
    after that context is built, scans keep coming back empty even though the
    device is physically attached. list_printers() must recover: when a scan
    is empty BUT uhubctl still sees the DYMO, drop the cached context and
    rescan once — without ever resuming a deliberately powered-off port."""

    @patch("printer_service.usb_power")
    @patch("printer_service.DeviceManager")
    def test_recovers_when_printer_still_attached(
        self, mock_dm_cls, mock_usb_power, no_virtual_printers_env
    ):
        from labelle.lib.devices.device_manager import DeviceManagerNoDevices

        mock_dm = MagicMock()
        # First scan: stale context sees nothing. After cache invalidation the
        # second scan re-enumerates and finds the device.
        mock_dm.scan.side_effect = [DeviceManagerNoDevices("none"), None]
        mock_dm.devices = [_fake_device(serial="ABC123")]
        mock_dm_cls.return_value = mock_dm
        mock_usb_power.printer_attached.return_value = True

        from printer_service import list_printers

        result = list_printers()

        mock_usb_power.invalidate_libusb_cache.assert_called_once()
        assert [p["id"] for p in result] == ["serial:ABC123"]

    @patch("printer_service.usb_power")
    @patch("printer_service.DeviceManager")
    def test_no_refresh_when_uhubctl_does_not_see_printer(
        self, mock_dm_cls, mock_usb_power, no_virtual_printers_env
    ):
        """Powered-off / genuinely-absent: uhubctl sees no DYMO, so we must
        NOT touch the libusb cache (a refresh would resume the hub and
        re-energize a port the user deliberately powered off)."""
        from labelle.lib.devices.device_manager import DeviceManagerNoDevices

        mock_dm = MagicMock()
        mock_dm.scan.side_effect = DeviceManagerNoDevices("none")
        mock_dm_cls.return_value = mock_dm
        mock_usb_power.printer_attached.return_value = False

        from printer_service import list_printers

        result = list_printers()

        mock_usb_power.invalidate_libusb_cache.assert_not_called()
        assert result == []

    @patch("printer_service.usb_power")
    @patch("printer_service.DeviceManager")
    def test_no_uhubctl_probe_on_successful_first_scan(
        self, mock_dm_cls, mock_usb_power, no_virtual_printers_env
    ):
        """The happy path must not consult uhubctl or refresh the cache."""
        mock_dm = MagicMock()
        mock_dm.devices = [_fake_device(serial="ABC123")]
        mock_dm_cls.return_value = mock_dm

        from printer_service import list_printers

        result = list_printers()

        mock_usb_power.printer_attached.assert_not_called()
        mock_usb_power.invalidate_libusb_cache.assert_not_called()
        assert [p["id"] for p in result] == ["serial:ABC123"]

    @patch("printer_service.usb_power")
    @patch("printer_service.DeviceManager")
    def test_refresh_that_still_finds_nothing_returns_empty(
        self, mock_dm_cls, mock_usb_power, no_virtual_printers_env
    ):
        """If the refresh+rescan still finds nothing, return gracefully
        rather than raising."""
        from labelle.lib.devices.device_manager import DeviceManagerNoDevices

        mock_dm = MagicMock()
        mock_dm.scan.side_effect = [
            DeviceManagerNoDevices("none"),
            DeviceManagerNoDevices("still none"),
        ]
        mock_dm_cls.return_value = mock_dm
        mock_usb_power.printer_attached.return_value = True

        from printer_service import list_printers

        result = list_printers()

        mock_usb_power.invalidate_libusb_cache.assert_called_once()
        assert result == []


class TestPrintStaleLibusbContextRecovery:
    """The same stale-libusb-context failure that empties list_printers() also
    breaks the *print* path: print_label / print_bitmap scan for the requested
    device and, with a stale context, find nothing (or the wrong device) even
    though the printer is physically attached. They must recover the same way
    list_printers() does — refresh the cache and rescan once, gated on uhubctl
    confirming the DYMO is still present. See #48."""

    @patch("printer_service.usb_power")
    @patch("printer_service.render_payload")
    @patch("printer_service.DymoLabeler")
    @patch("printer_service.DeviceManager")
    def test_print_label_recovers_when_printer_still_attached(
        self, mock_dm_cls, mock_labeler_cls, mock_render, mock_usb_power,
        sample_widgets, sample_settings,
    ):
        from labelle.lib.devices.device_manager import DeviceManagerNoDevices

        dev = _fake_device(serial="ABC123")
        mock_dm = MagicMock()
        # First scan: stale context sees nothing. After cache invalidation the
        # second scan re-enumerates and the device reappears.
        mock_dm.scan.side_effect = [DeviceManagerNoDevices("none"), None]
        mock_dm.devices = [dev]
        mock_dm_cls.return_value = mock_dm
        mock_usb_power.printer_attached.return_value = True

        from printer_service import print_label

        print_label(sample_widgets, sample_settings, printer_id="serial:ABC123")

        mock_usb_power.invalidate_libusb_cache.assert_called_once()
        dev.setup.assert_called_once()
        mock_labeler_cls.return_value.print.assert_called_once()

    @patch("printer_service.usb_power")
    @patch("printer_service.DeviceManager")
    def test_print_label_no_refresh_when_uhubctl_does_not_see_printer(
        self, mock_dm_cls, mock_usb_power, sample_widgets, sample_settings,
    ):
        """Powered-off / genuinely-absent: don't touch the libusb cache, and
        surface the same "Printer not found" the caller already handles."""
        from labelle.lib.devices.device_manager import DeviceManagerNoDevices

        mock_dm = MagicMock()
        mock_dm.scan.side_effect = DeviceManagerNoDevices("none")
        mock_dm_cls.return_value = mock_dm
        mock_usb_power.printer_attached.return_value = False

        from printer_service import print_label

        with pytest.raises(ValueError, match="Printer not found"):
            print_label(sample_widgets, sample_settings, printer_id="serial:ABC123")

        mock_usb_power.invalidate_libusb_cache.assert_not_called()

    @patch("printer_service.usb_power")
    @patch("printer_service.render_payload")
    @patch("printer_service.DymoLabeler")
    @patch("printer_service.DeviceManager")
    def test_print_label_no_uhubctl_probe_on_successful_first_scan(
        self, mock_dm_cls, mock_labeler_cls, mock_render, mock_usb_power,
        sample_widgets, sample_settings,
    ):
        """The happy path must not consult uhubctl or refresh the cache."""
        dev = _fake_device(serial="ABC123")
        mock_dm = MagicMock()
        mock_dm.devices = [dev]
        mock_dm_cls.return_value = mock_dm

        from printer_service import print_label

        print_label(sample_widgets, sample_settings, printer_id="serial:ABC123")

        mock_usb_power.printer_attached.assert_not_called()
        mock_usb_power.invalidate_libusb_cache.assert_not_called()

    @patch("printer_service.usb_power")
    @patch("printer_service.DymoLabeler")
    @patch("printer_service.DeviceManager")
    def test_print_bitmap_recovers_when_printer_still_attached(
        self, mock_dm_cls, mock_labeler_cls, mock_usb_power, sample_settings,
    ):
        """print_bitmap is the path that actually failed in the field (the
        cut-mark print goes through it)."""
        from PIL import Image
        from labelle.lib.devices.device_manager import DeviceManagerNoDevices

        dev = _fake_device(serial="ABC123")
        mock_dm = MagicMock()
        mock_dm.scan.side_effect = [DeviceManagerNoDevices("none"), None]
        mock_dm.devices = [dev]
        mock_dm_cls.return_value = mock_dm
        mock_usb_power.printer_attached.return_value = True

        from printer_service import print_bitmap

        print_bitmap(Image.new("1", (8, 8)), sample_settings, printer_id="serial:ABC123")

        mock_usb_power.invalidate_libusb_cache.assert_called_once()
        dev.setup.assert_called_once()
        mock_labeler_cls.return_value.print.assert_called_once()

    @patch("printer_service.usb_power")
    @patch("printer_service.render_payload")
    @patch("printer_service.DymoLabeler")
    @patch("printer_service.DeviceManager")
    def test_auto_select_recovers_when_printer_still_attached(
        self, mock_dm_cls, mock_labeler_cls, mock_render, mock_usb_power,
        sample_widgets, sample_settings,
    ):
        """Auto-select (printer_id=None) resolves via find_and_select_device;
        it too must recover from a stale context rather than wrongly falling
        back to a virtual printer when the real one is attached."""
        from labelle.lib.devices.device_manager import DeviceManagerNoDevices

        dev = _fake_device(serial="ABC123")
        mock_dm = MagicMock()
        mock_dm.find_and_select_device.side_effect = [DeviceManagerNoDevices("none"), dev]
        mock_dm_cls.return_value = mock_dm
        mock_usb_power.printer_attached.return_value = True

        from printer_service import print_label

        print_label(sample_widgets, sample_settings, printer_id=None)

        mock_usb_power.invalidate_libusb_cache.assert_called_once()
        dev.setup.assert_called_once()


class TestAutoSelectWithVirtualPrinters:
    @patch("printer_service.DeviceManager")
    def test_auto_select_falls_back_to_virtual_printer(
        self, mock_dm_cls, sample_widgets, sample_settings, virtual_printer_env
    ):
        """When no USB printers exist but virtual printers are configured,
        auto-select should use the first virtual printer."""
        mock_dm = MagicMock()
        mock_dm.scan.side_effect = Exception("No supported devices found")
        mock_dm_cls.return_value = mock_dm

        from printer_service import print_label

        # Should NOT raise — should fall back to virtual printer
        print_label(sample_widgets, sample_settings, printer_id=None)

    @patch("printer_service.DeviceManager")
    def test_auto_select_saves_to_virtual_printer_output_dir(
        self, mock_dm_cls, sample_widgets, sample_settings, virtual_printer_env
    ):
        """Auto-select fallback should actually save a file to the virtual printer's output dir."""
        mock_dm = MagicMock()
        mock_dm.scan.side_effect = Exception("No supported devices found")
        mock_dm_cls.return_value = mock_dm

        from printer_service import print_label

        print_label(sample_widgets, sample_settings, printer_id=None)

        # Check that a file was saved to the first virtual printer's output dir
        output_dir = virtual_printer_env[0]["path"]
        files = os.listdir(output_dir)
        assert len(files) == 1
        assert files[0].endswith(".png")

    @patch("printer_service.DeviceManager")
    def test_auto_select_no_printers_at_all_raises(
        self, mock_dm_cls, sample_widgets, sample_settings, no_virtual_printers_env
    ):
        """When no USB printers AND no virtual printers exist, auto-select should raise."""
        mock_dm = MagicMock()
        mock_dm.scan.side_effect = Exception("No supported devices found")
        mock_dm_cls.return_value = mock_dm

        from printer_service import print_label

        with pytest.raises(Exception):
            print_label(sample_widgets, sample_settings, printer_id=None)
