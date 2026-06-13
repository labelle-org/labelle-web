"""Configuration loader for Labelle Web server.

Loads environment variables and provides configuration for features like virtual printers.
"""

import json
import logging
import os

from virtual_printer import compute_virtual_id, is_valid_virtual_id

LOG = logging.getLogger(__name__)

VALID_OUTPUT_MODES = {"image", "json", "both"}


def get_virtual_printers() -> list[dict]:
    """Load virtual printer configuration from VIRTUAL_PRINTERS environment variable.

    Expected format: JSON array of objects with 'name' and 'path', plus optional
    'output' and 'id' fields.
    Example: [{"name": "Office Printer", "path": "./output/office", "output": "both", "id": "office"}]

    The 'output' field controls what files are saved: "image" (default), "json", or "both".

    The optional 'id' gives the printer a stable identity (URL-safe
    [A-Za-z0-9_-]) decoupled from its display name; when omitted the id is
    slugged from the name. Entries with an invalid or colliding id are
    skipped with a warning. See #42.

    Returns:
        List of virtual printer configuration dictionaries.
        Returns empty list if not configured or on parse error.
    """
    virtual_printers_env = os.environ.get("VIRTUAL_PRINTERS", "")
    if not virtual_printers_env.strip():
        return []

    try:
        printers = json.loads(virtual_printers_env)
        if not isinstance(printers, list):
            LOG.error("VIRTUAL_PRINTERS must be a JSON array")
            return []

        # Validate structure
        valid_printers = []
        seen_ids: dict[str, str] = {}
        for printer in printers:
            if not isinstance(printer, dict):
                LOG.warning(f"Skipping invalid virtual printer config: {printer}")
                continue
            if "name" not in printer or "path" not in printer:
                LOG.warning(f"Virtual printer missing 'name' or 'path': {printer}")
                continue
            if not isinstance(printer["name"], str) or not isinstance(printer["path"], str):
                # Skip rather than letting a non-string name/path crash id
                # computation (re.sub) or directory creation downstream.
                LOG.warning(f"Virtual printer 'name' and 'path' must be strings: {printer}")
                continue

            output = printer.get("output", "image")
            if output not in VALID_OUTPUT_MODES:
                LOG.warning(f"Invalid output mode '{output}' for virtual printer '{printer['name']}' (must be one of {VALID_OUTPUT_MODES})")
                continue
            printer.setdefault("output", "image")

            # Optional explicit id (stable, decoupled from the name). Must be
            # URL-safe since it travels in the settings route path. See #42.
            explicit_id = printer.get("id")
            if explicit_id is not None and not is_valid_virtual_id(explicit_id):
                LOG.warning(
                    f"Skipping virtual printer '{printer['name']}': id {explicit_id!r} "
                    "must be a non-empty string of [A-Za-z0-9_-]"
                )
                continue

            # Reject ids that collide with an earlier entry — otherwise both
            # would share one settings entry and the second would be shadowed
            # at print time (_find_virtual_printer returns the first match).
            pid = compute_virtual_id(printer["name"], explicit_id)
            if pid in seen_ids:
                LOG.warning(
                    f"Skipping virtual printer '{printer['name']}': id '{pid}' "
                    f"collides with earlier printer '{seen_ids[pid]}'"
                )
                continue
            seen_ids[pid] = printer["name"]

            valid_printers.append(printer)

        LOG.info(f"Loaded {len(valid_printers)} virtual printer(s) from config")
        return valid_printers
    except json.JSONDecodeError as e:
        LOG.error(f"Failed to parse VIRTUAL_PRINTERS environment variable: {e}")
        return []
