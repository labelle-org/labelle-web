import type { LabelWidget } from "../types/label";

const VAR_REGEX = /:([a-zA-Z_]\w*):/g;

export function detectVariables(widgets: LabelWidget[]): string[] {
  const vars = new Set<string>();
  for (const w of widgets) {
    let text: string | undefined;
    if (w.type === "text") text = w.text;
    else if (w.type === "qr" || w.type === "barcode") text = w.content;
    if (text) {
      for (const match of text.matchAll(VAR_REGEX)) {
        const name = match[1];
        if (name) vars.add(name);
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
