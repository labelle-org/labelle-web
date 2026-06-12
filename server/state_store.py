"""Shared owner of the on-disk JSON state file (LABELLE_STATE_FILE).

Several features persist a little long-lived state across container
restarts — the USB power feature caches the printer's (hub, port), and
per-printer label settings live here too (issue #20). They all share one
file so the standard deployment needs only the single `/app/output`
volume that's already mounted.

Sharing one file means a writer touching its own slice must not drop
another feature's slice. So every write is a read-modify-write of the
whole document under a process-wide lock, and `update()` hands the
mutator the full dict to edit in place. Writes are atomic-on-POSIX
(serialize to a sibling `.tmp`, then `os.replace`), so a crash or a
concurrent writer leaves the file fully old or fully new, never torn.

Best-effort by design: a write failure (read-only fs, missing mount,
permissions) only loses cross-restart memory, it never breaks runtime.
"""

import json
import logging
import os
import threading
from pathlib import Path
from typing import Callable

logger = logging.getLogger(__name__)

# Default lives inside the Docker output mount, already a persistent
# volume in the standard deployment — avoids requiring a new mount just
# for this state. Tests pass an explicit path.
STATE_FILE = Path(
    os.environ.get("LABELLE_STATE_FILE", "/app/output/.labelle/state.json")
)

# Serializes read-modify-write across all callers. waitress serves on
# multiple threads, and two features writing different slices of the same
# file would otherwise interleave their read/write and lose one update.
_lock = threading.Lock()


def read_all(path: Path | None = None) -> dict:
    """Return the whole state document as a dict; {} if absent/corrupt.

    A missing file is the normal first-run state. A corrupt or
    wrong-shaped file is logged and treated as empty rather than
    crashing callers — the worst case is that prior state is forgotten
    (and overwritten cleanly on the next write).
    """
    if path is None:
        path = STATE_FILE
    try:
        data = json.loads(path.read_text())
    except FileNotFoundError:
        return {}
    except (OSError, json.JSONDecodeError) as e:
        logger.warning("Could not read state file %s: %s", path, e)
        return {}
    if isinstance(data, dict):
        return data
    logger.warning("Ignoring state file %s: top level is not an object", path)
    return {}


def update(mutator: Callable[[dict], None], path: Path | None = None) -> dict:
    """Atomically read-modify-write the state file under the shared lock.

    `mutator` receives the full document and edits it in place. Returns
    the resulting document. Write failures are swallowed (best-effort);
    the in-memory result is still returned so callers see their change.
    """
    if path is None:
        path = STATE_FILE
    with _lock:
        data = read_all(path)
        mutator(data)
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            tmp = path.with_suffix(path.suffix + ".tmp")
            tmp.write_text(json.dumps(data))
            tmp.replace(path)
        except OSError as e:
            logger.warning("Could not write state file %s: %s", path, e)
        return data
