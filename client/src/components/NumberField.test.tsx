import { describe, it, expect, afterEach, vi } from "vitest";
import { render, screen, cleanup } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { useState } from "react";

import { NumberField } from "./NumberField";

afterEach(() => {
  cleanup();
});

/** Controlled wrapper so the displayed value reflects committed changes,
 *  mirroring how TextWidgetEditor drives NumberField through the store. */
function Harness({
  initial = 90,
  min = 10,
  max = 150,
  onCommit,
}: {
  initial?: number;
  min?: number;
  max?: number;
  onCommit?: (n: number) => void;
}) {
  const [value, setValue] = useState(initial);
  return (
    <NumberField
      label="Scale %"
      value={value}
      min={min}
      max={max}
      onChange={(n) => {
        setValue(n);
        onCommit?.(n);
      }}
    />
  );
}

describe("NumberField", () => {
  it("clearing the field shows empty, not 0, and commits nothing", async () => {
    const user = userEvent.setup();
    const onCommit = vi.fn();
    render(<Harness onCommit={onCommit} />);
    const input = screen.getByRole("spinbutton") as HTMLInputElement;

    await user.clear(input);

    expect(input.value).toBe("");
    expect(onCommit).not.toHaveBeenCalledWith(0);
  });

  it("lets you clear and type a fresh value without a leading zero", async () => {
    const user = userEvent.setup();
    const onCommit = vi.fn();
    render(<Harness onCommit={onCommit} />);
    const input = screen.getByRole("spinbutton") as HTMLInputElement;

    await user.clear(input);
    await user.type(input, "60");

    expect(input.value).toBe("60");
    expect(onCommit).toHaveBeenLastCalledWith(60);
  });

  it("clamps a committed value below the minimum", async () => {
    const user = userEvent.setup();
    const onCommit = vi.fn();
    render(<Harness min={10} onCommit={onCommit} />);
    const input = screen.getByRole("spinbutton") as HTMLInputElement;

    await user.clear(input);
    await user.type(input, "6");

    expect(onCommit).toHaveBeenLastCalledWith(10);
  });

  it("clamps a committed value above the maximum", async () => {
    const user = userEvent.setup();
    const onCommit = vi.fn();
    render(<Harness max={150} onCommit={onCommit} />);
    const input = screen.getByRole("spinbutton") as HTMLInputElement;

    await user.clear(input);
    await user.type(input, "999");

    expect(onCommit).toHaveBeenLastCalledWith(150);
  });

  it("settles the field to the committed (clamped) value on blur", async () => {
    const user = userEvent.setup();
    render(<Harness min={10} />);
    const input = screen.getByRole("spinbutton") as HTMLInputElement;

    await user.clear(input);
    await user.type(input, "6");
    expect(input.value).toBe("6"); // not fought while typing
    await user.tab();

    expect(input.value).toBe("10");
  });

  it("reflects an external value change when not being edited", async () => {
    function Rerenderer() {
      const [value, setValue] = useState(90);
      return (
        <>
          <button onClick={() => setValue(120)}>set</button>
          <NumberField
            label="Scale %"
            value={value}
            min={10}
            max={150}
            onChange={() => {}}
          />
        </>
      );
    }
    const user = userEvent.setup();
    render(<Rerenderer />);
    const input = screen.getByRole("spinbutton") as HTMLInputElement;
    expect(input.value).toBe("90");

    await user.click(screen.getByText("set"));

    expect(input.value).toBe("120");
  });
});
