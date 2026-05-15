"""Tests for the /api/batch-print and /api/batch-print/cancel endpoints."""
import json
from unittest.mock import patch

import pytest


@pytest.fixture
def client(virtual_printer_env):
    from app import app

    app.config["TESTING"] = True
    # Drain any leftover jobs from prior tests (the module-level dict is
    # process-wide and tests share it).
    from app import _batch_jobs

    _batch_jobs.clear()
    with app.test_client() as client:
        yield client


def _settings():
    return {
        "tapeSizeMm": 12,
        "marginPx": 56,
        "minLengthMm": 0,
        "justify": "center",
        "foregroundColor": "black",
        "backgroundColor": "white",
        "showMargins": False,
        "printerId": "virtual:Test_Printer",
    }


def _widget():
    return {"type": "text", "text": "Hello :name:", "id": "1"}


def _read_sse(resp):
    """Drain an SSE response into a list of event dicts."""
    events = []
    buffer = ""
    for chunk in resp.response:
        buffer += chunk.decode()
        while "\n\n" in buffer:
            frame, buffer = buffer.split("\n\n", 1)
            for line in frame.split("\n"):
                if line.startswith("data: "):
                    events.append(json.loads(line[6:]))
    return events


class TestBatchPrintValidation:
    def test_missing_widgets_returns_400(self, client):
        resp = client.post(
            "/api/batch-print",
            data=json.dumps({"widgets": [], "settings": _settings(), "rows": [{}]}),
            content_type="application/json",
        )
        assert resp.status_code == 400
        assert resp.json["message"] == "No widgets provided"

    def test_missing_rows_returns_400(self, client):
        resp = client.post(
            "/api/batch-print",
            data=json.dumps({"widgets": [_widget()], "settings": _settings(), "rows": []}),
            content_type="application/json",
        )
        assert resp.status_code == 400
        assert resp.json["message"] == "No rows provided"

    def test_non_numeric_copies_returns_400(self, client):
        resp = client.post(
            "/api/batch-print",
            data=json.dumps({
                "widgets": [_widget()],
                "settings": _settings(),
                "rows": [{"name": "A"}],
                "copies": "lots",
            }),
            content_type="application/json",
        )
        assert resp.status_code == 400
        assert "numeric" in resp.json["message"]

    def test_copies_above_max_returns_400(self, client):
        resp = client.post(
            "/api/batch-print",
            data=json.dumps({
                "widgets": [_widget()],
                "settings": _settings(),
                "rows": [{"name": "A"}],
                "copies": 9999,
            }),
            content_type="application/json",
        )
        assert resp.status_code == 400
        assert "copies" in resp.json["message"]

    def test_pause_above_max_returns_400(self, client):
        resp = client.post(
            "/api/batch-print",
            data=json.dumps({
                "widgets": [_widget()],
                "settings": _settings(),
                "rows": [{"name": "A"}],
                "pauseTime": 600,
            }),
            content_type="application/json",
        )
        assert resp.status_code == 400
        assert "pauseTime" in resp.json["message"]

    def test_too_many_rows_returns_400(self, client):
        from app import MAX_BATCH_ROWS

        rows = [{"name": str(i)} for i in range(MAX_BATCH_ROWS + 1)]
        resp = client.post(
            "/api/batch-print",
            data=json.dumps({
                "widgets": [_widget()],
                "settings": _settings(),
                "rows": rows,
            }),
            content_type="application/json",
        )
        assert resp.status_code == 400
        assert "Too many rows" in resp.json["message"]

    def test_too_large_total_returns_400(self, client):
        # 100 rows × 200 copies = 20000, well over MAX_BATCH_TOTAL=10000
        rows = [{"name": str(i)} for i in range(100)]
        resp = client.post(
            "/api/batch-print",
            data=json.dumps({
                "widgets": [_widget()],
                "settings": _settings(),
                "rows": rows,
                "copies": 200,
            }),
            content_type="application/json",
        )
        assert resp.status_code == 400
        assert "Batch too large" in resp.json["message"]

    def test_non_dict_row_returns_400(self, client):
        resp = client.post(
            "/api/batch-print",
            data=json.dumps({
                "widgets": [_widget()],
                "settings": _settings(),
                "rows": [{"name": "A"}, "not-a-dict"],
            }),
            content_type="application/json",
        )
        assert resp.status_code == 400
        assert "Row 1" in resp.json["message"]

    def test_pause_budget_too_long_returns_400(self, client):
        # 1000 rows × 1 copy × 60s pause = 60000s ≈ 16.7h, over the 8h cap.
        rows = [{"name": str(i)} for i in range(1000)]
        resp = client.post(
            "/api/batch-print",
            data=json.dumps({
                "widgets": [_widget()],
                "settings": _settings(),
                "rows": rows,
                "copies": 1,
                "pauseTime": 60,
            }),
            content_type="application/json",
        )
        assert resp.status_code == 400
        assert "pause budget" in resp.json["message"]

    @patch("app.print_label")
    def test_non_string_value_is_coerced(self, mock_print, client):
        # Non-string values shouldn't crash the SSE stream — they get coerced
        # to strings during row validation.
        resp = client.post(
            "/api/batch-print",
            data=json.dumps({
                "widgets": [_widget()],
                "settings": _settings(),
                "rows": [{"name": 42}],
            }),
            content_type="application/json",
        )
        assert resp.status_code == 200
        _read_sse(resp)
        call_widgets = mock_print.call_args_list[0][0][0]
        assert call_widgets[0]["text"] == "Hello 42"


class TestBatchPrintExecution:
    @patch("app.print_label")
    def test_prints_each_row_with_substitution(self, mock_print, client):
        resp = client.post(
            "/api/batch-print",
            data=json.dumps({
                "widgets": [_widget()],
                "settings": _settings(),
                "rows": [{"name": "Alice"}, {"name": "Bob"}],
            }),
            content_type="application/json",
        )
        assert resp.status_code == 200
        events = _read_sse(resp)
        assert events[0]["event"] == "started"
        assert events[0]["total"] == 2
        assert events[-1]["event"] == "done"
        assert mock_print.call_count == 2
        # First call substituted "Alice"
        first_call_widgets = mock_print.call_args_list[0][0][0]
        assert first_call_widgets[0]["text"] == "Hello Alice"
        # Second call substituted "Bob"
        second_call_widgets = mock_print.call_args_list[1][0][0]
        assert second_call_widgets[0]["text"] == "Hello Bob"

    @patch("app.print_label")
    def test_missing_value_leaves_placeholder_literal(self, mock_print, client):
        # Rationale: visible "you forgot" indicator. Empty-string values
        # are substituted as empty (separate behavior).
        resp = client.post(
            "/api/batch-print",
            data=json.dumps({
                "widgets": [_widget()],
                "settings": _settings(),
                "rows": [{}],  # no "name" key at all
            }),
            content_type="application/json",
        )
        assert resp.status_code == 200
        _read_sse(resp)
        call_widgets = mock_print.call_args_list[0][0][0]
        assert call_widgets[0]["text"] == "Hello :name:"

    @patch("app.print_label")
    def test_empty_string_value_substitutes_as_empty(self, mock_print, client):
        resp = client.post(
            "/api/batch-print",
            data=json.dumps({
                "widgets": [_widget()],
                "settings": _settings(),
                "rows": [{"name": ""}],
            }),
            content_type="application/json",
        )
        assert resp.status_code == 200
        _read_sse(resp)
        call_widgets = mock_print.call_args_list[0][0][0]
        assert call_widgets[0]["text"] == "Hello "

    @patch("app.print_label")
    def test_copies_multiplies_rows(self, mock_print, client):
        resp = client.post(
            "/api/batch-print",
            data=json.dumps({
                "widgets": [_widget()],
                "settings": _settings(),
                "rows": [{"name": "A"}, {"name": "B"}],
                "copies": 3,
            }),
            content_type="application/json",
        )
        assert resp.status_code == 200
        events = _read_sse(resp)
        assert events[0]["total"] == 6
        assert mock_print.call_count == 6

    @patch("app.print_label")
    def test_pops_completed_job_from_tracking(self, mock_print, client):
        from app import _batch_jobs

        resp = client.post(
            "/api/batch-print",
            data=json.dumps({
                "widgets": [_widget()],
                "settings": _settings(),
                "rows": [{"name": "Alice"}],
            }),
            content_type="application/json",
        )
        assert resp.status_code == 200
        _read_sse(resp)
        # The job should be cleared once the stream completes (no memory leak).
        assert _batch_jobs == {}


class TestBatchPrintHeaders:
    @patch("app.print_label")
    def test_sse_response_has_anti_buffering_headers(self, mock_print, client):
        resp = client.post(
            "/api/batch-print",
            data=json.dumps({
                "widgets": [_widget()],
                "settings": _settings(),
                "rows": [{"name": "A"}],
            }),
            content_type="application/json",
        )
        assert resp.headers.get("Cache-Control") == "no-cache"
        assert resp.headers.get("X-Accel-Buffering") == "no"
        _read_sse(resp)  # drain


class TestBatchPrintConcurrency:
    def test_returns_409_when_another_job_running(self, client):
        # Seed a fake in-flight job in the tracker.
        from app import _batch_jobs

        _batch_jobs["fake"] = {"cancelled": False}

        resp = client.post(
            "/api/batch-print",
            data=json.dumps({
                "widgets": [_widget()],
                "settings": _settings(),
                "rows": [{"name": "A"}],
            }),
            content_type="application/json",
        )
        assert resp.status_code == 409
        assert "already running" in resp.json["message"]
        _batch_jobs.clear()


class TestBatchCancel:
    def test_cancel_unknown_job_returns_404(self, client):
        resp = client.post(
            "/api/batch-print/cancel",
            data=json.dumps({"jobId": "does-not-exist"}),
            content_type="application/json",
        )
        assert resp.status_code == 404

    def test_cancel_sets_flag_on_running_job(self, client):
        from app import _batch_jobs

        _batch_jobs["live"] = {"cancelled": False}
        resp = client.post(
            "/api/batch-print/cancel",
            data=json.dumps({"jobId": "live"}),
            content_type="application/json",
        )
        assert resp.status_code == 200
        assert _batch_jobs["live"]["cancelled"] is True
        _batch_jobs.clear()

    @patch("app.print_label")
    def test_cancellation_stops_batch_between_prints(self, mock_print, client):
        # Set the cancelled flag from the first print_label call so the
        # next iteration's check sees it.
        from app import _batch_jobs

        def cancel_after_first_call(*args, **kwargs):
            for job in _batch_jobs.values():
                job["cancelled"] = True

        mock_print.side_effect = cancel_after_first_call
        resp = client.post(
            "/api/batch-print",
            data=json.dumps({
                "widgets": [_widget()],
                "settings": _settings(),
                "rows": [{"name": "A"}, {"name": "B"}, {"name": "C"}],
            }),
            content_type="application/json",
        )
        assert resp.status_code == 200
        events = _read_sse(resp)
        assert mock_print.call_count == 1
        assert any(e["event"] == "cancelled" for e in events)
