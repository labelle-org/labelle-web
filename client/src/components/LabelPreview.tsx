import { useRef, useEffect, useState, useMemo } from "react";
import { useLabelStore } from "../state/useLabelStore";
import { fetchServerPreview } from "../lib/api";
import { substituteWidgets } from "../lib/variables";

export function LabelPreview() {
  const widgets = useLabelStore((s) => s.widgets);
  const settings = useLabelStore((s) => s.settings);
  const batch = useLabelStore((s) => s.batch);
  const [previewUrl, setPreviewUrl] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const prevUrlRef = useRef<string | null>(null);

  const previewWidgets = useMemo(() => {
    if (batch.enabled && batch.selectedRowIndex !== null) {
      const row = batch.rows[batch.selectedRowIndex];
      if (row) return substituteWidgets(widgets, row);
    }
    return widgets;
  }, [widgets, batch.enabled, batch.selectedRowIndex, batch.rows]);

  useEffect(() => {
    const hasContent = previewWidgets.some((w) => {
      if (w.type === "text") return w.text.trim().length > 0;
      if (w.type === "qr" || w.type === "barcode") return w.content.trim().length > 0;
      if (w.type === "image") return w.filename.length > 0;
      return false;
    });

    if (!hasContent) {
      if (prevUrlRef.current) {
        URL.revokeObjectURL(prevUrlRef.current);
        prevUrlRef.current = null;
      }
      setPreviewUrl(null);
      setLoading(false);
      return;
    }

    const controller = new AbortController();
    setLoading(true);

    const timer = setTimeout(() => {
      fetchServerPreview(previewWidgets, settings, controller.signal)
        .then((url) => {
          if (prevUrlRef.current) {
            URL.revokeObjectURL(prevUrlRef.current);
          }
          prevUrlRef.current = url;
          setPreviewUrl(url);
          setLoading(false);
        })
        .catch((err) => {
          if (err instanceof DOMException && err.name === "AbortError") return;
          console.error("Preview failed:", err);
          setLoading(false);
        });
    }, 300);

    return () => {
      clearTimeout(timer);
      controller.abort();
    };
  }, [previewWidgets, settings]);

  return (
    <div className="bg-white rounded-lg shadow p-4">
      <h2 className="text-sm font-medium text-gray-600 mb-2">Preview</h2>
      <div className="overflow-x-auto">
        {previewUrl ? (
          <img
            src={previewUrl}
            alt="Label preview"
            className="border border-gray-200 rounded transition-opacity duration-150"
            style={{
              maxWidth: "100%",
              height: "auto",
              imageRendering: "pixelated",
              opacity: loading ? 0.5 : 1,
            }}
          />
        ) : (
          <div className="border border-gray-200 rounded h-16 flex items-center justify-center text-gray-400 text-sm">
            {loading ? "Loading preview…" : "Add a widget to see preview"}
          </div>
        )}
      </div>
    </div>
  );
}
