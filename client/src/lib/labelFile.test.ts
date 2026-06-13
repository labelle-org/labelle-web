import { describe, it, expect } from "vitest";
import { exportLabel } from "./labelFile";
import type { LabelWidget, LabelSettings } from "../types/label";

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
});
