import { useEffect } from "react";
import { useLabelStore } from "./useLabelStore";
import { fetchPrinterSettings, savePrinterSettings } from "../lib/api";
import {
  effectivePrinterId,
  pickPersisted,
} from "../lib/printerSettings";
import type { PersistedPrinterSettings } from "../types/label";

/**
 * Wires per-printer settings persistence (issue #20) in two directions:
 *
 * - **Apply on select:** whenever the effective printer changes, fetch its
 *   saved subset and apply it to the store.
 * - **Save on change:** `persist(patch)` writes the full current subset for
 *   the effective printer. Callers invoke it from user-driven onChange only,
 *   so applying-from-server never loops back into a save.
 *
 * Each save sends the whole subset (not just the changed field) so the
 * server's wholesale-per-printer write never drops a previously saved value.
 */
export function usePrinterSettings(): {
  persist: (patch: PersistedPrinterSettings) => void;
} {
  const settings = useLabelStore((s) => s.settings);
  const availablePrinters = useLabelStore((s) => s.availablePrinters);
  const updateSettings = useLabelStore((s) => s.updateSettings);

  const printerId = effectivePrinterId(settings.printerId, availablePrinters);

  useEffect(() => {
    if (!printerId) return;
    let cancelled = false;
    fetchPrinterSettings(printerId)
      .then((saved) => {
        if (!cancelled && Object.keys(saved).length > 0) updateSettings(saved);
      })
      .catch((error) => {
        console.error("Failed to load printer settings:", error);
      });
    return () => {
      cancelled = true;
    };
  }, [printerId, updateSettings]);

  const persist = (patch: PersistedPrinterSettings) => {
    if (!printerId) return;
    // Read the live store rather than the `settings` captured in this render:
    // consecutive user edits can fire before a re-render, and the full subset
    // we send must reflect the latest values, not stale ones.
    const current = useLabelStore.getState().settings;
    savePrinterSettings(printerId, { ...pickPersisted(current), ...patch }).catch(
      (error) => {
        console.error("Failed to save printer settings:", error);
      },
    );
  };

  return { persist };
}
