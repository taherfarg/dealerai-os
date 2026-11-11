import { render } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { Icon } from "./Icon";

describe("Icon", () => {
  it("is never read out: the control it sits in has the name", () => {
    const { container } = render(<Icon name="bell" />);
    const drawing = container.querySelector("svg");
    expect(drawing?.getAttribute("aria-hidden")).toBe("true");
    expect(drawing?.querySelector("path")).not.toBeNull();
  });
});
