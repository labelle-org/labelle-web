import { useRef, useState } from "react";
import { useLabelStore } from "../state/useLabelStore";
import { exportLabel, importLabel } from "../lib/labelFile";

export function SaveLoadButtons() {
  const widgets = useLabelStore((s) => s.widgets);
  const settings = useLabelStore((s) => s.settings);
  const batch = useLabelStore((s) => s.batch);
  const loadLabel = useLabelStore((s) => s.loadLabel);
  const fileRef = useRef<HTMLInputElement>(null);
  const [busy, setBusy] = useState(false);

  const handleSave = async () => {
    setBusy(true);
    try {
      const json = await exportLabel(widgets, settings, batch);
      const blob = new Blob([json], { type: "application/json" });
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      a.download = "label.json";
      a.click();
      URL.revokeObjectURL(url);
    } catch (err) {
      console.error("Save failed:", err);
    } finally {
      setBusy(false);
    }
  };

  const handleLoad = async (file: File) => {
    setBusy(true);
    try {
      const json = await file.text();
      const { widgets: w, settings: s, batch: b } = await importLabel(json);
      loadLabel(w, s, b);
    } catch (err) {
      console.error("Load failed:", err);
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="flex gap-2">
      <button className="btn flex-1" onClick={handleSave} disabled={busy}>
        {busy ? "..." : "Save"}
      </button>
      <button
        className="btn flex-1"
        onClick={() => fileRef.current?.click()}
        disabled={busy}
      >
        Load
      </button>
      <input
        ref={fileRef}
        type="file"
        accept=".json"
        className="hidden"
        onChange={(e) => {
          const file = e.target.files?.[0];
          if (file) handleLoad(file);
          e.target.value = "";
        }}
      />
    </div>
  );
}
