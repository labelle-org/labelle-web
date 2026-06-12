import { describe, it, expect, vi, beforeEach } from "vitest";
import {
  fetchPrinters,
  fetchPowerStatus,
  powerOn,
  powerOff,
  printLabel,
  fetchServerPreview,
  uploadImage,
  fetchPrinterSettings,
  savePrinterSettings,
} from "./api";
import type { LabelWidget, LabelSettings } from "../types/label";

const mockFetch = vi.fn();
vi.stubGlobal("fetch", mockFetch);

const mockCreateObjectURL = vi.fn(() => "blob:http://localhost/fake-url");
vi.stubGlobal("URL", { createObjectURL: mockCreateObjectURL });

beforeEach(() => {
  mockFetch.mockReset();
  mockCreateObjectURL.mockClear();
});

const sampleWidgets: LabelWidget[] = [
  { id: "1", type: "text", text: "Hello", fontStyle: "regular", fontScale: 90, frameWidthPx: 0, align: "left" },
];

const sampleSettings: LabelSettings = {
  tapeSizeMm: 12,
  marginPx: 56,
  minLengthMm: 0,
  justify: "center",
  foregroundColor: "black",
  backgroundColor: "white",
  showMargins: false,
  cutMark: false,
};

describe("fetchPrinters", () => {
  it("returns printers from the API", async () => {
    const printers = [
      { id: "usb:1", name: "DYMO LabelWriter", vendorProductId: "0922:1002" },
      { id: "virtual:Office", name: "Office (Virtual)", vendorProductId: "virtual" },
    ];
    mockFetch.mockResolvedValueOnce({
      ok: true,
      json: async () => ({ printers }),
    });

    const result = await fetchPrinters();
    expect(result).toEqual(printers);
    expect(mockFetch).toHaveBeenCalledWith("/api/printers");
  });

  it("returns empty array when no printers available", async () => {
    mockFetch.mockResolvedValueOnce({
      ok: true,
      json: async () => ({ printers: [] }),
    });

    const result = await fetchPrinters();
    expect(result).toEqual([]);
  });

  it("throws on fetch error", async () => {
    mockFetch.mockResolvedValueOnce({
      ok: false,
      status: 500,
      json: async () => ({ message: "Internal error" }),
    });

    await expect(fetchPrinters()).rejects.toThrow("Failed to fetch printers");
  });

  it("throws on network failure", async () => {
    mockFetch.mockRejectedValueOnce(new TypeError("Failed to fetch"));

    await expect(fetchPrinters()).rejects.toThrow("Failed to fetch");
  });
});

describe("printLabel", () => {
  it("sends POST to /api/print with widgets and settings", async () => {
    const responseData = { status: "success", message: "Label sent to printer." };
    mockFetch.mockResolvedValueOnce({
      ok: true,
      json: async () => responseData,
    });

    const result = await printLabel(sampleWidgets, sampleSettings);

    expect(mockFetch).toHaveBeenCalledWith("/api/print", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ widgets: sampleWidgets, settings: sampleSettings }),
    });
    expect(result).toEqual(responseData);
  });
});

describe("fetchServerPreview", () => {
  it("sends POST to /api/preview and returns object URL", async () => {
    const fakeBlob = new Blob(["fake-png"], { type: "image/png" });
    mockFetch.mockResolvedValueOnce({
      ok: true,
      blob: async () => fakeBlob,
    });

    const result = await fetchServerPreview(sampleWidgets, sampleSettings);

    expect(mockFetch).toHaveBeenCalledWith("/api/preview", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ widgets: sampleWidgets, settings: sampleSettings }),
      signal: undefined,
    });
    expect(mockCreateObjectURL).toHaveBeenCalledWith(fakeBlob);
    expect(result).toBe("blob:http://localhost/fake-url");
  });

  it("throws on error response", async () => {
    mockFetch.mockResolvedValueOnce({
      ok: false,
      json: async () => ({ status: "error", message: "No widgets provided" }),
    });

    await expect(fetchServerPreview(sampleWidgets, sampleSettings)).rejects.toThrow(
      "No widgets provided",
    );
  });

  it("passes abort signal to fetch", async () => {
    const controller = new AbortController();
    const fakeBlob = new Blob(["fake-png"]);
    mockFetch.mockResolvedValueOnce({
      ok: true,
      blob: async () => fakeBlob,
    });

    await fetchServerPreview(sampleWidgets, sampleSettings, controller.signal);

    expect(mockFetch).toHaveBeenCalledWith("/api/preview", expect.objectContaining({
      signal: controller.signal,
    }));
  });
});

describe("fetchPowerStatus", () => {
  it("returns the power status on 200", async () => {
    mockFetch.mockResolvedValueOnce({
      ok: true,
      status: 200,
      json: async () => ({ hub: "1-1", port: 3, powered: true, connected: true }),
    });

    const result = await fetchPowerStatus();
    expect(result).toEqual({ hub: "1-1", port: 3, powered: true, connected: true });
    expect(mockFetch).toHaveBeenCalledWith("/api/power/status");
  });

  it("returns null on 404 (no controllable printer)", async () => {
    mockFetch.mockResolvedValueOnce({
      ok: false,
      status: 404,
      json: async () => ({ status: "error", message: "Printer not detected" }),
    });

    const result = await fetchPowerStatus();
    expect(result).toBeNull();
  });

  it("throws with server error message on 500", async () => {
    mockFetch.mockResolvedValueOnce({
      ok: false,
      status: 500,
      json: async () => ({ status: "error", message: "uhubctl failed" }),
    });

    await expect(fetchPowerStatus()).rejects.toThrow("uhubctl failed");
  });
});

describe("powerOn", () => {
  it("sends POST and returns the updated status", async () => {
    mockFetch.mockResolvedValueOnce({
      ok: true,
      json: async () => ({
        status: "success",
        hub: "1-1",
        port: 3,
        powered: true,
        connected: true,
      }),
    });

    const result = await powerOn();
    expect(result).toEqual({ hub: "1-1", port: 3, powered: true, connected: true });
    expect(mockFetch).toHaveBeenCalledWith("/api/power/on", { method: "POST" });
  });

  it("throws with server error message on failure", async () => {
    mockFetch.mockResolvedValueOnce({
      ok: false,
      status: 500,
      json: async () => ({ status: "error", message: "uhubctl: hub not found" }),
    });

    await expect(powerOn()).rejects.toThrow("uhubctl: hub not found");
  });
});

describe("powerOff", () => {
  it("sends POST and returns the updated status", async () => {
    mockFetch.mockResolvedValueOnce({
      ok: true,
      json: async () => ({
        status: "success",
        hub: "1-1",
        port: 3,
        powered: false,
        connected: false,
      }),
    });

    const result = await powerOff();
    expect(result).toEqual({ hub: "1-1", port: 3, powered: false, connected: false });
    expect(mockFetch).toHaveBeenCalledWith("/api/power/off", { method: "POST" });
  });
});

describe("uploadImage", () => {
  it("sends POST to /api/upload-image with FormData", async () => {
    mockFetch.mockResolvedValueOnce({
      ok: true,
      json: async () => ({ filename: "abc123.png" }),
    });

    const file = new File(["fake-image"], "test.png", { type: "image/png" });
    const result = await uploadImage(file);

    expect(result).toEqual({ filename: "abc123.png" });
    expect(mockFetch).toHaveBeenCalledWith("/api/upload-image", {
      method: "POST",
      body: expect.any(FormData),
    });
  });

  it("throws with server error message on failure", async () => {
    mockFetch.mockResolvedValueOnce({
      ok: false,
      json: async () => ({ status: "error", message: "No file provided" }),
    });

    const file = new File(["fake"], "test.png", { type: "image/png" });
    await expect(uploadImage(file)).rejects.toThrow("No file provided");
  });
});

describe("fetchPrinterSettings", () => {
  it("GETs the URL-encoded printer id and returns the settings", async () => {
    mockFetch.mockResolvedValueOnce({
      ok: true,
      json: async () => ({ settings: { tapeSizeMm: 19 } }),
    });

    const result = await fetchPrinterSettings("Bus 001 Device 005: ID 0922:1234");

    expect(result).toEqual({ tapeSizeMm: 19 });
    expect(mockFetch).toHaveBeenCalledWith(
      "/api/printers/Bus%20001%20Device%20005%3A%20ID%200922%3A1234/settings",
    );
  });

  it("returns {} when the server reports no saved settings", async () => {
    mockFetch.mockResolvedValueOnce({
      ok: true,
      json: async () => ({ settings: {} }),
    });
    expect(await fetchPrinterSettings("usb:1")).toEqual({});
  });

  it("throws on a non-ok response", async () => {
    mockFetch.mockResolvedValueOnce({ ok: false });
    await expect(fetchPrinterSettings("usb:1")).rejects.toThrow();
  });
});

describe("savePrinterSettings", () => {
  it("PUTs the settings as JSON to the encoded id", async () => {
    mockFetch.mockResolvedValueOnce({ ok: true, json: async () => ({}) });

    await savePrinterSettings("virtual:Office", {
      tapeSizeMm: 12,
      foregroundColor: "black",
      backgroundColor: "white",
    });

    expect(mockFetch).toHaveBeenCalledWith(
      "/api/printers/virtual%3AOffice/settings",
      {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          tapeSizeMm: 12,
          foregroundColor: "black",
          backgroundColor: "white",
        }),
      },
    );
  });

  it("throws on a non-ok response", async () => {
    mockFetch.mockResolvedValueOnce({ ok: false });
    await expect(
      savePrinterSettings("usb:1", { tapeSizeMm: 12 }),
    ).rejects.toThrow();
  });
});
