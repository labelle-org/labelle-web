import io
import json
import os
from unittest.mock import patch

import pytest
from PIL import Image


@pytest.fixture
def client(virtual_printer_env):
    """Flask test client with virtual printers configured."""
    from app import app

    app.config["TESTING"] = True
    with app.test_client() as client:
        yield client


class TestApiPrintWithVirtualPrinter:
    @patch("app.print_label")
    def test_print_with_virtual_printer_id(self, mock_print, client):
        payload = {
            "widgets": [{"type": "text", "text": "Hello", "id": "1"}],
            "settings": {
                "tapeSizeMm": 12,
                "marginPx": 56,
                "minLengthMm": 0,
                "justify": "center",
                "foregroundColor": "black",
                "backgroundColor": "white",
                "showMargins": False,
                "printerId": "virtual:Test_Printer",
            },
        }

        resp = client.post(
            "/api/print",
            data=json.dumps(payload),
            content_type="application/json",
        )

        assert resp.status_code == 200
        mock_print.assert_called_once()
        # Verify printer_id was passed through
        call_kwargs = mock_print.call_args
        assert call_kwargs[1]["printer_id"] == "virtual:Test_Printer"

    @patch("app.print_label")
    def test_print_with_auto_select(self, mock_print, client):
        payload = {
            "widgets": [{"type": "text", "text": "Hello", "id": "1"}],
            "settings": {
                "tapeSizeMm": 12,
                "marginPx": 56,
                "minLengthMm": 0,
                "justify": "center",
                "foregroundColor": "black",
                "backgroundColor": "white",
                "showMargins": False,
            },
        }

        resp = client.post(
            "/api/print",
            data=json.dumps(payload),
            content_type="application/json",
        )

        assert resp.status_code == 200
        mock_print.assert_called_once()
        # Auto-select: printerId is absent, so printer_id should be None
        call_kwargs = mock_print.call_args
        assert call_kwargs[1]["printer_id"] is None

    @patch("app.print_label")
    def test_print_with_empty_string_printer_id(self, mock_print, client):
        """Frontend sends empty string when Auto-select is chosen."""
        payload = {
            "widgets": [{"type": "text", "text": "Hello", "id": "1"}],
            "settings": {
                "tapeSizeMm": 12,
                "marginPx": 56,
                "minLengthMm": 0,
                "justify": "center",
                "foregroundColor": "black",
                "backgroundColor": "white",
                "showMargins": False,
                "printerId": "",
            },
        }

        resp = client.post(
            "/api/print",
            data=json.dumps(payload),
            content_type="application/json",
        )

        assert resp.status_code == 200
        mock_print.assert_called_once()
        # Empty string from settings.get("printerId") — passed as-is
        call_kwargs = mock_print.call_args
        assert call_kwargs[1]["printer_id"] == ""


class TestApiPreview:
    @patch("app.preview_label")
    def test_returns_png_for_valid_text_widget(self, mock_preview, client):
        # Create a minimal valid PNG
        img = Image.new("RGB", (10, 10), "white")
        buf = io.BytesIO()
        img.save(buf, format="PNG")
        mock_preview.return_value = buf.getvalue()

        payload = {
            "widgets": [{"type": "text", "text": "Hello", "id": "1"}],
            "settings": {"tapeSizeMm": 12},
        }
        resp = client.post(
            "/api/preview",
            data=json.dumps(payload),
            content_type="application/json",
        )

        assert resp.status_code == 200
        assert resp.content_type == "image/png"
        assert resp.data[:8] == b"\x89PNG\r\n\x1a\n"

    def test_returns_400_for_empty_widgets(self, client):
        payload = {"widgets": [], "settings": {}}
        resp = client.post(
            "/api/preview",
            data=json.dumps(payload),
            content_type="application/json",
        )
        assert resp.status_code == 400

    def test_returns_400_for_missing_widgets_key(self, client):
        payload = {"settings": {}}
        resp = client.post(
            "/api/preview",
            data=json.dumps(payload),
            content_type="application/json",
        )
        assert resp.status_code == 400

    @patch("app.preview_label")
    def test_returns_500_when_preview_raises(self, mock_preview, client):
        mock_preview.side_effect = Exception("Render failed")

        payload = {
            "widgets": [{"type": "text", "text": "Hello", "id": "1"}],
            "settings": {"tapeSizeMm": 12},
        }
        resp = client.post(
            "/api/preview",
            data=json.dumps(payload),
            content_type="application/json",
        )

        assert resp.status_code == 500
        assert "Render failed" in resp.get_json()["message"]


class TestApiUploadImage:
    def test_uploads_png_returns_filename(self, client):
        img = Image.new("RGB", (10, 10), "red")
        buf = io.BytesIO()
        img.save(buf, format="PNG")
        buf.seek(0)

        resp = client.post(
            "/api/upload-image",
            data={"file": (buf, "test.png")},
            content_type="multipart/form-data",
        )

        assert resp.status_code == 200
        data = resp.get_json()
        assert "filename" in data
        assert data["filename"].endswith(".png")

    def test_rgba_image_saved_as_rgb(self, client):
        img = Image.new("RGBA", (10, 10), (255, 0, 0, 128))
        buf = io.BytesIO()
        img.save(buf, format="PNG")
        buf.seek(0)

        resp = client.post(
            "/api/upload-image",
            data={"file": (buf, "rgba.png")},
            content_type="multipart/form-data",
        )

        assert resp.status_code == 200
        filename = resp.get_json()["filename"]
        # Verify the saved file is RGB (transparency flattened)
        from app import UPLOAD_DIR

        saved = Image.open(os.path.join(UPLOAD_DIR, filename))
        assert saved.mode == "RGB"

    def test_returns_400_when_no_file(self, client):
        resp = client.post(
            "/api/upload-image",
            content_type="multipart/form-data",
        )
        assert resp.status_code == 400

    def test_returns_400_when_empty_filename(self, client):
        buf = io.BytesIO(b"fake")
        resp = client.post(
            "/api/upload-image",
            data={"file": (buf, "")},
            content_type="multipart/form-data",
        )
        assert resp.status_code == 400


class TestApiServeUpload:
    def test_serves_previously_uploaded_file(self, client):
        # Upload first
        img = Image.new("RGB", (5, 5), "blue")
        buf = io.BytesIO()
        img.save(buf, format="PNG")
        buf.seek(0)

        upload_resp = client.post(
            "/api/upload-image",
            data={"file": (buf, "serve_test.png")},
            content_type="multipart/form-data",
        )
        filename = upload_resp.get_json()["filename"]

        # Now serve it
        resp = client.get(f"/api/uploads/{filename}")
        assert resp.status_code == 200

    def test_returns_404_for_nonexistent_file(self, client):
        resp = client.get("/api/uploads/nonexistent_abc123.png")
        assert resp.status_code == 404


class TestApiHealth:
    def test_returns_ok_status(self, client):
        resp = client.get("/api/health")
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["status"] == "ok"

    def test_includes_version(self, client):
        resp = client.get("/api/health")
        data = resp.get_json()
        # SemVer MAJOR.MINOR.PATCH, optionally with -pre-release suffix
        assert "version" in data
        parts = data["version"].split(".")
        assert len(parts) == 3

    def test_includes_commit_and_branch_from_env(self, client, monkeypatch):
        monkeypatch.setenv("GIT_SHA", "abc1234")
        monkeypatch.setenv("GIT_BRANCH", "feature/foo")
        resp = client.get("/api/health")
        data = resp.get_json()
        assert data["commit"] == "abc1234"
        assert data["branch"] == "feature/foo"

    def test_falls_back_to_git_when_env_unset(self, client, monkeypatch):
        monkeypatch.delenv("GIT_SHA", raising=False)
        monkeypatch.delenv("GIT_BRANCH", raising=False)
        resp = client.get("/api/health")
        data = resp.get_json()
        # Tests run in the project git repo, so git fallback should work
        assert "commit" in data
        assert "branch" in data
        assert len(data["commit"]) >= 7  # short SHA

    def test_no_commit_branch_when_subprocess_fails(self, client, monkeypatch):
        monkeypatch.delenv("GIT_SHA", raising=False)
        monkeypatch.delenv("GIT_BRANCH", raising=False)
        import subprocess

        def boom(*args, **kwargs):
            raise FileNotFoundError("git not installed")

        monkeypatch.setattr(subprocess, "check_output", boom)
        resp = client.get("/api/health")
        data = resp.get_json()
        assert "commit" not in data
        assert "branch" not in data
        # status/version still present
        assert data["status"] == "ok"
        assert "version" in data


class TestApiPower:
    @patch("app.usb_power.get_port_status")
    @patch("app.usb_power.find_or_recall_printer_port")
    def test_status_returns_hub_port_and_state(self, mock_find, mock_status, client):
        mock_find.return_value = ("1-1", 3)
        mock_status.return_value = {"powered": True, "connected": True}
        resp = client.get("/api/power/status")
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["hub"] == "1-1"
        assert data["port"] == 3
        assert data["powered"] is True
        assert data["connected"] is True

    @patch("app.usb_power.find_or_recall_printer_port")
    def test_status_returns_404_when_no_printer(self, mock_find, client):
        mock_find.return_value = None
        resp = client.get("/api/power/status")
        assert resp.status_code == 404
        assert "not detected" in resp.get_json()["message"].lower()

    @patch("app.time.sleep")
    @patch("app.usb_power.get_port_status")
    @patch("app.usb_power.power_on")
    @patch("app.usb_power.find_or_recall_printer_port")
    def test_on_powers_and_returns_status(
        self, mock_find, mock_on, mock_status, mock_sleep, client
    ):
        mock_find.return_value = ("1-1", 3)
        mock_status.return_value = {"powered": True, "connected": True}
        resp = client.post("/api/power/on")
        assert resp.status_code == 200
        mock_on.assert_called_once_with("1-1", 3)
        data = resp.get_json()
        assert data["powered"] is True

    @patch("app.usb_power.get_port_status")
    @patch("app.usb_power.power_off")
    @patch("app.usb_power.find_or_recall_printer_port")
    def test_off_powers_and_returns_status(
        self, mock_find, mock_off, mock_status, client
    ):
        mock_find.return_value = ("1-1", 3)
        mock_status.return_value = {"powered": False, "connected": False}
        resp = client.post("/api/power/off")
        assert resp.status_code == 200
        mock_off.assert_called_once_with("1-1", 3)
        assert resp.get_json()["powered"] is False

    @patch("app.usb_power.find_or_recall_printer_port")
    def test_on_returns_404_when_no_known_port(self, mock_find, client):
        mock_find.return_value = None
        resp = client.post("/api/power/on")
        assert resp.status_code == 404

    @patch("app.usb_power.find_or_recall_printer_port")
    def test_off_returns_404_when_no_known_port(self, mock_find, client):
        mock_find.return_value = None
        resp = client.post("/api/power/off")
        assert resp.status_code == 404

    @patch("app.time.sleep")
    @patch("app.usb_power.power_on")
    @patch("app.usb_power.find_or_recall_printer_port")
    def test_on_returns_500_when_uhubctl_fails(
        self, mock_find, mock_on, mock_sleep, client
    ):
        import subprocess

        mock_find.return_value = ("1-1", 3)
        mock_on.side_effect = subprocess.CalledProcessError(1, "uhubctl")
        resp = client.post("/api/power/on")
        assert resp.status_code == 500
        assert resp.get_json()["status"] == "error"

    @patch("app.usb_power.get_port_status")
    @patch("app.usb_power.find_or_recall_printer_port")
    def test_status_returns_500_envelope_on_parse_error(
        self, mock_find, mock_status, client
    ):
        mock_find.return_value = ("1-1", 3)
        mock_status.side_effect = ValueError("Port 3 not found on hub 1-1")
        resp = client.get("/api/power/status")
        assert resp.status_code == 500
        data = resp.get_json()
        assert data["status"] == "error"
        assert "Port 3" in data["message"]

    @patch("app.usb_power.get_port_status")
    @patch("app.usb_power.find_or_recall_printer_port")
    def test_status_returns_500_envelope_on_subprocess_error(
        self, mock_find, mock_status, client
    ):
        import subprocess

        mock_find.return_value = ("1-1", 3)
        mock_status.side_effect = subprocess.CalledProcessError(1, "uhubctl")
        resp = client.get("/api/power/status")
        assert resp.status_code == 500
        assert resp.get_json()["status"] == "error"

    @patch("app.usb_power.get_port_status")
    @patch("app.usb_power.power_off")
    @patch("app.usb_power.find_or_recall_printer_port")
    def test_off_returns_500_envelope_when_post_status_fails(
        self, mock_find, mock_off, mock_status, client
    ):
        # power_off itself succeeds, but the post-action status read fails.
        mock_find.return_value = ("1-1", 3)
        mock_status.side_effect = ValueError("parse failure")
        resp = client.post("/api/power/off")
        assert resp.status_code == 500
        assert resp.get_json()["status"] == "error"


class TestPowerSaveHook:
    """The before_request hook should record activity for normal routes and
    skip the noisy/feedback-loop ones (health, power-control)."""

    @patch("app.power_save.record_activity")
    def test_health_does_not_record_activity(self, mock_record, client):
        client.get("/api/health")
        mock_record.assert_not_called()

    @patch("app.power_save.ensure_powered")
    @patch("app.power_save.record_activity")
    def test_power_status_does_not_record_activity(
        self, mock_record, mock_ensure, client
    ):
        with patch("app.usb_power.find_or_recall_printer_port", return_value=None):
            client.get("/api/power/status")
        mock_record.assert_not_called()
        mock_ensure.assert_not_called()

    @patch("app.power_save.ensure_powered")
    @patch("app.power_save.record_activity")
    @patch("app.list_printers", return_value=[])
    def test_printers_records_activity_and_wakes(
        self, mock_list, mock_record, mock_ensure, client
    ):
        client.get("/api/printers")
        mock_record.assert_called_once()
        mock_ensure.assert_called_once()

    @patch("app.power_save.ensure_powered")
    @patch("app.power_save.record_activity")
    @patch("app.preview_label")
    def test_preview_records_activity_and_wakes(
        self, mock_preview, mock_record, mock_ensure, client
    ):
        import io

        img = Image.new("RGB", (10, 10), "white")
        buf = io.BytesIO()
        img.save(buf, format="PNG")
        mock_preview.return_value = buf.getvalue()
        client.post(
            "/api/preview",
            data=json.dumps(
                {"widgets": [{"type": "text", "text": "x", "id": "1"}], "settings": {}}
            ),
            content_type="application/json",
        )
        mock_record.assert_called_once()
        mock_ensure.assert_called_once()

    @patch("app.power_save.ensure_powered")
    @patch("app.power_save.record_activity")
    @patch("app.list_printers", return_value=[])
    def test_ensure_powered_failure_does_not_break_request(
        self, mock_list, mock_record, mock_ensure, client
    ):
        mock_ensure.side_effect = RuntimeError("uhubctl exploded")
        resp = client.get("/api/printers")
        # The before_request hook swallowed the failure; the route still 200s.
        assert resp.status_code == 200


class TestApiPrintErrors:
    @patch("app.print_label")
    def test_returns_400_for_empty_widgets(self, mock_print, client):
        payload = {"widgets": [], "settings": {}}
        resp = client.post(
            "/api/print",
            data=json.dumps(payload),
            content_type="application/json",
        )
        assert resp.status_code == 400
        mock_print.assert_not_called()

    @patch("app.print_label")
    def test_returns_500_when_print_raises(self, mock_print, client):
        mock_print.side_effect = Exception("Printer on fire")

        payload = {
            "widgets": [{"type": "text", "text": "Hello", "id": "1"}],
            "settings": {"tapeSizeMm": 12},
        }
        resp = client.post(
            "/api/print",
            data=json.dumps(payload),
            content_type="application/json",
        )

        assert resp.status_code == 500
        assert "Printer on fire" in resp.get_json()["message"]


class TestPrinterSettingsEndpoints:
    """GET/PUT /api/printers/<id>/settings — per-printer settings (issue #20)."""

    @pytest.fixture
    def state_file(self, tmp_path, monkeypatch):
        import state_store

        path = tmp_path / "state.json"
        monkeypatch.setattr(state_store, "STATE_FILE", path)
        return path

    def test_get_returns_empty_when_unsaved(self, client, state_file):
        resp = client.get("/api/printers/virtual:Test_Printer/settings")
        assert resp.status_code == 200
        assert resp.get_json() == {"settings": {}}

    def test_put_then_get_round_trips(self, client, state_file):
        body = {"tapeSizeMm": 19, "foregroundColor": "white", "backgroundColor": "blue"}
        put = client.put(
            "/api/printers/virtual:Test_Printer/settings",
            data=json.dumps(body),
            content_type="application/json",
        )
        assert put.status_code == 200
        assert put.get_json()["settings"] == body

        got = client.get("/api/printers/virtual:Test_Printer/settings")
        assert got.get_json() == {"settings": body}

    def test_put_invalid_value_returns_400(self, client, state_file):
        resp = client.put(
            "/api/printers/virtual:Test_Printer/settings",
            data=json.dumps({"tapeSizeMm": 13}),
            content_type="application/json",
        )
        assert resp.status_code == 400
        assert resp.get_json()["status"] == "error"

    def test_put_unknown_key_returns_400(self, client, state_file):
        resp = client.put(
            "/api/printers/virtual:Test_Printer/settings",
            data=json.dumps({"marginPx": 10}),
            content_type="application/json",
        )
        assert resp.status_code == 400

    def test_put_non_json_body_returns_400_without_clearing(self, client, state_file):
        # Seed a saved value, then send a malformed PUT.
        client.put(
            "/api/printers/virtual:Test_Printer/settings",
            data=json.dumps({"tapeSizeMm": 19}),
            content_type="application/json",
        )
        resp = client.put(
            "/api/printers/virtual:Test_Printer/settings",
            data="not json",
            content_type="text/plain",
        )
        assert resp.status_code == 400
        # The previously-saved value must survive — not be wiped to {}.
        got = client.get("/api/printers/virtual:Test_Printer/settings")
        assert got.get_json() == {"settings": {"tapeSizeMm": 19}}

    def test_ids_with_spaces_and_colons_round_trip(self, client, state_file):
        # Real USB ids look like "Bus 001 Device 005: ID 0922:1234".
        from urllib.parse import quote

        printer_id = "Bus 001 Device 005: ID 0922:1234"
        encoded = quote(printer_id, safe="")
        client.put(
            f"/api/printers/{encoded}/settings",
            data=json.dumps({"tapeSizeMm": 6}),
            content_type="application/json",
        )
        got = client.get(f"/api/printers/{encoded}/settings")
        assert got.get_json() == {"settings": {"tapeSizeMm": 6}}
