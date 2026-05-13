"""Auto-idle USB power saver for the Dymo printer.

Gated by `USB_POWER_SAVE=true`. When enabled, a background thread
checks every minute whether the server has been idle longer than
`USB_POWER_SAVE_IDLE_MINUTES` (default 60). If so, the printer's USB
port is powered off via uhubctl. Manual `/api/power/*` endpoints in
`app.py` stay always-on regardless of this gate — they're inert when
not called, so there's no reason to hide them.

Activity is recorded by `record_activity()` (wired from a Flask
`before_request` hook). On a printer-using request, the hook also
calls `ensure_powered()` so the printer is back on the bus by the
time the handler runs.
"""

import logging
import os
import threading
import time
import traceback

import usb_power

logger = logging.getLogger(__name__)

_CHECK_INTERVAL_SECONDS = 60

# Tracks the last "meaningful" request time (not /api/health or
# /api/power/*). Reads are unlocked (CPython makes a single
# assignment atomic under the GIL); writes happen from request
# handlers via `record_activity()`. Decisions that *act* on this
# value (`check_idle()` powering off) re-check it under `_LOCK`.
_last_activity: float = time.monotonic()

# Serializes `check_idle()` (specifically its decision-to-power-off
# critical region) with `ensure_powered()` so the idle daemon can't
# call `power_off()` while a request handler is in the middle of
# bringing the port up. Without this, the daemon's slow subprocess
# calls (`find_or_recall_printer_port`, `get_port_status`) open a
# window where a fresh request can complete `ensure_powered()` and
# proceed to use the printer just before the daemon issues `off`.
_LOCK = threading.Lock()

# Power-on settle delay so the device has time to re-enumerate before
# the next status read / handler runs against it.
_POWER_ON_SETTLE_SECONDS = 1.5


def is_enabled() -> bool:
    return os.environ.get("USB_POWER_SAVE", "").lower() in ("true", "1", "yes")


def idle_seconds() -> int:
    return int(os.environ.get("USB_POWER_SAVE_IDLE_MINUTES", "60")) * 60


def record_activity() -> None:
    global _last_activity
    _last_activity = time.monotonic()


def ensure_powered() -> bool:
    """If we know the printer's port and it's off, power it on.

    Returns True iff a power-on was performed. No-op when the saver
    is disabled, the printer isn't known, or it's already powered.
    Blocks ~1.5s on power-on so callers don't race re-enumeration.

    Holds `_LOCK` for the status-check + potential power-on so the
    idle daemon can't interleave a power-off into the critical
    region.
    """
    if not is_enabled():
        return False
    with _LOCK:
        port = usb_power.find_or_recall_printer_port()
        if not port:
            return False
        hub, port_num = port
        status = usb_power.get_port_status(hub, port_num)
        if status["powered"]:
            return False
        usb_power.power_on(hub, port_num)
    # Settle delay outside the lock — other requests don't need to
    # wait on the device re-enumerating.
    time.sleep(_POWER_ON_SETTLE_SECONDS)
    return True


def check_idle() -> bool:
    """If the idle threshold is exceeded and the port is on, power it off.

    Returns True iff a power-off was performed. Safe to call repeatedly.

    Re-checks `_last_activity` under `_LOCK` immediately before
    `power_off()` so a request that bumps activity between the first
    (unlocked) check and acquiring the lock will abort the power-off.
    """
    if not is_enabled():
        return False
    if time.monotonic() - _last_activity < idle_seconds():
        return False
    with _LOCK:
        if time.monotonic() - _last_activity < idle_seconds():
            return False
        port = usb_power.find_or_recall_printer_port()
        if not port:
            return False
        hub, port_num = port
        status = usb_power.get_port_status(hub, port_num)
        if not status["powered"]:
            return False
        usb_power.power_off(hub, port_num)
    return True


def _idle_loop() -> None:
    """Background loop — runs forever in a daemon thread."""
    while True:
        time.sleep(_CHECK_INTERVAL_SECONDS)
        try:
            if check_idle():
                logger.info("USB power-save: idle exceeded, port powered off")
        except Exception:
            # Swallow + log so the thread survives transient uhubctl
            # failures (USB hub momentarily missing, etc.)
            traceback.print_exc()


def start() -> None:
    """Spin up the background idle-check thread if the saver is enabled."""
    if not is_enabled():
        return
    thread = threading.Thread(target=_idle_loop, daemon=True, name="usb-power-save")
    thread.start()
    logger.info(
        "USB power-save enabled: will power off Dymo port after %d minutes idle",
        idle_seconds() // 60,
    )
