import type { LabelWidget } from "../types/label";

const VAR_REGEX = /\{\{([\w-]+)\}\}/g;
// Also matches the empty placeholder `{{}}`. Used only by the rename heuristic
// (see useLabelStore.updateWidget): while renaming a variable by backspacing
// its name to nothing and retyping, the text passes through `{{}}`. Treating
// that empty placeholder as a (transient) variable lets the rename bridge
// `{{old}}` -> `{{}}` -> `{{new}}` instead of seeing a pure removal then a
// pure addition, which would orphan the batch value.
const VAR_REGEX_WITH_EMPTY = /\{\{([\w-]*)\}\}/g;

export function detectVariables(
  widgets: LabelWidget[],
  { includeEmpty = false }: { includeEmpty?: boolean } = {},
): string[] {
  const regex = includeEmpty ? VAR_REGEX_WITH_EMPTY : VAR_REGEX;
  const vars = new Set<string>();
  for (const w of widgets) {
    let text: string | undefined;
    if (w.type === "text") text = w.text;
    else if (w.type === "qr" || w.type === "barcode") text = w.content;
    if (text) {
      for (const match of text.matchAll(regex)) {
        const name = match[1] ?? "";
        if (includeEmpty || name) vars.add(name);
      }
    }
  }
  return [...vars];
}

export function substituteWidgets(
  widgets: LabelWidget[],
  values: Record<string, string>,
): LabelWidget[] {
  return widgets.map((w) => {
    if (w.type === "text") {
      return { ...w, text: replaceVars(w.text, values) };
    }
    if (w.type === "qr") {
      return { ...w, content: replaceVars(w.content, values) };
    }
    if (w.type === "barcode") {
      return { ...w, content: replaceVars(w.content, values) };
    }
    return w;
  });
}

function replaceVars(text: string, values: Record<string, string>): string {
  return text.replace(VAR_REGEX, (match, name: string) => {
    const val = values[name];
    return val !== undefined ? val : match;
  });
}
