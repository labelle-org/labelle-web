export type TapeSize = 6 | 9 | 12 | 19;

export type FontStyle = "regular" | "bold" | "italic" | "narrow";

export type Alignment = "left" | "center" | "right";

export type BarcodeType =
  | "code128"
  | "code39"
  | "codabar"
  | "ean"
  | "ean13"
  | "ean14"
  | "ean8"
  | "gs1"
  | "gs1_128"
  | "isbn"
  | "isbn10"
  | "isbn13"
  | "itf"
  | "upc"
  | "upca";

export type LabelColor =
  | "white"
  | "black"
  | "yellow"
  | "blue"
  | "red"
  | "green";

export interface TextWidget {
  id: string;
  type: "text";
  text: string;
  fontStyle: FontStyle;
  fontScale: number;
  frameWidthPx: number;
  align: Alignment;
}

export interface QrWidget {
  id: string;
  type: "qr";
  content: string;
}

export interface BarcodeWidget {
  id: string;
  type: "barcode";
  content: string;
  barcodeType: BarcodeType;
  showText: boolean;
}

export interface ImageWidget {
  id: string;
  type: "image";
  filename: string;
}

export type LabelWidget = TextWidget | QrWidget | BarcodeWidget | ImageWidget;

export interface PrinterInfo {
  id: string;
  name: string;
  vendorProductId: string;
  serialNumber?: string;
}

export interface PowerStatus {
  hub: string;
  port: number;
  powered: boolean;
  connected: boolean;
}

export interface BatchRow {
  // Stable id so React keys survive row reordering/removal. Internal only —
  // stripped on export, regenerated on import.
  id: string;
  values: Record<string, string>;
}

// Batch mode is active when the widgets contain :variable: placeholders;
// there is no explicit on/off flag. `rows` holds the per-label values that
// only get exercised once variables exist.
export interface BatchState {
  copies: number;
  pauseTime: number;
  rows: BatchRow[];
  selectedRowIndex: number | null;
}

export interface LabelSettings {
  tapeSizeMm: TapeSize;
  marginPx: number;
  minLengthMm: number;
  justify: Alignment;
  foregroundColor: LabelColor;
  backgroundColor: LabelColor;
  showMargins: boolean;
  // Print a dotted vertical line on the right edge of each batch-printed
  // label so the user can tear/cut between them. Ignored in single-label
  // mode (visible only in BatchPanel) but stored here so it round-trips
  // through save/load with the rest of the label settings.
  cutMark: boolean;
  printerId?: string; // Optional printer ID for multi-printer setups
}

// The subset of LabelSettings persisted per printer: the
// physical "what tape/colors are loaded" properties. Partial because a
// printer may only have some of them saved. Kept narrow on purpose —
// margins/justify/cutMark are label preferences, not printer state.
export type PersistedPrinterSettings = Partial<
  Pick<LabelSettings, "tapeSizeMm" | "foregroundColor" | "backgroundColor">
>;
