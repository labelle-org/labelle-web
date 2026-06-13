import { useLabelStore } from "../state/useLabelStore";
import { usePrinterSettings } from "../state/usePrinterSettings";
import { TAPE_SIZES, LABEL_COLORS } from "../lib/constants";
import { fetchPrinters } from "../lib/api";
import type { TapeSize, Alignment, LabelColor } from "../types/label";
import { useState } from "react";
import { PowerToggle } from "./PowerToggle";

export function SettingsBar() {
  const settings = useLabelStore((s) => s.settings);
  const update = useLabelStore((s) => s.updateSettings);
  const availablePrinters = useLabelStore((s) => s.availablePrinters);
  const setAvailablePrinters = useLabelStore((s) => s.setAvailablePrinters);
  const [isRefreshing, setIsRefreshing] = useState(false);

  // Per-printer settings persistence: applies saved tape/color for the
  // selected printer, and `persist` saves user changes to those. `loading`
  // is true until those settings resolve — we disable the persisted controls
  // until then so a late-arriving fetch can't clobber an edit.
  const { persist, loading: settingsLoading } = usePrinterSettings();

  const handleRefreshPrinters = async () => {
    setIsRefreshing(true);
    try {
      const printers = await fetchPrinters();
      setAvailablePrinters(printers);
    } catch (error) {
      console.error("Failed to fetch printers:", error);
    } finally {
      setIsRefreshing(false);
    }
  };

  // Only show printer selector if multiple printers are detected.
  // Tape size + colors now persist per printer; the rest of
  // the multi-printer UI cluster (status indicators, capability-aware tape
  // display, aliases, presets) is tracked in #38.
  const showPrinterSelector = availablePrinters.length > 1;

  // Hide the USB power toggle when a virtual printer is selected —
  // virtual printers don't have a USB port to power off. When
  // Auto-select is active or a real USB printer is selected, the
  // toggle stays visible (and itself hides if the server can't
  // resolve a controllable port).
  const selectedPrinter = settings.printerId
    ? availablePrinters.find((p) => p.id === settings.printerId)
    : null;
  const selectedIsVirtual = selectedPrinter?.vendorProductId === "virtual";

  return (
    <details className="bg-white rounded-lg shadow">
      <summary className="cursor-pointer select-none p-3 text-sm font-medium text-gray-700">
        Settings
      </summary>
      <div className="p-3 pt-0 flex flex-wrap items-center gap-4 text-sm">
      {showPrinterSelector && (
        <>
          <Field label="Printer">
            <select
              className="input w-48"
              value={settings.printerId || ""}
              onChange={(e) =>
                update({ printerId: e.target.value || undefined })
              }
            >
              <option value="">Auto-select</option>
              {availablePrinters.map((p) => (
                <option key={p.id} value={p.id}>
                  {p.name}
                </option>
              ))}
            </select>
          </Field>
          <button
            className="text-xs px-2 py-1 bg-gray-200 hover:bg-gray-300 rounded disabled:opacity-50"
            onClick={handleRefreshPrinters}
            disabled={isRefreshing}
          >
            {isRefreshing ? "..." : "↻"}
          </button>
        </>
      )}

      {!selectedIsVirtual && <PowerToggle />}

      {settingsLoading && (
        <span className="text-xs text-gray-500 italic">
          Loading printer settings…
        </span>
      )}

      <Field label="Tape (mm)">
        <select
          className="input w-20"
          value={settings.tapeSizeMm}
          disabled={settingsLoading}
          onChange={(e) => {
            const tapeSizeMm = Number(e.target.value) as TapeSize;
            update({ tapeSizeMm });
            persist({ tapeSizeMm });
          }}
        >
          {TAPE_SIZES.map((s) => (
            <option key={s} value={s}>
              {s}
            </option>
          ))}
        </select>
      </Field>

      <Field label="Margin (px)">
        <input
          type="number"
          className="input w-20"
          min={0}
          max={500}
          value={settings.marginPx}
          onChange={(e) => update({ marginPx: Number(e.target.value) })}
        />
      </Field>

      <Field label="Min length (mm)">
        <input
          type="number"
          className="input w-20"
          min={0}
          max={500}
          value={settings.minLengthMm}
          onChange={(e) => update({ minLengthMm: Number(e.target.value) })}
        />
      </Field>

      <Field label="Justify">
        <select
          className="input w-24"
          value={settings.justify}
          onChange={(e) => update({ justify: e.target.value as Alignment })}
        >
          <option value="left">Left</option>
          <option value="center">Center</option>
          <option value="right">Right</option>
        </select>
      </Field>

      <Field label="FG color">
        <select
          className="input w-24"
          value={settings.foregroundColor}
          disabled={settingsLoading}
          onChange={(e) => {
            const foregroundColor = e.target.value as LabelColor;
            update({ foregroundColor });
            persist({ foregroundColor });
          }}
        >
          {LABEL_COLORS.map((c) => (
            <option key={c} value={c}>
              {c}
            </option>
          ))}
        </select>
      </Field>

      <Field label="BG color">
        <select
          className="input w-24"
          value={settings.backgroundColor}
          disabled={settingsLoading}
          onChange={(e) => {
            const backgroundColor = e.target.value as LabelColor;
            update({ backgroundColor });
            persist({ backgroundColor });
          }}
        >
          {LABEL_COLORS.map((c) => (
            <option key={c} value={c}>
              {c}
            </option>
          ))}
        </select>
      </Field>

      <label className="flex items-center gap-1.5 cursor-pointer">
        <input
          type="checkbox"
          checked={settings.showMargins}
          onChange={(e) => update({ showMargins: e.target.checked })}
        />
        Show margins
      </label>
      </div>
    </details>
  );
}

function Field({
  label,
  children,
}: {
  label: string;
  children: React.ReactNode;
}) {
  return (
    <label className="flex items-center gap-1.5">
      <span className="text-gray-600 whitespace-nowrap">{label}</span>
      {children}
    </label>
  );
}
