import time
from unittest.mock import patch

import pytest

import power_save
import usb_power


@pytest.fixture(autouse=True)
def reset_state(monkeypatch):
    """Fresh module state per test so cross-test pollution can't hide bugs."""
    monkeypatch.setattr(power_save, "_last_activity", time.monotonic())
    yield


class TestIsEnabled:
    def test_default_disabled(self, monkeypatch):
        monkeypatch.delenv("USB_POWER_SAVE", raising=False)
        assert power_save.is_enabled() is False

    @pytest.mark.parametrize("val", ["true", "True", "TRUE", "1", "yes"])
    def test_truthy_values_enable(self, monkeypatch, val):
        monkeypatch.setenv("USB_POWER_SAVE", val)
        assert power_save.is_enabled() is True

    @pytest.mark.parametrize("val", ["false", "0", "no", "off", ""])
    def test_falsy_values_disable(self, monkeypatch, val):
        monkeypatch.setenv("USB_POWER_SAVE", val)
        assert power_save.is_enabled() is False


class TestIdleSeconds:
    def test_default_60_minutes(self, monkeypatch):
        monkeypatch.delenv("USB_POWER_SAVE_IDLE_MINUTES", raising=False)
        assert power_save.idle_seconds() == 3600

    def test_custom_value(self, monkeypatch):
        monkeypatch.setenv("USB_POWER_SAVE_IDLE_MINUTES", "30")
        assert power_save.idle_seconds() == 1800


class TestRecordActivity:
    def test_updates_last_activity(self):
        before = power_save._last_activity
        time.sleep(0.001)  # ensure monotonic ticks
        power_save.record_activity()
        assert power_save._last_activity > before


class TestEnsurePowered:
    @patch("power_save.usb_power.power_on")
    @patch("power_save.usb_power.get_port_status")
    @patch("power_save.usb_power.find_or_recall_printer_port")
    def test_no_op_when_disabled(
        self, mock_find, mock_status, mock_on, monkeypatch
    ):
        monkeypatch.delenv("USB_POWER_SAVE", raising=False)
        assert power_save.ensure_powered() is False
        mock_find.assert_not_called()
        mock_on.assert_not_called()

    @patch("power_save.usb_power.power_on")
    @patch("power_save.usb_power.get_port_status")
    @patch("power_save.usb_power.find_or_recall_printer_port")
    def test_no_op_when_no_printer_known(
        self, mock_find, mock_status, mock_on, monkeypatch
    ):
        monkeypatch.setenv("USB_POWER_SAVE", "true")
        mock_find.return_value = None
        assert power_save.ensure_powered() is False
        mock_on.assert_not_called()

    @patch("power_save.usb_power.power_on")
    @patch("power_save.usb_power.get_port_status")
    @patch("power_save.usb_power.find_or_recall_printer_port")
    def test_no_op_when_already_powered(
        self, mock_find, mock_status, mock_on, monkeypatch
    ):
        monkeypatch.setenv("USB_POWER_SAVE", "true")
        mock_find.return_value = ("1-1", 3)
        mock_status.return_value = {"powered": True, "connected": True}
        assert power_save.ensure_powered() is False
        mock_on.assert_not_called()

    @patch("power_save.time.sleep")
    @patch("power_save.usb_power.power_on")
    @patch("power_save.usb_power.get_port_status")
    @patch("power_save.usb_power.find_or_recall_printer_port")
    def test_powers_on_when_off(
        self, mock_find, mock_status, mock_on, mock_sleep, monkeypatch
    ):
        monkeypatch.setenv("USB_POWER_SAVE", "true")
        mock_find.return_value = ("1-1", 3)
        mock_status.return_value = {"powered": False, "connected": False}
        assert power_save.ensure_powered() is True
        mock_on.assert_called_once_with("1-1", 3)


class TestCheckIdle:
    @patch("power_save.usb_power.power_off")
    @patch("power_save.usb_power.get_port_status")
    @patch("power_save.usb_power.find_or_recall_printer_port")
    def test_no_op_when_disabled(
        self, mock_find, mock_status, mock_off, monkeypatch
    ):
        monkeypatch.delenv("USB_POWER_SAVE", raising=False)
        assert power_save.check_idle() is False
        mock_off.assert_not_called()

    @patch("power_save.usb_power.power_off")
    @patch("power_save.usb_power.get_port_status")
    @patch("power_save.usb_power.find_or_recall_printer_port")
    def test_no_op_when_recently_active(
        self, mock_find, mock_status, mock_off, monkeypatch
    ):
        monkeypatch.setenv("USB_POWER_SAVE", "true")
        monkeypatch.setenv("USB_POWER_SAVE_IDLE_MINUTES", "60")
        power_save._last_activity = time.monotonic()  # just now
        assert power_save.check_idle() is False
        mock_off.assert_not_called()

    @patch("power_save.usb_power.power_off")
    @patch("power_save.usb_power.get_port_status")
    @patch("power_save.usb_power.find_or_recall_printer_port")
    def test_no_op_when_already_off(
        self, mock_find, mock_status, mock_off, monkeypatch
    ):
        monkeypatch.setenv("USB_POWER_SAVE", "true")
        monkeypatch.setenv("USB_POWER_SAVE_IDLE_MINUTES", "1")
        # Force the idle threshold to be exceeded
        power_save._last_activity = time.monotonic() - 1000
        mock_find.return_value = ("1-1", 3)
        mock_status.return_value = {"powered": False, "connected": False}
        assert power_save.check_idle() is False
        mock_off.assert_not_called()

    @patch("power_save.usb_power.power_off")
    @patch("power_save.usb_power.get_port_status")
    @patch("power_save.usb_power.find_or_recall_printer_port")
    def test_powers_off_when_idle_exceeded(
        self, mock_find, mock_status, mock_off, monkeypatch
    ):
        monkeypatch.setenv("USB_POWER_SAVE", "true")
        monkeypatch.setenv("USB_POWER_SAVE_IDLE_MINUTES", "1")
        power_save._last_activity = time.monotonic() - 1000
        mock_find.return_value = ("1-1", 3)
        mock_status.return_value = {"powered": True, "connected": True}
        assert power_save.check_idle() is True
        mock_off.assert_called_once_with("1-1", 3)

    @patch("power_save.usb_power.power_off")
    @patch("power_save.usb_power.find_or_recall_printer_port")
    def test_no_op_when_no_printer_known(
        self, mock_find, mock_off, monkeypatch
    ):
        monkeypatch.setenv("USB_POWER_SAVE", "true")
        monkeypatch.setenv("USB_POWER_SAVE_IDLE_MINUTES", "1")
        power_save._last_activity = time.monotonic() - 1000
        mock_find.return_value = None
        assert power_save.check_idle() is False
        mock_off.assert_not_called()

    @patch("power_save.usb_power.power_off")
    @patch("power_save.usb_power.find_or_recall_printer_port")
    def test_re_check_under_lock_aborts_when_activity_fresh(
        self, mock_find, mock_off, monkeypatch
    ):
        """If a request bumps `_last_activity` between the unlocked first
        check and the lock acquisition, the re-check inside the critical
        region must abort the power-off.

        Simulated by patching `time.monotonic` to return two values: a
        far-future one for the first (unlocked) check so idle is
        exceeded, then a close-to-`_last_activity` one for the re-check
        so it looks fresh again.
        """
        monkeypatch.setenv("USB_POWER_SAVE", "true")
        monkeypatch.setenv("USB_POWER_SAVE_IDLE_MINUTES", "1")  # 60s threshold

        base = 1000.0
        power_save._last_activity = base
        with patch(
            "power_save.time.monotonic",
            side_effect=[base + 1000, base + 30],
        ):
            assert power_save.check_idle() is False

        mock_off.assert_not_called()
        # The re-check aborts before we ever shell out to uhubctl.
        mock_find.assert_not_called()


class TestStart:
    def test_does_not_start_thread_when_disabled(self, monkeypatch):
        monkeypatch.delenv("USB_POWER_SAVE", raising=False)
        with patch("power_save.threading.Thread") as mock_thread:
            power_save.start()
            mock_thread.assert_not_called()

    def test_starts_daemon_thread_when_enabled(self, monkeypatch):
        monkeypatch.setenv("USB_POWER_SAVE", "true")
        with patch("power_save.threading.Thread") as mock_thread:
            power_save.start()
            mock_thread.assert_called_once()
            assert mock_thread.call_args.kwargs["daemon"] is True
            mock_thread.return_value.start.assert_called_once()
