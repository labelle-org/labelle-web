"""Per-printer label settings persistence (issue #20).

The physical tape loaded in a printer — its width and colors — is a
long-lived property of *that printer*, not a per-label choice. We save
the subset the user picks, keyed by printer id, so it isn't re-selected
on every visit (especially painful in kiosk / shared-tablet setups).

Keyed by `PrinterInfo.id`: the USB id string for real printers
(`Bus 001 Device 005: ID 0922:1234`) or `virtual:<name>` for virtual
ones — both stable across reboots. State rides in the shared state file
under a "printers" namespace alongside the USB power cache.

Out of scope: batch row data (lives in the label JSON),
and recovering settings for a disconnected printer (we just keep the
entry and restore it when the printer reappears).

v2 follow-ups (aliases, remember-last, presets) are expected to extend
this same per-printer store — keep the shape easy to grow.
"""

import state_store

# The subset we persist, with their allowed values. Deliberately the
# "physical printer state" minimum — margin/justify/cutMark
# are arguably label preferences and are left out until that's decided.
_VALID_TAPE_SIZES = {6, 9, 12, 19}
_VALID_COLORS = {"white", "black", "yellow", "blue", "red", "green"}

# Allowed values per persisted key. Single source of truth for both
# _validate (raise on write) and _sanitize (drop on read).
_ALLOWED_VALUES = {
    "tapeSizeMm": _VALID_TAPE_SIZES,
    "foregroundColor": _VALID_COLORS,
    "backgroundColor": _VALID_COLORS,
}

_PERSISTED_KEYS = tuple(_ALLOWED_VALUES)

_PRINTERS_KEY = "printers"

# Cap the persisted printer-id length. Real ids are short (a USB id string
# or "serial:"/"virtual:" + name); this just stops an unauthenticated client
# from bloating the shared state file with absurdly long keys.
_MAX_PRINTER_ID_LEN = 256


def _is_allowed(key: str, value) -> bool:
    """Whether `value` is permitted for `key`. Unhashable values (a list or
    dict from a malformed request / hand-edited file) are simply not allowed,
    rather than raising TypeError from the set-membership check."""
    try:
        return value in _ALLOWED_VALUES[key]
    except TypeError:
        return False


def _validate(settings: dict) -> None:
    if not isinstance(settings, dict):
        raise ValueError("settings must be an object")
    unknown = set(settings) - set(_PERSISTED_KEYS)
    if unknown:
        raise ValueError(f"Unknown printer setting(s): {sorted(unknown)}")
    for key, value in settings.items():
        if not _is_allowed(key, value):
            raise ValueError(f"Invalid {key}: {value!r}")


def _sanitize(entry: dict) -> dict:
    """Best-effort filter to known keys with allowed values; never raises.

    Used on read so a hand-edited/corrupt state file can't serve unknown
    keys or out-of-range values back to the client. The mirror of
    _validate, which raises on the same conditions at write time.
    """
    return {
        key: value
        for key, value in entry.items()
        if key in _ALLOWED_VALUES and _is_allowed(key, value)
    }


def get_settings(printer_id: str, path=None) -> dict:
    """Return the saved subset for a printer, or {} if none saved.

    Sanitizes on read so a corrupt/hand-edited file yields only valid
    values, consistent with the validation enforced at write time.
    """
    printers = state_store.read_all(path).get(_PRINTERS_KEY)
    if not isinstance(printers, dict):
        return {}
    entry = printers.get(printer_id)
    return _sanitize(entry) if isinstance(entry, dict) else {}


def save_settings(printer_id: str, settings: dict, path=None) -> dict:
    """Validate and persist the subset for a printer. Returns it.

    The write replaces that printer's entry wholesale (not a deep-merge);
    the client always sends the full current subset.
    """
    if not isinstance(printer_id, str) or not printer_id:
        raise ValueError("printer_id must be a non-empty string")
    if len(printer_id) > _MAX_PRINTER_ID_LEN:
        raise ValueError(f"printer_id too long (max {_MAX_PRINTER_ID_LEN} chars)")
    _validate(settings)

    def mutate(d: dict) -> None:
        # A corrupt/hand-edited file may carry a non-dict "printers"; replace
        # it rather than letting __setitem__ raise and fail the write.
        if not isinstance(d.get(_PRINTERS_KEY), dict):
            d[_PRINTERS_KEY] = {}
        d[_PRINTERS_KEY][printer_id] = settings

    state_store.update(mutate, path)
    return settings
