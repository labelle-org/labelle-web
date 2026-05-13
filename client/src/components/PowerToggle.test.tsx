import { describe, it, expect, beforeEach, afterEach, vi } from "vitest";
import { render, screen, cleanup, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

vi.mock("../lib/api", () => ({
  fetchPowerStatus: vi.fn(),
  powerOn: vi.fn(),
  powerOff: vi.fn(),
}));

import { PowerToggle } from "./PowerToggle";
import * as api from "../lib/api";
import type { PowerStatus } from "../types/label";

const mockFetch = vi.mocked(api.fetchPowerStatus);
const mockOn = vi.mocked(api.powerOn);
const mockOff = vi.mocked(api.powerOff);

beforeEach(() => {
  mockFetch.mockReset();
  mockOn.mockReset();
  mockOff.mockReset();
});

afterEach(() => {
  cleanup();
});

describe("PowerToggle", () => {
  it("renders nothing while the initial status is loading", () => {
    mockFetch.mockReturnValue(new Promise(() => {})); // never resolves
    const { container } = render(<PowerToggle />);
    expect(container.firstChild).toBeNull();
  });

  it("renders nothing when the server reports no controllable printer (null)", async () => {
    mockFetch.mockResolvedValue(null);
    const { container } = render(<PowerToggle />);
    await waitFor(() => {
      expect(container.firstChild).toBeNull();
    });
  });

  it("shows powered-on state with a Turn off button", async () => {
    mockFetch.mockResolvedValue({
      hub: "1-1",
      port: 3,
      powered: true,
      connected: true,
    });
    render(<PowerToggle />);
    await waitFor(() => {
      expect(screen.getByRole("button", { name: /turn off/i })).toBeInTheDocument();
    });
  });

  it("shows powered-off state with a Turn on button", async () => {
    mockFetch.mockResolvedValue({
      hub: "1-1",
      port: 3,
      powered: false,
      connected: false,
    });
    render(<PowerToggle />);
    await waitFor(() => {
      expect(screen.getByRole("button", { name: /turn on/i })).toBeInTheDocument();
    });
  });

  it("clicking Turn off calls powerOff and updates the UI", async () => {
    mockFetch.mockResolvedValue({
      hub: "1-1",
      port: 3,
      powered: true,
      connected: true,
    });
    mockOff.mockResolvedValue({
      hub: "1-1",
      port: 3,
      powered: false,
      connected: false,
    });
    render(<PowerToggle />);
    const btn = await screen.findByRole("button", { name: /turn off/i });
    await userEvent.click(btn);
    expect(mockOff).toHaveBeenCalledOnce();
    await waitFor(() => {
      expect(screen.getByRole("button", { name: /turn on/i })).toBeInTheDocument();
    });
  });

  it("clicking Turn on calls powerOn and updates the UI", async () => {
    mockFetch.mockResolvedValue({
      hub: "1-1",
      port: 3,
      powered: false,
      connected: false,
    });
    mockOn.mockResolvedValue({
      hub: "1-1",
      port: 3,
      powered: true,
      connected: true,
    });
    render(<PowerToggle />);
    const btn = await screen.findByRole("button", { name: /turn on/i });
    await userEvent.click(btn);
    expect(mockOn).toHaveBeenCalledOnce();
    await waitFor(() => {
      expect(screen.getByRole("button", { name: /turn off/i })).toBeInTheDocument();
    });
  });

  it("disables the button and shows a pending label while a toggle is in flight", async () => {
    mockFetch.mockResolvedValue({
      hub: "1-1",
      port: 3,
      powered: false,
      connected: false,
    });
    // Block powerOn so we can observe the in-flight state
    let resolveOn: (v: PowerStatus) => void = () => {};
    mockOn.mockReturnValue(
      new Promise<PowerStatus>((resolve) => {
        resolveOn = resolve;
      }),
    );
    render(<PowerToggle />);
    const btn = await screen.findByRole("button", { name: /turn on/i });
    await userEvent.click(btn);
    // While the request is pending, the button is disabled and shows the
    // pending label so the user sees something is happening (~1.5s).
    expect(screen.getByRole("button", { name: /powering on/i })).toBeDisabled();
    resolveOn({ hub: "1-1", port: 3, powered: true, connected: true });
    await waitFor(() => {
      expect(screen.getByRole("button", { name: /turn off/i })).toBeInTheDocument();
    });
  });

  it("recovers gracefully when a toggle fails (button re-enabled, state unchanged)", async () => {
    mockFetch.mockResolvedValue({
      hub: "1-1",
      port: 3,
      powered: true,
      connected: true,
    });
    mockOff.mockRejectedValue(new Error("uhubctl exploded"));
    const consoleSpy = vi.spyOn(console, "error").mockImplementation(() => {});
    render(<PowerToggle />);
    const btn = await screen.findByRole("button", { name: /turn off/i });
    await userEvent.click(btn);
    // After the rejection the button is back to its "Turn off" state,
    // not stuck in pending, and the user can retry.
    await waitFor(() => {
      const retry = screen.getByRole("button", { name: /turn off/i });
      expect(retry).not.toBeDisabled();
    });
    consoleSpy.mockRestore();
  });
});
