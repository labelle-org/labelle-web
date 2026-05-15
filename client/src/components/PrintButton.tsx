import { useState, useRef } from "react";
import { useLabelStore } from "../state/useLabelStore";
import { printLabel, batchPrint, cancelBatchPrint } from "../lib/api";
import type { BatchEvent } from "../lib/api";

export function PrintButton() {
  const widgets = useLabelStore((s) => s.widgets);
  const settings = useLabelStore((s) => s.settings);
  const batch = useLabelStore((s) => s.batch);
  const [status, setStatus] = useState<{
    type: "idle" | "loading" | "success" | "error";
    message?: string;
  }>({ type: "idle" });
  const jobIdRef = useRef<string | null>(null);

  const totalLabels = batch.enabled
    ? batch.rows.length * batch.copies
    : 1;

  const handlePrint = async () => {
    if (widgets.length === 0) {
      setStatus({ type: "error", message: "Add at least one widget" });
      return;
    }

    setStatus({ type: "loading" });

    try {
      if (batch.enabled) {
        await batchPrint(
          widgets,
          settings,
          batch.rows,
          batch.copies,
          batch.pauseTime,
          (event: BatchEvent) => {
            switch (event.event) {
              case "started":
                jobIdRef.current = event.jobId ?? null;
                break;
              case "printing":
                setStatus({
                  type: "loading",
                  message: `Printing ${(event.index ?? 0) + 1}/${event.total}...`,
                });
                break;
              case "done":
                setStatus({
                  type: "success",
                  message: `Printed ${event.total} labels.`,
                });
                break;
              case "cancelled":
                setStatus({
                  type: "success",
                  message: `Cancelled after ${event.printed} labels.`,
                });
                break;
              case "error":
                setStatus({
                  type: "error",
                  message: event.message ?? "Print error",
                });
                break;
            }
          },
        );
      } else {
        const result = await printLabel(widgets, settings);
        if (result.status === "success") {
          setStatus({ type: "success", message: result.message });
        } else {
          setStatus({ type: "error", message: result.message });
        }
      }
    } catch (err) {
      setStatus({
        type: "error",
        message: err instanceof Error ? err.message : "Network error",
      });
    } finally {
      jobIdRef.current = null;
    }

    setTimeout(() => {
      setStatus((s) => (s.type === "success" ? { type: "idle" } : s));
    }, 3000);
  };

  const handleCancel = () => {
    if (jobIdRef.current) {
      cancelBatchPrint(jobIdRef.current);
    }
  };

  return (
    <div>
      <div className="flex gap-2">
        <button
          className="flex-1 bg-blue-600 hover:bg-blue-700 disabled:bg-gray-400 text-white py-3 rounded-lg font-semibold transition-colors"
          onClick={handlePrint}
          disabled={status.type === "loading"}
        >
          {status.type === "loading"
            ? status.message ?? "Printing..."
            : batch.enabled
              ? `Batch Print (${totalLabels} labels)`
              : "Print Label"}
        </button>
        {status.type === "loading" && batch.enabled && (
          <button
            className="bg-red-500 hover:bg-red-600 text-white px-4 py-3 rounded-lg font-semibold transition-colors"
            onClick={handleCancel}
          >
            Cancel
          </button>
        )}
      </div>
      {status.message && status.type !== "loading" && (
        <p
          className={`text-sm mt-2 text-center ${
            status.type === "success" ? "text-green-600" : "text-red-600"
          }`}
        >
          {status.message}
        </p>
      )}
    </div>
  );
}
