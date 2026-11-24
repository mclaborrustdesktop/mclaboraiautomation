import { describe, expect, it } from "vitest";
import { ApiError, describeError, duplicateMatches } from "./api";

const match = { id: 7, name: "Dana Q", score: 0.9, level: "likely", reasons: ["same phone number"], city: null, state: null, phone: null, email: null, status: null };

describe("duplicate conflict helpers", () => {
  it("extracts matches from a 409 response", () => {
    const err = new ApiError(409, "Request failed (409)", { detail: { message: "This looks like an employee who is already on file.", matches: [match] } });
    expect(duplicateMatches(err)).toEqual([match]);
    expect(describeError(err)).toBe("This looks like an employee who is already on file.");
  });

  it("ignores other errors", () => {
    expect(duplicateMatches(new ApiError(422, "x", { detail: "First name is required" }))).toBeNull();
    expect(duplicateMatches(new ApiError(409, "x", { detail: "Initials already in use" }))).toBeNull();
    expect(duplicateMatches(new Error("boom"))).toBeNull();
  });

  it("formats validation errors", () => {
    const err = new ApiError(422, "x", { detail: [{ loc: ["body", "EmEmail"], msg: "Value error, is not a valid e-mail address" }] });
    expect(describeError(err)).toBe("EmEmail: Value error, is not a valid e-mail address");
  });
});
