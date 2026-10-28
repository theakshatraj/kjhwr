import { defineConfig } from "vitest/config";

/**
 * Unit tests cover the pure helpers (formatting and the energy calculation).
 * Chart tests opt into jsdom per file with a `@vitest-environment` docblock.
 */
export default defineConfig({
  test: {
    environment: "node",
    include: ["src/**/*.test.ts", "src/**/*.test.tsx"],
  },
});
