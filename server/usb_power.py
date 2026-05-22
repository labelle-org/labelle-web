"""Per-port USB power control via uhubctl.

Lets us power off the Dymo printer's USB port when idle so its transformer
isn't running 24/7, and power it back on when the user opens the page.

Requires `uhubctl` on PATH (apt-installed in the Docker image). The hub must
support per-port power switching (ppps) — confirmed for the 2109:3431 USB
2.0 hub on hector.
"""

import json
import logging
import os
import re
import subprocess
from pathlib import Path

import usb.backend.libusb1

logger = logging.getLogger(__name__)

UHUBCTL_BIN = os.environ.get("UHUBCTL_BIN", "uhubctl")
DYMO_USB_ID = "0922:1002"

_HUB_LINE_RE = re.compile(r"Current status for hub (\S+)")
_PORT_DEVICE_RE = re.compile(r"\s+Port (\d+):.*\[(\S+) ")
_PORT_LINE_RE = re.compile(r"\s+Port (\d+):\s+(\w+)(.*)")

# Latch the "uhubctl missing" warning so we log it once at first call
# rather than re-spamming every /api/power/status poll. Reset only
# matters for tests, which monkeypatch `_run`'s subprocess call.
#
# Intentionally unlocked: under waitress's threaded serving a concurrent
# request burst at startup can log the warning a handful of extra times
# before the latch settles, but the race window is microseconds and is
# self-limiting — once True, no further races possible. A lock would
# add per-call overhead to every _run() (incl. the happy path on hosts
# where uhubctl is present) for a worst-case of N duplicate log lines
# once per process lifetime. Same trade-off as `_last_known_port` below.
_uhubctl_missing_logged = False


def _invalidate_libusb_cache() -> None:
    """Drop pyusb's cached libusb context so the next scan re-enumerates.

    pyusb's `usb.backend.libusb1` caches a `_lib_object` at module level
    on first use. In a long-lived process the cached context never
    notices that a USB device disappeared and re-appeared at a new bus
    address — `usb.core.find()` keeps returning the stale list.

    We call this only after `power_on()`, never after `power_off()`.
    Reason: re-creating a libusb context triggers a fresh USB
    enumeration, which the kernel handles by resuming the hub if it
    was auto-suspended. That resume re-energizes any port we just
    powered off, so on hubs with autosuspend enabled (like the
    2109:3431 we use on hector) a refresh after `power_off()` would
    immediately undo the off. After `power_on()` the port is supposed
    to be powered anyway, so the resume is harmless and we get an
    up-to-date device list.
    """
    usb.backend.libusb1._lib_object = None
    usb.backend.libusb1._lib = None


def _run(*args: str) -> str:
    try:
        result = subprocess.run(
            [UHUBCTL_BIN, *args],
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            timeout=10,
            check=True,
        )
    except FileNotFoundError:
        global _uhubctl_missing_logged
        if not _uhubctl_missing_logged:
            logger.warning(
                "uhubctl executable not found (%r); USB power-cycle features "
                "disabled. Install uhubctl (e.g. `sudo apt install uhubctl`) "
                "or set UHUBCTL_BIN to a working path.",
                UHUBCTL_BIN,
            )
            _uhubctl_missing_logged = True
        raise
    return result.stdout.decode()


def find_printer_port(vendor_product_id: str = DYMO_USB_ID) -> tuple[str, int] | None:
    """Locate (hub, port) for a USB device by `VVVV:PPPP` id, or None if absent.

    Raises FileNotFoundError if uhubctl isn't on PATH; callers should catch
    that and surface it as "no controllable printer". See
    find_or_recall_printer_port for the cache-aware variant the API uses.
    """
    output = _run()
    current_hub: str | None = None
    for line in output.splitlines():
        if m := _HUB_LINE_RE.match(line):
            current_hub = m.group(1)
            continue
        if current_hub and (m := _PORT_DEVICE_RE.match(line)):
            if m.group(2) == vendor_product_id:
                return current_hub, int(m.group(1))
    return None


def get_port_status(hub: str, port: int) -> dict:
    """Return {'powered': bool, 'connected': bool} for a specific hub port.

    uhubctl prints the upstream hub's port alongside the target hub's
    port, so we have to filter to the right hub before reading the
    port line — otherwise we read the upstream's status (which never
    reports `connect`).

    The status keywords (`power`, `enable`, `connect`, ...) appear
    before the optional `[VVVV:PPPP Vendor Product ...]` device
    descriptor, so we strip the descriptor first and tokenize the
    rest — otherwise a product name containing "power" or "connect"
    would false-match.
    """
    output = _run("-l", hub, "-p", str(port))
    in_target_hub = False
    for line in output.splitlines():
        if m := _HUB_LINE_RE.match(line):
            in_target_hub = m.group(1) == hub
            continue
        if in_target_hub and (m := _PORT_LINE_RE.match(line)) and int(m.group(1)) == port:
            flags_part = m.group(3).split("[", 1)[0]
            tokens = flags_part.split()
            return {
                "powered": "power" in tokens,
                "connected": "connect" in tokens,
            }
    raise ValueError(f"Port {port} not found on hub {hub}")


def set_port_power(hub: str, port: int, on: bool) -> None:
    _run("-l", hub, "-p", str(port), "-a", "on" if on else "off")


def power_on(hub: str, port: int) -> None:
    set_port_power(hub, port, on=True)
    # Device just (re-)appeared at a new bus address; drop libusb's
    # cached enumeration so the next scan sees the live state.
    _invalidate_libusb_cache()


def power_off(hub: str, port: int) -> None:
    set_port_power(hub, port, on=False)
    # Deliberately NOT invalidating the libusb cache here — see
    # `_invalidate_libusb_cache` docstring. A libusb re-init would
    # trigger a hub auto-resume that re-energizes the port we just
    # turned off. Callers that need to read accurate USB topology
    # while a port is off should use uhubctl-based status (`/api/
    # power/status`) rather than libusb-based device enumeration.


# Path where `_last_known_port` is persisted across container restarts.
# Default lives inside the Docker output mount, which is already a
# persistent volume in the standard deployment — avoids requiring a
# new volume mount just for this state. Tests pass an explicit path.
_STATE_FILE = Path(
    os.environ.get("LABELLE_STATE_FILE", "/app/output/.labelle/state.json")
)


def _load_state(path: Path | None = None) -> tuple[str, int] | None:
    """Read a previously-saved (hub, port) from disk, or None if absent/invalid."""
    if path is None:
        path = _STATE_FILE
    try:
        data = json.loads(path.read_text())
    except FileNotFoundError:
        return None
    except (OSError, json.JSONDecodeError) as e:
        logger.warning("Could not load printer port state from %s: %s", path, e)
        return None
    hub = data.get("hub")
    port = data.get("port")
    if isinstance(hub, str) and isinstance(port, int):
        return hub, port
    logger.warning(
        "Ignoring printer port state from %s: unexpected shape %r", path, data
    )
    return None


def _save_state(hub: str, port: int, path: Path | None = None) -> None:
    """Persist (hub, port) so a container restart can recover the cache.

    Best-effort: a write failure (read-only fs, missing volume mount,
    permissions) only loses cross-restart memory, never breaks runtime.

    Writes are atomic-on-POSIX: serialize to a sibling `.tmp` file
    first, then `os.replace()` over the target. A process interrupted
    mid-write (or another thread writing concurrently) leaves the
    target either fully old or fully new, never a torn JSON that
    `_load_state` would have to discard.
    """
    if path is None:
        path = _STATE_FILE
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(path.suffix + ".tmp")
        tmp.write_text(json.dumps({"hub": hub, "port": port}))
        tmp.replace(path)
    except OSError as e:
        logger.warning("Could not save printer port state to %s: %s", path, e)


# Module-global, intentionally unlocked. waitress serves requests on
# multiple threads, but Python's GIL makes the single-assignment update
# atomic and the worst-case race outcome is "valid value overwritten by
# another valid value" — benign for a single-printer setup. Revisit if
# we ever need per-printer caching for multiple devices.
#
# Seeded from disk at module load so a container restart while the
# printer is powered off doesn't lose the port — without that, the
# /api/power/on endpoint would 404 until the device was re-attached
# (or manually re-powered via shell uhubctl).
_last_known_port: tuple[str, int] | None = _load_state()


def find_or_recall_printer_port(
    vendor_product_id: str = DYMO_USB_ID,
) -> tuple[str, int] | None:
    """Like find_printer_port, but remembers the last live result.

    Needed because once we power off the port, the device disappears from
    the USB tree — `find_printer_port` would return None and we'd have no
    way to power it back on. This falls back to the cached result.

    On a live discovery (cache miss or hit-with-new-value) we persist the
    new value to disk, so a container restart picks up where we left off.

    Thread safety: best-effort, see `_last_known_port` comment above.

    When uhubctl is missing entirely, the cached port is useless — every
    downstream operation (`get_port_status`, `set_port_power`) would also
    fail. Return None outright in that case so /api/power/* renders as
    404 "no controllable printer" rather than 500-trampling on the cache.
    """
    global _last_known_port
    try:
        found = find_printer_port(vendor_product_id)
    except FileNotFoundError:
        return None
    if found and found != _last_known_port:
        _last_known_port = found
        _save_state(*found)
    return found or _last_known_port
