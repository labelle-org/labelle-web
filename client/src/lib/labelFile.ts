import { v4 as uuidv4 } from "uuid";
import type { LabelWidget, LabelSettings, BatchState } from "../types/label";
import { uploadImage } from "./api";

interface LabelFileBatch {
  copies: number;
  pauseTime: number;
  rows: Record<string, string>[];
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

  const data: LabelFile = { version: 2, settings, widgets: exportWidgets };

  if (batch?.enabled) {
    data.batch = {
      copies: batch.copies,
      pauseTime: batch.pauseTime,
      rows: batch.rows,
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
    if (copies !== undefined && (typeof copies !== "number" || copies < 1)) {
      throw new Error("Invalid label file: batch.copies must be a number >= 1");
    }
    if (
      pauseTime !== undefined &&
      (typeof pauseTime !== "number" || pauseTime < 0)
    ) {
      throw new Error("Invalid label file: batch.pauseTime must be a number >= 0");
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

    batch = {
      enabled: true,
      copies: copies ?? 1,
      pauseTime: pauseTime ?? 0,
      rows: rows?.length ? rows : [{}],
      selectedRowIndex: null,
    };
  }

  return { widgets, settings: data.settings, batch };
}
