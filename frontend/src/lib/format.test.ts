import { describe, expect, it } from "vitest";
import { buildQuery, daysUntil, formatCompactMoney, formatDate, formatHours, formatMoney, formatPercent, initials } from "./format";

describe("format helpers", () => {
  it("formats ISO dates without timezone shift", () => {
    expect(formatDate("2026-11-20")).toBe("Nov 20, 2026");
    expect(formatDate(null)).toBe("—");
    expect(formatDate("not-a-date")).toBe("—");
  });

  it("formats money", () => {
    expect(formatMoney(1234.5)).toBe("$1,234.50");
    expect(formatMoney(null)).toBe("—");
    expect(formatCompactMoney(250000)).toBe("$250K");
    expect(formatCompactMoney(1_500_000)).toBe("$1.5M");
    expect(formatCompactMoney(42)).toBe("$42");
  });

  it("formats percents and hours", () => {
    expect(formatPercent(0.3125)).toBe("31.3%");
    expect(formatHours(40)).toBe("40");
    expect(formatHours(37.5)).toBe("37.5");
  });

  it("builds initials", () => {
    expect(initials("Demo Administrator")).toBe("DA");
    expect(initials("Cher")).toBe("C");
  });

  it("builds query strings skipping empty values", () => {
    expect(buildQuery({ q: "smith", page: 2, empty: "", nothing: null, flag: true })).toBe("?q=smith&page=2&flag=true");
    expect(buildQuery({})).toBe("");
  });

  it("computes days until a date", () => {
    const d = new Date();
    d.setDate(d.getDate() + 10);
    const iso = `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;
    expect(daysUntil(iso)).toBe(10);
    expect(daysUntil(null)).toBeNull();
  });
});
