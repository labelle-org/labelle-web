import { useMemo } from "react";
import { useLabelStore } from "../state/useLabelStore";
import { detectVariables } from "../lib/variables";

export function BatchPanel() {
  const widgets = useLabelStore((s) => s.widgets);
  const batch = useLabelStore((s) => s.batch);
  const updateBatch = useLabelStore((s) => s.updateBatch);
  const setBatchRow = useLabelStore((s) => s.setBatchRow);
  const addBatchRow = useLabelStore((s) => s.addBatchRow);
  const removeBatchRow = useLabelStore((s) => s.removeBatchRow);

  const variables = useMemo(() => detectVariables(widgets), [widgets]);

  return (
    <details
      className="bg-white rounded-lg shadow"
      open={batch.enabled}
      onToggle={(e) =>
        updateBatch({ enabled: (e.target as HTMLDetailsElement).open })
      }
    >
      <summary className="cursor-pointer select-none p-3 text-sm font-medium text-gray-700">
        Batch Print
      </summary>
      <div className="p-3 pt-0 space-y-3 text-sm">
        <div className="flex flex-wrap gap-4">
          <label className="flex items-center gap-1.5">
            <span className="text-gray-600">Copies</span>
            <input
              type="number"
              className="input w-20"
              min={1}
              max={999}
              value={batch.copies}
              onChange={(e) =>
                updateBatch({ copies: Math.max(1, Number(e.target.value)) })
              }
            />
          </label>
          <label className="flex items-center gap-1.5">
            <span className="text-gray-600">Pause (s)</span>
            <input
              type="number"
              className="input w-20"
              min={0}
              max={60}
              step={0.5}
              value={batch.pauseTime}
              onChange={(e) =>
                updateBatch({
                  pauseTime: Math.max(0, Number(e.target.value)),
                })
              }
            />
          </label>
        </div>

        {variables.length === 0 ? (
          <p className="text-gray-400 text-xs">
            Use <code className="bg-gray-100 px-1 rounded">:varname:</code> in
            widget text to define variables.
          </p>
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
                    <th className="border border-gray-200 px-2 py-1 w-8" />
                  </tr>
                </thead>
                <tbody>
                  {batch.rows.map((row, rowIdx) => (
                    <tr
                      key={rowIdx}
                      className={`cursor-pointer ${
                        batch.selectedRowIndex === rowIdx
                          ? "bg-blue-50"
                          : "hover:bg-gray-50"
                      }`}
                      onClick={() =>
                        updateBatch({
                          selectedRowIndex:
                            batch.selectedRowIndex === rowIdx
                              ? null
                              : rowIdx,
                        })
                      }
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
                            value={row[v] ?? ""}
                            onClick={(e) => e.stopPropagation()}
                            onChange={(e) =>
                              setBatchRow(rowIdx, v, e.target.value)
                            }
                          />
                        </td>
                      ))}
                      <td className="border border-gray-200 px-1 py-0.5 text-center">
                        {batch.rows.length > 1 && (
                          <button
                            className="text-red-400 hover:text-red-600"
                            title="Remove row"
                            onClick={(e) => {
                              e.stopPropagation();
                              removeBatchRow(rowIdx);
                            }}
                          >
                            x
                          </button>
                        )}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            <button
              className="text-blue-600 hover:text-blue-800 text-xs"
              onClick={addBatchRow}
            >
              + Add Row
            </button>
          </>
        )}
      </div>
    </details>
  );
}
