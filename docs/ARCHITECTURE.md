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
- Refresh button to re-scan USB devices

The selection defaults to the first printer in the list (the first real USB printer when one is present; virtual printers are listed after), set in `setAvailablePrinters` — which also re-selects the first printer if the previously-selected one is no longer connected. The selected `printerId` is stored in `settings` and sent with print requests. (The server still accepts no `printerId` and auto-selects the first available printer; the UI just always sends a concrete one.)

### Batch Print

The batch print feature allows printing multiple labels with variable content (e.g. name badges, asset tags).

**Variable syntax:** `{{varname}}` in text, QR, or barcode widget content fields. Names match `[\w-]+` so letters, digits, underscores, and hyphens are all allowed (e.g. `{{first-name}}`). Variables are auto-detected via regex in `lib/variables.ts` using `detectVariables()`, which runs in components via `useMemo` (derived, not stored). The double-brace form was chosen over `:name:` (1.6.0–1.6.1) because colons are common in legitimate QR/barcode content (URLs, IPv6 literals, key:value pairs) and caused false matches.

**`BatchPanel`** is a collapsible `<details>` panel that shows:
- Copies per row and pause time between prints
- An auto-detected variable table based on current widget content
- Editable rows; clicking a row selects it for preview
- Helper text when no variables are detected

**`PrintButton`** switches to batch mode when `batch.enabled` is true: shows "Batch Print (N labels)", streams progress from the server, and offers a cancel button during printing.

**Print order:** row-major. With N rows and C copies the printer outputs `row1 × C, row2 × C, …` so each label's copies stay together — this matches the common "N copies of each" case where users tear off a stack per recipient. Copy-major ordering (`row1 row2 … rowN` repeated C times) is not currently supported.

**Variable rename heuristic:** when a `updateWidget` edit removes one variable from a widget and adds another, the store treats it as a rename — batch row values follow the new name, and any other widgets referencing the old name are rewritten. The heuristic is set-diff over the widget's variables and has a known limitation: keystroke-by-keystroke typing in a real `<input>` (e.g. `{{name}}` → `{{names}` → `{{names}}`) produces an intermediate state with no closing braces, where the regex sees a pure removal followed later by a pure addition. The row value for `name` orphans in that case. In practice users edit via select-and-replace or paste, which works correctly; orphaned values reappear if the original name is typed back.

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
- Identified by serial number (`serial:<sn>`) when the device reports one,
  falling back to the USB bus/address (`Bus 001 Device 005: ID 0922:1234`)
  only when it doesn't. The serial is stable across re-enumeration (replug,
  reboot, USB power-cycle); the bus/address is not. See `_printer_id`.
- Send output directly to USB device via labelle's `DymoLabeler.print()`

#### Virtual Printers
- Configured via `VIRTUAL_PRINTERS` environment variable
- Identified by `virtual:{id}` — an optional explicit `id` from config (stable, decoupled from the display name), else a path-safe slug of the name (e.g. "virtual:Office_Printer")
- Save labels as PNG files to configured directories
- Useful for testing, archiving, and development without hardware

**Printer ID Format:**
- Real printers: `serial:{serial_number}`, or the full USB bus/address ID string when the device reports no serial
- Virtual printers: `virtual:{id}` — the optional config `id` (URL-safe `[A-Za-z0-9_-]`), else a path-safe slug of the name (non-word runs → `_`). Colliding ids are rejected at config load.

**Output Filename Format (virtual printers):** `label_YYYYMMDD_HHMMSS_uuid.png`

### Persistent State (`state_store.py`)

A single JSON file (`LABELLE_STATE_FILE`, default `/app/output/.labelle/state.json`,
inside the already-mounted output volume) holds the small bits of state that
must survive container restarts. `state_store.py` owns it and is the only writer:
every write is an atomic read-modify-write of the whole document under a shared
lock, so independent features can each persist their slice without clobbering
the others.

Current slices:
- **USB power** (`usb_power.py`): top-level `hub`/`port` — the last known
  controllable port, so power-on still works after the device has been powered
  off and dropped off the USB tree.
- **Per-printer settings** (`printer_settings.py`): a `printers` map keyed by
  `PrinterInfo.id`, storing the long-lived tape size + foreground/background
  colors loaded in each printer. Validated server-side; the client
  applies a printer's saved subset on selection and writes back on change
  (`usePrinterSettings`). The "effective printer" is the explicit selection,
  or the sole printer when on Auto-select — so single-printer kiosks persist
  too. v2 follow-ups (aliases, presets, remember-last) are expected to extend
  this same per-printer map.

  The persisted controls (tape/colors) are **disabled until the effective
  printer's settings have resolved** — before the printer list loads and while
  the fetch is in flight — so a late-arriving fetch can't revert an edit and
  pre-load edits aren't lost; a fetch error unlocks them (keep defaults). And
  `printerId` is **stripped from exported label files** (it's a local
  serial/virtual id, not portable content); importing a label keeps the
  printer you're currently on.

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
      -> _substitute_widgets(widgets, row)    # Replace {{varname}} placeholders
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
    -> Read commit + branch from GIT_SHA/GIT_BRANCH env (set at Docker build)
       or git rev-parse fallback
  <- { status, version, commit, branch }
```

### Versioning convention

`package.json` always holds the version this commit *would* release if merged — there is **no `-dev` suffix on feature branches**. The footer (`client/src/components/Footer.tsx`) reads `/api/health` at runtime and renders `v{version}-dev ({commit})` whenever `/api/health` reports a `branch` that isn't `main` (if the health call fails the footer omits `-dev` rather than mislabeling a build with no commit info). Dev / PR / local builds are therefore visually distinguishable from production releases without needing to mutate `package.json` at merge time. `release.yml` tags `vX.Y.Z` when the version on `main` changes, so the merge commit *is* the release commit.

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

Each entry takes `name` and `path`, plus optional `output` (`image` (default) / `json` / `both`) and an optional `id`. Set `id` (URL-safe `[A-Za-z0-9_-]`) to give a printer a stable identity decoupled from its display name — its saved per-printer settings then survive renaming the `name`. Without `id`, the id is slugged from the name; entries whose ids collide are skipped at load with a warning.

In Docker, configure in `.env` (loaded via `env_file` in `compose.yaml`):
```bash
VIRTUAL_PRINTERS=[{"name":"Office","path":"/app/output/office"}]
```
Uncomment the output volume mount in `compose.yaml` to access saved labels on the host.

## Future Improvements

TODOs documented in code comments:

**Backend (app.py, label_builder.py):**
- Printer status/health checks (online/offline, tape level)
- Printer list caching to reduce USB scans
- Printer capability detection (supported tape sizes, colors)

(Per-printer tape-size/color persistence shipped in v1.8.0 — see "Per-printer
settings" below. The remaining three are tracked in issue #38.)

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
