from unittest.mock import patch

import pytest

import usb_power


UHUBCTL_DEFAULT_OUTPUT = """\
Current status for hub 2 [1d6b:0003 Linux 6.12.62+rpt-rpi-v8 xhci-hcd xHCI Host Controller 0000:01:00.0, USB 3.00, 4 ports, ppps]
  Port 1: 02a0 power 5gbps Rx.Detect
  Port 2: 02a0 power 5gbps Rx.Detect
  Port 3: 02a0 power 5gbps Rx.Detect
  Port 4: 02a0 power 5gbps Rx.Detect
Current status for hub 1-1 [2109:3431 USB2.0 Hub, USB 2.10, 4 ports, ppps]
  Port 1: 0100 power
  Port 2: 0100 power
  Port 3: 0103 power enable connect [0922:1002 Dymo DYMO LabelManager PnP 08383504012013]
  Port 4: 0100 power
"""

UHUBCTL_PORT_ON = """\
Current status for hub 2 [1d6b:0003 xHCI Host Controller, USB 3.00, 4 ports, ppps]
  Port 3: 02a0 power 5gbps Rx.Detect
Current status for hub 1-1 [2109:3431 USB2.0 Hub, USB 2.10, 4 ports, ppps]
  Port 3: 0103 power enable connect [0922:1002 Dymo DYMO LabelManager PnP 08383504012013]
"""

UHUBCTL_PORT_OFF = """\
Current status for hub 2 [1d6b:0003 xHCI Host Controller, USB 3.00, 4 ports, ppps]
  Port 3: 0080 off
Current status for hub 1-1 [2109:3431 USB2.0 Hub, USB 2.10, 4 ports, ppps]
  Port 3: 0000 off
"""


def _result(stdout: str):
    """Build a fake CompletedProcess with bytes stdout."""

    class R:
        pass

    r = R()
    r.stdout = stdout.encode()
    return r


@pytest.fixture
def mock_run():
    """Patch subprocess.run inside usb_power so tests stay hermetic."""
    with patch.object(usb_power.subprocess, "run") as m:
        yield m


class TestFindPrinterPort:
    def test_finds_dymo_on_hub_1_1_port_3(self, mock_run):
        mock_run.return_value = _result(UHUBCTL_DEFAULT_OUTPUT)
        assert usb_power.find_printer_port("0922:1002") == ("1-1", 3)

    def test_defaults_to_dymo_usb_id(self, mock_run):
        mock_run.return_value = _result(UHUBCTL_DEFAULT_OUTPUT)
        assert usb_power.find_printer_port() == ("1-1", 3)

    def test_returns_none_when_device_absent(self, mock_run):
        mock_run.return_value = _result(UHUBCTL_DEFAULT_OUTPUT)
        assert usb_power.find_printer_port("dead:beef") is None

    def test_returns_none_for_empty_output(self, mock_run):
        mock_run.return_value = _result("")
        assert usb_power.find_printer_port("0922:1002") is None


class TestGetPortStatus:
    def test_powered_with_device_connected(self, mock_run):
        mock_run.return_value = _result(UHUBCTL_PORT_ON)
        s = usb_power.get_port_status("1-1", 3)
        assert s == {"powered": True, "connected": True}

    def test_powered_off(self, mock_run):
        mock_run.return_value = _result(UHUBCTL_PORT_OFF)
        s = usb_power.get_port_status("1-1", 3)
        assert s == {"powered": False, "connected": False}

    def test_raises_when_port_not_in_output(self, mock_run):
        mock_run.return_value = _result(
            "Current status for hub 1-1 [...]\n  Port 1: 0100 power\n"
        )
        with pytest.raises(ValueError):
            usb_power.get_port_status("1-1", 99)

    def test_device_name_with_power_word_does_not_false_match(self, mock_run):
        # Hypothetical product whose name contains "power" and "connect" —
        # status should reflect only the flag tokens, not the descriptor.
        mock_run.return_value = _result(
            "Current status for hub 1-1 [2109:3431 USB2.0 Hub, USB 2.10, 4 ports, ppps]\n"
            "  Port 3: 0000 off [dead:beef PowerCo Connect-Pro 12345]\n"
        )
        s = usb_power.get_port_status("1-1", 3)
        assert s == {"powered": False, "connected": False}


class TestFindOrRecall:
    def setup_method(self):
        usb_power._last_known_port = None

    def test_uses_live_result_when_device_present(self, mock_run):
        mock_run.return_value = _result(UHUBCTL_DEFAULT_OUTPUT)
        assert usb_power.find_or_recall_printer_port() == ("1-1", 3)
        assert usb_power._last_known_port == ("1-1", 3)

    def test_falls_back_to_cache_when_device_absent(self, mock_run):
        usb_power._last_known_port = ("1-1", 3)
        mock_run.return_value = _result(
            UHUBCTL_DEFAULT_OUTPUT.replace("0922:1002", "dead:beef")
        )
        assert usb_power.find_or_recall_printer_port() == ("1-1", 3)

    def test_returns_none_when_no_cache_and_no_device(self, mock_run):
        mock_run.return_value = _result("")
        assert usb_power.find_or_recall_printer_port() is None


class TestPowerOnOff:
    def test_power_on_invokes_exact_command(self, mock_run):
        mock_run.return_value = _result("OK")
        usb_power.power_on("1-1", 3)
        assert mock_run.call_args[0][0] == [
            usb_power.UHUBCTL_BIN, "-l", "1-1", "-p", "3", "-a", "on"
        ]

    def test_power_off_invokes_exact_command(self, mock_run):
        mock_run.return_value = _result("OK")
        usb_power.power_off("1-1", 3)
        assert mock_run.call_args[0][0] == [
            usb_power.UHUBCTL_BIN, "-l", "1-1", "-p", "3", "-a", "off"
        ]

    def test_power_on_passes_hub_and_port(self, mock_run):
        mock_run.return_value = _result("OK")
        usb_power.power_on("2-3", 4)
        assert mock_run.call_args[0][0] == [
            usb_power.UHUBCTL_BIN, "-l", "2-3", "-p", "4", "-a", "on"
        ]
