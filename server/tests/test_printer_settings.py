"""Tests for per-printer label settings persistence.

Stores the long-lived "what tape/colors are loaded in this printer"
subset, keyed by printer id, in the shared state file. See issue #20.
"""

import pytest

import printer_settings
import state_store
import usb_power


class TestGet:
    def test_returns_empty_dict_when_printer_unknown(self, tmp_path):
        p = tmp_path / "state.json"
        assert printer_settings.get_settings("Bus 001 Device 005", p) == {}

    def test_round_trips_a_saved_subset(self, tmp_path):
        p = tmp_path / "state.json"
        printer_settings.save_settings(
            "virtual:Office",
            {"tapeSizeMm": 19, "foregroundColor": "white", "backgroundColor": "blue"},
            p,
        )
        assert printer_settings.get_settings("virtual:Office", p) == {
            "tapeSizeMm": 19,
            "foregroundColor": "white",
            "backgroundColor": "blue",
        }

    def test_settings_are_isolated_per_printer(self, tmp_path):
        p = tmp_path / "state.json"
        printer_settings.save_settings("a", {"tapeSizeMm": 6}, p)
        printer_settings.save_settings("b", {"tapeSizeMm": 19}, p)
        assert printer_settings.get_settings("a", p) == {"tapeSizeMm": 6}
        assert printer_settings.get_settings("b", p) == {"tapeSizeMm": 19}


class TestCorruptState:
    """A hand-edited or corrupt state file must not crash get/save."""

    def test_get_returns_empty_when_printers_is_not_a_dict(self, tmp_path):
        p = tmp_path / "state.json"
        state_store.update(lambda d: d.__setitem__("printers", []), p)
        assert printer_settings.get_settings("a", p) == {}

    def test_save_replaces_non_dict_printers(self, tmp_path):
        p = tmp_path / "state.json"
        state_store.update(lambda d: d.__setitem__("printers", "garbage"), p)
        printer_settings.save_settings("a", {"tapeSizeMm": 12}, p)
        assert printer_settings.get_settings("a", p) == {"tapeSizeMm": 12}


class TestSaveValidation:
    def test_rejects_unknown_key(self, tmp_path):
        p = tmp_path / "state.json"
        with pytest.raises(ValueError):
            printer_settings.save_settings("a", {"marginPx": 10}, p)

    def test_rejects_invalid_tape_size(self, tmp_path):
        p = tmp_path / "state.json"
        with pytest.raises(ValueError):
            printer_settings.save_settings("a", {"tapeSizeMm": 13}, p)

    def test_rejects_invalid_color(self, tmp_path):
        p = tmp_path / "state.json"
        with pytest.raises(ValueError):
            printer_settings.save_settings("a", {"foregroundColor": "magenta"}, p)

    def test_rejects_empty_printer_id(self, tmp_path):
        p = tmp_path / "state.json"
        with pytest.raises(ValueError):
            printer_settings.save_settings("", {"tapeSizeMm": 12}, p)

    def test_rejects_non_dict_body(self, tmp_path):
        p = tmp_path / "state.json"
        with pytest.raises(ValueError):
            printer_settings.save_settings("a", ["tapeSizeMm"], p)

    def test_partial_subset_is_allowed(self, tmp_path):
        """User may have only ever changed the tape size; persist just that."""
        p = tmp_path / "state.json"
        printer_settings.save_settings("a", {"tapeSizeMm": 9}, p)
        assert printer_settings.get_settings("a", p) == {"tapeSizeMm": 9}

    def test_save_replaces_prior_subset(self, tmp_path):
        p = tmp_path / "state.json"
        printer_settings.save_settings("a", {"tapeSizeMm": 9}, p)
        printer_settings.save_settings("a", {"foregroundColor": "red"}, p)
        # Latest write wins wholesale for that printer; not a deep-merge.
        assert printer_settings.get_settings("a", p) == {"foregroundColor": "red"}


class TestCoexistenceWithUsbPower:
    def test_saving_settings_preserves_usb_power_state(self, tmp_path):
        """The two features share one file; neither may clobber the other."""
        p = tmp_path / "state.json"
        usb_power._save_state("1-1", 3, p)
        printer_settings.save_settings("a", {"tapeSizeMm": 12}, p)
        assert usb_power._load_state(p) == ("1-1", 3)
        assert printer_settings.get_settings("a", p) == {"tapeSizeMm": 12}

    def test_usb_power_save_preserves_printer_settings(self, tmp_path):
        p = tmp_path / "state.json"
        printer_settings.save_settings("a", {"tapeSizeMm": 12}, p)
        usb_power._save_state("2-4", 7, p)
        assert printer_settings.get_settings("a", p) == {"tapeSizeMm": 12}
        assert usb_power._load_state(p) == ("2-4", 7)
