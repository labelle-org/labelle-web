import { useEffect, useState } from "react";

type NumberFieldProps = {
  label: string;
  value: number;
  min: number;
  max: number;
  className?: string;
  onChange: (value: number) => void;
};

/**
 * A numeric input that's pleasant to hand-edit.
 *
 * A plain controlled `<input type="number" value={number}>` fights the user:
 * clearing it yields `Number("") === 0` (so the field jumps to 0, and the
 * server then has to defend against a 0-size font), and the leftover leading
 * digit makes the next keystroke read as e.g. "06". Here we keep the visible
 * text as a free-form draft so the field can be emptied and retyped, commit a
 * clamped number to the parent only when the draft parses, and resync the draft
 * to the committed value on blur — never while typing, so clamping can't snap a
 * half-entered number out from under the cursor.
 */
export function NumberField({
  label,
  value,
  min,
  max,
  className,
  onChange,
}: NumberFieldProps) {
  const [draft, setDraft] = useState(String(value));
  const [focused, setFocused] = useState(false);

  // Mirror an external value change (e.g. loading a label file) into the field,
  // but stay out of the way while the user is actively editing it.
  useEffect(() => {
    if (!focused) setDraft(String(value));
  }, [value, focused]);

  const clamp = (n: number) => Math.min(max, Math.max(min, n));

  return (
    <label className="flex items-center gap-1 text-xs">
      {label}
      <input
        type="number"
        className={className}
        min={min}
        max={max}
        value={draft}
        onFocus={() => setFocused(true)}
        onBlur={() => setFocused(false)}
        onChange={(e) => {
          const raw = e.target.value;
          setDraft(raw);
          // Empty or non-numeric mid-edit: hold the last committed value so the
          // preview never renders an invalid size. The field settles on blur.
          if (raw.trim() === "") return;
          const parsed = Number(raw);
          if (!Number.isNaN(parsed)) onChange(clamp(parsed));
        }}
      />
    </label>
  );
}
