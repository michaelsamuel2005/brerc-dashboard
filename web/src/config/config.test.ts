import { describe, expect, it } from "vitest";
import { parseConfig } from "./index";

describe("parseConfig", () => {
  it("accepts a valid env and defaults the API base URL", () => {
    expect(parseConfig({ VITE_API_BASE_URL: "/api" }).apiBaseUrl).toBe("/api");
    expect(parseConfig({}).apiBaseUrl).toBe("/api");
  });

  it("fails loudly on an empty required API base URL", () => {
    expect(() => parseConfig({ VITE_API_BASE_URL: "" })).toThrow();
  });

  it("fails loudly on an invalid map style URL", () => {
    expect(() => parseConfig({ VITE_API_BASE_URL: "/api", VITE_MAP_STYLE_URL: "not-a-url" })).toThrow();
  });
});
