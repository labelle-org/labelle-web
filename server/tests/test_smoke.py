"""Smoke tests: verify all server modules import cleanly and the Flask app starts."""

import importlib
from pathlib import Path

import pytest

# Every .py file under server/ (excluding __pycache__, tests, etc.)
# Keep this list in sync with what ships in the Docker image.
# If a new module is added to server/ but not listed here, the
# cross-check test below will fail — reminding you to update
# the Dockerfile's COPY instruction too.
SERVER_MODULES = [
    "app",
    "config",
    "label_builder",
    "power_save",
    "printer_service",
    "state_store",
    "usb_power",
    "virtual_printer",
]


class TestModuleImports:
    """Each server module must import without errors."""

    @pytest.mark.parametrize("module", SERVER_MODULES)
    def test_import(self, module):
        importlib.import_module(module)


class TestModuleListSync:
    """SERVER_MODULES must match the actual .py files on disk."""

    def test_no_unlisted_modules(self):
        server_dir = Path(__file__).resolve().parent.parent
        py_files = {
            f.stem
            for f in server_dir.glob("*.py")
            if f.name != "__init__.py"
        }
        unlisted = py_files - set(SERVER_MODULES)
        assert not unlisted, (
            f"Server modules not in SERVER_MODULES: {unlisted}. "
            "Add them to the list and make sure the Dockerfile copies them."
        )

    def test_no_stale_entries(self):
        server_dir = Path(__file__).resolve().parent.parent
        py_files = {
            f.stem
            for f in server_dir.glob("*.py")
            if f.name != "__init__.py"
        }
        stale = set(SERVER_MODULES) - py_files
        assert not stale, (
            f"SERVER_MODULES lists modules that no longer exist: {stale}. "
            "Remove them from the list."
        )


class TestStateFileOwnership:
    """state_store.py is the single owner of the on-disk state file."""

    def test_only_state_store_references_the_state_file(self):
        """Every other feature must persist via state_store.read_all/update
        so writes stay atomic and non-clobbering. Reaching for
        LABELLE_STATE_FILE elsewhere is how the pre-refactor usb_power saver
        introduced full-file overwrites — guard against reintroducing it.

        Catches the realistic regression (a new feature grabbing the env
        var); a hand-hardcoded path would slip through, which is an
        acceptable trade for a zero-false-positive check.
        """
        server_dir = Path(__file__).resolve().parent.parent
        offenders = [
            f.name
            for f in server_dir.glob("*.py")
            if f.name != "state_store.py" and "LABELLE_STATE_FILE" in f.read_text()
        ]
        assert not offenders, (
            f"{offenders} reference LABELLE_STATE_FILE directly; "
            "go through state_store.read_all/update instead."
        )


class TestFlaskApp:
    """The Flask app must create and register expected routes."""

    def test_app_creates(self):
        from app import app

        assert app is not None
        assert app.name == "app"

    @pytest.mark.parametrize(
        "rule",
        [
            "/api/print",
            "/api/preview",
            "/api/printers",
            "/api/upload-image",
            "/api/uploads/<filename>",
            "/api/health",
            "/api/power/status",
            "/api/power/on",
            "/api/power/off",
        ],
    )
    def test_route_registered(self, rule):
        from app import app

        rules = [r.rule for r in app.url_map.iter_rules()]
        assert rule in rules, f"Route {rule} not registered"
