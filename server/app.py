import copy
import json
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

from flask import Flask, Response, jsonify, request, send_from_directory
from flask_cors import CORS
from werkzeug.utils import secure_filename

import power_save
import usb_power
from label_builder import preview_label
from printer_service import list_printers, print_label

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
# port off.
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


def _substitute_widgets(widgets, values):
    """Replace :varname: placeholders in widget text/content fields."""
    result = copy.deepcopy(widgets)
    pattern = re.compile(r":([a-zA-Z_]\w*):")
    for widget in result:
        for field in ("text", "content"):
            if field in widget and isinstance(widget[field], str):
                widget[field] = pattern.sub(
                    lambda m: values.get(m.group(1), m.group(0)), widget[field]
                )
    return result


@app.route("/api/batch-print", methods=["POST"])
def api_batch_print():
    data = request.get_json(silent=True) or {}
    widgets = data.get("widgets")
    settings = data.get("settings", {})
    printer_id = settings.get("printerId")
    rows = data.get("rows", [])
    copies = max(1, int(data.get("copies", 1)))
    pause_time = max(0.0, float(data.get("pauseTime", 0)))

    if not widgets or not isinstance(widgets, list) or len(widgets) == 0:
        return jsonify(status="error", message="No widgets provided"), 400
    if not rows or not isinstance(rows, list):
        return jsonify(status="error", message="No rows provided"), 400

    # Only one batch job at a time
    with _batch_lock:
        running = [j for j in _batch_jobs.values() if not j.get("done")]
        if running:
            return jsonify(status="error", message="Another batch job is already running"), 409

        job_id = uuid.uuid4().hex
        _batch_jobs[job_id] = {"cancelled": False, "done": False}

    # Build print list: each row × copies
    print_list = []
    for row in rows:
        for _ in range(copies):
            print_list.append(row)

    total = len(print_list)

    def generate():
        try:
            yield f"data: {json.dumps({'event': 'started', 'jobId': job_id, 'total': total})}\n\n"

            for idx, row_values in enumerate(print_list):
                job = _batch_jobs.get(job_id, {})
                if job.get("cancelled"):
                    yield f"data: {json.dumps({'event': 'cancelled', 'printed': idx})}\n\n"
                    return

                yield f"data: {json.dumps({'event': 'printing', 'index': idx, 'total': total})}\n\n"

                # Keep the idle timer happy while a long batch runs — the
                # initial before_request fires once, but the SSE stream
                # outlives it.
                power_save.record_activity()

                substituted = _substitute_widgets(widgets, row_values)
                try:
                    print_label(substituted, settings, upload_dir=UPLOAD_DIR, printer_id=printer_id)
                except Exception as e:
                    traceback.print_exc()
                    yield f"data: {json.dumps({'event': 'error', 'index': idx, 'message': str(e)})}\n\n"
                    return

                yield f"data: {json.dumps({'event': 'printed', 'index': idx, 'total': total})}\n\n"

                # Pause between prints (except after last)
                if pause_time > 0 and idx < total - 1:
                    elapsed = 0.0
                    while elapsed < pause_time:
                        if _batch_jobs.get(job_id, {}).get("cancelled"):
                            yield f"data: {json.dumps({'event': 'cancelled', 'printed': idx + 1})}\n\n"
                            return
                        time.sleep(min(0.1, pause_time - elapsed))
                        elapsed += 0.1

            yield f"data: {json.dumps({'event': 'done', 'total': total})}\n\n"
        finally:
            with _batch_lock:
                if job_id in _batch_jobs:
                    _batch_jobs[job_id]["done"] = True

    return Response(generate(), mimetype="text/event-stream")


@app.route("/api/batch-print/cancel", methods=["POST"])
def api_batch_cancel():
    data = request.get_json(silent=True) or {}
    job_id = data.get("jobId", "")

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
