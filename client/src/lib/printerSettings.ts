import type {
  LabelSettings,
  PersistedPrinterSettings,
  PrinterInfo,
} from "../types/label";

// The settings keys persisted per printer. Single source of truth for
// pickPersisted; the server validates the same set (printer_settings.py).
export const PERSISTED_PRINTER_KEYS = [
  "tapeSizeMm",
  "foregroundColor",
  "backgroundColor",
] as const;

/**
 * Which printer to persist settings against.
 *
 * - An explicit selection always wins.
 * - With no selection ("Auto-select") but exactly one printer connected,
 *   that printer is unambiguous, so kiosk/single-printer setups still get
 *   persistence even though the UI hides the selector.
 * - With multiple printers and no selection we can't know which one the
 *   server will auto-pick, so we persist nothing (undefined).
 */
export function effectivePrinterId(
  selectedId: string | undefined,
  printers: PrinterInfo[],
): string | undefined {
  if (selectedId) return selectedId;
  if (printers.length === 1) return printers[0]!.id;
  return undefined;
}

/** Extract just the per-printer-persisted subset from full label settings.
 *  Derived from PERSISTED_PRINTER_KEYS so it can't drift from that list. */
export function pickPersisted(settings: LabelSettings): PersistedPrinterSettings {
  return Object.fromEntries(
    PERSISTED_PRINTER_KEYS.map((key) => [key, settings[key]]),
  ) as PersistedPrinterSettings;
}
