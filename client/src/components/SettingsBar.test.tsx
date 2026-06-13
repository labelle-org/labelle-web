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
}));

import { SettingsBar } from "./SettingsBar";
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
    useLabelStore.getState().setAvailablePrinters(twoPrinters);
    render(<SettingsBar />);

    // Open the details
    screen.getByText("Settings").click();

    expect(screen.getByText("Printer")).toBeInTheDocument();
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

  it("lists all available printers (no Auto-select option)", () => {
    useLabelStore.getState().setAvailablePrinters(twoPrinters);
    render(<SettingsBar />);

    screen.getByText("Settings").click();

    // Defaults to the first printer; the "Auto-select" entry is gone.
    const select = screen.getByDisplayValue("DYMO LabelWriter 450");
    const options = select.querySelectorAll("option");
    expect(options).toHaveLength(2);
    expect(options[0]!.textContent).toBe("DYMO LabelWriter 450");
    expect(options[1]!.textContent).toBe("Office (Virtual)");
  });

  it("defaults the selection to the first printer when the list loads", () => {
    useLabelStore.getState().setAvailablePrinters(twoPrinters);
    expect(useLabelStore.getState().settings.printerId).toBe("usb:1");
  });

  it("selecting a printer updates the store", async () => {
    useLabelStore.getState().setAvailablePrinters(twoPrinters);
    render(<SettingsBar />);

    screen.getByText("Settings").click();

    const select = screen.getByDisplayValue("DYMO LabelWriter 450");
    await userEvent.selectOptions(select, "virtual:Office");

    expect(useLabelStore.getState().settings.printerId).toBe("virtual:Office");
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

  it("shows the power toggle when no printer is resolved yet (no printerId)", async () => {
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
