import { describe, expect, it } from "vitest";

import { absoluteMoney, compareMoney, formatMoney, maximumMoney } from "./money";

describe("decimal-safe money helpers", () => {
  it("compares values beyond JavaScript's safe integer range without Number conversion", () => {
    expect(compareMoney("9007199254740993.000001", "9007199254740992.999999")).toBe(1);
    expect(compareMoney("-2.000000", "-1.999999")).toBe(-1);
  });

  it("formats and selects fixed-precision values deterministically", () => {
    expect(formatMoney("1234567.5", "USD")).toBe("USD 1,234,567.500000");
    expect(absoluteMoney("-40.000000")).toBe("40.000000");
    expect(maximumMoney("20.000000", "40.000000")).toBe("40.000000");
  });
});
