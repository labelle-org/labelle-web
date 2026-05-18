import { describe, it, expect, beforeEach, afterEach } from "vitest";
import { render, screen, cleanup } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

import { BatchPanel } from "./BatchPanel";
import { useLabelStore } from "../state/useLabelStore";
import { DEFAULT_FONT_SCALE, DEFAULT_MARGIN_PX } from "../lib/constants";

afterEach(() => {
  cleanup();
});

beforeEach(() => {
  useLabelStore.setState({
    widgets: [
      {
        id: "w1",
        type: "text",
        text: "",
        fontStyle: "regular",
        fontScale: DEFAULT_FONT_SCALE,
        frameWidthPx: 0,
        align: "left",
      },
    ],
    settings: {
      tapeSizeMm: 12,
      marginPx: DEFAULT_MARGIN_PX,
      minLengthMm: 0,
      justify: "center",
      foregroundColor: "black",
      backgroundColor: "white",
      showMargins: false,
      cutMark: false,
    },
    batch: {
      copies: 1,
      pauseTime: 0,
      rows: [{ id: "r0", values: {} }],
      selectedRowIndex: null,
    },
  });
});

describe("BatchPanel auto-selects row 0 when batch mode first activates", () => {
  it("auto-selects row 0 after clicking + Add Variable", async () => {
    render(<BatchPanel />);

    expect(useLabelStore.getState().batch.selectedRowIndex).toBeNull();

    await userEvent.click(
      screen.getByRole("button", { name: /Add Variable/i }),
    );

    expect(useLabelStore.getState().batch.selectedRowIndex).toBe(0);
  });

  it("does not re-select row 0 after the user deselects via the eye icon", async () => {
    render(<BatchPanel />);

    await userEvent.click(
      screen.getByRole("button", { name: /Add Variable/i }),
    );
    expect(useLabelStore.getState().batch.selectedRowIndex).toBe(0);

    await userEvent.click(
      screen.getByRole("button", { name: /Stop previewing row 1/i }),
    );

    expect(useLabelStore.getState().batch.selectedRowIndex).toBeNull();
  });
});
