import { useEffect, useMemo, useRef, useState } from "react";
import { useLabelStore } from "../state/useLabelStore";
import { detectVariables } from "../lib/variables";
import {
  MAX_BATCH_COPIES,
  MAX_BATCH_PAUSE_SECONDS,
  MAX_BATCH_ROWS,
} from "../lib/constants";

function EyeIcon({ active }: { active: boolean }) {
  return (
    <svg
      width="14"
      height="14"
      viewBox="0 0 24 24"
      fill={active ? "currentColor" : "none"}
      stroke="currentColor"
      strokeWidth="2"
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden="true"
    >
      <path d="M2 12s3.5-7 10-7 10 7 10 7-3.5 7-10 7S2 12 2 12z" />
      <circle cx="12" cy="12" r="3" fill={active ? "white" : "none"} />
    </svg>
  );
}

export function BatchPanel() {
  const widgets = useLabelStore((s) => s.widgets);
  const batch = useLabelStore((s) => s.batch);
  const settings = useLabelStore((s) => s.settings);
  const updateSettings = useLabelStore((s) => s.updateSettings);
  const updateBatch = useLabelStore((s) => s.updateBatch);
  const setBatchRow = useLabelStore((s) => s.setBatchRow);
  const addBatchRow = useLabelStore((s) => s.addBatchRow);
  const removeBatchRow = useLabelStore((s) => s.removeBatchRow);
  const addTextWidget = useLabelStore((s) => s.addTextWidget);
  const updateWidget = useLabelStore((s) => s.updateWidget);

  const variables = useMemo(() => detectVariables(widgets), [widgets]);
  const hasVariables = variables.length > 0;

  // <details> auto-opens when variables appear (initial mount or a later
  // edit / file load), and stays open while they exist. The user can still
  // collapse it manually for a quick view of the rest of the editor.
  const [open, setOpen] = useState(hasVariables);
  useEffect(() => {
    if (hasVariables) setOpen(true);
  }, [hasVariables]);

  // Auto-select row 0 on the false->true transition of hasVariables so the
  // preview substitutes immediately when batch mode first activates (button
  // click or typing {{...}} into a widget). The transition check is
  // load-bearing: a plain "select if null" effect would fight the user every
  // time they deselect via the eye icon (which sets selectedRowIndex back to
  // null). On initial mount the ref captures the starting value, so a loaded
  // file's selectedRowIndex is preserved.
  const prevHasVariablesRef = useRef(hasVariables);
  useEffect(() => {
    const prev = prevHasVariablesRef.current;
    prevHasVariablesRef.current = hasVariables;
    if (
      !prev &&
      hasVariables &&
      batch.selectedRowIndex === null &&
      batch.rows.length > 0
    ) {
      updateBatch({ selectedRowIndex: 0 });
    }
  }, [hasVariables, batch.selectedRowIndex, batch.rows.length, updateBatch]);

  // Local string state for number inputs so the user can clear and retype
  // without the value snapping back to a clamped minimum mid-edit.
  const [copiesInput, setCopiesInput] = useState(String(batch.copies));
  const [pauseInput, setPauseInput] = useState(String(batch.pauseTime));
  useEffect(() => setCopiesInput(String(batch.copies)), [batch.copies]);
  useEffect(() => setPauseInput(String(batch.pauseTime)), [batch.pauseTime]);

  const commitCopies = () => {
    const parsed = Number(copiesInput);
    const n = Number.isFinite(parsed)
      ? Math.max(1, Math.min(MAX_BATCH_COPIES, parsed))
      : 1;
    updateBatch({ copies: n });
    setCopiesInput(String(n));
  };
  const commitPause = () => {
    const parsed = Number(pauseInput);
    const n = Number.isFinite(parsed)
      ? Math.max(0, Math.min(MAX_BATCH_PAUSE_SECONDS, parsed))
      : 0;
    updateBatch({ pauseTime: n });
    setPauseInput(String(n));
  };

  const handleAddVariable = () => {
    const state = useLabelStore.getState();
    const existing = new Set(detectVariables(state.widgets));
    let i = 1;
    while (existing.has(`var${i}`)) i++;
    const placeholder = `{{var${i}}}`;

    const firstText = state.widgets.find((w) => w.type === "text");
    if (firstText) {
      const sep = firstText.text.length > 0 ? " " : "";
      updateWidget(firstText.id, { text: `${firstText.text}${sep}${placeholder}` });
    } else {
      const newId = addTextWidget();
      updateWidget(newId, { text: placeholder });
    }
  };

  return (
    <details
      className="bg-white rounded-lg shadow"
      open={open}
      onToggle={(e) => setOpen((e.target as HTMLDetailsElement).open)}
    >
      <summary className="cursor-pointer select-none p-3 text-sm font-medium text-gray-700">
        Batch Print
      </summary>
      <div className="p-3 pt-0 space-y-3 text-sm">
        {variables.length === 0 ? (
          <div className="space-y-2">
            <p className="text-gray-400 text-xs">
              Add a variable, or type <code className="bg-gray-100 px-1 rounded">{`{{varname}}`}</code> into a widget.
            </p>
            <button
              className="text-blue-600 hover:text-blue-800 text-xs"
              onClick={handleAddVariable}
            >
              + Add Variable
            </button>
          </div>
        ) : (
          <>
            <div className="overflow-x-auto">
              <table className="w-full border-collapse text-xs">
                <thead>
                  <tr className="bg-gray-50">
                    <th className="border border-gray-200 px-2 py-1 text-left w-8">
                      #
                    </th>
                    {variables.map((v) => (
                      <th
                        key={v}
                        className="border border-gray-200 px-2 py-1 text-left"
                      >
                        {v}
                      </th>
                    ))}
                    <th className="border border-gray-200 px-2 py-1 w-16" />
                  </tr>
                </thead>
                <tbody>
                  {batch.rows.map((row, rowIdx) => {
                    const isPreviewed = batch.selectedRowIndex === rowIdx;
                    return (
                      <tr
                        key={row.id}
                        className={isPreviewed ? "bg-blue-50" : ""}
                      >
                        <td className="border border-gray-200 px-2 py-1 text-gray-400">
                          {rowIdx + 1}
                        </td>
                        {variables.map((v) => (
                          <td
                            key={v}
                            className="border border-gray-200 px-1 py-0.5"
                          >
                            <input
                              type="text"
                              className="w-full bg-transparent outline-none px-1 py-0.5"
                              value={row.values[v] ?? ""}
                              onChange={(e) =>
                                setBatchRow(rowIdx, v, e.target.value)
                              }
                            />
                          </td>
                        ))}
                        <td className="border border-gray-200 px-1 py-0.5">
                          <div className="flex items-center justify-center gap-4">
                            <button
                              className={
                                isPreviewed
                                  ? "text-blue-600"
                                  : "text-gray-400 hover:text-blue-600"
                              }
                              title={
                                isPreviewed
                                  ? `Stop previewing row ${rowIdx + 1}`
                                  : `Preview row ${rowIdx + 1}`
                              }
                              aria-label={
                                isPreviewed
                                  ? `Stop previewing row ${rowIdx + 1}`
                                  : `Preview row ${rowIdx + 1}`
                              }
                              aria-pressed={isPreviewed}
                              onClick={() =>
                                updateBatch({
                                  selectedRowIndex: isPreviewed ? null : rowIdx,
                                })
                              }
                            >
                              <EyeIcon active={isPreviewed} />
                            </button>
                            {batch.rows.length > 1 ? (
                              <button
                                className="text-red-400 hover:text-red-600"
                                title={`Remove row ${rowIdx + 1}`}
                                aria-label={`Remove row ${rowIdx + 1}`}
                                onClick={() => removeBatchRow(rowIdx)}
                              >
                                <span aria-hidden="true">x</span>
                              </button>
                            ) : (
                              <span className="w-3" />
                            )}
                          </div>
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
            <div className="flex gap-3 items-center">
              <button
                className="text-blue-600 hover:text-blue-800 disabled:text-gray-400 disabled:cursor-not-allowed text-xs"
                onClick={addBatchRow}
                disabled={batch.rows.length >= MAX_BATCH_ROWS}
                title={
                  batch.rows.length >= MAX_BATCH_ROWS
                    ? `Maximum ${MAX_BATCH_ROWS} rows`
                    : undefined
                }
              >
                + Add Row
              </button>
              <button
                className="text-blue-600 hover:text-blue-800 text-xs"
                onClick={handleAddVariable}
              >
                + Add Variable
              </button>
            </div>
          </>
        )}

        <div className="flex flex-wrap items-center gap-4 pt-1 border-t border-gray-100">
          <label className="flex items-center gap-1.5">
            <span className="text-gray-600">Copies</span>
            <input
              type="number"
              className="input w-20"
              min={1}
              max={MAX_BATCH_COPIES}
              value={copiesInput}
              onChange={(e) => setCopiesInput(e.target.value)}
              onBlur={commitCopies}
            />
          </label>
          <label className="flex items-center gap-1.5">
            <span className="text-gray-600">Pause (s)</span>
            <input
              type="number"
              className="input w-20"
              min={0}
              max={MAX_BATCH_PAUSE_SECONDS}
              step={0.5}
              value={pauseInput}
              onChange={(e) => setPauseInput(e.target.value)}
              onBlur={commitPause}
            />
          </label>
          <label
            className="flex items-center gap-1.5"
            title="Print a dotted line on the right edge of each label so you can tear/cut between them"
          >
            <input
              type="checkbox"
              checked={settings.cutMark}
              onChange={(e) => updateSettings({ cutMark: e.target.checked })}
            />
            <span className="text-gray-600">Cut mark</span>
          </label>
        </div>
      </div>
    </details>
  );
}
