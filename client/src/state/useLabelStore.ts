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

const DEFAULT_BATCH: BatchState = {
  enabled: false,
  copies: 1,
  pauseTime: 0,
  rows: [{}],
  selectedRowIndex: null,
};

interface LabelStore {
  widgets: LabelWidget[];
  settings: LabelSettings;
  availablePrinters: PrinterInfo[];
  batch: BatchState;

  addTextWidget: () => void;
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
  },

  availablePrinters: [],

  batch: { ...DEFAULT_BATCH },

  addTextWidget: () =>
    set((s) => ({
      widgets: [
        ...s.widgets,
        {
          id: uuidv4(),
          type: "text",
          text: "",
          fontStyle: "regular",
          fontScale: DEFAULT_FONT_SCALE,
          frameWidthPx: 0,
          align: "left",
        } satisfies TextWidget,
      ],
    })),

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
    set((s) => ({
      widgets: s.widgets.map((w) =>
        w.id === id ? ({ ...w, ...patch } as LabelWidget) : w,
      ),
    })),

  updateSettings: (patch) =>
    set((s) => ({ settings: { ...s.settings, ...patch } })),

  setAvailablePrinters: (printers) => set({ availablePrinters: printers }),

  updateBatch: (patch) =>
    set((s) => ({ batch: { ...s.batch, ...patch } })),

  setBatchRow: (rowIndex, varName, value) =>
    set((s) => {
      const rows = s.batch.rows.map((row, i) =>
        i === rowIndex ? { ...row, [varName]: value } : row,
      );
      return { batch: { ...s.batch, rows } };
    }),

  addBatchRow: () =>
    set((s) => ({
      batch: { ...s.batch, rows: [...s.batch.rows, {}] },
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
      return { batch: { ...s.batch, rows: rows.length ? rows : [{}], selectedRowIndex } };
    }),

  loadLabel: (widgets, settings, batch) =>
    set({ widgets, settings, batch: batch ?? { ...DEFAULT_BATCH } }),
}));
