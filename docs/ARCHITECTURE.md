# Architecture

## Overview

Labelle Web is a monorepo with a React frontend and a Python/Flask backend:

```
labelle-web/
  package.json              # Root: npm workspace for client, dev scripts
  client/                   # Frontend: Vite + React + TypeScript + Tailwind
  server/                   # Backend: Python/Flask, imports labelle as a library
```

The frontend handles all UI. Label preview images are rendered server-side by the backend using labelle's render engines directly, giving pixel-perfect output that matches what will be printed.

## Frontend (`client/`)

### Tech Stack

- **React 19** with TypeScript
- **Vite** for dev server and bundling
- **Tailwind CSS** for styling
- **Zustand** for state management

### State Management

A single Zustand store (`state/useLabelStore.ts`) holds all application state:

```
{
  widgets: LabelWidget[]           # Ordered list of text/QR/barcode/image widgets
  settings: LabelSettings          # Tape size, margins, justify, colors, printerId
  availablePrinters: PrinterInfo[] # List of detected printers (real + virtual)
  batch: BatchState                # Batch print config: copies, pause, variable rows
}
```

The store exposes actions for widget CRUD (`addTextWidget`, `removeWidget`, `updateWidget`), settings updates (`updateSettings`), printer management (`setAvailablePrinters`), and batch management (`updateBatch`, `setBatchRow`, `addBatchRow`, `removeBatchRow`). All components subscribe to the store via selectors, so changes automatically trigger re-renders.

### Component Tree

```
App
  WidgetList                # Maps widgets[] to WidgetEditor components, drag-and-drop reorder
    WidgetEditor            # Drag handle + type badge + delete button + dispatches to:
      TextWidgetEditor      # Textarea, font style/scale, frame, alignment
      QrWidgetEditor        # Content input
      BarcodeWidgetEditor   # Content, type dropdown, show-text toggle
      ImageWidgetEditor     # Thumbnail, filename, replace button
  AddWidgetMenu             # + Text / + QR / + Barcode / + Image buttons
  PrintButton               # Print trigger with loading/success/error states; batch mode
  SaveLoadButtons           # Save/load label JSON files (v2 format with batch data)
  BatchPanel                # Batch print config: copies, pause, variable table
  SettingsBar               # Tape size, margin, min-length, justify, colors, printer selector
  LabelPreview              # Server-rendered preview image with debounced fetching
```

### Server-Side Preview

The preview updates on every state change with a 300ms debounce. The `LabelPreview` component calls `POST /api/preview` with the current widgets and settings, and displays the returned PNG image. An `AbortController` cancels in-flight requests when state changes again, and previous object URLs are revoked to prevent memory leaks. The preview is pixel-perfect because it uses the same labelle render engines as printing.

When batch mode is active and a row is selected, `LabelPreview` substitutes variables before sending to the server, so the preview shows the resolved content for that row.

### Multi-Printer UI

The app fetches available printers on load via `GET /api/printers`. If multiple printers are detected, a dropdown selector appears in the Settings panel with:
- List of all printers (real USB + virtual printers)
- "Auto-select" option (default)
- Refresh button to re-scan USB devices

The selected `printerId` is stored in `settings` and sent with print requests.

### Batch Print

The batch print feature allows printing multiple labels with variable content (e.g. name badges, asset tags).

**Variable syntax:** `:varname:` in text, QR, or barcode widget content fields. Variables are auto-detected via regex in `lib/variables.ts` using `detectVariables()`, which runs in components via `useMemo` (derived, not stored).

**`BatchPanel`** is a collapsible `<details>` panel that shows:
- Copies per row and pause time between prints
- An auto-detected variable table based on current widget content
- Editable rows; clicking a row selects it for preview
- Helper text when no variables are detected

**`PrintButton`** switches to batch mode when `batch.enabled` is true: shows "Batch Print (N labels)", streams progress from the server, and offers a cancel button during printing.

### Type Definitions

All shared types live in `types/label.ts`:

- `TextWidget` -- text, fontStyle, fontScale, frameWidthPx, align
- `QrWidget` -- content
- `BarcodeWidget` -- content, barcodeType, showText
- `ImageWidget` -- filename (server-side reference from upload)
- `LabelSettings` -- tapeSizeMm, marginPx, minLengthMm, justify, foregroundColor, backgroundColor, showMargins, printerId
- `PrinterInfo` -- id, name, vendorProductId, serialNumber
- `BatchState` -- enabled, copies, pauseTime, rows (variable value maps), selectedRowIndex
- Union type `LabelWidget = TextWidget | QrWidget | BarcodeWidget | ImageWidget`

### Constants

`lib/constants.ts` defines shared UI constants:

| Constant | Value | Description |
|----------|-------|-------------|
| `TAPE_SIZES` | [6, 9, 12, 19] | Available tape widths in mm |
| `DEFAULT_MARGIN_PX` | 56 | Default horizontal margin (from labelle) |
| `DEFAULT_FONT_SCALE` | 90 | Default font scale percentage |
| `BARCODE_TYPES` | 15 types | Barcode format options for the dropdown |
| `LABEL_COLORS` | 6 colors | Available foreground/background colors |

## Backend (`server/`)

### Tech Stack

- **Flask** (Python) with flask-cors
- **labelle** imported as a Python library (not called as a CLI subprocess)

### Printer System

The backend supports two types of printers:

#### Real USB Printers
- Detected via `DeviceManager().scan()` from labelle library
- Identified by USB bus/address (e.g. "Bus 001 Device 005: ID 0922:1234")
- Send output directly to USB device via labelle's `DymoLabeler.print()`

#### Virtual Printers
- Configured via `VIRTUAL_PRINTERS` environment variable
- Identified by `virtual:{sanitized_name}` format (e.g. "virtual:Office_Printer")
- Save labels as PNG files to configured directories
- Useful for testing, archiving, and development without hardware

**Printer ID Format:**
- Real printers: Full USB ID string from device manager
- Virtual printers: `virtual:{name}` where name has spaces/special chars replaced with underscores

**Output Filename Format (virtual printers):** `label_YYYYMMDD_HHMMSS_uuid.png`

### Request Flow

```
GET /api/printers
  -> app.py (api_printers)
    -> DeviceManager().scan() for real printers
    -> get_virtual_printers() from config
    -> Combine both lists
  <- JSON array of PrinterInfo objects

POST /api/print
  -> app.py (api_print)
    -> Extract printerId from settings
    -> label_builder.print_label(widgets, settings, printerId)
      -> Check if printerId starts with "virtual:"
      -> If virtual:
        -> Find matching VirtualPrinter from config
        -> _build_render_engines(widgets)
        -> HorizontallyCombinedRenderEngine
        -> PrintPayloadRenderEngine
        -> VirtualPrinter.save_label(bitmap)  # Save to file
      -> Else (real printer):
        -> DeviceManager().scan()
        -> Find device by USB ID or auto-select
        -> _build_render_engines(widgets)
        -> HorizontallyCombinedRenderEngine
        -> PrintPayloadRenderEngine
        -> DymoLabeler.print(bitmap)          # Send to USB
  <- { status, message }

POST /api/preview
  -> app.py (api_preview)
    -> label_builder.preview_label(widgets, settings)
      -> _build_render_engines(widgets)
      -> HorizontallyCombinedRenderEngine
      -> PrintPreviewRenderEngine
      -> PNG bytes via PIL
  <- image/png

POST /api/batch-print (SSE streaming)
  -> app.py (api_batch_print)
    -> For each row × copies:
      -> _substitute_widgets(widgets, row)    # Replace :varname: placeholders
      -> label_builder.print_label(...)       # Print one label
      -> SSE event: printing/printed
    -> Check cancellation flag between prints (during pause sleep)
  <- SSE events: started, printing, printed, done/cancelled/error

POST /api/batch-print/cancel
  -> Sets cancelled flag for the running job
  <- { status: "ok" }

GET /api/health
  -> app.py (api_health)
    -> Read version from package.json
  <- { status, version }
```

### Label Builder (`label_builder.py`)

Converts the widget JSON array into labelle `RenderEngine` instances:

- **Text widgets** → `TextRenderEngine` with per-widget `font_file_name`, `font_size_ratio`, `frame_width_px`, and `align`
- **QR widgets** → `QrRenderEngine(content)`
- **Barcode widgets** → `BarcodeRenderEngine(content, barcode_type)` or `BarcodeWithTextRenderEngine(...)` when `showText` is true
- **Image widgets** → `PictureRenderEngine(picture_path)` where path is resolved from uploaded filename

All engines are combined with `HorizontallyCombinedRenderEngine`, then wrapped with either `PrintPayloadRenderEngine` (for printing) or `PrintPreviewRenderEngine` (for preview).

Settings like `marginPx`, `minLengthMm`, `justify`, `tapeSizeMm`, `foregroundColor`, and `backgroundColor` are applied via `RenderContext` and the payload/preview wrapper.

### Virtual Printer System

**Config Module** (`config.py`):
- Loads `VIRTUAL_PRINTERS` environment variable
- Parses JSON array of `{name, path}` objects
- Validates structure and logs errors
- Returns empty list if not configured or invalid

**Virtual Printer Class** (`virtual_printer.py`):
- `__init__(name, output_path)` - Creates printer, ensures directory exists
- `id` property - Returns `virtual:{sanitized_name}`
- `display_name` property - Returns `{name} (Virtual)`
- `save_label(bitmap)` - Saves PIL Image to PNG file with timestamp+UUID filename

### Flask App (`app.py`)

- `GET /api/health` — Lightweight health check, returns server status and version (no USB scan)
- `GET /api/printers` — Scans USB devices + loads virtual printer config, returns combined list
- `POST /api/print` — Validates request, extracts printerId, calls `print_label()`, returns JSON status
- `POST /api/preview` — Validates request, calls `preview_label()`, returns PNG bytes
- `POST /api/batch-print` — SSE streaming endpoint: substitutes variables per row, prints each label, streams progress events. Only one batch job can run at a time (409 if another is active). Cancellation checked between prints during pause sleep.
- `POST /api/batch-print/cancel` — sets cancelled flag for a running batch job by jobId
- `POST /api/upload-image` — Accepts multipart file upload, saves with UUID filename, returns `{ filename }`
- `GET /api/uploads/<filename>` — Serves uploaded images (used by the editor thumbnail)
- Static file serving from `dist-client/` with SPA fallback to `index.html`

## Testing

### Unit Tests

Backend tests live in `server/tests/` and run via pytest:

```bash
npm run test:server
# or directly:
.venv/bin/python -m pytest server/tests/ -v
```

### Smoke Tests

Smoke tests catch "the app can't start" issues that unit tests miss (e.g. a module not included in the Docker image).

**Layer 1: Import smoke tests** (`server/tests/test_smoke.py`)

- Imports every server module via `importlib` to catch missing dependencies
- Verifies Flask app creates and all API routes are registered
- Cross-checks the module list against `server/*.py` on disk — if a new module is added but not listed, the test fails, reminding you to update the Dockerfile too

Run locally with `npm run test:server` (no extra setup needed).

**Layer 2: Docker smoke tests** (CI only, defined in `_docker-smoke-test.yml`)

A reusable workflow (`_docker-smoke-test.yml`) builds the Docker image, starts a container with a virtual printer, and hits key endpoints (`/api/health`, `/api/printers`, `/api/preview`, `/`). Both `test.yml` and `release.yml` call this workflow:

- On PRs (`test.yml`): the `docker-smoke` job calls the reusable workflow after unit tests pass.
- On release (`release.yml`): a `smoke-test` job calls the reusable workflow after tagging. The `build-and-push` job only runs after the smoke test succeeds.

## Build and Deployment

### Development

`npm run dev` uses `concurrently` to start:
- Vite dev server on port 5173 (with HMR)
- Flask dev server on port 5000

Vite proxies `/api/*` requests to the Flask backend.

### Production

`npm run build` runs `vite build` in `client/` (outputs to `server/dist-client/`).

`npm start` runs the Flask server (`python server/app.py`), which serves both the static client bundle and the API on a single port.

### Deployment Diagram

```
Browser (any device on LAN)
    |
    | HTTP :5000
    v
Flask Server (e.g. Raspberry Pi)
    |
    +-- labelle library (direct Python import)
    |   |
    |   | USB (real printers)
    |   v
    | DYMO Label Printer(s)
    |
    +-- virtual_printer.py (virtual printers)
        |
        | File I/O
        v
    Output directories (./output/*)
```

## Configuration

All configuration via environment variables:

| Variable | Default | Description |
|----------|---------|-------------|
| `PORT` | 5000 | Flask server listen port |
| `PYTHONUNBUFFERED` | (unset) | Python output buffering (set to 1 for Docker logs) |
| `VIRTUAL_PRINTERS` | (none) | JSON array of virtual printer configs |

### Virtual Printer Configuration Example

```bash
export VIRTUAL_PRINTERS='[
  {"name":"Office Printer","path":"./output/office"},
  {"name":"Warehouse Printer","path":"./output/warehouse"}
]'
```

In Docker, configure in `.env` (loaded via `env_file` in `compose.yaml`):
```bash
VIRTUAL_PRINTERS=[{"name":"Office","path":"/app/output/office"}]
```
Uncomment the output volume mount in `compose.yaml` to access saved labels on the host.

## Future Improvements

TODOs documented in code comments:

**Backend (app.py, label_builder.py):**
- Per-printer settings persistence (tape size, margins, color)
- Printer status/health checks (online/offline, tape level)
- Printer list caching to reduce USB scans
- Printer capability detection (supported tape sizes, colors)

**Frontend (SettingsBar.tsx):**
- Printer status indicators in UI
- Display tape type/color/width for each printer
- User-defined printer aliases
- Remember last selected printer per user
- Printer-specific preset configurations

**USB Power Management:**
- Toggle USB port power to save energy and reduce printer wear when idle
- Use `uhubctl` to power off printer USB ports after an idle timeout (e.g. 1 hour since last print)
- Power on the port when the web page is opened, with a brief delay for printer initialization
- Detect hub/port dynamically by matching device vendor:product ID (e.g. `0922:1002` for Dymo) rather than hardcoding hub/port paths
- Requires passwordless sudo for `uhubctl` (sudoers rule on the host)
- Confirmed working on Raspberry Pi with USB 2.0 hub (2109:3431) that supports per-port power switching (ppps)
- Handle "powering up" state in UI (spinner/status indicator while printer initializes)
- Consider per-printer port mapping for multi-printer setups

**Home Assistant Integration (separate repo: `labelle-web-hacs`):**
- HACS integration that connects to Labelle Web's REST API over the network
- Config flow: server URL input + connection validation
- HA services: `labelle.print_label`, `labelle.preview` — thin REST client calls
- Sensor/button entities per printer (status, quick-print)
- Custom Lovelace card: text input, template picker, preview, print button
- Enables HA automations (e.g. print label on package arrival)
- Uses `GET /api/health` for connectivity monitoring (lightweight, no USB scan)
