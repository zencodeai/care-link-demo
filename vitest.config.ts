import { defineConfig } from "vitest/config";
export default defineConfig({
  test: {
    include: [
      "tests/contract/*.test.ts",
      "packages/contracts/typescript/**/*.test.ts",
      "apps/web/**/*.test.ts",
      "apps/web/**/*.test.tsx",
    ],
    environment: "jsdom",
  },
});
