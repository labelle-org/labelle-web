"""Per-printer label settings persistence (issue #20).

The physical tape loaded in a printer — its width and colors — is a
long-lived property of *that printer*, not a per-label choice. We save
the subset the user picks, keyed by printer id, so it isn't re-selected
on every visit (especially painful in kiosk / shared-tablet setups).

Keyed by `PrinterInfo.id`: the USB id string for real printers
(`Bus 001 Device 005: ID 0922:1234`) or `virtual:<name>` for virtual
ones — both stable across reboots. State rides in the shared state file
under a "printers" namespace alongside the USB power cache.

Out of scope (see issue #20): batch row data (lives in the label JSON),
and recovering settings for a disconnected printer (we just keep the
entry and restore it when the printer reappears).

v2 follow-ups (aliases, remember-last, presets) are expected to extend
this same per-printer store — keep the shape easy to grow.
"""

import state_store

# The subset we persist, with their allowed values. Deliberately the
# "physical printer state" minimum from issue #20 — margin/justify/cutMark
# are arguably label preferences and are left out until that's decided.
_VALID_TAPE_SIZES = {6, 9, 12, 19}
_VALID_COLORS = {"white", "black", "yellow", "blue", "red", "green"}

_PERSISTED_KEYS = ("tapeSizeMm", "foregroundColor", "backgroundColor")

_PRINTERS_KEY = "printers"


def _validate(settings: dict) -> None:
    if not isinstance(settings, dict):
        raise ValueError("settings must be an object")
    unknown = set(settings) - set(_PERSISTED_KEYS)
    if unknown:
        raise ValueError(f"Unknown printer setting(s): {sorted(unknown)}")
    if "tapeSizeMm" in settings and settings["tapeSizeMm"] not in _VALID_TAPE_SIZES:
        raise ValueError(f"Invalid tapeSizeMm: {settings['tapeSizeMm']!r}")
    for key in ("foregroundColor", "backgroundColor"):
        if key in settings and settings[key] not in _VALID_COLORS:
            raise ValueError(f"Invalid {key}: {settings[key]!r}")


def get_settings(printer_id: str, path=None) -> dict:
    """Return the saved subset for a printer, or {} if none saved."""
    printers = state_store.read_all(path).get(_PRINTERS_KEY, {})
    entry = printers.get(printer_id)
    return entry if isinstance(entry, dict) else {}


def save_settings(printer_id: str, settings: dict, path=None) -> dict:
    """Validate and persist the subset for a printer. Returns it.

    The write replaces that printer's entry wholesale (not a deep-merge);
    the client always sends the full current subset.
    """
    if not printer_id:
        raise ValueError("printer_id must be non-empty")
    _validate(settings)
    state_store.update(
        lambda d: d.setdefault(_PRINTERS_KEY, {}).__setitem__(printer_id, settings),
        path,
    )
    return settings
