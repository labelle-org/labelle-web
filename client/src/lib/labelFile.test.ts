import { describe, it, expect } from "vitest";
import { exportLabel } from "./labelFile";
import type { LabelWidget, LabelSettings, BatchState } from "../types/label";

const settings: LabelSettings = {
  tapeSizeMm: 12,
  marginPx: 56,
  minLengthMm: 0,
  justify: "center",
  foregroundColor: "black",
  backgroundColor: "white",
  showMargins: false,
  cutMark: false,
  printerId: "serial:ABC123",
};

describe("exportLabel", () => {
  it("omits printerId from the exported settings", async () => {
    // printerId is environment-specific (local serial / virtual id), not
    // portable label content, and shouldn't leak into a shared file.
    const widgets: LabelWidget[] = [{ id: "1", type: "qr", content: "x" }];
    const json = JSON.parse(await exportLabel(widgets, settings));
    expect("printerId" in json.settings).toBe(false);
    expect(json.settings.tapeSizeMm).toBe(12);
  });

  it("strips the transient empty-string rename key from exported rows", async () => {
    // Backspacing a variable name to {{}} parks its value under "" in the
    // store; that must not leak into a shared file. (The widget is incidental
    // here — what matters is the batch rows.)
    const widgets: LabelWidget[] = [{ id: "1", type: "qr", content: "x" }];
    const batch: BatchState = {
      copies: 1,
      pauseTime: 0,
      rows: [{ id: "r0", values: { name: "Alice", "": "stale" } }],
      selectedRowIndex: null,
    };
    const json = JSON.parse(await exportLabel(widgets, settings, batch));
    expect(json.batch.rows).toEqual([{ name: "Alice" }]);
  });

  it("omits the batch block entirely when a row holds only the empty key", async () => {
    // User backspaced to {{}} and abandoned the edit: nothing real to persist.
    const widgets: LabelWidget[] = [{ id: "1", type: "qr", content: "x" }];
    const batch: BatchState = {
      copies: 1,
      pauseTime: 0,
      rows: [{ id: "r0", values: { "": "stale" } }],
      selectedRowIndex: null,
    };
    const json = JSON.parse(await exportLabel(widgets, settings, batch));
    expect("batch" in json).toBe(false);
  });
});
