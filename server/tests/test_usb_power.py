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


class TestUhubctlMissing:
    """When uhubctl isn't installed (e.g. local dev outside Docker),
    subprocess.run raises FileNotFoundError. Surface that as a benign
    "no controllable printer" path so /api/power/* returns 404 (which
    the frontend already treats as "hide the toggle") instead of
    spamming a 500-traceback on every poll."""

    def setup_method(self):
        usb_power._uhubctl_missing_logged = False
        usb_power._last_known_port = None

    def test_find_printer_port_raises_filenotfound(self, mock_run):
        mock_run.side_effect = FileNotFoundError(2, "No such file", "uhubctl")
        with pytest.raises(FileNotFoundError):
            usb_power.find_printer_port()

    def test_find_or_recall_returns_none_with_no_cache(self, mock_run):
        mock_run.side_effect = FileNotFoundError(2, "No such file", "uhubctl")
        assert usb_power.find_or_recall_printer_port() is None

    def test_find_or_recall_bypasses_cache_when_uhubctl_missing(self, mock_run):
        # Regression: a state.json from a prior run on a host that had
        # uhubctl leaves _last_known_port set. If uhubctl is now missing,
        # returning that cached port would cause /api/power/* to proceed,
        # then 500 in get_port_status() — the symptom this PR aims to fix.
        usb_power._last_known_port = ("1-1", 3)
        mock_run.side_effect = FileNotFoundError(2, "No such file", "uhubctl")
        assert usb_power.find_or_recall_printer_port() is None

    def test_warning_logged_once_across_repeat_calls(self, mock_run, caplog):
        mock_run.side_effect = FileNotFoundError(2, "No such file", "uhubctl")
        with caplog.at_level("WARNING", logger="usb_power"):
            usb_power.find_or_recall_printer_port()
            usb_power.find_or_recall_printer_port()
            usb_power.find_or_recall_printer_port()
        uhubctl_warnings = [r for r in caplog.records if "uhubctl" in r.message]
        assert len(uhubctl_warnings) == 1


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


class TestStatePersistence:
    """The (hub, port) cache must survive a container restart so /api/power/on
    can find the port even if the printer is currently powered off."""

    def test_load_state_returns_none_when_file_missing(self, tmp_path):
        assert usb_power._load_state(tmp_path / "absent.json") is None

    def test_load_state_returns_tuple_when_file_valid(self, tmp_path):
        p = tmp_path / "state.json"
        p.write_text('{"hub": "1-1", "port": 3}')
        assert usb_power._load_state(p) == ("1-1", 3)

    def test_load_state_returns_none_when_json_corrupt(self, tmp_path):
        p = tmp_path / "state.json"
        p.write_text("{not json")
        assert usb_power._load_state(p) is None

    def test_load_state_returns_none_when_shape_wrong(self, tmp_path):
        p = tmp_path / "state.json"
        # port as string, not int
        p.write_text('{"hub": "1-1", "port": "3"}')
        assert usb_power._load_state(p) is None

    def test_save_state_writes_round_trippable_json(self, tmp_path):
        p = tmp_path / "state.json"
        usb_power._save_state("2-4", 7, p)
        assert usb_power._load_state(p) == ("2-4", 7)

    def test_save_state_creates_parent_dirs(self, tmp_path):
        p = tmp_path / "nested" / "dir" / "state.json"
        usb_power._save_state("1-1", 3, p)
        assert p.exists()

    def test_save_state_swallows_write_errors(self, tmp_path):
        # Make a path that can't be written (parent is a file, not a dir)
        blocker = tmp_path / "blocker"
        blocker.write_text("not a dir")
        bad_path = blocker / "state.json"
        # Should not raise — best-effort
        usb_power._save_state("1-1", 3, bad_path)

    def test_find_or_recall_persists_new_discovery_to_disk(
        self, mock_run, tmp_path, monkeypatch
    ):
        state_file = tmp_path / "state.json"
        monkeypatch.setattr(usb_power, "_STATE_FILE", state_file)
        usb_power._last_known_port = None

        mock_run.return_value = _result(UHUBCTL_DEFAULT_OUTPUT)
        usb_power.find_or_recall_printer_port()

        # Read it back through `_load_state()` with no arg so it
        # resolves the same monkeypatched `_STATE_FILE`.
        assert usb_power._load_state() == ("1-1", 3)

    def test_find_or_recall_does_not_rewrite_unchanged_value(
        self, mock_run, tmp_path, monkeypatch
    ):
        state_file = tmp_path / "state.json"
        monkeypatch.setattr(usb_power, "_STATE_FILE", state_file)
        usb_power._last_known_port = ("1-1", 3)

        mock_run.return_value = _result(UHUBCTL_DEFAULT_OUTPUT)
        usb_power.find_or_recall_printer_port()

        # File should not exist — no write happened because value is unchanged
        assert not state_file.exists()


class TestLibusbCacheInvalidation:
    """power_on must invalidate the pyusb libusb cache so the next scan
    re-enumerates the device that just came back. power_off must NOT
    invalidate it — re-creating a libusb context triggers a kernel hub
    auto-resume that would immediately re-energize the port we just
    powered off (observed on the 2109:3431 hub on hector)."""

    def test_power_on_clears_libusb_cache(self, mock_run):
        import usb.backend.libusb1

        usb.backend.libusb1._lib_object = "sentinel"
        usb.backend.libusb1._lib = "sentinel"

        mock_run.return_value = _result("OK")
        usb_power.power_on("1-1", 3)

        assert usb.backend.libusb1._lib_object is None
        assert usb.backend.libusb1._lib is None

    def test_power_off_does_NOT_clear_libusb_cache(self, mock_run):
        """Critical: clearing the cache after `off` would re-trigger the
        kernel hub resume and undo the off. Leave it stale."""
        import usb.backend.libusb1

        usb.backend.libusb1._lib_object = "sentinel"
        usb.backend.libusb1._lib = "sentinel"

        mock_run.return_value = _result("OK")
        usb_power.power_off("1-1", 3)

        assert usb.backend.libusb1._lib_object == "sentinel"
        assert usb.backend.libusb1._lib == "sentinel"
