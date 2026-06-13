import { create } from "zustand";
import { v4 as uuidv4 } from "uuid";
import type {
  LabelWidget,
  LabelSettings,
  BatchState,
  TextWidget,
  QrWidget,
  BarcodeWidget,
  ImageWidget,
  PrinterInfo,
} from "../types/label";
import { DEFAULT_MARGIN_PX, DEFAULT_FONT_SCALE } from "../lib/constants";
import { detectVariables } from "../lib/variables";

function newBatchRow(values: Record<string, string> = {}) {
  return { id: uuidv4(), values };
}

function defaultBatch(): BatchState {
  return {
    copies: 1,
    pauseTime: 0,
    rows: [newBatchRow()],
    selectedRowIndex: null,
  };
}

interface LabelStore {
  widgets: LabelWidget[];
  settings: LabelSettings;
  availablePrinters: PrinterInfo[];
  // Whether the initial /api/printers fetch has settled. Distinguishes
  // "not fetched yet" from "fetched, none found" so per-printer settings
  // can hold edits until the effective printer's settings are known.
  availablePrintersLoaded: boolean;
  batch: BatchState;

  addTextWidget: () => string;
  addQrWidget: () => void;
  addBarcodeWidget: () => void;
  addImageWidget: (filename: string) => void;
  removeWidget: (id: string) => void;
  moveWidget: (fromIndex: number, toIndex: number) => void;
  updateWidget: (id: string, patch: Partial<LabelWidget>) => void;
  updateSettings: (patch: Partial<LabelSettings>) => void;
  setAvailablePrinters: (printers: PrinterInfo[]) => void;
  updateBatch: (patch: Partial<BatchState>) => void;
  setBatchRow: (rowIndex: number, varName: string, value: string) => void;
  addBatchRow: () => void;
  removeBatchRow: (index: number) => void;
  loadLabel: (
    widgets: LabelWidget[],
    settings: LabelSettings,
    batch?: BatchState,
  ) => void;
}

export const useLabelStore = create<LabelStore>((set) => ({
  widgets: [
    {
      id: uuidv4(),
      type: "text",
      text: "Hello",
      fontStyle: "regular",
      fontScale: DEFAULT_FONT_SCALE,
      frameWidthPx: 0,
      align: "left",
    } satisfies TextWidget,
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

  availablePrinters: [],
  availablePrintersLoaded: false,

  batch: defaultBatch(),

  addTextWidget: () => {
    const id = uuidv4();
    set((s) => ({
      widgets: [
        ...s.widgets,
        {
          id,
          type: "text",
          text: "",
          fontStyle: "regular",
          fontScale: DEFAULT_FONT_SCALE,
          frameWidthPx: 0,
          align: "left",
        } satisfies TextWidget,
      ],
    }));
    return id;
  },

  addQrWidget: () =>
    set((s) => ({
      widgets: [
        ...s.widgets,
        {
          id: uuidv4(),
          type: "qr",
          content: "",
        } satisfies QrWidget,
      ],
    })),

  addBarcodeWidget: () =>
    set((s) => ({
      widgets: [
        ...s.widgets,
        {
          id: uuidv4(),
          type: "barcode",
          content: "",
          barcodeType: "code128",
          showText: false,
        } satisfies BarcodeWidget,
      ],
    })),

  addImageWidget: (filename: string) =>
    set((s) => ({
      widgets: [
        ...s.widgets,
        {
          id: uuidv4(),
          type: "image",
          filename,
        } satisfies ImageWidget,
      ],
    })),

  removeWidget: (id) =>
    set((s) => ({ widgets: s.widgets.filter((w) => w.id !== id) })),

  moveWidget: (fromIndex, toIndex) =>
    set((s) => {
      if (fromIndex === toIndex) return s;
      const moved = s.widgets[fromIndex];
      if (!moved) return s;
      const widgets = s.widgets.filter((_, i) => i !== fromIndex);
      widgets.splice(toIndex, 0, moved);
      return { widgets };
    }),

  updateWidget: (id, patch) =>
    set((s) => {
      const oldWidget = s.widgets.find((w) => w.id === id);
      if (!oldWidget) return s;
      const newWidget = { ...oldWidget, ...patch } as LabelWidget;

      // Variable rename detection: compare variables in JUST the changed
      // widget. If exactly one disappeared and one appeared, treat it as a
      // rename — propagate to other widgets and migrate the batch row key.
      // Scoping to one widget avoids the cross-widget false-positive where
      // unrelated edits in two widgets could each contribute a single add
      // and remove.
      //
      // Known limitation: keystroke-by-keystroke typing in a controlled
      // <input> (e.g. {{name}} -> {{names} -> {{names}}) hits an
      // intermediate state with no closing braces, where detectVariables
      // returns []. The transition then looks like a pure removal followed
      // (one keystroke later) by a pure addition — neither half triggers
      // the rename branch, and the row value for the old name orphans. In
      // practice users edit via select-and-replace or paste, which works.
      // See docs/ARCHITECTURE.md "Variable rename heuristic" for context.
      const before = detectVariables([oldWidget]);
      const after = detectVariables([newWidget]);
      const removed = before.filter((v) => !after.includes(v));
      const added = after.filter((v) => !before.includes(v));

      if (removed.length === 1 && added.length === 1) {
        const oldName = removed[0]!;
        const newName = added[0]!;
        // Variable names match [\w-]+; none of those characters need regex
        // escaping (hyphen is only a metacharacter inside character classes).
        const placeholderRe = new RegExp(`\\{\\{${oldName}\\}\\}`, "g");
        const newPlaceholder = `{{${newName}}}`;

        const widgets = s.widgets.map((w) => {
          if (w.id === id) return newWidget;
          if (w.type === "text")
            return { ...w, text: w.text.replace(placeholderRe, newPlaceholder) };
          if (w.type === "qr" || w.type === "barcode")
            return {
              ...w,
              content: w.content.replace(placeholderRe, newPlaceholder),
            };
          return w;
        });

        // Migrate row values keys. If `newName` already existed in the
        // row (e.g. user renamed `{{name}}` -> `{{full_name}}` while
        // another widget already used `{{full_name}}`), the rename takes
        // precedence and the prior value is overwritten — the user's
        // most recent edit wins.
        const rows = s.batch.rows.map((row) => {
          if (!(oldName in row.values)) return row;
          const value = row.values[oldName] ?? "";
          const nextValues: Record<string, string> = {};
          for (const [k, v] of Object.entries(row.values)) {
            if (k !== oldName) nextValues[k] = v;
          }
          nextValues[newName] = value;
          return { ...row, values: nextValues };
        });

        return { widgets, batch: { ...s.batch, rows } };
      }

      const widgets = s.widgets.map((w) => (w.id === id ? newWidget : w));
      return { widgets };
    }),

  updateSettings: (patch) =>
    set((s) => ({ settings: { ...s.settings, ...patch } })),

  setAvailablePrinters: (printers) =>
    set({ availablePrinters: printers, availablePrintersLoaded: true }),

  updateBatch: (patch) =>
    set((s) => ({ batch: { ...s.batch, ...patch } })),

  setBatchRow: (rowIndex, varName, value) =>
    set((s) => {
      const rows = s.batch.rows.map((row, i) =>
        i === rowIndex
          ? { ...row, values: { ...row.values, [varName]: value } }
          : row,
      );
      return { batch: { ...s.batch, rows } };
    }),

  addBatchRow: () =>
    set((s) => ({
      batch: { ...s.batch, rows: [...s.batch.rows, newBatchRow()] },
    })),

  removeBatchRow: (index) =>
    set((s) => {
      const rows = s.batch.rows.filter((_, i) => i !== index);
      const selectedRowIndex =
        s.batch.selectedRowIndex === index
          ? null
          : s.batch.selectedRowIndex !== null &&
              s.batch.selectedRowIndex > index
            ? s.batch.selectedRowIndex - 1
            : s.batch.selectedRowIndex;
      return {
        batch: {
          ...s.batch,
          rows: rows.length ? rows : [newBatchRow()],
          selectedRowIndex,
        },
      };
    }),

  loadLabel: (widgets, settings, batch) =>
    // Keep the currently-selected printer; a label file describes design
    // content (tape/colors/widgets), not which printer you're on. Its
    // printerId is stripped on export and ignored here regardless.
    set((s) => ({
      widgets,
      settings: { ...settings, printerId: s.settings.printerId },
      batch: batch ?? defaultBatch(),
    })),
}));
