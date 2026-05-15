import type {
  LabelWidget,
  LabelSettings,
  PrinterInfo,
  PowerStatus,
} from "../types/label";

interface PrintResponse {
  status: string;
  message: string;
}

interface PrintersResponse {
  printers: PrinterInfo[];
}

interface PowerResponse extends PowerStatus {
  status?: string;
}

export interface BatchEvent {
  event: "started" | "printing" | "printed" | "done" | "cancelled" | "error";
  jobId?: string;
  index?: number;
  total?: number;
  printed?: number;
  message?: string;
}

export async function printLabel(
  widgets: LabelWidget[],
  settings: LabelSettings,
): Promise<PrintResponse> {
  const res = await fetch("/api/print", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ widgets, settings }),
  });
  return res.json() as Promise<PrintResponse>;
}

export async function uploadImage(
  file: File,
): Promise<{ filename: string }> {
  const form = new FormData();
  form.append("file", file);
  const res = await fetch("/api/upload-image", {
    method: "POST",
    body: form,
  });
  if (!res.ok) {
    const err = (await res.json()) as PrintResponse;
    throw new Error(err.message);
  }
  return res.json() as Promise<{ filename: string }>;
}

export async function fetchServerPreview(
  widgets: LabelWidget[],
  settings: LabelSettings,
  signal?: AbortSignal,
): Promise<string> {
  const res = await fetch("/api/preview", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ widgets, settings }),
    signal,
  });
  if (!res.ok) {
    const err = (await res.json()) as PrintResponse;
    throw new Error(err.message);
  }
  const blob = await res.blob();
  return URL.createObjectURL(blob);
}

export async function fetchPrinters(): Promise<PrinterInfo[]> {
  const res = await fetch("/api/printers");
  if (!res.ok) {
    throw new Error("Failed to fetch printers");
  }
  const data = (await res.json()) as PrintersResponse;
  return data.printers;
}

export async function batchPrint(
  widgets: LabelWidget[],
  settings: LabelSettings,
  rows: Record<string, string>[],
  copies: number,
  pauseTime: number,
  onProgress: (event: BatchEvent) => void,
  signal?: AbortSignal,
): Promise<void> {
  const res = await fetch("/api/batch-print", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ widgets, settings, rows, copies, pauseTime }),
    signal,
  });

  if (!res.ok) {
    const err = (await res.json()) as PrintResponse;
    throw new Error(err.message);
  }

  const reader = res.body?.getReader();
  if (!reader) throw new Error("No response body");

  const decoder = new TextDecoder();
  let buffer = "";

  while (true) {
    const { done, value } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true });

    const lines = buffer.split("\n");
    buffer = lines.pop() ?? "";

    for (const line of lines) {
      if (line.startsWith("data: ")) {
        const event = JSON.parse(line.slice(6)) as BatchEvent;
        onProgress(event);
      }
    }
  }
}

export async function cancelBatchPrint(jobId: string): Promise<void> {
  await fetch("/api/batch-print/cancel", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ jobId }),
  });
}

// 404 here means the server can't resolve a controllable USB port for
// the Dymo — either no printer detected or no cached port. UI treats
// that as "this deployment doesn't have USB power control" and hides
// the toggle. Non-200/404 errors propagate so the user sees them.
async function _readPowerResponse(res: Response): Promise<PowerStatus> {
  if (!res.ok) {
    const err = (await res.json()) as PrintResponse;
    throw new Error(err.message);
  }
  const data = (await res.json()) as PowerResponse;
  return {
    hub: data.hub,
    port: data.port,
    powered: data.powered,
    connected: data.connected,
  };
}

export async function fetchPowerStatus(): Promise<PowerStatus | null> {
  const res = await fetch("/api/power/status");
  if (res.status === 404) return null;
  return _readPowerResponse(res);
}

export async function powerOn(): Promise<PowerStatus> {
  const res = await fetch("/api/power/on", { method: "POST" });
  return _readPowerResponse(res);
}

export async function powerOff(): Promise<PowerStatus> {
  const res = await fetch("/api/power/off", { method: "POST" });
  return _readPowerResponse(res);
}
