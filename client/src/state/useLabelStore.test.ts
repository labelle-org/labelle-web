import { describe, it, expect, beforeEach } from "vitest";
import { useLabelStore } from "./useLabelStore";
import { DEFAULT_MARGIN_PX, DEFAULT_FONT_SCALE } from "../lib/constants";
import type { LabelWidget, LabelSettings, PrinterInfo } from "../types/label";

beforeEach(() => {
  // Reset store to initial state before each test
  useLabelStore.setState(useLabelStore.getInitialState());
});

describe("Widget CRUD", () => {
  it("addTextWidget adds a text widget with defaults", () => {
    useLabelStore.getState().addTextWidget();
    const widgets = useLabelStore.getState().widgets;
    // Initial "Hello" widget + new one
    expect(widgets).toHaveLength(2);
    const added = widgets[1]!;
    expect(added.type).toBe("text");
    if (added.type === "text") {
      expect(added.text).toBe("");
      expect(added.fontStyle).toBe("regular");
      expect(added.fontScale).toBe(DEFAULT_FONT_SCALE);
      expect(added.frameWidthPx).toBe(0);
      expect(added.align).toBe("left");
    }
  });

  it("addQrWidget adds a QR widget", () => {
    useLabelStore.getState().addQrWidget();
    const widgets = useLabelStore.getState().widgets;
    expect(widgets).toHaveLength(2);
    const added = widgets[1]!;
    expect(added.type).toBe("qr");
    if (added.type === "qr") {
      expect(added.content).toBe("");
    }
  });

  it("addBarcodeWidget adds a barcode widget", () => {
    useLabelStore.getState().addBarcodeWidget();
    const widgets = useLabelStore.getState().widgets;
    expect(widgets).toHaveLength(2);
    const added = widgets[1]!;
    expect(added.type).toBe("barcode");
    if (added.type === "barcode") {
      expect(added.content).toBe("");
      expect(added.barcodeType).toBe("code128");
      expect(added.showText).toBe(false);
    }
  });

  it("addImageWidget adds an image widget with given filename", () => {
    useLabelStore.getState().addImageWidget("photo.png");
    const widgets = useLabelStore.getState().widgets;
    expect(widgets).toHaveLength(2);
    const added = widgets[1]!;
    expect(added.type).toBe("image");
    if (added.type === "image") {
      expect(added.filename).toBe("photo.png");
    }
  });

  it("removeWidget removes by ID", () => {
    const initialId = useLabelStore.getState().widgets[0]!.id;
    useLabelStore.getState().removeWidget(initialId);
    expect(useLabelStore.getState().widgets).toHaveLength(0);
  });

  it("moveWidget reorders widgets", () => {
    useLabelStore.getState().addQrWidget();
    const before = useLabelStore.getState().widgets;
    const firstId = before[0]!.id;
    const secondId = before[1]!.id;

    useLabelStore.getState().moveWidget(0, 1);

    const after = useLabelStore.getState().widgets;
    expect(after[0]!.id).toBe(secondId);
    expect(after[1]!.id).toBe(firstId);
  });

  it("moveWidget is no-op when fromIndex === toIndex", () => {
    const before = useLabelStore.getState().widgets;
    useLabelStore.getState().moveWidget(0, 0);
    const after = useLabelStore.getState().widgets;
    // Same reference (no state update)
    expect(after).toBe(before);
  });

  it("updateWidget merges partial updates", () => {
    const id = useLabelStore.getState().widgets[0]!.id;
    useLabelStore.getState().updateWidget(id, { text: "Updated" } as Partial<LabelWidget>);
    const widget = useLabelStore.getState().widgets[0]!;
    expect(widget.type).toBe("text");
    if (widget.type === "text") {
      expect(widget.text).toBe("Updated");
      // Other fields preserved
      expect(widget.fontStyle).toBe("regular");
    }
  });
});

describe("Settings", () => {
  it("updateSettings merges partial settings", () => {
    useLabelStore.getState().updateSettings({ tapeSizeMm: 19 });
    const settings = useLabelStore.getState().settings;
    expect(settings.tapeSizeMm).toBe(19);
    // Other settings preserved
    expect(settings.justify).toBe("center");
  });

  it("default settings match expected values", () => {
    const settings = useLabelStore.getState().settings;
    expect(settings).toEqual({
      tapeSizeMm: 12,
      marginPx: DEFAULT_MARGIN_PX,
      minLengthMm: 0,
      justify: "center",
      foregroundColor: "black",
      backgroundColor: "white",
      showMargins: false,
      cutMark: false,
    });
  });
});

describe("Printers", () => {
  it("setAvailablePrinters stores printer list", () => {
    const printers: PrinterInfo[] = [
      { id: "usb:1", name: "DYMO", vendorProductId: "0922:1002" },
    ];
    useLabelStore.getState().setAvailablePrinters(printers);
    expect(useLabelStore.getState().availablePrinters).toEqual(printers);
  });

  it("setAvailablePrinters marks the list as loaded", () => {
    // The per-printer settings gate keys off this; App also calls
    // setAvailablePrinters([]) on fetch error so the gate still lifts.
    useLabelStore.setState({ availablePrintersLoaded: false });
    useLabelStore.getState().setAvailablePrinters([]);
    expect(useLabelStore.getState().availablePrintersLoaded).toBe(true);
  });

  it("defaults the selection to the first printer when none is chosen", () => {
    useLabelStore.getState().setAvailablePrinters([
      { id: "usb:1", name: "A", vendorProductId: "0922:1002" },
      { id: "virtual:b", name: "B", vendorProductId: "virtual" },
    ]);
    expect(useLabelStore.getState().settings.printerId).toBe("usb:1");
  });

  it("keeps the current selection when it is still present", () => {
    useLabelStore.setState({
      settings: { ...useLabelStore.getState().settings, printerId: "virtual:b" },
    });
    useLabelStore.getState().setAvailablePrinters([
      { id: "usb:1", name: "A", vendorProductId: "0922:1002" },
      { id: "virtual:b", name: "B", vendorProductId: "virtual" },
    ]);
    expect(useLabelStore.getState().settings.printerId).toBe("virtual:b");
  });

  it("re-selects the first printer when the selected one vanishes", () => {
    useLabelStore.setState({
      settings: { ...useLabelStore.getState().settings, printerId: "virtual:b" },
    });
    useLabelStore.getState().setAvailablePrinters([
      { id: "usb:1", name: "A", vendorProductId: "0922:1002" },
    ]);
    expect(useLabelStore.getState().settings.printerId).toBe("usb:1");
  });

  it("clears the selection when no printers are present", () => {
    useLabelStore.setState({
      settings: { ...useLabelStore.getState().settings, printerId: "usb:1" },
    });
    useLabelStore.getState().setAvailablePrinters([]);
    expect(useLabelStore.getState().settings.printerId).toBeUndefined();
  });
});

describe("Load", () => {
  it("loadLabel replaces widgets and settings", () => {
    const widgets: LabelWidget[] = [
      { id: "new-1", type: "qr", content: "hello" },
    ];
    const settings: LabelSettings = {
      tapeSizeMm: 6,
      marginPx: 20,
      minLengthMm: 10,
      justify: "left",
      foregroundColor: "blue",
      backgroundColor: "yellow",
      showMargins: true,
      cutMark: false,
    };

    useLabelStore.getState().loadLabel(widgets, settings);

    expect(useLabelStore.getState().widgets).toEqual(widgets);
    expect(useLabelStore.getState().settings).toEqual(settings);
  });

  it("loadLabel keeps the current printer selection", () => {
    // Importing a label loads its design content but must not reassign the
    // printer you're on (its printerId is stripped on export anyway).
    useLabelStore.setState({
      settings: { ...useLabelStore.getState().settings, printerId: "serial:ME" },
    });
    const settings: LabelSettings = {
      tapeSizeMm: 6,
      marginPx: 20,
      minLengthMm: 10,
      justify: "left",
      foregroundColor: "blue",
      backgroundColor: "yellow",
      showMargins: true,
      cutMark: false,
      printerId: "serial:OTHER",
    };

    useLabelStore.getState().loadLabel([], settings);

    expect(useLabelStore.getState().settings.printerId).toBe("serial:ME");
    expect(useLabelStore.getState().settings.tapeSizeMm).toBe(6);
  });
});

describe("Variable rename in batch rows", () => {
  function seedTextWidgetWith(text: string): string {
    useLabelStore.setState({
      widgets: [
        {
          id: "w1",
          type: "text",
          text,
          fontStyle: "regular",
          fontScale: DEFAULT_FONT_SCALE,
          frameWidthPx: 0,
          align: "left",
        },
      ],
    });
    return "w1";
  }

  function seedRows(values: Record<string, string>[]) {
    return values.map((v, i) => ({ id: `r${i}`, values: v }));
  }

  function rowValues(idx = 0) {
    return useLabelStore.getState().batch.rows[idx]?.values;
  }

  it("carries batch row values from old name to new on rename", () => {
    const id = seedTextWidgetWith("Hi {{name}}");
    useLabelStore.setState({
      batch: {
        copies: 1,
        pauseTime: 0,
        rows: seedRows([{ name: "Alice" }, { name: "Bob" }]),
        selectedRowIndex: null,
      },
    });

    useLabelStore.getState().updateWidget(id, { text: "Hi {{full_name}}" });

    expect(rowValues(0)).toEqual({ full_name: "Alice" });
    expect(rowValues(1)).toEqual({ full_name: "Bob" });
  });

  it("carries values through incremental typing edits", () => {
    const id = seedTextWidgetWith("{{name}}");
    useLabelStore.setState({
      batch: {
        copies: 1,
        pauseTime: 0,
        rows: seedRows([{ name: "Alice" }]),
        selectedRowIndex: null,
      },
    });

    // Simulate typing "name" -> "names"
    useLabelStore.getState().updateWidget(id, { text: "{{names}}" });
    expect(rowValues(0)).toEqual({ names: "Alice" });
  });

  it("carries values through a backspace-to-empty rename (color -> size)", () => {
    const id = seedTextWidgetWith("{{color}}");
    useLabelStore.setState({
      batch: {
        copies: 1,
        pauseTime: 0,
        rows: seedRows([{ color: "red" }, { color: "blue" }]),
        selectedRowIndex: null,
      },
    });

    // The gesture the user actually makes: backspace "color" down to {{}} one
    // character at a time, then type "size". Every keystroke is its own
    // updateWidget call — the empty {{}} state must not orphan the value.
    const steps = [
      "{{colo}}", "{{col}}", "{{co}}", "{{c}}", "{{}}",
      "{{s}}", "{{si}}", "{{siz}}", "{{size}}",
    ];
    for (const text of steps) {
      useLabelStore.getState().updateWidget(id, { text });
    }

    const widget = useLabelStore.getState().widgets[0] as { text: string };
    expect(widget.text).toBe("{{size}}");
    expect(rowValues(0)).toEqual({ size: "red" });
    expect(rowValues(1)).toEqual({ size: "blue" });
  });

  it("preserves the value across the empty {{}} intermediate state", () => {
    const id = seedTextWidgetWith("{{name}}");
    useLabelStore.setState({
      batch: {
        copies: 1,
        pauseTime: 0,
        rows: seedRows([{ name: "Alice" }]),
        selectedRowIndex: null,
      },
    });

    // Backspaced the whole name (held under the empty key)…
    useLabelStore.getState().updateWidget(id, { text: "{{}}" });
    // …then a fresh name picks it back up.
    useLabelStore.getState().updateWidget(id, { text: "{{email}}" });

    expect(rowValues(0)).toEqual({ email: "Alice" });
  });

  it("propagates a backspace rename to other widgets sharing the variable", () => {
    useLabelStore.setState({
      widgets: [
        {
          id: "w1",
          type: "text",
          text: "{{color}}",
          fontStyle: "regular",
          fontScale: DEFAULT_FONT_SCALE,
          frameWidthPx: 0,
          align: "left",
        },
        { id: "w2", type: "qr", content: "{{color}}" },
      ],
      batch: {
        copies: 1,
        pauseTime: 0,
        rows: seedRows([{ color: "red" }]),
        selectedRowIndex: null,
      },
    });

    const steps = [
      "{{colo}}", "{{col}}", "{{co}}", "{{c}}", "{{}}",
      "{{s}}", "{{si}}", "{{siz}}", "{{size}}",
    ];
    for (const text of steps) {
      useLabelStore.getState().updateWidget("w1", { text });
    }

    const widgets = useLabelStore.getState().widgets;
    expect((widgets[0] as { text: string }).text).toBe("{{size}}");
    expect((widgets[1] as { content: string }).content).toBe("{{size}}");
    expect(rowValues(0)).toEqual({ size: "red" });
  });

  it("does not touch rows when a variable is purely added", () => {
    const id = seedTextWidgetWith("{{name}}");
    useLabelStore.setState({
      batch: {
        copies: 1,
        pauseTime: 0,
        rows: seedRows([{ name: "Alice" }]),
        selectedRowIndex: null,
      },
    });

    useLabelStore.getState().updateWidget(id, { text: "{{name}} {{age}}" });

    expect(rowValues(0)).toEqual({ name: "Alice" });
  });

  it("does not touch rows when a variable is purely removed", () => {
    const id = seedTextWidgetWith("{{name}} {{age}}");
    useLabelStore.setState({
      batch: {
        copies: 1,
        pauseTime: 0,
        rows: seedRows([{ name: "Alice", age: "30" }]),
        selectedRowIndex: null,
      },
    });

    useLabelStore.getState().updateWidget(id, { text: "{{name}}" });

    // age value orphans but isn't reassigned to something else
    expect(rowValues(0)).toEqual({ name: "Alice", age: "30" });
  });

  it("detects and renames hyphenated variable names", () => {
    const id = seedTextWidgetWith("Hi {{first-name}}");
    useLabelStore.setState({
      batch: {
        copies: 1,
        pauseTime: 0,
        rows: seedRows([{ "first-name": "Alice" }]),
        selectedRowIndex: null,
      },
    });

    useLabelStore.getState().updateWidget(id, { text: "Hi {{full-name}}" });

    expect(rowValues(0)).toEqual({ "full-name": "Alice" });
  });

  it("preserves row id across rename migration", () => {
    const id = seedTextWidgetWith("{{name}}");
    useLabelStore.setState({
      batch: {
        copies: 1,
        pauseTime: 0,
        rows: seedRows([{ name: "Alice" }]),
        selectedRowIndex: null,
      },
    });

    useLabelStore.getState().updateWidget(id, { text: "{{full_name}}" });

    expect(useLabelStore.getState().batch.rows[0]?.id).toBe("r0");
  });

  it("propagates rename to other widgets that reference the same variable", () => {
    useLabelStore.setState({
      widgets: [
        {
          id: "w1",
          type: "text",
          text: "Hello {{name}}",
          fontStyle: "regular",
          fontScale: DEFAULT_FONT_SCALE,
          frameWidthPx: 0,
          align: "left",
        },
        { id: "w2", type: "qr", content: "user/{{name}}" },
        { id: "w3", type: "barcode", content: "{{name}}", barcodeType: "code128", showText: false },
      ],
      batch: {
        copies: 1,
        pauseTime: 0,
        rows: seedRows([{ name: "Alice" }]),
        selectedRowIndex: null,
      },
    });

    useLabelStore.getState().updateWidget("w1", { text: "Hello {{full_name}}" });

    const widgets = useLabelStore.getState().widgets;
    expect((widgets[0] as { text: string }).text).toBe("Hello {{full_name}}");
    expect((widgets[1] as { content: string }).content).toBe("user/{{full_name}}");
    expect((widgets[2] as { content: string }).content).toBe("{{full_name}}");
    expect(rowValues(0)).toEqual({ full_name: "Alice" });
  });

  it("does not propagate when a different widget gets an unrelated edit", () => {
    // Two unrelated edits in different widgets — without per-widget scoping
    // the heuristic could see {removed:[a], added:[b]} from cross-widget
    // bookkeeping and incorrectly carry values. Per-widget scoping prevents
    // this: removing var from B doesn't migrate A's row data.
    useLabelStore.setState({
      widgets: [
        {
          id: "w1",
          type: "text",
          text: "{{name}}",
          fontStyle: "regular",
          fontScale: DEFAULT_FONT_SCALE,
          frameWidthPx: 0,
          align: "left",
        },
        {
          id: "w2",
          type: "text",
          text: "{{age}}",
          fontStyle: "regular",
          fontScale: DEFAULT_FONT_SCALE,
          frameWidthPx: 0,
          align: "left",
        },
      ],
      batch: {
        copies: 1,
        pauseTime: 0,
        rows: seedRows([{ name: "Alice", age: "30" }]),
        selectedRowIndex: null,
      },
    });

    // Remove {{age}} from widget 2 only (a pure removal).
    useLabelStore.getState().updateWidget("w2", { text: "" });

    // Row data should be unchanged — age value orphans but name is not
    // migrated into age (or vice versa).
    expect(rowValues(0)).toEqual({ name: "Alice", age: "30" });
  });
});
