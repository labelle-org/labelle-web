import { v4 as uuidv4 } from "uuid";
import type { LabelWidget, LabelSettings, BatchState } from "../types/label";
import { uploadImage } from "./api";
import { MAX_BATCH_COPIES, MAX_BATCH_PAUSE_SECONDS } from "./constants";

// All fields optional: importLabel tolerates missing keys with safe
// defaults, and `??` fallbacks at the use site only fire on
// undefined — required types would lie about the runtime contract.
interface LabelFileBatch {
  copies?: number;
  pauseTime?: number;
  rows?: Record<string, string>[];
}

interface LabelFile {
  version: number;
  widgets: Record<string, unknown>[];
  settings: LabelSettings;
  batch?: LabelFileBatch;
}

function blobToDataUrl(blob: Blob): Promise<string> {
  return new Promise((resolve, reject) => {
    const r = new FileReader();
    r.onload = () => resolve(r.result as string);
    r.onerror = () => reject(r.error);
    r.readAsDataURL(blob);
  });
}

// While renaming a variable by backspacing its name to `{{}}`, the store
// briefly parks that row's value under the empty-string key (see the rename
// handling in useLabelStore). It's never a real column, and if the user
// abandons the edit at `{{}}` it can linger — so strip it from anything we
// persist rather than leak `{"": "..."}` into shared label files.
function withoutEmptyKey(
  values: Record<string, string>,
): Record<string, string> {
  if (!("" in values)) return values;
  const rest: Record<string, string> = {};
  for (const [k, v] of Object.entries(values)) {
    if (k !== "") rest[k] = v;
  }
  return rest;
}

function _hasBatchData(batch: BatchState): boolean {
  if (batch.copies !== 1) return true;
  if (batch.pauseTime !== 0) return true;
  if (batch.rows.length > 1) return true;
  if (batch.rows.some((r) => Object.keys(withoutEmptyKey(r.values)).length > 0))
    return true;
  return false;
}

function dataUrlToFile(dataUrl: string, filename: string): File {
  const [header, base64] = dataUrl.split(",");
  if (!header || !base64) throw new Error("Invalid data URL");
  const mime = header.match(/:(.*?);/)?.[1] ?? "image/png";
  const bytes = atob(base64);
  const arr = new Uint8Array(bytes.length);
  for (let i = 0; i < bytes.length; i++) {
    arr[i] = bytes.charCodeAt(i);
  }
  return new File([arr], filename, { type: mime });
}

export async function exportLabel(
  widgets: LabelWidget[],
  settings: LabelSettings,
  batch?: BatchState,
): Promise<string> {
  const exportWidgets: Record<string, unknown>[] = [];

  for (const widget of widgets) {
    const { id: _, ...rest } = widget;

    if (widget.type === "image" && widget.filename) {
      const res = await fetch(`/api/uploads/${widget.filename}`);
      const blob = await res.blob();
      const dataUrl = await blobToDataUrl(blob);
      exportWidgets.push({ ...rest, imageData: dataUrl });
    } else {
      exportWidgets.push(rest);
    }
  }

  // Omit printerId: it's environment-specific (a USB serial / local virtual
  // id), not portable label content, and would otherwise leak the local
  // printer identity into shared files. JSON.stringify drops the undefined.
  const data: LabelFile = {
    version: 2,
    settings: { ...settings, printerId: undefined },
    widgets: exportWidgets,
  };

  // Export the batch block whenever the user has touched anything in the
  // panel (rows with values, or non-default copies/pause). Batch mode is
  // derived from variable presence at runtime, so there's no on/off flag
  // to persist.
  if (batch && _hasBatchData(batch)) {
    data.batch = {
      copies: batch.copies,
      pauseTime: batch.pauseTime,
      // Strip the internal `id` (runtime React-key only) and the transient
      // empty-string rename key.
      rows: batch.rows.map((r) => withoutEmptyKey(r.values)),
    };
  }

  return JSON.stringify(data, null, 2);
}

export async function importLabel(
  json: string,
): Promise<{
  widgets: LabelWidget[];
  settings: LabelSettings;
  batch?: BatchState;
}> {
  const data = JSON.parse(json) as LabelFile;

  if (
    typeof data.version !== "number" ||
    data.version < 1 ||
    !data.widgets ||
    !data.settings
  ) {
    throw new Error("Invalid label file");
  }
  if (data.version > 2) {
    throw new Error(
      `Unsupported label file version ${data.version}. Update Labelle Web to load this file.`,
    );
  }

  const widgets: LabelWidget[] = [];

  for (const raw of data.widgets) {
    const id = uuidv4();

    if (raw.type === "image" && typeof raw.imageData === "string") {
      const file = dataUrlToFile(
        raw.imageData,
        (raw.filename as string) || "image.png",
      );
      const { filename } = await uploadImage(file);
      widgets.push({ id, type: "image", filename });
    } else {
      widgets.push({ id, ...raw } as LabelWidget);
    }
  }

  let batch: BatchState | undefined;
  if (data.batch !== undefined) {
    if (
      typeof data.batch !== "object" ||
      data.batch === null ||
      Array.isArray(data.batch)
    ) {
      throw new Error("Invalid label file: batch must be an object");
    }
    const { copies, pauseTime, rows } = data.batch;
    if (
      copies !== undefined &&
      (typeof copies !== "number" || copies < 1 || copies > MAX_BATCH_COPIES)
    ) {
      throw new Error(
        `Invalid label file: batch.copies must be a number between 1 and ${MAX_BATCH_COPIES}`,
      );
    }
    if (
      pauseTime !== undefined &&
      (typeof pauseTime !== "number" ||
        pauseTime < 0 ||
        pauseTime > MAX_BATCH_PAUSE_SECONDS)
    ) {
      throw new Error(
        `Invalid label file: batch.pauseTime must be a number between 0 and ${MAX_BATCH_PAUSE_SECONDS}`,
      );
    }
    if (rows !== undefined && !Array.isArray(rows)) {
      throw new Error("Invalid label file: batch.rows must be an array");
    }
    if (rows) {
      for (const row of rows) {
        if (typeof row !== "object" || row === null || Array.isArray(row)) {
          throw new Error("Invalid label file: batch.rows entries must be objects");
        }
        for (const v of Object.values(row)) {
          if (typeof v !== "string") {
            throw new Error("Invalid label file: batch.rows values must be strings");
          }
        }
      }
    }

    const importedRows = (rows?.length ? rows : [{}]).map((values) => ({
      id: uuidv4(),
      values,
    }));
    batch = {
      copies: copies ?? 1,
      pauseTime: pauseTime ?? 0,
      rows: importedRows,
      selectedRowIndex: null,
    };
  }

  return { widgets, settings: data.settings, batch };
}
