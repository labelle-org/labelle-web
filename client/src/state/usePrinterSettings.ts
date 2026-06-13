import { useEffect, useState } from "react";
import { useLabelStore } from "./useLabelStore";
import { fetchPrinterSettings, savePrinterSettings } from "../lib/api";
import {
  effectivePrinterId,
  pickPersisted,
} from "../lib/printerSettings";
import type { PersistedPrinterSettings } from "../types/label";

/**
 * Wires per-printer settings persistence in two directions:
 *
 * - **Apply on select:** whenever the effective printer changes, fetch its
 *   saved subset and apply it to the store.
 * - **Save on change:** `persist(patch)` writes the full current subset for
 *   the effective printer. Callers invoke it from user-driven onChange only,
 *   so applying-from-server never loops back into a save.
 *
 * Each save sends the whole subset (not just the changed field) so the
 * server's wholesale-per-printer write never drops a previously saved value.
 *
 * Returns `loading`: true from app start until the effective printer's
 * settings have resolved (or there is no effective printer). Callers disable
 * the persisted controls while it's true, which closes two races: a slow
 * apply-fetch reverting a concurrent edit, and edits made before the printer
 * list resolves being lost. On a fetch error it clears (graceful unlock —
 * keep defaults, don't persist) so the UI never locks permanently.
 */
export function usePrinterSettings(): {
  persist: (patch: PersistedPrinterSettings) => void;
  loading: boolean;
} {
  const settings = useLabelStore((s) => s.settings);
  const availablePrinters = useLabelStore((s) => s.availablePrinters);
  const availablePrintersLoaded = useLabelStore((s) => s.availablePrintersLoaded);
  const updateSettings = useLabelStore((s) => s.updateSettings);

  const printerId = effectivePrinterId(settings.printerId, availablePrinters);
  const [settingsLoading, setSettingsLoading] = useState(false);

  useEffect(() => {
    if (!printerId) {
      setSettingsLoading(false);
      return;
    }
    let cancelled = false;
    setSettingsLoading(true);
    fetchPrinterSettings(printerId)
      .then((saved) => {
        if (!cancelled && Object.keys(saved).length > 0) updateSettings(saved);
      })
      .catch((error) => {
        if (!cancelled) console.error("Failed to load printer settings:", error);
      })
      .finally(() => {
        if (!cancelled) setSettingsLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [printerId, updateSettings]);

  // Block edits to persisted fields until we know what they should be:
  // before the printer list loads, and while the chosen printer's settings
  // are being fetched.
  const loading =
    !availablePrintersLoaded || (printerId !== undefined && settingsLoading);

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

  return { persist, loading };
}
