import { describe, it, expect, beforeEach, afterEach, vi } from "vitest";
import { render, screen, cleanup, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

// PowerToggle (rendered inside SettingsBar) fires fetchPowerStatus on
// mount. Stub it out so these tests stay focused on the settings UI
// and don't make real HTTP calls.
vi.mock("../lib/api", () => ({
  fetchPrinters: vi.fn().mockResolvedValue([]),
  fetchPowerStatus: vi.fn().mockResolvedValue({
    hub: "1-1",
    port: 3,
    powered: true,
    connected: true,
  }),
  powerOn: vi.fn(),
  powerOff: vi.fn(),
  // usePrinterSettings runs inside SettingsBar.
  fetchPrinterSettings: vi.fn().mockResolvedValue({}),
  savePrinterSettings: vi.fn().mockResolvedValue(undefined),
}));

import { SettingsBar } from "./SettingsBar";
import { fetchPrinterSettings, savePrinterSettings } from "../lib/api";
import { useLabelStore } from "../state/useLabelStore";
import type { PrinterInfo } from "../types/label";

const twoPrinters: PrinterInfo[] = [
  { id: "usb:1", name: "DYMO LabelWriter 450", vendorProductId: "0922:1002" },
  { id: "virtual:Office", name: "Office (Virtual)", vendorProductId: "virtual" },
];

afterEach(() => {
  cleanup();
});

beforeEach(() => {
  vi.clearAllMocks();
  // Reset store to defaults
  useLabelStore.setState({
    availablePrinters: [],
    settings: {
      tapeSizeMm: 12,
      marginPx: 56,
      minLengthMm: 0,
      justify: "center",
      foregroundColor: "black",
      backgroundColor: "white",
      showMargins: false,
      cutMark: false,
    },
  });
});

describe("SettingsBar printer selector", () => {
  it("shows printer selector when multiple printers available", () => {
    useLabelStore.setState({ availablePrinters: twoPrinters });
    render(<SettingsBar />);

    // Open the details
    screen.getByText("Settings").click();

    expect(screen.getByText("Printer")).toBeInTheDocument();
    expect(screen.getByText("Auto-select")).toBeInTheDocument();
  });

  it("hides printer selector when 0 printers", () => {
    useLabelStore.setState({ availablePrinters: [] });
    render(<SettingsBar />);

    screen.getByText("Settings").click();

    expect(screen.queryByText("Printer")).not.toBeInTheDocument();
  });

  it("hides printer selector when only 1 printer", () => {
    useLabelStore.setState({ availablePrinters: [twoPrinters[0]!] });
    render(<SettingsBar />);

    screen.getByText("Settings").click();

    expect(screen.queryByText("Printer")).not.toBeInTheDocument();
  });

  it("lists all printers plus Auto-select", () => {
    useLabelStore.setState({ availablePrinters: twoPrinters });
    render(<SettingsBar />);

    screen.getByText("Settings").click();

    const select = screen.getByDisplayValue("Auto-select");
    const options = select.querySelectorAll("option");

    // Auto-select + 2 printers = 3 options
    expect(options).toHaveLength(3);
    expect(options[0]!.textContent).toBe("Auto-select");
    expect(options[1]!.textContent).toBe("DYMO LabelWriter 450");
    expect(options[2]!.textContent).toBe("Office (Virtual)");
  });

  it("selecting a printer updates the store", async () => {
    useLabelStore.setState({ availablePrinters: twoPrinters });
    render(<SettingsBar />);

    screen.getByText("Settings").click();

    const select = screen.getByDisplayValue("Auto-select");
    await userEvent.selectOptions(select, "virtual:Office");

    expect(useLabelStore.getState().settings.printerId).toBe("virtual:Office");
  });

  it("selecting Auto-select clears printerId", async () => {
    useLabelStore.setState({
      availablePrinters: twoPrinters,
      settings: {
        ...useLabelStore.getState().settings,
        printerId: "usb:1",
      },
    });
    render(<SettingsBar />);

    screen.getByText("Settings").click();

    const select = screen.getByDisplayValue("DYMO LabelWriter 450");
    await userEvent.selectOptions(select, "");

    expect(useLabelStore.getState().settings.printerId).toBeUndefined();
  });
});

describe("SettingsBar per-printer settings persistence", () => {
  it("applies saved settings when a printer is selected", async () => {
    vi.mocked(fetchPrinterSettings).mockResolvedValueOnce({ tapeSizeMm: 6 });
    useLabelStore.setState({
      availablePrinters: twoPrinters,
      settings: { ...useLabelStore.getState().settings, printerId: "usb:1" },
    });
    render(<SettingsBar />);

    await waitFor(() => {
      expect(useLabelStore.getState().settings.tapeSizeMm).toBe(6);
    });
    expect(fetchPrinterSettings).toHaveBeenCalledWith("usb:1");
  });

  it("persists the full subset when the tape size changes", async () => {
    useLabelStore.setState({
      availablePrinters: twoPrinters,
      settings: { ...useLabelStore.getState().settings, printerId: "usb:1" },
    });
    render(<SettingsBar />);
    screen.getByText("Settings").click();

    const tapeSelect = screen.getByDisplayValue("12");
    await userEvent.selectOptions(tapeSelect, "19");

    expect(savePrinterSettings).toHaveBeenCalledWith("usb:1", {
      tapeSizeMm: 19,
      foregroundColor: "black",
      backgroundColor: "white",
    });
  });

  it("uses the single connected printer even on Auto-select", async () => {
    useLabelStore.setState({
      availablePrinters: [twoPrinters[0]!],
      settings: { ...useLabelStore.getState().settings, printerId: undefined },
    });
    render(<SettingsBar />);

    await waitFor(() => {
      expect(fetchPrinterSettings).toHaveBeenCalledWith("usb:1");
    });
  });

  it("does not persist on Auto-select with multiple printers", async () => {
    useLabelStore.setState({
      availablePrinters: twoPrinters,
      settings: { ...useLabelStore.getState().settings, printerId: undefined },
    });
    render(<SettingsBar />);
    screen.getByText("Settings").click();

    const tapeSelect = screen.getByDisplayValue("12");
    await userEvent.selectOptions(tapeSelect, "19");

    expect(savePrinterSettings).not.toHaveBeenCalled();
    // Ambiguous which printer the server picks, so we don't read either.
    expect(fetchPrinterSettings).not.toHaveBeenCalled();
  });
});

describe("SettingsBar power toggle visibility", () => {
  it("shows the power toggle when a real USB printer is selected", async () => {
    useLabelStore.setState({
      availablePrinters: twoPrinters,
      settings: { ...useLabelStore.getState().settings, printerId: "usb:1" },
    });
    render(<SettingsBar />);
    screen.getByText("Settings").click();

    await waitFor(() => {
      expect(screen.getByText("Printer power")).toBeInTheDocument();
    });
  });

  it("shows the power toggle on Auto-select (no printerId)", async () => {
    useLabelStore.setState({
      availablePrinters: twoPrinters,
      settings: { ...useLabelStore.getState().settings, printerId: undefined },
    });
    render(<SettingsBar />);
    screen.getByText("Settings").click();

    await waitFor(() => {
      expect(screen.getByText("Printer power")).toBeInTheDocument();
    });
  });

  it("hides the power toggle when a virtual printer is selected", async () => {
    useLabelStore.setState({
      availablePrinters: twoPrinters,
      settings: {
        ...useLabelStore.getState().settings,
        printerId: "virtual:Office",
      },
    });
    render(<SettingsBar />);
    screen.getByText("Settings").click();

    // Even after the api mock resolves, "Printer power" should never
    // appear because PowerToggle isn't rendered at all.
    await new Promise((r) => setTimeout(r, 50));
    expect(screen.queryByText("Printer power")).not.toBeInTheDocument();
  });
});
