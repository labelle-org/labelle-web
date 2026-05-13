import { useEffect, useState } from "react";
import { fetchPowerStatus, powerOn, powerOff } from "../lib/api";
import type { PowerStatus } from "../types/label";

// `undefined` = initial fetch in flight, `null` = server has no
// controllable printer (404 from /api/power/status), object = live
// state. The component renders nothing in the first two cases — a
// deployment without per-port USB power switching shouldn't see the
// toggle at all.
type Status = PowerStatus | null | undefined;

export function PowerToggle() {
  const [status, setStatus] = useState<Status>(undefined);
  // null = no toggle in flight; "on"/"off" = the action that's running
  // (used both for the disabled-while-pending logic and for the
  // accessible button label so screen readers see "Powering on...").
  const [pending, setPending] = useState<"on" | "off" | null>(null);

  useEffect(() => {
    fetchPowerStatus()
      .then(setStatus)
      .catch((e: unknown) => {
        // Treat fetch failure the same as 404 so a broken /api/power
        // endpoint hides the UI rather than rendering it in a stuck
        // state. The error is still logged for debugging.
        console.error("Failed to fetch power status:", e);
        setStatus(null);
      });
  }, []);

  if (status === undefined || status === null) return null;

  const handleToggle = async () => {
    if (pending !== null) return;
    const action = status.powered ? "off" : "on";
    setPending(action);
    try {
      const next = action === "on" ? await powerOn() : await powerOff();
      setStatus(next);
    } catch (e: unknown) {
      console.error(`Failed to power ${action}:`, e);
      // Leave `status` untouched so the user can retry from the same
      // state. `pending` is cleared in `finally`.
    } finally {
      setPending(null);
    }
  };

  const label =
    pending === "on"
      ? "Powering on…"
      : pending === "off"
      ? "Powering off…"
      : status.powered
      ? "Turn off"
      : "Turn on";

  return (
    <div className="flex items-center gap-1.5">
      <span className="text-gray-600 whitespace-nowrap">Printer power</span>
      <span
        className={`inline-block w-2 h-2 rounded-full ${
          status.powered ? "bg-green-500" : "bg-gray-400"
        }`}
        aria-hidden="true"
      />
      <button
        type="button"
        className="text-xs px-2 py-1 bg-gray-200 hover:bg-gray-300 rounded disabled:opacity-50"
        onClick={handleToggle}
        disabled={pending !== null}
      >
        {label}
      </button>
    </div>
  );
}
