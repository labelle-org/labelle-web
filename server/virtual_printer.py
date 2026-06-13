"""Virtual printer implementation for testing and development.

Virtual printers save label output to a configured directory instead of sending
to a physical USB printer. Output can be a preview PNG, label JSON, or both,
controlled by the `output_mode` setting.
"""

import datetime
import json
import logging
import os
import re
import uuid
from pathlib import Path

from PIL import Image

LOG = logging.getLogger(__name__)

# A virtual printer id suffix must be URL-safe: it travels in the
# /api/printers/<path:printer_id>/settings route. See #42.
_VIRTUAL_ID_CHARSET = re.compile(r"^[A-Za-z0-9_-]+$")


def slugify_printer_name(name: str) -> str:
    """Derive a path-safe id suffix from a printer name.

    Collapses any run of non-word characters (anything outside letters,
    digits, `_`, `-` — `\\w` keeps Unicode letters, which `%`-encode fine
    in a URL path) to a single `_` and trims leading/trailing `_`. The
    point is to drop path-hostile characters like `/`. Falls back to
    "printer" for a name with no usable characters, so the id is never an
    empty `virtual:` (a collision then surfaces via config validation)."""
    slug = re.sub(r"[^\w-]+", "_", name).strip("_")
    return slug or "printer"


def compute_virtual_id(name: str, explicit_id: str | None = None) -> str:
    """Full virtual printer id (`virtual:<suffix>`).

    Uses an explicit id when given (stable, decoupled from the display
    name; assumed already charset-validated by the config loader), else a
    URL-safe slug of the name."""
    suffix = explicit_id if explicit_id else slugify_printer_name(name)
    return f"virtual:{suffix}"


def is_valid_virtual_id(value) -> bool:
    """Whether an explicit config id is a non-empty URL-safe string."""
    return isinstance(value, str) and bool(_VIRTUAL_ID_CHARSET.match(value))


class VirtualPrinter:
    """Virtual printer that saves labels as PNG and/or JSON files."""

    VALID_OUTPUT_MODES = ("image", "json", "both")

    def __init__(
        self,
        name: str,
        output_path: str,
        output_mode: str = "image",
        printer_id: str | None = None,
    ):
        if output_mode not in self.VALID_OUTPUT_MODES:
            raise ValueError(
                f"Invalid output_mode '{output_mode}' for virtual printer '{name}'. "
                f"Must be one of: {', '.join(self.VALID_OUTPUT_MODES)}"
            )
        self.name = name
        self.output_path = output_path
        self.output_mode = output_mode
        # Optional stable id from config; when absent the id is slugged
        # from the name. See compute_virtual_id / #42.
        self._printer_id = printer_id
        self._ensure_output_directory()

    @classmethod
    def from_config(cls, config: dict) -> "VirtualPrinter":
        """Build from a validated VIRTUAL_PRINTERS entry, honoring an
        optional explicit `id`. Single construction path so every caller
        resolves the same id."""
        return cls(
            config["name"],
            config["path"],
            output_mode=config.get("output", "image"),
            printer_id=config.get("id"),
        )

    def _ensure_output_directory(self):
        """Create output directory if it doesn't exist."""
        try:
            Path(self.output_path).mkdir(parents=True, exist_ok=True)
            LOG.info(f"Virtual printer '{self.name}' output directory: {self.output_path}")
        except Exception as e:
            LOG.error(f"Failed to create output directory {self.output_path}: {e}")

    @property
    def id(self) -> str:
        """Stable `virtual:<suffix>` id — explicit config id, else name slug."""
        return compute_virtual_id(self.name, self._printer_id)

    @property
    def display_name(self) -> str:
        """Get display name with virtual indicator."""
        return f"{self.name} (Virtual)"

    def _generate_base_path(self) -> str:
        """Generate a unique base file path (without extension)."""
        timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
        unique_id = uuid.uuid4().hex[:8]
        return os.path.join(self.output_path, f"label_{timestamp}_{unique_id}")

    def save_preview(self, bitmap: Image.Image, base_path: str | None = None) -> str:
        """Save preview bitmap as PNG.

        Returns:
            Path to saved file.

        Raises:
            IOError: If file cannot be saved.
        """
        filepath = (base_path or self._generate_base_path()) + ".png"
        try:
            bitmap.save(filepath, format="PNG")
            LOG.info(f"Virtual printer '{self.name}' saved preview to: {filepath}")
            return filepath
        except Exception as e:
            LOG.error(f"Failed to save preview to {filepath}: {e}")
            raise IOError(f"Failed to save preview: {e}") from e

    def save_json(self, widgets: list[dict], settings: dict, base_path: str | None = None) -> str:
        """Save label data as JSON.

        Returns:
            Path to saved file.

        Raises:
            IOError: If file cannot be saved.
        """
        filepath = (base_path or self._generate_base_path()) + ".json"
        data = {"widgets": widgets, "settings": settings}
        try:
            with open(filepath, "w") as f:
                json.dump(data, f, indent=2)
            LOG.info(f"Virtual printer '{self.name}' saved JSON to: {filepath}")
            return filepath
        except Exception as e:
            LOG.error(f"Failed to save JSON to {filepath}: {e}")
            raise IOError(f"Failed to save JSON: {e}") from e

    def save(
        self,
        preview_bitmap: Image.Image,
        widgets: list[dict],
        settings: dict,
    ) -> list[str]:
        """Save output based on configured output_mode.

        Returns:
            List of saved file paths.
        """
        paths: list[str] = []
        base_path = self._generate_base_path()
        if self.output_mode in ("image", "both"):
            paths.append(self.save_preview(preview_bitmap, base_path))
        if self.output_mode in ("json", "both"):
            paths.append(self.save_json(widgets, settings, base_path))
        return paths
