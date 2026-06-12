import json
import logging
import math
import os
import re
import subprocess
import tempfile
import threading
import time
import traceback
import uuid

from dotenv import load_dotenv

load_dotenv(os.path.join(os.path.dirname(__file__), "..", ".env"))

# Configure root logging before any module-level loggers emit. Default
# is WARNING (production-safe — only surface things an operator should
# actually look at). `.env.example` sets LOG_LEVEL=DEBUG so dev defaults
# to verbose via `npm run dev`; production deployments without a .env
# stay at WARNING, or can dial up via the env var as needed.
#
# Resolve LOG_LEVEL defensively: passing an unrecognized value (typo,
# numeric like "20", whitespace) straight to basicConfig would raise
# ValueError at import and prevent the server from starting. Fall back
# to WARNING and surface the bad value once logging is configured.
_raw_log_level = os.environ.get("LOG_LEVEL", "WARNING").upper()
_log_level = getattr(logging, _raw_log_level, None)
if not isinstance(_log_level, int):
    _log_level = logging.WARNING

logging.basicConfig(
    level=_log_level,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)

if os.environ.get("LOG_LEVEL") is not None and not isinstance(
    getattr(logging, os.environ["LOG_LEVEL"].upper(), None), int
):
    logging.warning(
        "Unrecognized LOG_LEVEL=%r; using WARNING.", os.environ["LOG_LEVEL"]
    )

from flask import Flask, Response, jsonify, request, send_from_directory
from flask_cors import CORS
from labelle.lib.constants import DEFAULT_MARGIN_PX
from werkzeug.utils import secure_filename

import power_save
import printer_settings
import usb_power
from label_builder import paint_cut_mark_in_trailing_margin, preview_label, render_payload
from printer_service import list_printers, print_bitmap, print_label

# Seconds to wait after power-on before reading status, so the device has
# time to re-enumerate on the USB bus.
POWER_ON_SETTLE_SECONDS = 1.5

# Routes that should NOT count as "activity" for the idle timer:
# - /api/health: monitoring tools poll it constantly, would keep the
#   printer awake forever
# - /api/power/*: manual control endpoints, shouldn't feed back into
#   the auto-idle logic
_POWER_SAVE_IGNORED_PATHS = ("/api/health",)
_POWER_SAVE_IGNORED_PREFIXES = ("/api/power/",)

# Routes that need the printer to be powered on. The before_request
# hook will block on a power-on for these if the saver has turned the
# port off. Membership check uses exact equality (not prefix), so
# /api/batch-print triggers wake-up but /api/batch-print/cancel
# deliberately does not — cancelling shouldn't be gated on the
# printer being awake.
_PRINTER_USING_PATHS = (
    "/api/print",
    "/api/preview",
    "/api/printers",
    "/api/upload-image",
    "/api/batch-print",
)

app = Flask(__name__, static_folder=None)
CORS(app)

DIST_DIR = os.path.join(os.path.dirname(__file__), "dist-client")
UPLOAD_DIR = tempfile.mkdtemp(prefix="labelle-uploads-")

# Batch job tracking
_batch_jobs: dict[str, dict] = {}
_batch_lock = threading.Lock()

# Caps for batch requests. Untrusted JSON otherwise; without these a client
# could tie up the printer indefinitely and lock out every other batch run.
MAX_BATCH_COPIES = 999
MAX_BATCH_ROWS = 1000
MAX_BATCH_TOTAL = 10000
MAX_BATCH_PAUSE_SECONDS = 60
# Cap on total pause time (total labels × pause). Individual caps don't bound
# the product — 10000 × 60s would be ~7 days holding the print slot — so the
# combined wall-clock budget caps that out at 8h.
MAX_BATCH_DURATION_SECONDS = 8 * 3600


@app.before_request
def _track_activity_and_wake_printer():
    path = request.path
    if path in _POWER_SAVE_IGNORED_PATHS:
        return
    if any(path.startswith(p) for p in _POWER_SAVE_IGNORED_PREFIXES):
        return
    power_save.record_activity()
    if path in _PRINTER_USING_PATHS:
        try:
            power_save.ensure_powered()
        except Exception:
            # ensure_powered failures must not break the request — the
            # downstream handler will fail loudly enough on its own if
            # the printer really isn't there.
            traceback.print_exc()


power_save.start()


def _print_label_with_cut_mark(
    widgets: list, settings: dict, printer_id: str | None
) -> None:
    """Print a label with a cut mark painted into its trailing margin.

    Renders the label normally then injects the dotted column into the
    already-allocated trailing blank — no extra tape consumed, dot
    sits in the middle of what would otherwise be the inter-label gap.
    """
    bitmap = render_payload(widgets, settings, upload_dir=UPLOAD_DIR)
    paint_cut_mark_in_trailing_margin(
        bitmap, margin_px=settings.get("marginPx", DEFAULT_MARGIN_PX)
    )
    print_bitmap(bitmap, settings, printer_id=printer_id, widgets=widgets)


@app.route("/api/print", methods=["POST"])
def api_print():
    data = request.get_json(silent=True) or {}
    widgets = data.get("widgets")
    settings = data.get("settings", {})
    printer_id = settings.get("printerId")  # Optional printer ID from settings

    if not widgets or not isinstance(widgets, list) or len(widgets) == 0:
        return jsonify(status="error", message="No widgets provided"), 400

    try:
        print_label(widgets, settings, upload_dir=UPLOAD_DIR, printer_id=printer_id)
        return jsonify(status="success", message="Label sent to printer.")
    except Exception as e:
        traceback.print_exc()
        return jsonify(status="error", message=str(e)), 500


@app.route("/api/preview", methods=["POST"])
def api_preview():
    data = request.get_json(silent=True) or {}
    widgets = data.get("widgets")
    settings = data.get("settings", {})

    if not widgets or not isinstance(widgets, list) or len(widgets) == 0:
        return jsonify(status="error", message="No widgets provided"), 400

    try:
        png_bytes = preview_label(widgets, settings, upload_dir=UPLOAD_DIR)
        return app.response_class(png_bytes, mimetype="image/png")
    except Exception as e:
        traceback.print_exc()
        return jsonify(status="error", message=str(e)), 500


@app.route("/api/upload-image", methods=["POST"])
def api_upload_image():
    if "file" not in request.files:
        return jsonify(status="error", message="No file provided"), 400

    file = request.files["file"]
    if not file.filename:
        return jsonify(status="error", message="No file selected"), 400

    filename = f"{uuid.uuid4().hex}.png"
    filepath = os.path.join(UPLOAD_DIR, filename)

    # Flatten transparency onto white background so labelle's grayscale
    # conversion doesn't turn transparent pixels black.
    from PIL import Image

    img = Image.open(file.stream)
    if img.mode in ("RGBA", "LA", "PA"):
        background = Image.new("RGB", img.size, (255, 255, 255))
        background.paste(img, mask=img.getchannel("A"))
        img = background
    elif img.mode != "RGB":
        img = img.convert("RGB")
    img.save(filepath, format="PNG")

    return jsonify(filename=filename)


@app.route("/api/uploads/<filename>")
def api_serve_upload(filename):
    filename = secure_filename(filename)
    return send_from_directory(UPLOAD_DIR, filename)


@app.route("/api/printers", methods=["GET"])
def api_printers():
    return jsonify(printers=list_printers())


# Per-printer label settings (issue #20). Printer ids contain spaces and
# colons (e.g. "Bus 001 Device 005: ID 0922:1234", "virtual:Office"), so
# the client URL-encodes them and we take the whole segment via <path:>.
@app.route("/api/printers/<path:printer_id>/settings", methods=["GET"])
def api_get_printer_settings(printer_id):
    return jsonify(settings=printer_settings.get_settings(printer_id))


@app.route("/api/printers/<path:printer_id>/settings", methods=["PUT"])
def api_put_printer_settings(printer_id):
    body = request.get_json(silent=True) or {}
    try:
        saved = printer_settings.save_settings(printer_id, body)
    except ValueError as e:
        return jsonify(status="error", message=str(e)), 400
    return jsonify(status="success", settings=saved)


def _printer_port_or_404():
    port = usb_power.find_or_recall_printer_port()
    if port is None:
        return None, (jsonify(status="error", message="Printer not detected"), 404)
    return port, None


# Errors that the /api/power/* endpoints translate into a 500 with a
# JSON {status, message} body: uhubctl failed to run, hung, isn't
# installed, or produced output get_port_status couldn't parse.
_POWER_ERRORS = (subprocess.SubprocessError, ValueError, OSError)


def _power_error_response(e: Exception):
    traceback.print_exc()
    return jsonify(status="error", message=str(e)), 500


@app.route("/api/power/status", methods=["GET"])
def api_power_status():
    port, err = _printer_port_or_404()
    if err:
        return err
    hub, port_num = port
    try:
        status = usb_power.get_port_status(hub, port_num)
    except _POWER_ERRORS as e:
        return _power_error_response(e)
    return jsonify(hub=hub, port=port_num, **status)


@app.route("/api/power/on", methods=["POST"])
def api_power_on():
    port, err = _printer_port_or_404()
    if err:
        return err
    hub, port_num = port
    try:
        usb_power.power_on(hub, port_num)
        time.sleep(POWER_ON_SETTLE_SECONDS)
        status = usb_power.get_port_status(hub, port_num)
    except _POWER_ERRORS as e:
        return _power_error_response(e)
    return jsonify(status="success", hub=hub, port=port_num, **status)


@app.route("/api/power/off", methods=["POST"])
def api_power_off():
    port, err = _printer_port_or_404()
    if err:
        return err
    hub, port_num = port
    try:
        usb_power.power_off(hub, port_num)
        status = usb_power.get_port_status(hub, port_num)
    except _POWER_ERRORS as e:
        return _power_error_response(e)
    return jsonify(status="success", hub=hub, port=port_num, **status)


_VAR_PATTERN = re.compile(r"\{\{([\w-]+)\}\}")


def _substitute_widgets(widgets, values):
    """Replace {{varname}} placeholders in widget text/content fields.

    Each widget is shallow-copied because only the immutable string fields
    `text`/`content` are reassigned — deepcopy was wasteful per row × per
    copy at batch scale. Values are coerced to str so a stray non-string
    slipping past validation doesn't crash re.sub's callback.
    """
    result = []
    for widget in widgets:
        new_widget = dict(widget)
        for field in ("text", "content"):
            if isinstance(new_widget.get(field), str):
                new_widget[field] = _VAR_PATTERN.sub(
                    lambda m: str(values.get(m.group(1), m.group(0))),
                    new_widget[field],
                )
        result.append(new_widget)
    return result


@app.route("/api/batch-print", methods=["POST"])
def api_batch_print():
    data = request.get_json(silent=True) or {}
    widgets = data.get("widgets")
    settings = data.get("settings", {})
    printer_id = settings.get("printerId")
    rows = data.get("rows", [])

    # Presence checks first: a user with both missing widgets and bad
    # copies should hear about the more fundamental problem first.
    if not widgets or not isinstance(widgets, list) or len(widgets) == 0:
        return jsonify(status="error", message="No widgets provided"), 400
    if not rows or not isinstance(rows, list):
        return jsonify(status="error", message="No rows provided"), 400
    if len(rows) > MAX_BATCH_ROWS:
        return jsonify(status="error", message=f"Too many rows (max {MAX_BATCH_ROWS})"), 400

    raw_copies = data.get("copies", 1)
    # Reject bool (True/False are ints in Python) and non-integer numerics
    # like 1.9 — silent truncation is surprising for API consumers.
    if isinstance(raw_copies, bool):
        return jsonify(status="error", message="copies must be an integer"), 400
    try:
        copies_float = float(raw_copies)
    except (TypeError, ValueError):
        return jsonify(status="error", message="copies must be numeric"), 400
    if not math.isfinite(copies_float) or not copies_float.is_integer():
        return jsonify(status="error", message="copies must be a finite integer"), 400
    copies = int(copies_float)

    raw_pause = data.get("pauseTime", 0)
    if isinstance(raw_pause, bool):
        return jsonify(status="error", message="pauseTime must be a number"), 400
    try:
        pause_time = float(raw_pause)
    except (TypeError, ValueError):
        return jsonify(status="error", message="pauseTime must be numeric"), 400
    if not math.isfinite(pause_time):
        return jsonify(status="error", message="pauseTime must be a finite number"), 400

    if copies < 1 or copies > MAX_BATCH_COPIES:
        return jsonify(
            status="error",
            message=f"copies must be between 1 and {MAX_BATCH_COPIES}",
        ), 400
    if pause_time < 0 or pause_time > MAX_BATCH_PAUSE_SECONDS:
        return jsonify(
            status="error",
            message=f"pauseTime must be between 0 and {MAX_BATCH_PAUSE_SECONDS} seconds",
        ), 400

    # Validate row shape up front so failures surface as clean 400s rather
    # than blowing up the SSE stream mid-print. Numeric values are coerced
    # to strings so `{name: 42}` becomes `{name: "42"}`; other non-string
    # types (None, bool, list, dict) are rejected because str()-ing them
    # would print surprising literals on the label like "None" or "True".
    # Row indices in the error message are 1-based to match the BatchPanel UI.
    normalised_rows = []
    for i, row in enumerate(rows):
        if not isinstance(row, dict):
            return jsonify(status="error", message=f"Row {i + 1} must be an object"), 400
        clean: dict[str, str] = {}
        for k, v in row.items():
            if isinstance(v, bool) or not isinstance(v, (str, int, float)):
                return jsonify(
                    status="error",
                    message=f"Row {i + 1} field {k!r} must be a string or number",
                ), 400
            clean[str(k)] = str(v)
        normalised_rows.append(clean)
    rows = normalised_rows

    total = len(rows) * copies
    if total > MAX_BATCH_TOTAL:
        return jsonify(
            status="error",
            message=f"Batch too large: {total} labels (max {MAX_BATCH_TOTAL})",
        ), 400

    pause_budget = total * pause_time
    if pause_budget > MAX_BATCH_DURATION_SECONDS:
        return jsonify(
            status="error",
            message=(
                f"Batch pause budget too long: {pause_budget:.0f}s "
                f"(max {MAX_BATCH_DURATION_SECONDS}s = "
                f"{MAX_BATCH_DURATION_SECONDS // 3600}h)"
            ),
        ), 400

    # Reserve the slot atomically here so concurrent requests get a
    # consistent HTTP 409 + JSON error (instead of one client racing past
    # the check and finding out via an SSE error frame later). Cleanup is
    # registered on the Response via call_on_close so the slot is released
    # even if the generator never iterates (e.g. client aborts before
    # reading the body).
    #
    # The client may provide its own jobId so it can request cancellation
    # without waiting for the `started` SSE event (closes an unmount-race
    # window). Server falls back to its own uuid if the client didn't
    # supply one. Accepted format: 8-64 chars of [a-zA-Z0-9_-].
    raw_job_id = data.get("jobId")
    if raw_job_id is not None:
        if not isinstance(raw_job_id, str) or not re.fullmatch(r"[a-zA-Z0-9_-]{8,64}", raw_job_id):
            return jsonify(status="error", message="jobId must be 8-64 chars of [a-zA-Z0-9_-]"), 400
        job_id = raw_job_id
    else:
        job_id = uuid.uuid4().hex

    with _batch_lock:
        if _batch_jobs:
            return jsonify(status="error", message="Another batch job is already running"), 409
        _batch_jobs[job_id] = {"cancelled": False}

    def _release_slot():
        with _batch_lock:
            _batch_jobs.pop(job_id, None)

    # Build print list: each row × copies
    print_list = []
    for row in rows:
        for _ in range(copies):
            print_list.append(row)

    def generate():
        try:
            yield f"data: {json.dumps({'event': 'started', 'jobId': job_id, 'total': total})}\n\n"

            for idx, row_values in enumerate(print_list):
                # Lockless read of the cancellation flag is intentional:
                # dict.get and single-field reads are atomic under CPython's
                # GIL, and this runs on every iteration. Writes (in the
                # cancel endpoint) take _batch_lock to serialize against
                # other writers, but readers don't need it.
                job = _batch_jobs.get(job_id, {})
                if job.get("cancelled"):
                    yield f"data: {json.dumps({'event': 'cancelled', 'printed': idx})}\n\n"
                    return

                yield f"data: {json.dumps({'event': 'printing', 'index': idx, 'total': total})}\n\n"

                # Keep the idle timer happy while a long batch runs — the
                # initial before_request fires once, but the SSE stream
                # outlives it.
                power_save.record_activity()

                try:
                    substituted = _substitute_widgets(widgets, row_values)
                    # Paint the cut mark into the trailing margin of every
                    # label except the last — that gap is already there
                    # (labelle builds ~14 mm of trailing blank into each
                    # label's bitmap), so the dot lands in its centre with
                    # zero extra tape.
                    if idx < total - 1 and settings.get("cutMark"):
                        _print_label_with_cut_mark(substituted, settings, printer_id)
                    else:
                        print_label(substituted, settings, upload_dir=UPLOAD_DIR, printer_id=printer_id)
                except Exception as e:
                    traceback.print_exc()
                    yield f"data: {json.dumps({'event': 'error', 'index': idx, 'message': str(e)})}\n\n"
                    return

                yield f"data: {json.dumps({'event': 'printed', 'index': idx, 'total': total})}\n\n"

                # Pause between prints (except after last). Use monotonic
                # deadline so the actual elapsed time matches pause_time
                # regardless of clock skew or fractional sleep durations.
                if pause_time > 0 and idx < total - 1:
                    deadline = time.monotonic() + pause_time
                    while True:
                        remaining = deadline - time.monotonic()
                        if remaining <= 0:
                            break
                        if _batch_jobs.get(job_id, {}).get("cancelled"):
                            yield f"data: {json.dumps({'event': 'cancelled', 'printed': idx + 1})}\n\n"
                            return
                        time.sleep(min(0.1, remaining))

            yield f"data: {json.dumps({'event': 'done', 'total': total})}\n\n"
        finally:
            _release_slot()

    response = Response(generate(), mimetype="text/event-stream")
    # Disable proxy/server buffering so progress events stream to the client
    # in real time instead of arriving in one chunk at the end.
    response.headers["Cache-Control"] = "no-cache"
    response.headers["X-Accel-Buffering"] = "no"
    # Defence-in-depth cleanup: if the WSGI layer closes the response before
    # generate() ever iterates (e.g. client aborts pre-iteration), this fires
    # and releases the slot. Both paths are idempotent via pop(default=None).
    # On normal completion, the generator's finally runs first and pops; the
    # trailing call_on_close is a no-op. _release_slot closes over this job's
    # id, so a new batch submitted between the two events isn't affected.
    response.call_on_close(_release_slot)
    return response


@app.route("/api/batch-print/cancel", methods=["POST"])
def api_batch_cancel():
    data = request.get_json(silent=True) or {}
    job_id = data.get("jobId")

    if not job_id or not isinstance(job_id, str):
        return jsonify(status="error", message="jobId is required"), 400

    with _batch_lock:
        job = _batch_jobs.get(job_id)
        if not job:
            return jsonify(status="error", message="Job not found"), 404
        job["cancelled"] = True

    return jsonify(status="ok")


def _build_info() -> dict:
    """Return {commit, branch} from env vars (set at Docker build time) or git."""
    info = {}
    if sha := os.environ.get("GIT_SHA"):
        info["commit"] = sha
    if branch := os.environ.get("GIT_BRANCH"):
        info["branch"] = branch
    if info:
        return info

    repo_root = os.path.join(os.path.dirname(__file__), "..")
    try:
        sha = subprocess.check_output(
            ["git", "rev-parse", "--short", "HEAD"],
            cwd=repo_root, stderr=subprocess.DEVNULL, timeout=2,
        ).decode().strip()
        branch = subprocess.check_output(
            ["git", "rev-parse", "--abbrev-ref", "HEAD"],
            cwd=repo_root, stderr=subprocess.DEVNULL, timeout=2,
        ).decode().strip()
        return {"commit": sha, "branch": branch}
    except (subprocess.SubprocessError, FileNotFoundError, OSError):
        return {}


@app.route("/api/health", methods=["GET"])
def api_health():
    pkg_path = os.path.join(os.path.dirname(__file__), "..", "package.json")
    with open(pkg_path) as f:
        version = json.load(f)["version"]

    return jsonify(status="ok", version=version, **_build_info())


# --- Static file serving for production (SPA fallback) ---


@app.route("/", defaults={"path": ""})
@app.route("/<path:path>")
def serve_static(path):
    # Try to serve the requested file from dist-client
    full_path = os.path.join(DIST_DIR, path)
    if path and os.path.isfile(full_path):
        return send_from_directory(DIST_DIR, path)
    # SPA fallback: serve index.html for all other routes
    index = os.path.join(DIST_DIR, "index.html")
    if os.path.isfile(index):
        return send_from_directory(DIST_DIR, "index.html")
    return "Client not built. Run 'npm run build' first.", 404


if __name__ == "__main__":
    from waitress import serve

    port = int(os.environ.get("PORT", 5000))
    print(f"Labelle server running at http://0.0.0.0:{port}")
    serve(app, host="0.0.0.0", port=port)
