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

export interface BatchState {
  enabled: boolean;
  copies: number;
  pauseTime: number;
  rows: Record<string, string>[];
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
  printerId?: string; // Optional printer ID for multi-printer setups
}
