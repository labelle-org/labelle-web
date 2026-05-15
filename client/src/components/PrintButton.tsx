import { useState, useRef, useEffect, useMemo } from "react";
import { v4 as uuidv4 } from "uuid";
import { useLabelStore } from "../state/useLabelStore";
import { printLabel, batchPrint, cancelBatchPrint } from "../lib/api";
import type { BatchEvent } from "../lib/api";
import { detectVariables } from "../lib/variables";

export function PrintButton() {
  const widgets = useLabelStore((s) => s.widgets);
  const settings = useLabelStore((s) => s.settings);
  const batch = useLabelStore((s) => s.batch);
  const hasVariables = useMemo(
    () => detectVariables(widgets).length > 0,
    [widgets],
  );
  const [status, setStatus] = useState<{
    type: "idle" | "loading" | "success" | "error";
    message?: string;
  }>({ type: "idle" });
  const jobIdRef = useRef<string | null>(null);
  const abortRef = useRef<AbortController | null>(null);

  // On unmount, abort the client-side SSE read AND tell the server to stop
  // — otherwise the server-side print loop keeps running and the next mount
  // will hit 409 until it finishes.
  useEffect(() => {
    return () => {
      abortRef.current?.abort();
      const jobId = jobIdRef.current;
      if (jobId) {
        cancelBatchPrint(jobId).catch(() => {
          // Nothing useful to do on unmount.
        });
      }
    };
  }, []);

  const totalLabels = hasVariables
    ? batch.rows.length * batch.copies
    : 1;

  const handlePrint = async () => {
    if (widgets.length === 0) {
      setStatus({ type: "error", message: "Add at least one widget" });
      return;
    }

    setStatus({ type: "loading" });

    try {
      if (hasVariables) {
        const controller = new AbortController();
        abortRef.current = controller;
        // Generate the jobId client-side so the unmount cleanup can cancel
        // the server-side batch immediately, even if it fires before the
        // `started` SSE event arrives (which is the only place the server
        // would otherwise echo back a server-chosen id).
        const jobId = uuidv4();
        jobIdRef.current = jobId;
        await batchPrint(
          widgets,
          settings,
          batch.rows.map((r) => r.values),
          batch.copies,
          batch.pauseTime,
          jobId,
          (event: BatchEvent) => {
            switch (event.event) {
              case "started":
                setStatus({
                  type: "loading",
                  message: `Starting batch of ${event.total}...`,
                });
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
          controller.signal,
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
      // AbortError on unmount: don't surface, the component is gone anyway.
      if (err instanceof DOMException && err.name === "AbortError") return;
      setStatus({
        type: "error",
        message: err instanceof Error ? err.message : "Network error",
      });
    } finally {
      jobIdRef.current = null;
      abortRef.current = null;
    }

    setTimeout(() => {
      setStatus((s) => (s.type === "success" ? { type: "idle" } : s));
    }, 3000);
  };

  const handleCancel = () => {
    if (jobIdRef.current) {
      cancelBatchPrint(jobIdRef.current).catch((err) => {
        console.warn("Cancel batch failed:", err);
      });
    }
  };

  return (
    <div>
      <div className="flex gap-2">
        <button
          className="flex-1 bg-blue-600 hover:bg-blue-700 disabled:bg-gray-400 text-white py-3 rounded-lg font-semibold transition-colors"
          onClick={handlePrint}
          disabled={
            status.type === "loading" ||
            (hasVariables && totalLabels === 0)
          }
        >
          {status.type === "loading"
            ? status.message ?? "Printing..."
            : hasVariables
              ? `Batch Print (${totalLabels} labels)`
              : "Print Label"}
        </button>
        {status.type === "loading" && hasVariables && (
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
