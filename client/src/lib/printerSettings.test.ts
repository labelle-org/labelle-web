import { describe, it, expect } from "vitest";
import { effectivePrinterId, pickPersisted } from "./printerSettings";
import type { LabelSettings, PrinterInfo } from "../types/label";

const printer = (id: string): PrinterInfo => ({
  id,
  name: id,
  vendorProductId: "0922:1002",
});

describe("effectivePrinterId", () => {
  it("returns the explicit selection when set", () => {
    expect(effectivePrinterId("usb:2", [printer("usb:1"), printer("usb:2")])).toBe(
      "usb:2",
    );
  });

  it("falls back to the sole printer on Auto-select", () => {
    expect(effectivePrinterId(undefined, [printer("usb:1")])).toBe("usb:1");
  });

  it("is undefined on Auto-select with multiple printers", () => {
    expect(
      effectivePrinterId(undefined, [printer("usb:1"), printer("usb:2")]),
    ).toBeUndefined();
  });

  it("is undefined on Auto-select with no printers", () => {
    expect(effectivePrinterId(undefined, [])).toBeUndefined();
  });
});

describe("pickPersisted", () => {
  it("keeps only the per-printer-persisted keys", () => {
    const settings: LabelSettings = {
      tapeSizeMm: 19,
      marginPx: 56,
      minLengthMm: 0,
      justify: "center",
      foregroundColor: "white",
      backgroundColor: "blue",
      showMargins: true,
      cutMark: true,
      printerId: "usb:1",
    };
    expect(pickPersisted(settings)).toEqual({
      tapeSizeMm: 19,
      foregroundColor: "white",
      backgroundColor: "blue",
    });
  });
});
