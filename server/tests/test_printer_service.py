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
